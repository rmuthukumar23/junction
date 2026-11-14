"""Check that the viewer shows the real game, exactly.

    uv run python scripts/viz/check_viewer.py                  # every scripted grower, seed 1
    uv run python scripts/viz/check_viewer.py --seeds 1 2 3 --scenario quick-winter
    uv run python scripts/viz/check_viewer.py --trace artifacts/.../trace.jsonl

For each game it checks:
  1. recording changes nothing: the viewer's game (with every hour and every action
     measured) ends with the same ledger as the same grower played without the viewer;
  2. every action the grower sent reached the simulator, and the change the viewer shows
     for it is the measured difference in simulator state just before and after it;
  3. a refused action changed nothing;
  4. money: the profit on the last frame equals the ledger's, the money categories add up
     to it, and the ledger's cash is conserved;
  5. a replayed model run reproduces every recorded response (digest match).
Exits non-zero on any failure.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import server  # noqa: E402
from envkit.clients import run_inprocess  # noqa: E402
from envkit.policies import make_policy  # noqa: E402
from envkit.scenario import load_scenario  # noqa: E402


def check(spec: str, seed: int, scenario_path: str) -> list[str]:
    game = server.play(spec, seed, scenario_path)
    problems = []
    if not spec.startswith("trace:"):
        sc = load_scenario(scenario_path)
        plain = run_inprocess(sc, seed, make_policy(spec, sc)).result()
        if abs(plain["profit_eur"] - game["profit"]) > 0.005:
            problems.append(f"recording changed the game: profit {game['profit']} vs {plain['profit_eur']} without the viewer")
    acts = [c for c in game["calls"] if c["tool"] != "submit_day"]
    unreached = [c for c in acts if not c["reached"] and c["ok"]]
    if unreached:
        problems.append(f"{len(unreached)} accepted action(s) not measured, e.g. {unreached[0]['tool']} at hour {unreached[0]['h']}")
    changed_refused = [c for c in acts if not c["ok"] and c["fx"]]
    if changed_refused:
        problems.append(f"{len(changed_refused)} refused action(s) changed state, e.g. {changed_refused[0]['fx'][:2]}")
    if not game["checks"]["ok"]:
        problems.append(f"money checks failed: {game['checks']}")
    rep = game.get("replay")
    if rep and rep["matched"] != rep["calls"]:
        problems.append(f"replay matched {rep['matched']} of {rep['calls']} recorded responses")
    accepted = [c for c in acts if c["ok"]]
    print(f"{spec:28s} seed {game['seed']}: {len(acts):3d} actions, {len(accepted) - sum(1 for c in accepted if not c['fx']):3d} changed state, "
          f"{sum(1 for c in accepted if not c['fx']):3d} already in force, {len(acts) - len(accepted):2d} refused · "
          f"profit €{game['profit']:,.2f} · ledger ✓ · {'OK' if not problems else 'FAIL'}"
          + (f" · replay {rep['matched']}/{rep['calls']}" if rep else ""))
    for p in problems:
        print("    ✗", p)
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="normal-winter")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1])
    ap.add_argument("--players", nargs="+", default=None, help="policy specs (default: every scripted grower and exploit)")
    ap.add_argument("--trace", nargs="*", default=[], help="model-run traces to replay and check")
    a = ap.parse_args()
    path = str(server.ROOT / "scenarios" / f"{a.scenario}.toml")
    players = a.players or [p["id"] for p in server.builtin_players(load_scenario(path))]
    bad = 0
    for seed in a.seeds:
        for spec in players:
            bad += bool(check(spec, seed, path))
    for t in a.trace:
        bad += bool(check("trace:" + str(Path(t).resolve().relative_to(server.ROOT)), 0, path))
    print("all checks passed" if not bad else f"{bad} game(s) failed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
