"""Post-run analysis: what would one different day have changed?

Method. Take a finished run's trace. Pick a day. Replace the plan that was in
effect on that day with one alternative plan, keep every other recorded
request exactly as it was, replay the whole episode in a fresh engine, and
compare final profit.

Feasibility is explicit. The alternative itself must pass the engine's own
plan validation at that point; if it does not, it is reported as infeasible
and not evaluated. A later recorded plan can become infeasible after the
substitution (for example, less water is left). The engine then rejects it,
exactly as it would live, and that day runs the default plan; the number of
such days is reported with the result.

What this shows and what it does not. A higher profit is evidence that the
day's plan could be improved locally, holding the player's later requests
fixed. It is not the best possible plan for that day, and it says nothing
about what the player would have done next had they seen a different
outcome. It is not a search for the optimal policy.
"""
from __future__ import annotations

from typing import Any

from envkit.core import Episode, replay
from envkit.scenario import Scenario

from rootcause.sim import RuleError

METHOD = ("One day's plan is replaced by an alternative; every other recorded request is replayed unchanged. "
          "A later recorded plan that becomes infeasible is rejected by the engine and that day runs the default "
          "plan. A gain is evidence of a local improvement, not of an optimal plan.")


def _calls(records: list[dict[str, Any]]) -> list[tuple[str, Any]]:
    return [(str(r["tool"]), r.get("args")) for r in records if r.get("k") == "call"]


def _replay_calls(scenario: Scenario, seed: int, calls: list[tuple[str, Any]]) -> tuple[Episode, list[bool]]:
    episode = Episode(scenario, seed)
    oks = [episode.call(tool, args)["ok"] for tool, args in calls]
    episode.finalize()
    return episode, oks


def substitute(calls: list[tuple[str, Any]], day: int, plan: dict[str, dict[str, float]]) -> list[tuple[str, Any]] | None:
    """The same request list with `plan` in effect on `day`. None if the player
    never advanced through that day (it ran after they stopped)."""
    out: list[tuple[str, Any]] = []
    advances = 0
    done = False
    for tool, args in calls:
        if advances == day and not done:
            if tool == "submit_day_plan":
                continue                       # drop the player's own plans for that day
            if tool in ("advance_day", "finish_episode"):
                out.append(("submit_day_plan", {"zone_plans": plan}))
                done = True
        out.append((tool, args))
        if tool == "advance_day":
            advances += 1
    return out if done else None


def alternatives(sim: Any, day: int) -> list[tuple[str, dict[str, dict[str, float]]]]:
    """A few simple, differently-motivated alternatives to the plan applied on
    `day`, built from that day's record. `sim` is the finished, replayed run."""
    record = sim.days[day]
    applied = {z: dict(r["plan"]) for z, r in record["zones"].items()}
    p = sim.p
    truth = {z: r["truth"] for z, r in record["zones"].items()}
    saltiest = max(truth, key=lambda z: truth[z]["midday_ec_ds_m"])
    hungriest = min(truth, key=lambda z: truth[z]["nutrient_factor"])

    def changed(zone: str, **delta: float) -> dict[str, dict[str, float]]:
        plan = {z: dict(v) for z, v in applied.items()}
        for key, value in delta.items():
            plan[zone][key] = max(0.0, plan[zone][key] + value)
        return plan

    options = [
        ("Default plan for every zone", sim.default_plan()),
        (f"Flush 300 L more in zone {saltiest} (highest mid-day EC that day)", changed(saltiest, flush_l=300.0)),
        (f"300 g more fertilizer in zone {hungriest} (lowest nutrient factor that day)", changed(hungriest, fertilizer_g=300.0)),
        (f"No fertilizer in zone {saltiest}", changed(saltiest, fertilizer_g=-p.fertilizer_max_g)),
        ("150 L more irrigation in every zone", {z: {**v, "irrigation_l": v["irrigation_l"] + 150.0} for z, v in applied.items()}),
    ]
    return [(label, plan) for label, plan in options if plan != applied]


def pick_days(sim: Any, played_days: int, count: int) -> list[int]:
    """The played days on which the most growth was lost to avoidable stress."""
    loss = []
    for record in sim.days[:played_days]:
        lost = 0.0
        for zr in record["zones"].values():
            t = zr["truth"]
            factor = t["water_factor"] * t["nutrient_factor"] * t["salinity_factor"]
            lost += zr["outcome"]["growth_kg"] * (1.0 / factor - 1.0) if factor > 1e-9 else 0.0
        loss.append((lost, record["day"]))
    return sorted(day for _, day in sorted(loss, reverse=True)[:count])


def counterfactuals(scenario: Scenario, seed: int, records: list[dict[str, Any]],
                    days: list[int] | None = None, max_days: int = 3) -> dict[str, Any]:
    calls = _calls(records)
    actual, actual_oks = _replay_calls(scenario, seed, calls)
    played_days = sum(1 for tool, _ in calls if tool == "advance_day")
    sim = actual.env.sim
    baseline = actual.env.ledger()["profit_eur"]
    chosen = days if days is not None else pick_days(sim, played_days, max_days)
    points = []
    for day in chosen:
        if not 0 <= day < played_days:
            continue
        options = []
        for label, plan in alternatives(sim, day):
            # Is the alternative feasible at that point? Ask the engine itself.
            probe, _ = replay(scenario, seed, [{"k": "call", "tool": t, "args": a}
                                               for t, a in _prefix(calls, day)])
            try:
                probe.env.sim.check_plan(plan)
            except RuleError as e:
                options.append({"alternative": label, "feasible": False, "reason": str(e)})
                continue
            swapped = substitute(calls, day, plan)
            if swapped is None:
                continue
            episode, oks = _replay_calls(scenario, seed, swapped)
            profit = episode.env.ledger()["profit_eur"]
            later_rejected = _newly_rejected(calls, actual_oks, swapped, oks)
            options.append({"alternative": label, "feasible": True, "plan": plan, "profit_eur": profit,
                            "delta_eur": round(profit - baseline, 2),
                            "later_plans_rejected": later_rejected})
        points.append({"day": day, "applied_plan": {z: dict(r["plan"]) for z, r in sim.days[day]["zones"].items()},
                       "plan_source": sim.days[day]["plan_source"], "alternatives": options})
    return {"method": METHOD, "actual_profit_eur": baseline, "days_played_by_player": played_days, "points": points}


def _prefix(calls: list[tuple[str, Any]], day: int) -> list[tuple[str, Any]]:
    """The recorded requests up to the morning of `day`, without that day's own plans."""
    out, advances = [], 0
    for tool, args in calls:
        if advances == day:
            if tool in ("advance_day", "finish_episode"):
                break
            if tool == "submit_day_plan":
                continue
        out.append((tool, args))
        if tool == "advance_day":
            advances += 1
    return out


def _newly_rejected(calls: list[tuple[str, Any]], oks: list[bool],
                    swapped: list[tuple[str, Any]], swapped_oks: list[bool]) -> int:
    """Recorded plans that were accepted in the real run but rejected after the
    substitution. Everything after the inserted plan is the recorded tail, in
    order, so only that tail is compared."""
    inserted = next(i for i, (a, b) in enumerate(zip(swapped, calls + [("", None)])) if a != b)
    tail = len(swapped) - inserted - 1
    if tail <= 0:
        return 0
    return sum(1 for (tool, _), was, now in zip(calls[-tail:], oks[-tail:], swapped_oks[-tail:])
               if tool == "submit_day_plan" and was and not now)
