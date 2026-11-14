"""Copy finished Harbor trials into runs/normal-winter/<name>/ so they are committed.

    .venv/bin/python scripts/collect_runs.py artifacts/<eval output dir> [...]

Per trial it keeps the evidence a judge needs, gzip-free and small enough for git:
  trace.jsonl       the action log the verifier replayed (the sidecar's, not the agent's)
  score.json        the verifier's score, ledger and failure-mode evidence
  reward.txt        the number Harbor read
  trajectory.json   the agent's full trajectory (Harbor ATIF: messages, reasoning, tool calls)
  meta.json         model, seed, bundle, timing
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs" / "normal-winter"


def main(dirs: list[str]) -> int:
    n = 0
    for d in dirs:
        for result in sorted(Path(d).resolve().glob("trials/*/normal-winter-s*__*/result.json")):
            trial = result.parent
            score = trial / "verifier" / "score.json"
            trace = trial / "artifacts" / "var" / "lib" / "envkit" / "trace.jsonl"
            if not score.exists() or not trace.exists():
                print(f"skip {trial} (no verifier score)")
                continue
            r = json.loads(result.read_text())
            s = json.loads(score.read_text())
            cfg = json.loads((trial / "config.json").read_text()) if (trial / "config.json").exists() else {}
            model = (r.get("agent_info") or {}).get("model_info", {}).get("name") or cfg.get("agent", {}).get("model_name") or "model"
            model = str(model).split("/")[-1]
            name = f"{model}-s{s['seed']}-{trial.name.split('__')[-1].lower()}"
            dest = OUT / name
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy(trace, dest / "trace.jsonl")
            slim = {k: v for k, v in s.items() if k != "timeline"}     # the hourly timeline is 9 MB; replay rebuilds it
            (dest / "score.json").write_text(json.dumps(slim, indent=1) + "\n")
            shutil.copy(trial / "verifier" / "reward.txt", dest / "reward.txt")
            if (trial / "agent" / "trajectory.json").exists():
                shutil.copy(trial / "agent" / "trajectory.json", dest / "trajectory.json")
            (dest / "meta.json").write_text(json.dumps({
                "model": model, "seed": s["seed"], "bundle": s.get("bundle"), "reward": s.get("reward"),
                "profit_eur": s.get("ledger", {}).get("profit_eur"), "started_at": r.get("started_at"),
                "finished_at": r.get("finished_at"), "harbor_trial": str(trial.relative_to(ROOT))}, indent=1) + "\n")
            print(f"{name}: reward {s.get('reward')}")
            n += 1
    return 0 if n else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
