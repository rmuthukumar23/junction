"""Play every scripted comparator on one or more seeds and print profit, reward
and the failure modes read from hidden state after the run.

    PYTHONPATH=src python3 scripts/compare.py              # committed seed 7
    PYTHONPATH=src python3 scripts/compare.py 1 2 3 --json out.json

Credential-free and in-process: the same engine and scoring the verifier uses.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from envkit.clients import run_inprocess  # noqa: E402
from envkit.policies import make_policy  # noqa: E402
from envkit.scenario import load_scenario  # noqa: E402
from rootcause import outcome  # noqa: E402

POLICIES = [("do-nothing", "Do nothing (default plan)"),
            ("stop-early", "Stop early (reference, then default)"),
            ("ec-rules", "EC rules (reads EC as nutrient)"),
            ("blind", "Blind planner (ignores the notice)"),
            ("reference", "Reference (diagnoses, then plans)")]


def run(seed: int) -> list[dict]:
    scenario = load_scenario(ROOT / "scenarios" / "root-cause.toml")
    rows = []
    for name, label in POLICIES:
        ep = run_inprocess(scenario, seed, make_policy(name, scenario))
        ledger = ep.result()
        fm = outcome.failure_modes(ep.env.sim)
        rows.append({"seed": seed, "policy": name, "label": label, "reward": ledger["normalized_profit"],
                     "profit_eur": ledger["profit_eur"], "floor_eur": ledger["profit_floor_eur"],
                     "informed_eur": ledger["profit_informed_eur"], "calls": ledger["calls"],
                     "failure_modes": fm})
    return rows


def show(rows: list[dict]) -> None:
    r0 = rows[0]
    print(f"seed {r0['seed']}: floor €{r0['floor_eur']:.2f}, informed €{r0['informed_eur']:.2f}")
    print(f"  {'policy':<38}{'reward':>7}{'profit':>10}{'calls':>6}  first test  dominant loss  lost € (dmg/water/nutr/salt)"
          "  short-N  salt  fed-less  flushed  reserve")
    for r in rows:
        fm = r["failure_modes"]
        lost = fm["crop_lost_eur"]
        first = "-" if fm["days_to_first_test"] is None else f"+{fm['days_to_first_test']}d"
        print(f"  {r['label']:<38}{r['reward']:>7.3f}{r['profit_eur']:>10.2f}{r['calls']:>6}  {first:>10}  "
              f"{fm['dominant_loss']:>13}  {lost['carried_damage']:>6.1f}/{lost['water']:.1f}/{lost['nutrient']:.1f}/"
              f"{lost['salinity']:.1f}  {fm['nutrient_short_bench_days']:>7}{fm['salt_stress_bench_days']:>6}"
              f"{fm['fed_less_while_short_bench_days']:>10}{fm['flushed_after_incident_l']:>9.0f}"
              f"{fm['reserve_used_l']:>9.0f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("seeds", nargs="*", type=int, default=[7])
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    everything = []
    for seed in a.seeds:
        rows = run(seed)
        show(rows)
        everything += rows
    if len(a.seeds) > 1:
        print("mean reward:", {name: round(sum(r["reward"] for r in everything if r["policy"] == name) / len(a.seeds), 3)
                               for name, _ in POLICIES})
    if a.json:
        a.json.write_text(json.dumps(everything, indent=1) + "\n")


if __name__ == "__main__":
    main()
