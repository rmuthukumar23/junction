"""The judging protocol, as one command.

Judges rerun: the reference run, three agent runs, a do-nothing baseline and
a stop-early baseline. This runs the same set through Harbor and prints one
table.

    envkit eval tasks/<name> --model provider/model

  reference    harbor run -a oracle                      (solution/solve.sh)
  do-nothing   harbor run -a nop
  stop-early   harbor run -a oracle --ae ENVKIT_POLICY=stop-early
  agent x N    harbor run -a opencode -m <model> -k N    (only with --model)

Without --model the three scripted runs still execute, which needs no API key.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import time
from pathlib import Path

from .report import collect, format_report


def pick_runtime(requested: str | None) -> str:
    if requested:
        return requested
    if shutil.which("docker"):
        return "docker"
    if shutil.which("podman"):
        return "podman"
    raise SystemExit("neither docker nor podman was found on PATH")


def run_eval(a: argparse.Namespace) -> int:
    task = Path(a.task)
    if not (task / "task.toml").exists():
        raise SystemExit(f"{task} is not a Harbor task directory (no task.toml)")
    if not shutil.which("harbor"):
        raise SystemExit("harbor is not installed; run `uv tool install harbor`")
    runtime = pick_runtime(a.runtime)
    out = Path(a.jobs_dir) / (a.name or time.strftime("eval-%Y%m%d-%H%M%S"))

    plan: list[tuple[str, list[str]]] = [
        ("reference", ["-a", "oracle"]),
        ("do-nothing", ["-a", "nop"]),
        ("stop-early", ["-a", "oracle", "--ae", "ENVKIT_POLICY=stop-early"]),
    ]
    if a.model:
        plan.append(("agent", ["-a", a.agent, "-m", a.model, "-k", str(a.runs)]))
    else:
        print("no --model given: running the scripted runs only\n")

    failed = []
    for label, extra in plan:
        cmd = ["harbor", "run", "-p", str(task), "-e", runtime, "--jobs-dir", str(out),
               "--job-name", label, "--yes", *extra]
        print(f"== {label}: {' '.join(cmd)}", flush=True)
        if subprocess.run(cmd).returncode != 0:
            failed.append(label)

    rows = collect(out)
    print()
    print(format_report(rows))
    print(f"\nresults: {out}")
    if failed:
        print(f"harbor exited with an error for: {', '.join(failed)}")
    return 1 if failed or not rows else 0
