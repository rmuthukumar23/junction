"""Comparator runs: the baselines and the reference, actually executed.

Every number shown next to a player's result comes from playing that policy on
the same scenario and seed through the same engine, and is kept with its trace
so it can be replayed. Nothing here is a stored constant.

Results are cached under <data>/comparators/<scenario>-s<seed>-<bundle>/ and
are recomputed whenever the code or scenario (the bundle hash) changes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from envkit.bundle import bundle_hash, source_files
from envkit.clients import run_inprocess
from envkit.policies import make_policy
from envkit.scenario import Scenario
from envkit.scoring import score

# (policy spec, label, what it is)
COMPARATORS = (
    ("do-nothing", "Do nothing", "Nobody decides anything: the default plan runs on all 14 days. This is the floor of the scale."),
    ("stop-early", "Stop early", "The reference policy plays the first 4 days and then stops; the default plan runs the rest."),
    ("rule-based", "Rule-based (EC rules, no tests)", "Tops water up to a fixed level and feeds or flushes by EC band, treating EC as a nutrient gauge. Never tests."),
    ("reference", "Reference planner", "Tests every zone once, tracks nutrients and salts with the published rules, and replans every morning over candidate plans. A strong comparator, not a proven optimum."),
)
LEDGER_KEYS = ("profit_eur", "normalized_profit", "revenue_eur", "harvest_kg", "cost_total_eur", "cost_water_eur",
               "cost_fertilizer_eur", "cost_discharge_eur", "cost_tests_eur", "fresh_water_used_l", "tests_ordered",
               "days_with_a_submitted_plan", "profit_floor_eur", "profit_ceiling_eur", "conservation_ok")


def run_comparator(scenario: Scenario, seed: int, spec: str, trace_path: Path | None = None) -> dict[str, Any]:
    bundle = bundle_hash(source_files(scenario))
    episode = run_inprocess(scenario, seed, make_policy(spec, scenario), trace_path, bundle)
    ledger = episode.result()
    sim = episode.env.sim
    return {
        "policy": spec, "seed": seed, "reward": score(scenario, ledger, None)["reward"],
        **{k: ledger[k] for k in LEDGER_KEYS},
        "calls": ledger["calls"], "faults": episode.faults,
        "zone_harvest_kg": {z: round(zone.harvest, 1) for z, zone in sim.zones.items()},
        "cumulative_profit_eur": _profit_curve(sim),
    }


def _profit_curve(sim: Any) -> list[float]:
    """Sales minus costs at the end of each day, tests charged on the day they were ordered."""
    p, total, curve = sim.p, 0.0, []
    for record in sim.days:
        total += p.price_per_kg * sum(z["outcome"]["growth_kg"] for z in record["zones"].values())
        total -= sum(record["cost"].values())
        total -= p.test_price * sum(1 for t in sim.tests if t["sampled_day"] == record["day"])
        curve.append(round(total, 2))
    return curve


def comparators(scenario: Scenario, seed: int, data_dir: Path) -> dict[str, Any]:
    """Execute (or load the cached execution of) every comparator for one seed."""
    bundle = bundle_hash(source_files(scenario))
    directory = Path(data_dir) / "comparators" / f"{scenario.id}-s{int(seed)}-{bundle}"
    cache = directory / "results.json"
    if cache.is_file():
        try:
            cached = json.loads(cache.read_text())
            if cached.get("bundle") == bundle and len(cached.get("runs", [])) == len(COMPARATORS):
                return cached
        except (OSError, json.JSONDecodeError):
            pass
    directory.mkdir(parents=True, exist_ok=True)
    runs = []
    for spec, label, description in COMPARATORS:
        trace = directory / f"{spec}.jsonl"
        trace.unlink(missing_ok=True)
        runs.append({"label": label, "description": description,
                     "trace": str(trace), **run_comparator(scenario, seed, spec, trace)})
    out = {"scenario": scenario.id, "seed": int(seed), "bundle": bundle, "runs": runs,
           "note": "Each row was produced by running that policy on this scenario and seed through the simulator. "
                   "Traces are kept next to this file and replay to the same numbers."}
    cache.write_text(json.dumps(out, indent=1) + "\n")
    return out


def llm_results(root: Path, scenario_id: str, seed: int) -> dict[str, Any]:
    """Recorded model runs for this seed, if any exist. Never synthesized."""
    path = root / "docs" / "root-cause-evidence.json"
    runs: list[dict[str, Any]] = []
    if path.is_file():
        try:
            evidence = json.loads(path.read_text())
            runs = [r for r in evidence.get("llm_runs", []) if r.get("seed") == seed and r.get("scenario") == scenario_id]
        except (OSError, json.JSONDecodeError):
            runs = []
    if runs:
        return {"status": "recorded", "runs": runs}
    return {
        "status": "not_run",
        "reason": "No model run has been recorded for this scenario and seed. A model run needs the Docker "
                  "daemon, Harbor and a provider credential; none was available when this was built.",
        "command": f"harbor run -p tasks/{scenario_id}-s{seed} -a opencode -m <provider/model>",
    }
