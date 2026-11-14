"""Calibration against scripted anchor policies.

For each scenario and seed, every anchor policy is played in-process and its
ledger recorded. Anchored score components take their `zero` and `scale`
from those ledgers (see scoring.fit_anchor). The result is written to
calibration.json and committed, so the constants a score depends on are
fixed, visible and reproducible: rerunning calibration on unchanged code
yields the identical file.

Layout (StoreBench's, generalized to several anchored components):

    {"tasks": {"<scenario>": {"<seed>": {
        "seed": 7, "bundle": "<hash>", "oracle": "reference", "threshold": 0.69,
        "components": {"business": {"zero": ..., "scale": ...}},
        "anchors": {"do-nothing": {"reward": 0.0, "components": {...}, "metrics": {...}}, ...}
    }}}}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .bundle import bundle_hash, source_files
from .clients import run_inprocess
from .policies import make_policy
from .scenario import Scenario
from .scoring import fit_anchor, score

CALIBRATION_FILE = "calibration.json"


class CalibrationError(RuntimeError):
    pass


def calibrate(scenario: Scenario, seed: int) -> dict[str, Any]:
    ledgers = {
        name: run_inprocess(scenario, seed, make_policy(name, scenario)).result()
        for name in scenario.anchor_names()
    }

    constants: dict[str, dict[str, float]] = {}
    for comp in scenario.components:
        if comp.kind != "anchored":
            continue
        metric = comp.metrics[0]

        def raw(names: tuple[str, ...]) -> list[float]:
            values = []
            for n in names:
                v = ledgers[n].get(metric)
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    raise CalibrationError(f"anchor '{n}' has no numeric ledger value '{metric}'")
                values.append(float(v))
            return values

        zero, scale = fit_anchor(raw(comp.zero_anchors), raw(comp.top_anchors), comp.target)
        if scale <= 0:
            raise CalibrationError(
                f"{scenario.id} seed {seed}: component '{comp.name}' has no positive scale. The top anchors "
                f"{list(comp.top_anchors)} do not beat the zero anchors {list(comp.zero_anchors)} on "
                f"'{metric}', so the environment shows no measurable skill."
            )
        constants[comp.name] = {"zero": round(zero, 6), "scale": scale}

    entry: dict[str, Any] = {
        "seed": int(seed),
        "bundle": bundle_hash(source_files(scenario)),
        "oracle": scenario.reference,
        "components": constants,
    }
    anchors = {}
    for name, ledger in ledgers.items():
        s = score(scenario, ledger, entry)
        anchors[name] = {"reward": s["reward"], "components": s["components"], "metrics": _scored(scenario, ledger)}
    top = [n for c in scenario.components for n in c.top_anchors]
    best_top = max((anchors[n]["reward"] for n in top), default=None)
    entry["threshold"] = None if best_top is None else round(best_top - scenario.pass_margin, 4)
    entry["anchors"] = anchors
    return entry


def load_calibration(root: Path) -> dict[str, Any]:
    path = root / CALIBRATION_FILE
    if not path.exists():
        return {"tasks": {}}
    return json.loads(path.read_text())


def save_calibration(root: Path, data: dict[str, Any]) -> None:
    (root / CALIBRATION_FILE).write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", newline="\n")


def entry_for(data: dict[str, Any], scenario_id: str, seed: int) -> dict[str, Any] | None:
    return data.get("tasks", {}).get(scenario_id, {}).get(str(int(seed)))


def _scored(scenario: Scenario, ledger: dict[str, Any]) -> dict[str, Any]:
    """Only the ledger values the score reads. Anything else (call counts, which
    of several equally good schedules a solver picked) may differ between
    machines without changing a score, and must not make calibration look stale."""
    names = dict.fromkeys(m for c in scenario.components for m in c.metrics)
    return {k: (round(ledger[k], 4) if isinstance(ledger.get(k), float) else ledger.get(k)) for k in names}
