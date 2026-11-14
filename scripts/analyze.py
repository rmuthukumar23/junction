"""Explain every Harbor trial of a judge run: what happened, why it scored what it did.

    PYTHONPATH=src python3 scripts/analyze.py artifacts/judge          # writes artifacts/judge/analysis.md

For each trial it finds the sidecar's collected trace.jsonl, replays it in
process with the same engine the verifier uses (so the numbers are the
verifier's), and reports:

  * reward, profit, and the failure modes read from hidden state;
  * a day-by-day table of what the player did and what was really in each
    bench (salt and nutrient, which the player could not see without a test);
  * what the agent wrote, if its logs contain text (OpenCode transcripts).

Nothing here affects a score: it reads traces after grading.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from envkit.core import replay  # noqa: E402
from envkit.scenario import load_scenario  # noqa: E402
from envkit.trace import read_trace  # noqa: E402
from rootcause import outcome  # noqa: E402

SCENARIO = load_scenario(ROOT / "scenarios" / "root-cause.toml")
PASS = 0.5   # recovered at least half of what knowing the root cause at once is worth
EXPLAIN = {
    "salinity": "salt from the backup water built up and cut growth (the reserve was not used enough)",
    "nutrient": "the crop ran short of nutrient; typically feeding was cut because rising EC was read as nutrient",
    "water": "benches ran low on solution",
    "carried_damage": "earlier stress lowered crop condition, which recovers slowly",
    "none": "no material loss",
}


def label_of(trial: Path) -> str:
    return trial.parent.name


def agent_text(trial: Path, limit: int = 12) -> list[str]:
    """Best-effort: pull text the agent wrote from its logs."""
    out: list[str] = []
    for path in sorted((trial / "agent").rglob("*")) if (trial / "agent").exists() else []:
        if not path.is_file() or path.stat().st_size > 20_000_000:
            continue
        try:
            raw = path.read_text(errors="replace")
        except OSError:
            continue
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for text in _texts(obj):
                    if len(text) > 40:
                        out.append(text)
    seen, unique = set(), []
    for t in out:
        key = t[:120]
        if key not in seen:
            seen.add(key)
            unique.append(re.sub(r"\s+", " ", t)[:600])
    return unique[-limit:]


def _texts(obj: object) -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        if obj.get("type") == "text" and isinstance(obj.get("text"), str):
            found.append(obj["text"])
        for v in obj.values():
            found += _texts(v)
    elif isinstance(obj, list):
        for v in obj:
            found += _texts(v)
    return found


def day_table(sim) -> list[str]:
    rows = ["| day | mains salt g/L | bench | plan: mains / reserve / fert / flush | EC seen | true salt / nutrient g/L | "
            "salt f | nutr f | growth kg |", "|---|---:|---|---|---:|---|---:|---:|---:|"]
    for rec in sim.days:
        d = rec["day"]
        for z, br in rec["benches"].items():
            pl, t = br["plan"], br["truth"]
            truth = sim.truth[d][z]
            rows.append(f"| {d} | {sim.instance.mains_salt(d):.2f} | {z} | {pl['mains_l']:.0f} / {pl['reserve_l']:.0f} / "
                        f"{pl['fertilizer_g']:.0f} / {pl['flush_l']:.0f} | {sim.mornings[d][z]['ec_ds_m']:.2f} | "
                        f"{truth['salt_g_l']:.2f} / {truth['nutrient_g_l']:.2f} | {t['salinity_factor']:.2f} | "
                        f"{t['nutrient_factor']:.2f} | {br['outcome']['growth_kg']:.1f} |")
    return rows


def analyze(trial: Path) -> dict | None:
    traces = sorted(trial.rglob("trace.jsonl"))
    if not traces:
        return None
    records = read_trace(traces[0])
    header = next((r for r in records if r.get("k") == "header"), {})
    seed = int(header.get("seed", SCENARIO.seeds[0]))
    episode, mismatches = replay(SCENARIO, seed, records)
    ledger = episode.result()
    sim = episode.env.sim
    calls = [r for r in records if r.get("k") == "call"]
    return {"trial": trial, "label": label_of(trial), "seed": seed, "ledger": ledger,
            "modes": outcome.failure_modes(sim), "sim": sim, "calls": len(calls),
            "tools": [r.get("tool") for r in calls], "mismatches": len(mismatches),
            "text": agent_text(trial)}


def render(results: list[dict]) -> str:
    lines = ["# Root Cause: trial analysis", "",
             "Each trial's trace was replayed with the verifier's engine. Hidden state (true salt and nutrient, "
             "the backup water's salinity) is shown here for analysis only; no player saw it during play.", "",
             f"A trial **passes** at reward >= {PASS}: it recovered at least half of what knowing the root cause at "
             "once is worth. The reference passes on every seed; the blind planner and EC rules on none.", "",
             "| trial | pass | reward | profit € | calls | first test after notice | mains test day | dominant loss | "
             "fed less while short (bench-days) | salt-stress bench-days | flushed after incident L | reserve used L |",
             "|---|---|---:|---:|---:|---|---|---|---:|---:|---:|---:|"]
    for r in results:
        fm, lg = r["modes"], r["ledger"]
        first = "never" if fm["days_to_first_test"] is None else f"+{fm['days_to_first_test']} d"
        mains = "never" if fm["mains_test_day"] is None else f"day {fm['mains_test_day']}"
        verdict = "yes" if lg["normalized_profit"] >= PASS else "no"
        lines.append(f"| {r['label']} | {verdict} | {lg['normalized_profit']:.3f} | {lg['profit_eur']:.2f} | {r['calls']} | {first} | "
                     f"{mains} | {fm['dominant_loss']} | {fm['fed_less_while_short_bench_days']} | "
                     f"{fm['salt_stress_bench_days']} | {fm['flushed_after_incident_l']:.0f} | {fm['reserve_used_l']:.0f} |")
    if results:
        lg = results[0]["ledger"]
        lines += ["", f"Scale: 0 = default plan (€{lg['profit_floor_eur']:.2f}), 1 = informed planner "
                      f"(€{lg['profit_informed_eur']:.2f}), which knows the backup salinity from the notice on."]
    for r in results:
        fm, lg = r["modes"], r["ledger"]
        if r["calls"] == 0 and "agent" in r["label"]:
            lines += ["", f"## {r['label']} ({r['trial'].name})", "",
                      "**No tool calls: the model never played.** This is almost always a provider problem (bad key, "
                      "unknown model id, quota), not an agent result. Check the trial's agent log under `agent/`.", ""]
            continue
        lines += ["", f"## {r['label']} ({r['trial'].name})", "",
                  f"Reward **{lg['normalized_profit']:.3f}**, profit €{lg['profit_eur']:.2f}, {r['calls']} calls, "
                  f"replay {'consistent' if r['mismatches'] == 0 else str(r['mismatches']) + ' mismatches'}.", "",
                  f"Main loss: **{fm['dominant_loss']}**: {EXPLAIN[fm['dominant_loss']]}.", "",
                  "Crop value lost, by cause (€): " + ", ".join(f"{k} {v:.1f}" for k, v in fm["crop_lost_eur"].items()),
                  "", f"Backup water held {r['sim'].instance.backup_salt_g_l:.2f} g/L salt from day "
                      f"{fm['incident_day']} (usual {r['sim'].p.mains_salt_g_l:.2f}).", ""]
        lines += day_table(r["sim"])
        if r["text"]:
            lines += ["", "What the agent wrote (last messages found in its logs):", ""]
            lines += [f"> {t}" for t in r["text"]]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path, help="the --output directory of scripts/judge.sh")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    trials = sorted(p.parent for p in a.run_dir.rglob("result.json") if p.parent.parent.parent.name == "trials")
    results = [r for r in (analyze(t) for t in trials) if r is not None]
    if not results:
        raise SystemExit(f"no collected traces under {a.run_dir}")
    out = a.out or a.run_dir / "analysis.md"
    out.write_text(render(results))
    print(render(results).split("\n## ")[0])
    print(f"Written to {out}")


if __name__ == "__main__":
    main()
