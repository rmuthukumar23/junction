"""The verifier: trace in, reward out.

Runs in the separate verifier container, which holds its own copy of the
bundle and receives only the trace collected from the simulation sidecar.
It replays the trace in a fresh process, finalizes the episode (every window
the agent did not play runs unattended), scores the resulting ledger against
the committed calibration, and writes:

    <out>/reward.txt   one number in [0, 1]
    <out>/score.json   components, ledger, replay check and per-window timeline

Nothing here trusts a value computed next to the agent. A trace with no
calls is graded as what it is: an episode in which nobody acted. A trace that
is missing altogether, or that cannot be graded, is an infrastructure failure:
no reward file is written and the exit code is non-zero, so the harness
records an error instead of a score of zero for the agent.

    python -m envkit.verify [--bundle DIR] [--trace FILE] [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any

from .bundle import load_bundle
from .core import replay
from .scoring import score
from .trace import read_trace

DEFAULT_TRACE = "/var/lib/envkit/trace.jsonl"
DEFAULT_OUT = "/logs/verifier"


def grade(bundle_dir: Path, trace_path: Path) -> dict[str, Any]:
    scenario, manifest, calibration = load_bundle(bundle_dir)
    if not trace_path.exists():
        raise FileNotFoundError(f"no trace at {trace_path}: sidecar collection failed")
    records = read_trace(trace_path)
    header = next((r for r in records if r.get("k") == "header"), None)

    episode, mismatches = replay(scenario, manifest["seed"], records)
    ledger = episode.result()
    result = score(scenario, ledger, calibration)

    notes = []
    if header and (header.get("bundle"), header.get("seed")) != (manifest["bundle"], manifest["seed"]):
        notes.append("trace header does not match this verifier's bundle; graded with the verifier's own scenario and seed")
    if calibration and calibration.get("bundle") != manifest["bundle"]:
        notes.append("calibration was computed for a different bundle; rerun `envkit build`")
    if mismatches:
        notes.append(f"{len(mismatches)} recorded response(s) did not reproduce on replay; the replayed result is authoritative")

    return {
        "reward": result["reward"],
        "passed": result["passed"],
        "threshold": result["threshold"],
        "components": result["components"],
        "weights": result["weights"],
        "scenario": scenario.id,
        "seed": manifest["seed"],
        "bundle": manifest["bundle"],
        "ledger": ledger,
        "replay": {
            "calls": sum(1 for r in records if r.get("k") == "call"),
            "consistent": not mismatches,
            "mismatches": mismatches[:20],
        },
        "notes": notes,
        "faults": episode.fault_log[:5],
        "timeline": episode.timeline,
    }


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bundle", type=Path, default=here)
    ap.add_argument("--trace", type=Path, default=Path(DEFAULT_TRACE))
    ap.add_argument("--out", type=Path, default=Path(DEFAULT_OUT))
    a = ap.parse_args(argv)

    a.out.mkdir(parents=True, exist_ok=True)
    try:
        out = grade(a.bundle, a.trace)
    except Exception:
        error = traceback.format_exc()
        print(error, file=sys.stderr)
        (a.out / "score.json").write_text(json.dumps({"reward": None, "error": error}, indent=1) + "\n")
        return 1
    (a.out / "score.json").write_text(json.dumps(out, indent=1, default=str) + "\n")
    (a.out / "reward.txt").write_text(f"{out['reward']:.4f}\n")
    summary = {k: out.get(k) for k in ("reward", "passed", "components", "notes") if k in out}
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
