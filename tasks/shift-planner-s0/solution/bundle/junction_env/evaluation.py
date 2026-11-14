"""Credential-free reference suite. This command makes no frontier-agent claim."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

from .runner import run_episode
from .scheduling import ShiftPlanner, generate
from .scheduling.reference import ReferencePolicy, do_nothing, earliest_deadline, stop_early
from .scheduling.verifier import verify_record


def code_metadata() -> dict:
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
        return {"code_sha": sha, "working_tree_dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"code_sha": "unknown", "working_tree_dirty": True}


def evaluate(seed: int, job_count: int, name: str) -> dict:
    policy = {"reference": ReferencePolicy, "do_nothing": lambda: do_nothing,
              "stop_early": lambda: stop_early, "earliest_deadline": lambda: earliest_deadline}[name]()
    env = ShiftPlanner(generate(seed, job_count))
    start = time.monotonic()
    episode = run_episode(env, policy, seed=seed, max_steps=64)
    record = env.record()
    verified = verify_record(record, env.instance)
    if episode.score != verified:
        raise RuntimeError("runner/verifier mismatch")
    return {"policy": name, "model": None, "seed": seed, "instance_hash": env.instance.digest,
            "harness_version": "local-v1", "generator_version": env.instance.generator_version,
            "duration_seconds": time.monotonic() - start,
            "limits": {"max_steps": 64, "action_limit": env.instance.action_limit},
            "solver": asdict(policy.schedule) if name == "reference" else None,
            "episode": asdict(episode), "record": record}


def report_markdown(report: dict) -> str:
    lines = ["# Shift Planner local evaluation", "", "Local policies only; frontier gap unmeasured.", "",
             "| Seed | Policy | Score | Actions | Status | Seconds |", "|---|---|---:|---:|---|---:|"]
    for run in report["runs"]:
        lines.append(f'| {run["seed"]} | {run["policy"]} | {run["episode"]["score"]:.4f} | '
                     f'{run["record"]["final"]["actions_used"]} | {run["episode"]["status"]} | '
                     f'{run["duration_seconds"]:.3f} |')
    for run in report["runs"]:
        lines.extend(["", f'## Seed {run["seed"]}: {run["policy"]}', "",
                      "| Job | Start | End | Deadline | Outcome |", "|---|---:|---:|---:|---|"])
        final = run["record"]["final"]
        for job in run["record"]["instance"]["jobs"]:
            start = final["starts"].get(job["id"])
            end = final["completed"].get(job["id"])
            outcome = "unfinished" if end is None else ("on time" if end <= job["deadline"] else "late")
            lines.append(f'| {job["id"]} | {start if start is not None else "—"} | '
                         f'{end if end is not None else "—"} | {job["deadline"]} | {outcome} |')
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(5)))
    parser.add_argument("--verify-count", type=int, default=0, help="reference seeds 0..N-1 (N <= 100)")
    parser.add_argument("--jobs", type=int, choices=(8, 10, 12), default=8)
    parser.add_argument("--output", type=Path, default=Path("artifacts/local"))
    args = parser.parse_args()
    if not 0 <= args.verify_count <= 100:
        parser.error("--verify-count must be 0..100; held-out seeds 100–102 remain reserved")
    runs = []
    started = time.monotonic()
    for seed in (range(args.verify_count) if args.verify_count else args.seeds):
        names = ("reference",) if args.verify_count else ("reference", "do_nothing", "stop_early", "earliest_deadline")
        for name in names:
            run = evaluate(seed, args.jobs, name)
            runs.append(run)
            if name == "reference" and run["episode"]["score"] != 1:
                raise RuntimeError(f"reference failed seed {seed}")
    report = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
              **code_metadata(), "frontier_evaluated": False, "submission_ready": False,
              "batch_duration_seconds": time.monotonic() - started, "runs": runs}
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    (args.output / "report.md").write_text(report_markdown(report))
    print(json.dumps({"runs": len(runs), "reference_scores": sorted({r["episode"]["score"] for r in runs if r["policy"] == "reference"}),
                      "max_reference_actions": max(r["record"]["final"]["actions_used"] for r in runs if r["policy"] == "reference"),
                      "report": str(args.output / "report.md"), "frontier_evaluated": False}))


if __name__ == "__main__":
    main()
