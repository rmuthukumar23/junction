"""Benchmark report: a model's score on the greenhouse against the scripted ladder.

    uv run --no-sync python scripts/benchmark_report.py artifacts/benchmark-<time>

Reads the results `envkit eval` wrote (results.json and each trial's verifier
score.json), recomputes the scripted ladder for the same scenario and seeds
in-process (the same code the verifier runs), and writes benchmark.md:

  * the ladder: nobody acting (0) .. reference (0.8), with the model's runs placed in it;
  * the gap: reference minus the model's mean score;
  * per model run: profit, money by category next to the reference's, and the
    failure-mode evidence (fm_*) the verifier recorded.

Scores are on the scenario's anchored scale: 0 = nobody acts, 0.8 = the reference.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from envkit.calibrate import calibrate  # noqa: E402
from envkit.clients import run_inprocess  # noqa: E402
from envkit.policies import make_policy  # noqa: E402
from envkit.scenario import load_scenario  # noqa: E402

LADDER = ["do-nothing", "naive", "rule-based", "stop-early", "reference"]
LABELS = {"do-nothing": "Nobody acts", "naive": "Naive grower", "rule-based": "Rule-based grower",
          "stop-early": "Reference, stops early", "reference": "Reference planner"}
FAILURES = {
    "fm_unsellable_harvests": "harvests below sellable weight",
    "fm_harvests": "harvests sold or attempted",
    "fm_outages": "equipment outages",
    "fm_outages_never_repaired": "outages never repaired",
    "fm_mean_repair_response_h": "mean hours to request a repair",
    "fm_harvest_wait_h": "hours harvests waited for workers",
    "fm_tasks_never_done": "tasks never done",
    "fm_late_deliveries": "late deliveries",
    "fm_orders_placed": "orders placed",
    "fm_import_price_paid_eur_per_kwh": "EUR/kWh paid for imported power",
    "fm_import_price_mean_eur_per_kwh": "EUR/kWh average hourly price",
}


def trials(run_dir: Path) -> list[dict]:
    out = []
    for result in sorted(run_dir.glob("trials/*/*/result.json")):
        trial = result.parent
        score_path = trial / "verifier" / "score.json"
        score = json.loads(score_path.read_text()) if score_path.exists() else {}
        raw = json.loads(result.read_text())
        out.append({"job": trial.parent.name, "trial": trial.name, "reward": score.get("reward"),
                    "ledger": score.get("ledger", {}), "error": (raw.get("exception_info") or {}).get("exception_type"),
                    "verifier_error": score.get("error")})
    return out


def money(ledger: dict) -> dict[str, float]:
    return {k[len("money_"):-len("_eur")]: v for k, v in ledger.items()
            if k.startswith("money_") and k.endswith("_eur") and k != "money_conservation_error_eur"}


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    run_dir = Path(sys.argv[1])
    results = json.loads((run_dir / "results.json").read_text())
    scenario = load_scenario(ROOT / "scenarios" / f"{results['scenario']}.toml")
    seeds = sorted(int(s) for s in results.get("expected", {})) or list(scenario.seeds)
    runs = [t for t in trials(run_dir) if "agent" in t["job"]]
    lines = [f"# Benchmark: {results.get('model')} on {scenario.id}", "",
             f"Code `{results.get('git_commit', '?')[:10]}`, backend {results.get('backend')}, "
             f"seeds {seeds}, {len(runs)} model run(s), {results.get('batch_duration_seconds', 0) / 60:.1f} min.",
             "Scale: 0 = nobody acts, 0.80 = the reference planner. Higher is better.", ""]
    for seed in seeds:
        entry = calibrate(scenario, seed)
        anchors = entry["anchors"]
        seed_runs = [t for t in runs if t["job"].startswith(f"s{seed}-")]
        scored = [t["reward"] for t in seed_runs if t["reward"] is not None]
        rows = [(LABELS[p], anchors[p]["reward"]) for p in LADDER if p in anchors]
        rows += [(f"**{results.get('model')}** ({t['trial']})", t["reward"]) for t in seed_runs if t["reward"] is not None]
        lines += [f"## Seed {seed}", "", "| Player | Score |", "|---|---:|"]
        lines += [f"| {name} | {score:.3f} |" for name, score in sorted(rows, key=lambda r: r[1])]
        if scored:
            mean = statistics.mean(scored)
            gap = anchors["reference"]["reward"] - mean
            lines += ["", f"**Gap: reference {anchors['reference']['reward']:.3f} - model mean {mean:.3f} = {gap:+.3f}** "
                          f"({'the model is below the reference' if gap > 0 else 'the model matches or beats the reference'})."]
        for t in seed_runs:
            if t["reward"] is None:
                lines += ["", f"Run {t['trial']}: **no score** ({t['verifier_error'] or t['error']}): an infrastructure "
                              "failure (key, model id, provider or container), not an agent result. "
                              "See agent/opencode.txt in the trial folder."]
        # Where the money went: the model's runs next to the reference.
        ref = run_inprocess(scenario, seed, make_policy("reference", scenario)).result()
        cats = sorted({c for t in seed_runs for c in money(t["ledger"])} | set(money(ref)))
        if any(t["ledger"] for t in seed_runs):
            header = "| EUR | Reference | " + " | ".join(t["trial"][-6:] for t in seed_runs if t["ledger"]) + " |"
            lines += ["", "### Where the money went", "", header, "|---|---:|" + "---:|" * sum(1 for t in seed_runs if t["ledger"])]
            lines.append("| **profit** | " + f"{ref['profit_eur']:,.0f} | " +
                         " | ".join(f"{t['ledger'].get('profit_eur', 0):,.0f}" for t in seed_runs if t["ledger"]) + " |")
            for c in cats:
                vals = [money(t["ledger"]).get(c, 0.0) for t in seed_runs if t["ledger"]]
                if abs(money(ref).get(c, 0.0)) < 0.5 and all(abs(v) < 0.5 for v in vals):
                    continue
                lines.append(f"| {c} | {money(ref).get(c, 0.0):,.0f} | " + " | ".join(f"{v:,.0f}" for v in vals) + " |")
            lines += ["", "### Failure evidence (from hidden state, after the run)", "",
                      "| Signal | Reference | " + " | ".join(t["trial"][-6:] for t in seed_runs if t["ledger"]) + " |",
                      "|---|---:|" + "---:|" * sum(1 for t in seed_runs if t["ledger"])]
            for key, label in FAILURES.items():
                vals = [t["ledger"].get(key) for t in seed_runs if t["ledger"]]
                fmt = (lambda v: "-" if v is None else (f"{v:.3f}" if "price" in key else f"{v:g}"))
                lines.append(f"| {label} | {fmt(ref.get(key))} | " + " | ".join(fmt(v) for v in vals) + " |")
            extra = [(t["trial"][-6:], t["ledger"].get("calls"), t["ledger"].get("end_reason"), t["ledger"].get("bankrupt"))
                     for t in seed_runs if t["ledger"]]
            lines += [""] + [f"Run {n}: {c} tool calls, ended by {e}" + (", **went bankrupt**" if b else "") + "."
                             for n, c, e, b in extra]
        lines.append("")
    report = "\n".join(lines) + "\n"
    (run_dir / "benchmark.md").write_text(report)
    print(report)
    print(f"Written to {run_dir / 'benchmark.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
