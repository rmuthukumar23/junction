"""Candidate Harbor judge suite; AfterQuery-specific compatibility is unverified."""
import argparse
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from junction_env.evaluation import code_metadata
from junction_env.scheduling import generate
from .harbor_task import HARBOR_VERSION, build_task
from .harbor_results import read_trial, summarize


def preflight(args):
    try:
        if version("harbor") != HARBOR_VERSION:
            raise RuntimeError(f"Harbor {HARBOR_VERSION} required")
    except PackageNotFoundError:
        raise RuntimeError("Run uv sync --locked --extra eval --extra mcp --extra harbor") from None
    if not shutil.which("harbor"):
        raise RuntimeError("harbor is not on PATH; use uv run or activate .venv")
    if args.backend == "docker":
        if not shutil.which("docker"):
            raise RuntimeError("Docker is required for local Harbor trials; the credential-free core uses scripts/check.sh")
        subprocess.run(["docker", "info"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    elif not (os.environ.get("MODAL_TOKEN_ID") and os.environ.get("MODAL_TOKEN_SECRET")) and not (Path.home() / ".modal.toml").exists():
        raise RuntimeError("Authenticate Modal first (modal setup), or set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET")
    if not args.smoke:
        if not args.model:
            raise RuntimeError("--model must identify the event-approved frontier model")
        if not os.environ.get(args.credential_env):
            raise RuntimeError(f"Set {args.credential_env} for frontier evaluation; never put its value in CLI arguments")


def run_command(command: list[str], log: Path) -> dict:
    started = time.monotonic()
    cleanup_unconfirmed = False
    with log.open("w") as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
        try:
            code = process.wait(timeout=1800)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("docker", "modal"), default="docker")
    parser.add_argument("--seeds", type=int, nargs="+", default=[0])
    parser.add_argument("--jobs", type=int, choices=(8, 10, 12), default=8)
    parser.add_argument("--model")
    parser.add_argument("--opencode-version", default="1.19.5")
    parser.add_argument("--credential-env", default="OPENAI_API_KEY")
    parser.add_argument("--smoke", action="store_true", help="one reference per seed; no model credentials")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        preflight(args)
    except (RuntimeError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"Preflight failed: {exc}\n")
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, **code_metadata(), "created_at": datetime.now(timezone.utc).isoformat(),
              "backend": args.backend, "harness_version": HARBOR_VERSION, "model": args.model,
              "opencode_version": args.opencode_version, "official_afterquery_compatibility": "unverified",
              "submission_ready": False, "commands": [], "runs": []}
    started = time.monotonic()
    failed = False
    try:
        for seed in args.seeds:
            policies = ("reference",) if args.smoke else ("reference", "frontier", "do_nothing", "stop_early")
            for policy in policies:
                task = build_task(args.output / "tasks" / f"{seed}-{policy}", seed, args.jobs,
                                  "reference" if policy == "frontier" else policy)
                job_dir = args.output / "trials" / f"{seed}-{policy}"
                attempts = 3 if policy == "frontier" else 1
                command = ["harbor", "run", "--path", str(task), "--agent", "opencode" if policy == "frontier" else "oracle",
                           "--env", args.backend, "--n-attempts", str(attempts), "--n-concurrent", str(attempts),
                           "--jobs-dir", str(job_dir), "--job-name", "batch", "--max-retries", "0", "--delete", "--yes", "--quiet"]
                if policy == "frontier":
                    command += ["--model", args.model, "--agent-kwarg", f"version={args.opencode_version}"]
                result = run_command(command, args.output / f"{seed}-{policy}.log")
                report["commands"].append(result)
                paths = [p for p in job_dir.rglob("result.json") if p.parent.name != "batch"]
                runs = [read_trial(path, generate(seed, args.jobs), policy, args.model if policy == "frontier" else None) for path in paths]
                report["runs"].extend(runs)
                missing = max(0, attempts - len(runs))
                for index in range(missing):
                    report["runs"].append({"seed": seed, "policy": policy, "model": args.model if policy == "frontier" else None,
                        "instance_hash": generate(seed, args.jobs).digest, "trace_path": str(job_dir),
                        "episode": {"score": None, "status": "infrastructure_failure", "stop_reason": "missing_trial_result"}})
                failed |= result["exit_code"] != 0 or missing > 0 or any(r["episode"]["status"] == "infrastructure_failure" for r in runs)
                if policy == "reference":
                    failed |= any(r["episode"]["score"] != 1 for r in runs)
                if policy in ("do_nothing", "stop_early"):
                    failed |= any(r["episode"]["score"] != 0 for r in runs)
                if failed:
                    break
            if failed:
                break
    finally:
        report["batch_duration_seconds"] = time.monotonic() - started
        (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
        (args.output / "report.md").write_text(summarize(report["runs"]))
    print(f"Report: {args.output / 'report.md'}; official compatibility remains unverified")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
