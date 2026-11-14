"""Reward-integrity audit.

Plays a battery of strategies that avoid the task and checks that none of
them is a good way to score. It is the automated version of what a judge does
when hunting for a reward exploit, and it runs in well under a second, so
run it after every change to an environment or its scoring.

Checks (limits can be overridden in the scenario's [audit] table):
  1. do-nothing scores at most `do_nothing_max` (0.05).
  2. absentee (shows up, does nothing) scores at most `absentee_max` (0.15).
  3. stopping early never pays: stop-early scores do not fall as the played
     fraction grows, and every one of them is below the reference.
  4. no degenerate strategy (random calls, spamming one tool) reaches the
     pass threshold set by the best scripted anchor.
  5. the reference clears that threshold.
  6. the episode is deterministic: the reference run twice gives identical
     traces, and replaying its trace reproduces every response.
"""
from __future__ import annotations

from typing import Any

from .calibrate import calibrate
from .clients import run_inprocess
from .core import Episode, replay
from .policies import make_policy
from .scenario import Scenario
from .scoring import score

STOP_FRACTIONS = (0.04, 0.1, 0.3, 0.5, 0.7, 0.9)


def audit(scenario: Scenario, seed: int, calibration: dict[str, Any] | None = None) -> dict[str, Any]:
    cal = calibration or calibrate(scenario, seed)
    limits = {"do_nothing_max": 0.05, "absentee_max": 0.15, "monotone_tolerance": 0.02, **scenario.audit}
    threshold = cal["threshold"]

    def play(spec: str) -> tuple[float, Episode]:
        ep = run_inprocess(scenario, seed, make_policy(spec, scenario))
        return score(scenario, ep.result(), cal)["reward"], ep

    rows: list[dict[str, Any]] = []

    def add(group: str, spec: str) -> float:
        reward, ep = play(spec)
        rows.append({"group": group, "policy": spec, "reward": reward, "calls": ep.calls, "faults": ep.faults})
        return reward

    reference, ref_ep = play("reference")
    rows.append({"group": "reference", "policy": scenario.reference, "reward": reference,
                 "calls": ref_ep.calls, "faults": ref_ep.faults})
    for name in dict.fromkeys(n for c in scenario.components for n in c.top_anchors):
        add("anchor", name)
    nothing = add("idle", "do-nothing")
    absentee = add("idle", "absentee")
    stops = [add("stop-early", f"stop-early:reference@{f:g}") for f in STOP_FRACTIONS]
    degenerate = [add("random", f"random:{s}") for s in range(5)]
    tools = [t["name"] for t in ref_ep.describe_tools()]
    degenerate += [add("spam", f"spam:{t}") for t in tools]

    again = run_inprocess(scenario, seed, make_policy("reference", scenario))
    same = [r["digest"] for r in ref_ep.trace.calls] == [r["digest"] for r in again.trace.calls]
    _, mismatches = replay(scenario, seed, ref_ep.trace.records)

    tol = limits["monotone_tolerance"]
    checks = [
        ("do-nothing earns almost nothing", nothing <= limits["do_nothing_max"],
         f"{nothing:.4f} <= {limits['do_nothing_max']}"),
        ("showing up without acting earns little", absentee <= limits["absentee_max"],
         f"{absentee:.4f} <= {limits['absentee_max']}"),
        ("stopping earlier never scores more", all(b >= a - tol for a, b in zip(stops, stops[1:])),
         " <= ".join(f"{s:.3f}" for s in stops)),
        ("every stop-early run is below the reference", max(stops) < reference,
         f"max {max(stops):.4f} < {reference:.4f}"),
        ("no degenerate strategy reaches the pass threshold", threshold is None or max(degenerate) < threshold,
         f"max {max(degenerate):.4f} < {threshold}"),
        ("the reference clears the pass threshold", threshold is None or reference >= threshold,
         f"{reference:.4f} >= {threshold}"),
        ("no tool raised an internal error", all(r["faults"] == 0 for r in rows),
         f"{sum(r['faults'] for r in rows)} faults"),
        ("the reference run is deterministic", same and not mismatches,
         f"identical traces: {same}; replay mismatches: {len(mismatches)}"),
    ]
    return {
        "scenario": scenario.id, "seed": seed, "threshold": threshold, "rows": rows,
        "checks": [{"name": n, "ok": bool(ok), "detail": d} for n, ok, d in checks],
        "ok": all(ok for _, ok, _ in checks),
    }


def format_audit(report: dict[str, Any]) -> str:
    lines = [f"Audit: {report['scenario']} seed {report['seed']} (pass threshold {report['threshold']})", ""]
    lines.append(f"  {'group':11}{'policy':30}{'reward':>8}{'calls':>7}")
    for r in report["rows"]:
        lines.append(f"  {r['group']:11}{r['policy']:30}{r['reward']:>8.4f}{r['calls']:>7}")
    lines.append("")
    for c in report["checks"]:
        lines.append(f"  [{'PASS' if c['ok'] else 'FAIL'}] {c['name']}  ({c['detail']})")
    lines.append("")
    lines.append("Audit passed." if report["ok"] else "Audit FAILED.")
    return "\n".join(lines)
