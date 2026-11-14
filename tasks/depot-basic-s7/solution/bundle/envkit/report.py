"""Summarize Harbor results.

Walks a jobs directory (jobs/<job>/<trial>/), reads each trial's reward and
the verifier's score.json, and prints one row per trial plus a per-job
summary and the gap between the reference run and the agent runs.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any


def collect(jobs_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for result_path in sorted(jobs_dir.rglob("result.json")):
        trial = result_path.parent
        if not (trial / "verifier").is_dir() and not (trial / "agent").is_dir():
            continue  # the job-level result.json
        try:
            result = json.loads(result_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        score: dict[str, Any] = {}
        score_path = trial / "verifier" / "score.json"
        if score_path.exists():
            try:
                score = json.loads(score_path.read_text())
            except json.JSONDecodeError:
                pass
        rewards = (result.get("verifier_result") or {}).get("rewards") or {}
        agent = result.get("agent_info") or {}
        model = (agent.get("model_info") or {}).get("name")
        ledger = score.get("ledger") or {}
        exc = result.get("exception_info") or {}
        rows.append({
            "job": trial.parent.name,
            "trial": trial.name,
            "task": result.get("task_name"),
            "agent": agent.get("name"),
            "model": model,
            "reward": rewards.get("reward"),
            "components": score.get("components") or {},
            "passed": score.get("passed"),
            "calls": ledger.get("calls"),
            "windows_acted": ledger.get("windows_acted"),
            "windows_total": ledger.get("windows_total"),
            "end_reason": ledger.get("end_reason"),
            "stopped_early": ledger.get("stopped_early"),
            "replay_consistent": (score.get("replay") or {}).get("consistent"),
            "notes": score.get("notes") or [],
            "exception": exc.get("exception_type") if isinstance(exc, dict) else None,
        })
    return rows


def format_report(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "no trial results found."
    comp_names = list(dict.fromkeys(k for r in rows for k in r["components"]))
    lines = [f"{'job':12}{'agent':10}{'model':24}{'reward':>8}"
             + "".join(f"{n:>13}" for n in comp_names) + f"{'windows':>9}{'calls':>7}  notes"]
    for r in rows:
        reward = "   error" if r["reward"] is None else f"{r['reward']:>8.4f}"
        windows = "" if r["windows_total"] is None else f"{r['windows_acted']}/{r['windows_total']}"
        notes = []
        if r["exception"]:
            notes.append(r["exception"])
        if r["replay_consistent"] is False:
            notes.append("replay mismatch")
        notes += r["notes"]
        lines.append(f"{r['job'][:11]:12}{(r['agent'] or '')[:9]:10}{(r['model'] or '-')[:23]:24}{reward}"
                     + "".join(f"{r['components'].get(n, float('nan')):>13.4f}" for n in comp_names)
                     + f"{windows:>9}{'' if r['calls'] is None else r['calls']:>7}  {'; '.join(notes)}")

    lines.append("")
    by_job: dict[str, list[float]] = {}
    for r in rows:
        if r["reward"] is not None:
            by_job.setdefault(r["job"], []).append(float(r["reward"]))
    for job, values in by_job.items():
        spread = f" (min {min(values):.4f}, max {max(values):.4f}, sd {statistics.pstdev(values):.4f})" if len(values) > 1 else ""
        lines.append(f"{job:12} n={len(values)}  mean {statistics.fmean(values):.4f}{spread}")
    if "reference" in by_job and "agent" in by_job:
        ref, agent = statistics.fmean(by_job["reference"]), by_job["agent"]
        lines.append("")
        lines.append(f"gap (reference - agent mean): {ref - statistics.fmean(agent):+.4f}; "
                     f"agent runs below the reference: {sum(v < ref for v in agent)}/{len(agent)}")
    return "\n".join(lines)
