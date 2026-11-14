"""Read Harbor trials without discarding failures or trusting agent files.

A trial's score comes from the verifier's score.json, which was computed by
replaying the sidecar's trace. Each trial gets one of three statuses:

  completed               the agent played until the episode ended
  interrupted             the agent stopped, timed out or hit a model limit;
                          work done before that keeps its credit
  infrastructure_failure  the harness, provider or verifier failed; the trial
                          has no score and says nothing about the agent
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

AGENT_FAILURES = {"AgentTimeoutError", "NonZeroAgentExitCodeError", "ContextWindowExceededError",
                  "OutputTokenExceededError", "ContextLengthExceededError", "OutputLengthExceededError",
                  "AgentSafetyRefusalError", "ContentPolicyViolationError"}
RATE_LIMITS = {"ApiRateLimitError", "RateLimitError"}


def read_trial(result_path: Path) -> dict[str, Any]:
    trial = result_path.parent
    raw = json.loads(result_path.read_text())
    error_type = (raw.get("exception_info") or {}).get("exception_type")
    status = "interrupted" if error_type in AGENT_FAILURES else "completed"
    if error_type and error_type not in AGENT_FAILURES:
        status = "infrastructure_failure"

    score: dict[str, Any] = {}
    reward, problem = None, None
    try:
        score = json.loads((trial / "verifier" / "score.json").read_text())
        harbor_reward = ((raw.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        if score.get("reward") is None:
            raise ValueError("the verifier could not grade the trace")
        if harbor_reward is None or abs(float(harbor_reward) - float(score["reward"])) > 1e-9:
            raise ValueError("Harbor's reward differs from the verifier's score.json")
        if not (score.get("replay") or {}).get("consistent", False):
            raise ValueError("the trace did not reproduce on replay")
        if status != "infrastructure_failure":
            reward = float(score["reward"])
    except (OSError, ValueError, TypeError, KeyError) as exc:
        status, problem = "infrastructure_failure", str(exc)

    ledger = score.get("ledger") or {}
    if status == "completed" and ledger.get("stopped_early"):
        status = "interrupted"
    duration = None
    if raw.get("started_at") and raw.get("finished_at"):
        duration = (datetime.fromisoformat(raw["finished_at"]) - datetime.fromisoformat(raw["started_at"])).total_seconds()
    agent = raw.get("agent_info") or {}
    timeline = score.get("timeline") or []
    return {
        "job": trial.parent.name,
        "trial": trial.name,
        "task": raw.get("task_name"),
        "scenario": score.get("scenario"),
        "seed": score.get("seed"),
        "bundle": score.get("bundle"),
        "agent": agent.get("name"),
        "model": (agent.get("model_info") or {}).get("name"),
        "reward": reward,
        "status": status,
        "stop_reason": error_type or ledger.get("end_reason"),
        "provider_rate_limit": error_type in RATE_LIMITS,
        "error_type": error_type,
        "verification_error": problem,
        "components": score.get("components") or {},
        "passed": score.get("passed"),
        "calls": ledger.get("calls"),
        "rejected": ledger.get("rejected"),
        "duration_seconds": duration,
        "notes": score.get("notes") or [],
        "final": timeline[-1] if timeline else None,
        "trace_path": str(trial),
    }


def collect(jobs_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for result_path in sorted(jobs_dir.rglob("result.json")):
        trial = result_path.parent
        if not (trial / "verifier").is_dir() and not (trial / "agent").is_dir():
            continue  # a job-level result.json
        try:
            rows.append(read_trial(result_path))
        except (OSError, json.JSONDecodeError):
            continue
    return rows


def format_report(rows: list[dict[str, Any]]) -> str:
    """A terminal table: one line per trial, then per-job means and the gap."""
    if not rows:
        return "no trial results found."
    comp_names = list(dict.fromkeys(k for r in rows for k in r["components"]))
    lines = [f"{'job':18}{'agent':10}{'model':22}{'reward':>8}"
             + "".join(f"{n[:13]:>14}" for n in comp_names) + f"{'calls':>7}  status"]
    for r in rows:
        reward = "   infra" if r["reward"] is None else f"{r['reward']:>8.4f}"
        detail = [r["status"]]
        if r["verification_error"]:
            detail.append(r["verification_error"])
        elif r["error_type"]:
            detail.append(r["error_type"])
        detail += r["notes"]
        lines.append(f"{r['job'][:17]:18}{(r['agent'] or '')[:9]:10}{(r['model'] or '-')[:21]:22}{reward}"
                     + "".join(f"{r['components'].get(n, float('nan')):>14.4f}" for n in comp_names)
                     + f"{'' if r['calls'] is None else r['calls']:>7}  {'; '.join(detail)}")
    lines.append("")
    by_job: dict[str, list[float]] = {}
    for r in rows:
        if r["reward"] is not None:
            by_job.setdefault(r["job"], []).append(r["reward"])
    for job, values in by_job.items():
        spread = (f" (min {min(values):.4f}, max {max(values):.4f}, sd {statistics.pstdev(values):.4f})"
                  if len(values) > 1 else "")
        lines.append(f"{job:18} n={len(values)}  mean {statistics.fmean(values):.4f}{spread}")
    for seed_job in [j for j in by_job if j.endswith("-reference")]:
        agent_job = seed_job.removesuffix("-reference") + "-agent"
        if agent_job in by_job:
            ref, agent = statistics.fmean(by_job[seed_job]), by_job[agent_job]
            lines.append(f"{agent_job}: gap to reference {ref - statistics.fmean(agent):+.4f}; "
                         f"runs below the reference: {sum(v < ref for v in agent)}/{len(agent)}")
    return "\n".join(lines)


def summarize(rows: list[dict[str, Any]]) -> str:
    """The Markdown report written next to results.json."""
    lines = ["# Harbor evaluation", "", "Event-kit compatibility and the performance gap require review.", "",
             "| Run | Agent | Scores (all attempts) | Mean | Std dev | Infra failures |",
             "|---|---|---|---:|---:|---:|"]
    for job in dict.fromkeys(r["job"] for r in rows):
        group = [r for r in rows if r["job"] == job]
        scores = [r["reward"] for r in group if r["reward"] is not None]
        shown = ", ".join("infra" if r["reward"] is None else f"{r['reward']:.4f}" for r in group)
        mean = f"{statistics.fmean(scores):.4f}" if scores else "—"
        stdev = f"{statistics.pstdev(scores):.4f}" if scores else "—"
        lines.append(f"| {job} | {group[0]['agent'] or '—'} | {shown} | {mean} | {stdev} | {len(group) - len(scores)} |")
    for r in rows:
        table = (r.get("final") or {}).get("table")
        lines.extend(["", f"## {r['job']}: {r['trial']} ({r['status']})", "",
                      f"Reward {'none' if r['reward'] is None else format(r['reward'], '.4f')}; "
                      f"stop reason {r['stop_reason']}; calls {r['calls']}; rejected {r['rejected']}. "
                      f"Trace: `{r['trace_path']}`"])
        if r["verification_error"]:
            lines.append(f"Verification error: {r['verification_error']}")
        if isinstance(table, list) and table and all(isinstance(x, dict) for x in table):
            columns = list(table[0])
            lines.extend(["", "| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)])
            for entry in table:
                lines.append("| " + " | ".join("—" if entry.get(c) is None else str(entry.get(c)) for c in columns) + " |")
    lines.extend(["", "These tables describe outcomes. Attribute an agent's mistakes only after reading its actual tool decisions."])
    return "\n".join(lines) + "\n"
