"""Build a Harbor task for any seed, and collect a finished Harbor run's verifier score.

    uv run --no-sync python scripts/finetune/harbor_task.py build --seed 101
    uv run --no-sync python scripts/finetune/harbor_task.py collect --job artifacts/finetune/harbor/<job>

`build` does what `envkit eval` does before a run (src/envkit/evalrun.py): calibrate the seed
(cached; held-out seeds are not in calibration.json) and write the task with
envkit.harbor.build_task into artifacts/finetune/tasks/<scenario>-s<seed>. The committed
tasks/ folder is not touched.

`collect` reads every trial's verifier/score.json in a job folder and writes
<job>/summary.json, which scripts/finetune/report.py puts in the README.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ARTIFACTS, ROOT, anchor_profit, calibration, code_sha, scenario_from  # noqa: E402

from envkit.harbor import build_task  # noqa: E402


def build(scenario_name: str, seed: int, out_root: Path) -> Path:
    scenario = scenario_from(scenario_name)
    entry = calibration(scenario, seed)
    task = build_task(scenario, seed, entry, out_root)
    print(task)
    return task


def collect(job: Path) -> dict:
    trials = []
    for score_file in sorted(job.glob("*/verifier/score.json")):
        trial = score_file.parent.parent
        s = json.loads(score_file.read_text())
        scenario = scenario_from(s.get("scenario", "normal-winter")) if s.get("scenario") else None
        entry = calibration(scenario, int(s["seed"])) if scenario else {}
        trials.append({
            "trial": trial.name, "seed": s.get("seed"), "reward": s.get("reward"),
            "profit_eur": (s.get("ledger") or {}).get("profit_eur"),
            "end_reason": (s.get("ledger") or {}).get("end_reason"),
            "calls": (s.get("ledger") or {}).get("calls"),
            "reference_profit_eur": anchor_profit(entry, "reference") if entry else None,
        })
    for t in sorted(job.glob("*/")):
        if t.is_dir() and not (t / "verifier" / "score.json").exists() and (t / "result.json").exists():
            r = json.loads((t / "result.json").read_text())
            trials.append({"trial": t.name, "reward": None, "error": str(r.get("exception_info") or "no verifier score")[:300]})
    summary = {"job": str(job.relative_to(ROOT)) if job.is_relative_to(ROOT) else str(job),
               "harness": "Harbor 0.26 + OpenCode 1.19.5", "code_sha": code_sha(), "trials": trials}
    (job / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    for t in trials:
        print(f"{t['trial']}: reward {t.get('reward')}  profit {t.get('profit_eur')}  {t.get('error', '')}")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--scenario", default="normal-winter")
    b.add_argument("--seed", type=int, required=True)
    b.add_argument("--out", default=str(ARTIFACTS / "tasks"))
    c = sub.add_parser("collect")
    c.add_argument("--job", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "build":
        build(a.scenario, a.seed, Path(a.out))
    else:
        if not collect(Path(a.job).resolve())["trials"]:
            print("no trials found")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
