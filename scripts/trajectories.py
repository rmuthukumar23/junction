"""Readable day-by-day logs from the agents' Harbor trajectories.

    .venv/bin/python scripts/trajectories.py

For each run in runs/normal-winter/<run>/, reads trajectory.json (Harbor's ATIF trajectory:
the agent's message, tool calls and observations per step) and trace.jsonl (what the
simulator recorded), and writes runs/normal-winter/<run>/DAYS.md: one row per day with
what the agent said, what it did, which actions were refused, and the cash after the day.
Also writes runs/TRAJECTORIES.md, an index with one line per run.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs" / "normal-winter"


def short(action: dict) -> str:
    a = {k: v for k, v in action.items() if k != "tool"}
    t = action.get("tool", "?")
    if t == "harvest":
        return f"harvest {', '.join(a.get('batch_ids', []))}"
    if t == "plant":
        return "plant " + ", ".join(f"{k} {v:,.0f} m²" for k, v in (a.get("areas_m2") or {}).items())
    if t == "place_orders":
        lines = dict(a.get("orders") or {})
        for line in a.get("order_list") or []:
            lines[line.get("item")] = line.get("quantity")
        return "order " + ", ".join(f"{k} {v:,.0f}" for k, v in lines.items())
    if t == "book_contractor":
        return f"contractor {a.get('trade')} → {a.get('target')}"
    keys = ", ".join(f"{k}={json.dumps(v)}" for k, v in a.items() if k != "lamp_hours")
    if "lamp_hours" in a:
        keys += f", lamps {len(a['lamp_hours'])} h"
    return f"{t} {keys}"[:140]


def days(run: Path) -> list[dict]:
    traj = json.loads((run / "trajectory.json").read_text()) if (run / "trajectory.json").exists() else {"steps": []}
    said = []
    for step in traj.get("steps", []):
        if step.get("source") != "agent":
            continue
        for call in step.get("tool_calls") or []:
            if call.get("function_name", "").endswith("submit_day"):
                said.append(str(step.get("message") or "").strip().replace("\n", " "))
    rows = []
    calls = [json.loads(line) for line in (run / "trace.jsonl").read_text().splitlines() if '"k":"call"' in line or '"k": "call"' in line]
    for i, c in enumerate(calls):
        r = c.get("response", {})
        acts = c.get("args", {}).get("actions", [])
        res = r.get("result", {}).get("results", []) if r.get("ok") else []
        refused = [f"{a.get('tool')}: {str(x.get('error'))[:90]}" for a, x in zip(acts, res) if not x.get("ok")]
        if not r.get("ok"):
            refused.append(f"whole call: {str(r.get('error'))[:90]}")
        rows.append({"day": i + 1, "said": said[i] if i < len(said) else "", "did": [short(a) for a in acts],
                     "refused": refused, "cash": r.get("header", {}).get("cash_eur")})
    return rows


def main() -> int:
    index = ["# Agent trajectories", "", "Each run's full Harbor trajectory is `trajectory.json` in its folder; `DAYS.md` is the readable",
             "day-by-day version (what the agent said, what it did, what was refused, cash after the day).", "",
             "| Run | Score | Days | Actions | Refused | Day-by-day |", "|---|---:|---:|---:|---:|---|"]
    for run in sorted(p for p in RUNS.iterdir() if p.is_dir()):
        rows = days(run)
        meta = json.loads((run / "meta.json").read_text())
        out = [f"# {meta['model']}, seed {meta['seed']}: score {meta['reward']}, profit €{meta['profit_eur']:,.0f}", "",
               "| Day | What the agent said | What it did | Refused | Cash € |", "|---:|---|---|---|---:|"]
        for r in rows:
            said = r["said"][:300].replace("|", "/") + ("…" if len(r["said"]) > 300 else "")
            out.append(f"| {r['day']} | {said} | {'<br>'.join(r['did']) or '(nothing)'} | {'<br>'.join(r['refused']).replace('|', '/')} | {r['cash'] or 0:,.0f} |")
        (run / "DAYS.md").write_text("\n".join(out) + "\n")
        n_act = sum(len(r["did"]) for r in rows)
        n_ref = sum(len(r["refused"]) for r in rows)
        index.append(f"| {run.name} | {meta['reward']} | {len(rows)} | {n_act} | {n_ref} | [DAYS.md](normal-winter/{run.name}/DAYS.md) |")
    (ROOT / "runs" / "TRAJECTORIES.md").write_text("\n".join(index) + "\n")
    print("\n".join(index))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
