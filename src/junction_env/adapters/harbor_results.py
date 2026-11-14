"""Normalize Harbor trials without discarding failures or trusting agent files."""
from datetime import datetime
import json
from pathlib import Path
import statistics

from junction_env.scheduling import Instance
from junction_env.scheduling.verifier import verify_record


AGENT_FAILURES = {"AgentTimeoutError", "NonZeroAgentExitCodeError", "ContextWindowExceededError",
                  "OutputTokenExceededError", "ContextLengthExceededError", "OutputLengthExceededError",
                  "AgentSafetyRefusalError", "ContentPolicyViolationError"}


def read_trial(path: Path, instance: Instance, policy: str, model: str | None) -> dict:
    raw = json.loads(path.read_text())
    exception = raw.get("exception_info") or {}
    error_type = exception.get("exception_type")
    status = "interrupted" if error_type in AGENT_FAILURES else "completed"
    if error_type and error_type not in AGENT_FAILURES:
        status = "infrastructure_failure"
    record_path = path.parent / "artifacts/trusted/episode.json"
    score, record, verification_error = None, None, None
    try:
        record = json.loads(record_path.read_text())
        actual = verify_record(record, instance)
        if status == "completed" and record["final"]["termination"] == "harness_interruption":
            status = "interrupted"
        rewards = (raw.get("verifier_result") or {}).get("rewards") or {}
        if rewards.get("reward") != actual:
            raise ValueError("Harbor reward differs from independent replay")
        if status != "infrastructure_failure":
            score = actual
    except (OSError, ValueError, TypeError, KeyError) as exc:
        status, verification_error = "infrastructure_failure", str(exc)
    duration = None
    if raw.get("started_at") and raw.get("finished_at"):
        duration = (datetime.fromisoformat(raw["finished_at"]) - datetime.fromisoformat(raw["started_at"])).total_seconds()
    return {"policy": policy, "model": model, "seed": instance.seed, "instance_hash": instance.digest,
            "generator_version": instance.generator_version, "harness_version": "harbor-0.26.0",
            "duration_seconds": duration, "limits": {"action_limit": instance.action_limit, "agent_seconds": 300},
            "episode": {"score": score, "status": status, "stop_reason": error_type or (record or {}).get("final", {}).get("termination")},
            "provider_rate_limit": error_type in ("ApiRateLimitError", "RateLimitError"),
            "error_type": error_type, "verification_error": verification_error,
            "trace_path": str(path.parent), "agent_info": raw.get("agent_info"), "record": record}


def summarize(runs: list[dict]) -> str:
    lines = ["# Harbor evaluation", "", "Event-kit compatibility and the performance gap require review.", "",
             "| Seed | Policy | Scores (all attempts) | Mean | Std dev | Infra failures |",
             "|---|---|---|---:|---:|---:|"]
    groups = sorted({(r["seed"], r["policy"]) for r in runs})
    for seed, policy in groups:
        group = [r for r in runs if r["seed"] == seed and r["policy"] == policy]
        scores = [r["episode"]["score"] for r in group if r["episode"]["score"] is not None]
        displayed = ", ".join("infra" if r["episode"]["score"] is None else f'{r["episode"]["score"]:.4f}' for r in group)
        mean = f"{statistics.mean(scores):.4f}" if scores else "—"
        stdev = f"{statistics.pstdev(scores):.4f}" if scores else "—"
        lines.append(f"| {seed} | {policy} | {displayed} | {mean} | {stdev} | {len(group)-len(scores)} |")
    for run in runs:
        record = run.get("record")
        if not record:
            continue
        lines.extend(["", f'## {run["seed"]}: {run["policy"]} — {run["trace_path"]}', "",
                      "| Job | Start | Completion | Deadline | Outcome |", "|---|---:|---:|---:|---|"])
        for job in record["instance"]["jobs"]:
            start = record["final"]["starts"].get(job["id"])
            end = record["final"]["completed"].get(job["id"])
            outcome = "unfinished" if end is None else "on time" if end <= job["deadline"] else "late"
            lines.append(f'| {job["id"]} | {start} | {end} | {job["deadline"]} | {outcome} |')
    lines.extend(["", "These tables describe outcomes. Attribute frontier mistakes only after reading its actual tool decisions."])
    return "\n".join(lines) + "\n"
