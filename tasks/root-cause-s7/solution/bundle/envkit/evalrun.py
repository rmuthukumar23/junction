"""The judging protocol through Harbor, as one command.

Judges rerun: the reference run, three agent runs, a do-nothing baseline and
a stop-early baseline. For every requested seed this builds a fresh Harbor
task from the working tree and runs:

  reference    harbor run -a oracle                      (solution/solve.sh)
  agent x N    harbor run -a opencode -m <model>         (only with --model)
  do-nothing   harbor run -a nop
  stop-early   harbor run -a oracle --ae ENVKIT_POLICY=stop-early

`--smoke` runs the reference only; `--agent-only` runs only the model
attempts (their scripted comparators are already in calibration.json). Without
`--model` the three scripted runs execute, which needs no credentials. Every scripted run must reproduce the
score calibration computed for it in-process; a mismatch fails the command.

The output directory must be new. It receives the tasks that were run, one
log per Harbor invocation, the raw trials, results.json and report.md.
AfterQuery-specific compatibility is unverified until this has been run
against the event's kit.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .bundle import ROOT
from .calibrate import calibrate
from .harbor import HARBOR_VERSION, build_task
from .report import collect, format_report, summarize
from .scenario import Scenario

OPENCODE_VERSION = "1.19.5"
SCRIPTED = {"reference": None, "do-nothing": "do-nothing", "stop-early": "stop-early"}


def code_metadata() -> dict[str, Any]:
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, cwd=ROOT,
                                      stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True, cwd=ROOT).strip())
        return {"code_sha": sha, "working_tree_dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"code_sha": "unknown", "working_tree_dirty": True}


def pick_backend(requested: str) -> str:
    if requested != "auto":
        return requested
    for name in ("docker", "podman"):
        if shutil.which(name):
            return name
    raise RuntimeError("neither docker nor podman is on PATH; pass --backend modal to use Modal")


# OpenCode's Google provider reads only this variable; Harbor does not map the host's
# GEMINI_API_KEY onto it, so without the forward below the agent dies with ProviderAuthError.
GOOGLE_OPENCODE_KEY = "GOOGLE_GENERATIVE_AI_API_KEY"


def is_google_model(model: str | None) -> bool:
    return bool(model) and model.split("/", 1)[0] in ("google", "gemini")


def credential_env_name(a: argparse.Namespace) -> str:
    return a.credential_env or ("GEMINI_API_KEY" if is_google_model(a.model) else "OPENAI_API_KEY")


def credential_forwarding(a: argparse.Namespace) -> list[str]:
    """`--ae` arguments that hand the host credential to the agent without putting its value
    on the command line: Harbor expands the ${NAME} template inside its own process."""
    if a.agent == "opencode" and is_google_model(a.model):
        return ["--ae", f"{GOOGLE_OPENCODE_KEY}=${{{credential_env_name(a)}}}"]
    return []


def preflight(a: argparse.Namespace, backend: str) -> None:
    if not shutil.which("harbor"):
        raise RuntimeError("harbor is not on PATH; run `uv sync --locked --extra eval --extra mcp --extra harbor` "
                           "and use `uv run`")
    found = subprocess.run(["harbor", "--version"], capture_output=True, text=True, timeout=60).stdout.strip()
    if found.split()[-1:] != [HARBOR_VERSION]:
        raise RuntimeError(f"Harbor {HARBOR_VERSION} required, found '{found}'")
    if backend in ("docker", "podman"):
        if not shutil.which(backend):
            raise RuntimeError(f"{backend} is required for local Harbor trials; the credential-free core "
                               "uses scripts/check.sh")
        subprocess.run([backend, "info"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    elif not (os.environ.get("MODAL_TOKEN_ID") and os.environ.get("MODAL_TOKEN_SECRET")) \
            and not (Path.home() / ".modal.toml").exists():
        raise RuntimeError("Authenticate Modal first (modal setup), or set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET")
    if a.model and not os.environ.get(credential_env_name(a)):
        raise RuntimeError(f"Set {credential_env_name(a)} for model runs; never put its value in CLI arguments")


def run_command(command: list[str], log: Path) -> dict[str, Any]:
    started = time.monotonic()
    cleanup_unconfirmed = False
    with log.open("w") as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
        try:
            code = process.wait(timeout=3 * 3600)
        except subprocess.TimeoutExpired:
            process.send_signal(signal.SIGINT)
            try:
                code = process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                code = process.wait()
                cleanup_unconfirmed = True
    return {"command": command, "exit_code": code, "duration_seconds": time.monotonic() - started,
            "cleanup_unconfirmed": cleanup_unconfirmed, "log": str(log)}


def run_eval(a: argparse.Namespace, scenario: Scenario) -> int:
    try:
        backend = pick_backend(a.backend)
        preflight(a, backend)
    except (RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Preflight failed: {exc}")
        return 2
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=False)

    if getattr(a, "agent_only", False) and not a.model:
        print("Preflight failed: --agent-only needs --model (or AFTERQUERY_MODEL in .env)")
        return 2
    if a.smoke:
        labels = ["reference"]
    elif getattr(a, "agent_only", False):
        labels = ["agent"]
    else:
        labels = ["reference", *(["agent"] if a.model else []), "do-nothing", "stop-early"]
    report: dict[str, Any] = {
        "schema_version": 2, **code_metadata(), "created_at": datetime.now(timezone.utc).isoformat(),
        "scenario": scenario.id, "backend": backend, "harness_version": HARBOR_VERSION, "model": a.model,
        "agent": a.agent, "opencode_version": a.opencode_version if a.agent == "opencode" else None,
        "official_afterquery_compatibility": "unverified", "submission_ready": False,
        "commands": [], "expected": {}, "runs": [],
    }
    started = time.monotonic()
    problems: list[str] = []
    try:
        for seed in (a.seeds or scenario.seeds):
            entry = calibrate(scenario, seed)
            task = build_task(scenario, seed, entry, out / "tasks")
            expected = {"reference": entry["anchors"][scenario.reference]["reward"],
                        "do-nothing": entry["anchors"]["do-nothing"]["reward"],
                        "stop-early": entry["anchors"]["stop-early"]["reward"]}
            report["expected"][str(seed)] = expected
            for label in labels:
                job = f"s{seed}-{label}"
                attempts = a.runs if label == "agent" else 1
                command = ["harbor", "run", "--path", str(task), "--env", backend,
                           "--n-attempts", str(attempts), "--n-concurrent", str(attempts),
                           "--jobs-dir", str(out / "trials"), "--job-name", job,
                           "--max-retries", "0", "--delete", "--yes", "--quiet"]
                if label == "agent":
                    command += ["--agent", a.agent, "--model", a.model]
                    if a.agent == "opencode":
                        command += ["--agent-kwarg", f"version={a.opencode_version}"]
                    command += credential_forwarding(a)
                elif label == "do-nothing":
                    command += ["--agent", "nop"]
                else:
                    command += ["--agent", "oracle"]
                    if SCRIPTED[label]:
                        command += ["--ae", f"ENVKIT_POLICY={SCRIPTED[label]}"]
                print(f"== seed {seed} {label}: {' '.join(command)}", flush=True)
                result = run_command(command, out / f"{job}.log")
                report["commands"].append(result)
                rows = collect(out / "trials" / job)
                report["runs"].extend(rows)
                if result["exit_code"] != 0:
                    problems.append(f"{job}: harbor exited with {result['exit_code']} (see {result['log']})")
                if len(rows) < attempts:
                    problems.append(f"{job}: {attempts - len(rows)} of {attempts} trial result(s) missing")
                for row in rows:
                    if row["status"] == "infrastructure_failure":
                        problems.append(f"{job}: infrastructure failure "
                                        f"({row['verification_error'] or row['error_type']})")
                    elif label in expected and row["reward"] != expected[label]:
                        problems.append(f"{job}: scored {row['reward']}, calibration expects {expected[label]}")
                if problems:
                    break
            if problems:
                break
    finally:
        report["batch_duration_seconds"] = time.monotonic() - started
        report["problems"] = problems
        (out / "results.json").write_text(json.dumps(report, indent=2) + "\n")
        (out / "report.md").write_text(summarize(report["runs"]))

    print()
    print(format_report(report["runs"]))
    print(f"\nReport: {out / 'report.md'}; official compatibility remains unverified")
    for p in problems:
        print(f"FAILED: {p}")
    return 1 if problems or not report["runs"] else 0
