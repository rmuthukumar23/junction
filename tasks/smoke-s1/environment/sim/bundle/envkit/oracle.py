"""Play a scripted policy against a live MCP server.

This is what the Harbor oracle runs (solution/solve.sh). The policy acts
through MCP tool calls, so the reference run is produced through exactly the
interface the agent uses and is graded by exactly the same verifier.

    python -m envkit.oracle --url http://sim:8000/mcp --policy reference
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .bundle import load_bundle
from .clients import run_over_mcp
from .core import Episode
from .policies import make_policy


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", required=True)
    ap.add_argument("--policy", default="reference")
    ap.add_argument("--bundle", type=Path, default=Path(__file__).resolve().parent.parent)
    a = ap.parse_args(argv)

    scenario, manifest, _ = load_bundle(a.bundle)
    policy = make_policy(a.policy, scenario)
    # The opening is a pure function of the seed: rebuild it as the instruction shows it.
    opening = Episode(scenario, int(manifest["seed"])).opening
    header = run_over_mcp(a.url, policy, opening)
    print(json.dumps({"policy": policy.name, "last_header": header}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
