"""Run the comparator policies over a seed suite and record what actually happened.

    python -m rootcause_app.evaluate --suite evaluation
    python -m rootcause_app.evaluate --suite all --evidence docs/root-cause-evidence.json

Suites: demo (seed 7), development (1-6, used to tune the mechanics) and
evaluation (101-108, never used for tuning). Every row is a real run through the
simulator; traces are written next to the results and replay to the same numbers.

`--evidence FILE` also writes the compact, committed record: code version, bundle
hash, every row, suite means, a what-if analysis of one trace, and the state of
model runs (none are invented: if no model was run, it says so and why).
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

from envkit.bundle import ROOT, bundle_hash, source_files
from envkit.trace import read_trace

from rootcause.generator import generate

from . import DEMO_SEED, DEVELOPMENT_SEEDS, EVALUATION_SEEDS
from .analysis import counterfactuals
from .compare import COMPARATORS, run_comparator
from .store import load_default_scenario

SUITES = {"demo": (DEMO_SEED,), "development": DEVELOPMENT_SEEDS, "evaluation": EVALUATION_SEEDS}
MODEL_PREREQUISITES = [
    "a running Docker (or Podman) daemon for Harbor's Compose sidecar",
    "a provider credential in the environment (for example OPENAI_API_KEY or ANTHROPIC_API_KEY)",
    "an event-approved model identifier",
]


def code_version() -> dict[str, Any]:
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, cwd=ROOT, stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True, cwd=ROOT).strip())
        return {"code_sha": sha, "working_tree_dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"code_sha": "unknown", "working_tree_dirty": True}


def describe_instance(config: dict[str, Any], seed: int) -> dict[str, Any]:
    """Facts about a seed's instance, for explaining results. Hidden during play."""
    inst = generate(config, seed)
    return {"seed": seed, "fresh_water_l": inst.fresh_water_l,
            "zones": {z.id: z.composition for z in inst.zones},
            "hottest_day": max(range(len(inst.temps)), key=lambda d: inst.temps[d]), "peak_temp_c": max(inst.temps),
            "mean_temp_c": round(sum(inst.temps) / len(inst.temps), 1)}


def run_suite(name: str, out: Path) -> dict[str, Any]:
    scenario = load_default_scenario()
    rows = []
    for seed in SUITES[name]:
        for spec, label, _ in COMPARATORS:
            trace = out / "traces" / f"s{seed}-{spec}.jsonl"
            trace.parent.mkdir(parents=True, exist_ok=True)
            trace.unlink(missing_ok=True)
            started = time.monotonic()
            row = run_comparator(scenario, seed, spec, trace)
            row.pop("cumulative_profit_eur")
            rows.append({"suite": name, "label": label, "seconds": round(time.monotonic() - started, 2), **row})
    means = {}
    for spec, label, _ in COMPARATORS:
        mine = [r for r in rows if r["policy"] == spec]
        means[spec] = {"label": label, "runs": len(mine),
                       "mean_reward": round(sum(r["reward"] for r in mine) / len(mine), 4),
                       "min_reward": min(r["reward"] for r in mine), "max_reward": max(r["reward"] for r in mine),
                       "mean_profit_eur": round(sum(r["profit_eur"] for r in mine) / len(mine), 2)}
    return {"suite": name, "seeds": list(SUITES[name]), "rows": rows, "means": means,
            "instances": [describe_instance(dict(scenario.env_config), s) for s in SUITES[name]]}


def format_suite(result: dict[str, Any]) -> str:
    specs = [spec for spec, _, _ in COMPARATORS]
    lines = [f"Suite: {result['suite']}   (profit EUR / reward)", "  seed  " + "".join(f"{s:>22}" for s in specs)]
    for seed in result["seeds"]:
        cells = []
        for spec in specs:
            r = next(x for x in result["rows"] if x["seed"] == seed and x["policy"] == spec)
            cells.append(f"{r['profit_eur']:>13.0f} / {r['reward']:.3f}")
        lines.append(f"  {seed:>4}  " + "".join(f"{c:>22}" for c in cells))
    lines.append("  mean  " + "".join(f"{result['means'][s]['mean_profit_eur']:>13.0f} / {result['means'][s]['mean_reward']:.3f}"
                                      for s in specs))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rootcause_app.evaluate", description=__doc__.split("\n")[0])
    ap.add_argument("--suite", choices=[*SUITES, "all"], default="evaluation")
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts" / "rootcause" / "eval")
    ap.add_argument("--evidence", type=Path, help="also write the compact record to this file")
    a = ap.parse_args(argv)

    scenario = load_default_scenario()
    names = list(SUITES) if a.suite == "all" else [a.suite]
    results = {}
    for name in names:
        results[name] = run_suite(name, a.out / name)
        print(format_suite(results[name]), end="\n\n")
    faults = sum(r["faults"] for res in results.values() for r in res["rows"])
    unbalanced = sum(1 for res in results.values() for r in res["rows"] if r["conservation_ok"] != 1.0)
    print(f"internal errors: {faults}   runs whose balances did not close: {unbalanced}")

    record = {"scenario": scenario.id, "bundle": bundle_hash(source_files(scenario)), **code_version(),
              "python": platform.python_version(), "suites": results}
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "results.json").write_text(json.dumps(record, indent=1) + "\n")
    print(f"results and traces: {a.out}")

    if a.evidence:
        # One worked what-if: the rule-based policy on the demo seed, because its
        # mistakes are the ones the benchmark is about.
        if "demo" not in results:
            results["demo"] = run_suite("demo", a.out / "demo")
        trace = read_trace(a.out / "demo" / "traces" / f"s{DEMO_SEED}-rule-based.jsonl")
        whatif = counterfactuals(scenario, DEMO_SEED, trace)
        previous_models: list[Any] = []
        if a.evidence.is_file():   # keep model runs that were recorded earlier
            try:
                previous_models = json.loads(a.evidence.read_text()).get("llm_runs", [])
            except (OSError, json.JSONDecodeError):
                previous_models = []
        evidence = {**record, "suites": results,
                    "whatif_rule_based_demo": whatif,
                    "llm_runs": previous_models,
                    "llm_status": "recorded" if previous_models else "not_run",
                    "llm_missing_prerequisites": [] if previous_models else MODEL_PREREQUISITES,
                    "llm_command": f"harbor run -p tasks/{scenario.id}-s{DEMO_SEED} -a opencode -m <provider/model>"}
        a.evidence.write_text(json.dumps(evidence, indent=1) + "\n")
        print(f"evidence: {a.evidence}")
    return 1 if faults or unbalanced else 0


if __name__ == "__main__":
    raise SystemExit(main())
