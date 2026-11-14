"""Command line.

    envkit run SCENARIO [--policy P] [--seed N] [--trace FILE]   play one policy in-process
    envkit anchors [SCENARIO...]       play every anchor policy and print the score table
    envkit audit [SCENARIO...]         reward-integrity checks
    envkit build [SCENARIO...]         calibrate, then (re)generate the Harbor tasks
    envkit check                       fail if calibration.json or tasks/ are stale
    envkit play SCENARIO [--record F]  play by hand in the terminal
    envkit replay SCENARIO TRACE       regrade a recorded trace
    envkit serve SCENARIO              run the MCP server locally
    envkit eval --scenario S --output DIR [--model M] [--smoke] [--seeds N...]
                                       the judging protocol, through Harbor
    envkit report DIR                  summarize Harbor trials under DIR

SCENARIO is a scenario id (scenarios/<id>.toml) or a path to a scenario file.
With no SCENARIO, commands that accept several act on all of them.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from .audit import audit, format_audit
from .bundle import ROOT, bundle_hash, source_files
from .calibrate import calibrate, entry_for, load_calibration, save_calibration
from .clients import InProcessClient, run_inprocess
from .core import Episode, replay
from .harbor import build_task, check_task, task_name
from .policies import make_policy
from .scenario import Scenario, load_scenario
from .scoring import score
from .trace import Trace, read_trace

TASKS_DIR = "tasks"


def find_scenarios(names: list[str]) -> list[Scenario]:
    if not names:
        paths = sorted((ROOT / "scenarios").glob("*.toml"))
        if not paths:
            raise SystemExit(f"no scenarios found in {ROOT / 'scenarios'}")
        return [load_scenario(p) for p in paths]
    out = []
    for name in names:
        candidates = [Path(name), ROOT / "scenarios" / f"{name}.toml"]
        path = next((p for p in candidates if p.is_file()), None)
        if path is None:
            raise SystemExit(f"scenario '{name}' not found (tried {', '.join(map(str, candidates))})")
        out.append(load_scenario(path))
    return out


def seeds_for(scenario: Scenario, seed: int | None) -> list[int]:
    return [seed] if seed is not None else list(scenario.seeds)


def calibration_for(scenario: Scenario, seed: int) -> dict[str, Any]:
    """The committed entry if it matches the current code, else a fresh one."""
    entry = entry_for(load_calibration(ROOT), scenario.id, seed)
    if entry and entry.get("bundle") == bundle_hash(source_files(scenario)):
        return entry
    return calibrate(scenario, seed)


def print_score(label: str, s: dict[str, Any], ledger: dict[str, Any]) -> None:
    comps = "  ".join(f"{k}={v:.4f}" for k, v in s["components"].items())
    passed = "" if s["passed"] is None else ("  PASS" if s["passed"] else "  below threshold")
    print(f"{label}: reward={s['reward']:.4f}{passed}   {comps}")
    print(f"  windows acted {ledger['windows_acted']}/{ledger['windows_total']}, "
          f"calls {ledger['calls']}, rejected {ledger['rejected']}, end: {ledger['end_reason']}"
          f"{' (stopped early)' if ledger['stopped_early'] else ''}")


# -- commands -------------------------------------------------------------------

def cmd_run(a: argparse.Namespace) -> int:
    (scenario,) = find_scenarios([a.scenario])
    for seed in seeds_for(scenario, a.seed):
        episode = run_inprocess(scenario, seed, make_policy(a.policy, scenario), a.trace)
        ledger = episode.result()
        s = score(scenario, ledger, calibration_for(scenario, seed))
        if a.json:
            print(json.dumps({**s, "seed": seed, "policy": a.policy, "ledger": ledger}, indent=1))
        else:
            print_score(f"{scenario.id} seed {seed} [{a.policy}]", s, ledger)
    return 0


def cmd_anchors(a: argparse.Namespace) -> int:
    for scenario in find_scenarios(a.scenarios):
        for seed in seeds_for(scenario, a.seed):
            entry = calibrate(scenario, seed)
            print(f"{scenario.id} seed {seed}   constants {json.dumps(entry['components'])}   "
                  f"pass threshold {entry['threshold']}")
            names = [c.name for c in scenario.components]
            print(f"  {'policy':26}{'reward':>8}" + "".join(f"{n:>13}" for n in names))
            for name, anchor in entry["anchors"].items():
                mark = "  <- reference" if name == scenario.reference else ""
                print(f"  {name:26}{anchor['reward']:>8.4f}"
                      + "".join(f"{anchor['components'][n]:>13.4f}" for n in names) + mark)
            print()
    return 0


def cmd_audit(a: argparse.Namespace) -> int:
    ok = True
    for scenario in find_scenarios(a.scenarios):
        for seed in seeds_for(scenario, a.seed):
            report = audit(scenario, seed)
            print(format_audit(report), end="\n\n")
            ok = ok and report["ok"]
    return 0 if ok else 1


def cmd_build(a: argparse.Namespace) -> int:
    data = load_calibration(ROOT)
    for scenario in find_scenarios(a.scenarios):
        data["tasks"][scenario.id] = {}
        for seed in scenario.seeds:
            entry = calibrate(scenario, seed)
            data["tasks"][scenario.id][str(seed)] = entry
            task = build_task(scenario, seed, entry, ROOT / TASKS_DIR)
            ref = entry["anchors"][scenario.reference]["reward"]
            print(f"built {task.relative_to(ROOT)}   bundle {entry['bundle']}   "
                  f"reference {ref:.4f}   threshold {entry['threshold']}")
    save_calibration(ROOT, data)
    return 0


def cmd_check(a: argparse.Namespace) -> int:
    data = load_calibration(ROOT)
    problems = []
    for scenario in find_scenarios([]):
        for seed in scenario.seeds:
            committed = entry_for(data, scenario.id, seed)
            fresh = calibrate(scenario, seed)
            name = task_name(scenario, seed)
            if committed != json.loads(json.dumps(fresh)):
                problems.append(f"{name}: calibration.json is stale")
                continue
            problems += [f"{name}: {d}" for d in check_task(scenario, seed, committed, ROOT / TASKS_DIR)]
    for p in problems:
        print(p)
    print("up to date." if not problems else "\nStale. Run `envkit build` and commit the result.")
    return 1 if problems else 0


def cmd_play(a: argparse.Namespace) -> int:
    from .repl import run_console

    (scenario,) = find_scenarios([a.scenario])
    seed = a.seed if a.seed is not None else scenario.seeds[0]
    record = Path(a.record) if a.record else None
    if record and record.exists():
        raise SystemExit(f"{record} already exists; choose another file or delete it first")
    episode = Episode(scenario, seed, Trace(record), bundle_hash(source_files(scenario)))
    run_console(InProcessClient(episode), scenario.render_prompt())
    ledger = episode.result()
    episode.trace.close()
    print_score(f"{scenario.id} seed {seed} [human]", score(scenario, ledger, calibration_for(scenario, seed)), ledger)
    if record:
        print(f"trace written to {record}\nto make it the reference run, set in the scenario:\n"
              f'  reference = "replay:{record.as_posix()}"')
    return 0


def cmd_replay(a: argparse.Namespace) -> int:
    (scenario,) = find_scenarios([a.scenario])
    records = read_trace(a.trace)
    header = next((r for r in records if r.get("k") == "header"), {})
    seed = a.seed if a.seed is not None else int(header.get("seed", scenario.seeds[0]))
    episode, mismatches = replay(scenario, seed, records)
    ledger = episode.result()
    print_score(f"{scenario.id} seed {seed} [replay of {a.trace}]",
                score(scenario, ledger, calibration_for(scenario, seed)), ledger)
    print(f"  replay consistent: {not mismatches}" + (f" ({len(mismatches)} mismatches)" if mismatches else ""))
    return 0 if not mismatches else 1


def cmd_serve(a: argparse.Namespace) -> int:
    import uvicorn

    from .server import build_app, resume

    (scenario,) = find_scenarios([a.scenario])
    seed = a.seed if a.seed is not None else scenario.seeds[0]
    state = Path(a.state_dir) if a.state_dir else Path(tempfile.mkdtemp(prefix="envkit-"))
    episode = resume(scenario, seed, state / "trace.jsonl", bundle_hash(source_files(scenario)))
    print(f"serving {scenario.id} seed {seed} at http://{a.host}:{a.port}/mcp   trace: {state / 'trace.jsonl'}",
          file=sys.stderr)
    uvicorn.run(build_app(episode), host=a.host, port=a.port, log_level="warning")
    return 0


def cmd_eval(a: argparse.Namespace) -> int:
    from .evalrun import run_eval

    (scenario,) = find_scenarios([a.scenario])
    return run_eval(a, scenario)


def cmd_report(a: argparse.Namespace) -> int:
    from .report import collect, format_report

    rows = collect(Path(a.dir))
    print(format_report(rows))
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=1) + "\n")
    return 0 if rows else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="envkit", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="play one policy in-process")
    p.add_argument("scenario")
    p.add_argument("--policy", default="reference")
    p.add_argument("--seed", type=int)
    p.add_argument("--trace", help="write the action log here")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_run)

    for name, fn, text in (("anchors", cmd_anchors, "score every anchor policy"),
                           ("audit", cmd_audit, "reward-integrity checks")):
        p = sub.add_parser(name, help=text)
        p.add_argument("scenarios", nargs="*")
        p.add_argument("--seed", type=int)
        p.set_defaults(fn=fn)

    p = sub.add_parser("build", help="calibrate and generate Harbor tasks")
    p.add_argument("scenarios", nargs="*")
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("check", help="verify calibration.json and tasks/ are current")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("play", help="play by hand")
    p.add_argument("scenario")
    p.add_argument("--seed", type=int)
    p.add_argument("--record", help="write the session trace here")
    p.set_defaults(fn=cmd_play)

    p = sub.add_parser("replay", help="regrade a trace")
    p.add_argument("scenario")
    p.add_argument("trace")
    p.add_argument("--seed", type=int)
    p.set_defaults(fn=cmd_replay)

    p = sub.add_parser("serve", help="run the MCP server locally")
    p.add_argument("scenario")
    p.add_argument("--seed", type=int)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--state-dir")
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("eval", help="run the judging protocol through Harbor")
    p.add_argument("--scenario", required=True, help="scenario id or path")
    p.add_argument("--output", required=True, help="new directory for tasks, logs, trials and reports")
    p.add_argument("--seeds", type=int, nargs="+", help="default: the scenario's committed seeds")
    p.add_argument("--model", help="provider/model for the agent runs; omit to run the scripted runs only")
    p.add_argument("--agent", default="opencode")
    p.add_argument("--opencode-version", default="1.19.5")
    p.add_argument("--credential-env", default=None,
                   help="name of the environment variable that must hold the model credential "
                        "(default: GEMINI_API_KEY for google/gemini models, else OPENAI_API_KEY)")
    p.add_argument("--runs", type=int, default=3, help="number of agent runs per seed")
    p.add_argument("--smoke", action="store_true", help="one reference run per seed; no model credentials")
    p.add_argument("--backend", choices=["auto", "docker", "podman", "modal"], default="auto",
                   help="auto: docker if present, else podman")
    p.set_defaults(fn=cmd_eval)

    p = sub.add_parser("report", help="summarize Harbor trials")
    p.add_argument("dir")
    p.add_argument("--json", help="also write the rows to this file")
    p.set_defaults(fn=cmd_report)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
