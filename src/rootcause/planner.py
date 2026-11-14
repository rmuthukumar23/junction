"""The planners: a diagnosing reference, a blind variant, and the informed bound.

All three share one planning core (`plan_day`) and differ only in what they
believe about the mains water:

  reference  Diagnoses. When the utility notice arrives it orders a mains water
             test at once, and from the next morning it also estimates the new
             salt content from the benches' own EC readings: the rise in EC that
             its nutrient model does not explain is salt brought by mains
             water. Plays through the public tools only.
  blind      The same planner and the same tools, but it ignores the notice and
             never tests: it assumes the water is unchanged and trusts its
             model. It shows what the incident costs a good planner that does
             not look for the root cause.
  informed   The same planner told the true backup salinity from the moment of
             the incident. It is not a player: the scorer runs it on the
             instance to set the top of the reward scale (outcome.informed_profit).

Plan. Each morning, for each bench, it scores a grid of candidates

    flush today  x  nutrient level to hold  x  volume level to hold
                 x  reserve share of today's top-up  x  reserve share of later top-ups

by simulating its estimate of that bench to the last day under the forecast
and the believed mains salt, adding up sales minus costs. Benches share the
reserve, so it then picks one candidate per bench to maximize the total while
the planned reserve use fits what is left, by raising an internal price on
reserve water. Only today's part of the plan is submitted; tomorrow it plans
again from new readings.
"""
from __future__ import annotations

from typing import Any, NamedTuple

from envkit.policies import Client, Policy

from .model import Params, demand_l, step_bench

FLUSHES_L = (0.0, 150.0, 300.0)
NUTRIENT_LEVELS_G_L = (0.6, 0.75, 0.9, 1.05)                  # held at mid-day
VOLUME_LEVELS_L = (650.0, 800.0, 950.0, 1100.0)               # held at the end of the day
RESERVE_SHARES = (0.0, 0.25, 0.5, 0.75, 1.0)                  # of a day's top-up: today, and every later day
RESERVE_PRICES = tuple(round(0.005 * k, 3) for k in range(0, 41)) + (0.3, 0.5, 1.0, 2.0)
# Until the first evidence arrives the reference assumes the new water is this
# salty (five times the usual mains): the notice and the rules say a backup
# source can carry several times as much salt, so it hedges rather than assume nothing changed.
PRECAUTION_SALT_G_L = 0.5


class Candidate(NamedTuple):
    value: float          # sales minus costs over the rest of the season, EUR
    reserve_total: float  # reserve this candidate uses over the rest of the season
    plan: dict[str, float]


class Belief(NamedTuple):
    """What a planner believes about one bench this morning."""
    growth_max: float
    transp_base: float
    volume: float
    nutrient: float
    salt: float
    condition: float


def day_amounts(p: Params, b: Belief, v: float, n: float, h: float, temp: float, flush: float,
                level: float, volume_level: float, share: float, last_day: bool) -> dict[str, float]:
    """The top-up and fertilizer that hold the two levels for one day."""
    demand = demand_l(p, b.transp_base, temp, h)
    if last_day:   # solution left after the cut is worth nothing
        volume_level = min(volume_level, p.comfort_volume_l + 0.5 * demand)
    top_up = max(0.0, min(p.top_up_max_l, p.capacity_l - v, volume_level + demand - v))
    n_after_flush = n * (1.0 - min(1.0, flush / v)) if v > 0 else n
    wanted = level * (v + top_up - 0.5 * demand)
    fertilizer = min(p.fertilizer_max_g, max(0.0, (wanted - n_after_flush) / (1.0 - p.fertilizer_ballast)))
    return {"mains_l": top_up * (1.0 - share), "reserve_l": top_up * share, "fertilizer_g": fertilizer,
            "flush_l": flush}


def rollout(p: Params, b: Belief, temps: list[float], day0: int, salt_by_day: list[float],
            flush_today: float, level: float, volume_level: float, share_today: float,
            share_later: float) -> Candidate:
    v, n, s, h = b.volume, b.nutrient, b.salt, b.condition
    value = reserve_total = 0.0
    today: dict[str, float] = {}
    last = len(temps) - 1
    for k, temp in enumerate(temps):
        flush = min(flush_today, max(0.0, v - p.dead_volume_l)) if k == 0 else 0.0
        share = share_today if k == 0 else share_later
        a = day_amounts(p, b, v, n, h, temp, flush, level, volume_level, share, k == last)
        r = step_bench(p, b.growth_max, b.transp_base, v, n, s, h, a["mains_l"], a["reserve_l"], a["fertilizer_g"],
                       a["flush_l"], temp, day0 + k, salt_by_day[k])
        value += (p.price_per_kg * r.growth_kg - (a["mains_l"] + a["flush_l"]) * p.mains_price_per_l
                  - a["reserve_l"] * p.reserve_price_per_l
                  - a["fertilizer_g"] * p.fertilizer_price_per_g - (a["flush_l"] + r.overflow_l) * p.discharge_price_per_l)
        reserve_total += a["reserve_l"]
        if k == 0:
            today = a
        v, n, s, h = r.volume_l, r.nutrient_g, r.salt_g, r.condition
    return Candidate(value, reserve_total, today)


def plan_day(p: Params, beliefs: dict[str, Belief], temps: list[float], day0: int, salt_by_day: list[float],
             reserve_left: float) -> dict[str, dict[str, float]]:
    """Today's plan for every bench."""
    options: dict[str, list[Candidate]] = {}
    for bench_id, b in beliefs.items():
        shares = RESERVE_SHARES if reserve_left > 1e-6 else (0.0,)
        options[bench_id] = [rollout(p, b, temps, day0, salt_by_day, f, lvl, vol, now, later)
                             for f in FLUSHES_L for lvl in NUTRIENT_LEVELS_G_L
                             for vol in VOLUME_LEVELS_L for now in shares for later in shares]
    picks: dict[str, Candidate] = {}
    for price in RESERVE_PRICES:
        picks = {z: max(cs, key=lambda c: c.value - price * c.reserve_total) for z, cs in options.items()}
        if sum(c.reserve_total for c in picks.values()) <= reserve_left + 1e-6:
            break
    else:   # nothing fits the season's reserve: take the thriftiest options
        picks = {z: min(cs, key=lambda c: (c.reserve_total, -c.value)) for z, cs in options.items()}
    plan = {z: dict(c.plan) for z, c in picks.items()}
    today = sum(bp["reserve_l"] for bp in plan.values())
    if today > reserve_left and today > 0:
        scale = reserve_left / today
        for bp in plan.values():
            moved = bp["reserve_l"] * (1.0 - scale)
            bp["reserve_l"] -= moved
            bp["mains_l"] += moved
    return {z: {k: int(v * 10) / 10.0 for k, v in bp.items()} for z, bp in plan.items()}   # round down


def horizon_temps(forecast: list[float], days_left: int) -> list[float]:
    temps = list(forecast[:days_left])
    while len(temps) < days_left:
        temps.append(temps[-1] if temps else 22.0)
    return temps


# -- the players ------------------------------------------------------------------------

class _Tracker:
    """A planner's own bookkeeping of each bench's nutrient and salt mass."""

    def __init__(self, p: Params, rules: dict[str, Any], status: dict[str, Any]):
        self.p = p
        self.specs = {b["bench_id"]: (b["growth_max_kg_per_day"], b["transpiration_base_l_per_day"])
                      for b in rules["benches"]}
        lab = status["lab_report_day_0"]
        self.mass = {z: (r["nutrient_g_l"] * r["volume_l"], r["salt_g_l"] * r["volume_l"]) for z, r in lab.items()}
        self.read(status)

    def read(self, status: dict[str, Any]) -> None:
        self.morning = {b["bench_id"]: b for b in status["benches"]}

    def beliefs(self) -> dict[str, Belief]:
        out = {}
        for z, (g, t) in self.specs.items():
            m = self.morning[z]
            n, s = self.mass[z]
            out[z] = Belief(g, t, m["volume_l"], n, s, m["condition"])
        return out

    def roll(self, day: int, plan: dict[str, dict[str, float]], temp: float, salt: float,
             before: dict[str, Belief]) -> None:
        """Move every bench's masses through the day just played."""
        for z, b in before.items():
            bp = plan[z]
            r = step_bench(self.p, b.growth_max, b.transp_base, b.volume, b.nutrient, b.salt, b.condition,
                           bp["mains_l"], bp["reserve_l"], bp["fertilizer_g"], bp["flush_l"], temp, day, salt)
            self.mass[z] = (r.nutrient_g, r.salt_g)


class Reference(Policy):
    """Diagnoses the incident, then plans with what it learned."""

    diagnose = True

    def run(self, client: Client) -> None:
        rules = client.call("get_rules")["result"]
        p = Params.from_mapping(rules["parameters"])
        status = client.call("get_status")["result"]
        track = _Tracker(p, rules, status)
        usual = p.mains_salt_g_l
        believed = usual            # salt in mains water, as far as this planner knows
        noticed_day: int | None = None
        history: list[dict[str, Any]] = []    # per played day: beliefs before, plan, temp
        while not client.done:
            day = status["day"]
            if self.diagnose and noticed_day is None and status["notices"]:
                noticed_day = day
                believed = PRECAUTION_SALT_G_L
                client.call("order_water_test")
            temps = horizon_temps([f["temp_c"] for f in status["forecast_c"]], status["days_left"])
            plan = plan_day(p, track.beliefs(), temps, day, [believed] * len(temps), status["reserve_left_l"])
            if not client.call("submit_day_plan", bench_plans=plan)["ok"]:
                plan = None
            before = track.beliefs()
            response = client.call("advance_day")
            if not response["ok"]:
                return
            report = response["result"]
            applied = {r["bench_id"]: r["plan"] for r in report["benches"]}
            history.append({"day": day, "before": before, "plan": applied, "temp": report["temp_c"]})
            status = report["status"]
            track.read(status)
            if self.diagnose and noticed_day is not None:
                measured = [t["result"]["salt_g_l"] for t in report["tests_delivered"]
                            if t["test_type"] == "mains_water"]
                if measured:
                    believed = measured[-1]
                else:
                    believed = self.estimate_salt(p, history, track, noticed_day, believed)
                # Replay every day since the notice with the corrected belief.
                self.replay(track, history, noticed_day, usual, believed)
            else:
                track.roll(day, applied, report["temp_c"], believed, before)
            if client.done:
                return

    @staticmethod
    def replay(track: _Tracker, history: list[dict[str, Any]], since: int, usual: float, salt: float) -> None:
        start = next(i for i, h in enumerate(history) if h["day"] == since)
        b0 = history[start]["before"]
        track.mass = {z: (b.nutrient, b.salt) for z, b in b0.items()}
        for h in history[start:]:
            before = {z: b._replace(nutrient=track.mass[z][0], salt=track.mass[z][1]) for z, b in h["before"].items()}
            h["before"] = before
            track.roll(h["day"], h["plan"], h["temp"], salt, before)

    @staticmethod
    def estimate_salt(p: Params, history: list[dict[str, Any]], track: _Tracker, since: int, guess: float) -> float:
        """The mains salt that best explains this morning's EC readings.

        EC is linear in dissolved mass and the masses are linear in the mains
        salt, so try a fine grid and keep the value with the least squared
        error over all benches. Sensor noise is small next to the signal."""
        best, best_err = guess, float("inf")
        saved = dict(track.mass)
        snapshots = [dict(h["before"]) for h in history]
        for k in range(0, 301):
            salt = k * 0.005
            Reference.replay(track, history, since, p.mains_salt_g_l, salt)
            err = 0.0
            for z, (n, s) in track.mass.items():
                m = track.morning[z]
                predicted = p.ec_per_g_l * (n + s) / m["volume_l"]
                err += (predicted - m["ec_ds_m"]) ** 2
            if err < best_err:
                best, best_err = salt, err
            for h, snap in zip(history, snapshots):
                h["before"] = dict(snap)
        track.mass = saved
        return best


class Blind(Reference):
    """The same planner, but it ignores the notice and never tests."""

    diagnose = False


def informed_run(sim: Any) -> None:
    """Play `sim` with the planner, told the true backup salinity from the incident on.

    Runs directly on a simulator (it is the scorer's yardstick, not a player).
    Its beliefs are the true masses each morning."""
    p, inst = sim.p, sim.instance
    while not sim.done:
        day = sim.day
        beliefs = {z: Belief(b.spec.growth_max_kg, b.spec.transp_base_l, b.volume, b.nutrient, b.salt, b.condition)
                   for z, b in sim.benches.items()}
        temps = horizon_temps(list(inst.forecasts[day]), sim.horizon - day)
        salts = [inst.mains_salt(d) if d >= inst.incident_day and day >= inst.incident_day else p.mains_salt_g_l
                 for d in range(day, sim.horizon)]
        plan = plan_day(p, beliefs, temps, day, salts, sim.reserve_l)
        sim.submit_plan(plan)
        sim.advance()
