"""Scoring, failure modes and the post-episode analysis.

Raw objective:   profit = price x crop gain - mains water - fertilizer - discharge - tests
Reward in [0,1]: clamp((profit - floor) / (informed - floor))

  floor     the profit of the default plan on this instance (run the same
            simulator with no requests). Doing nothing scores exactly 0.
  informed  the profit of the reference planner when it is told the backup
            water's salinity at the moment of the incident and sees the true
            bench state every morning (planner.informed_run). 1.0 therefore
            means "as good as a planner that knew the root cause at once";
            the reference, which has to diagnose it, scores below that.
  ceiling   a proven upper bound on any plan's profit, reported for context
            only. It ignores the incident, flushing and tests.

Both bounds are computed from the instance alone, by the same deterministic
code, in the verifier. Neither depends on who played. A player that beats the
informed planner clips to 1.0, which is why raw profit is always reported.

Failure modes are read from hidden state after the last day, never during
play, and never enter the reward. They say *how* a run lost value.
"""
from __future__ import annotations

import math
from typing import Any

from .model import best_condition, clamp, demand_l, heat_factor, uptake_rate

TOLERANCE = 1e-6
SHORT = 0.95        # a factor below this counts as a bench-day of that stress


def revenue(sim: Any) -> float:
    return sim.p.price_per_kg * sum(b.harvest for b in sim.benches.values())


def profit(sim: Any) -> float:
    return revenue(sim) - sum(sim.costs.values())


def ceiling(sim: Any) -> float:
    """An upper bound on profit for this instance.

    For each bench with h*_d the best condition reachable on day d:
      * growth g_d <= growth_max * h*_d * heat_factor(temp_d) =: g*_d;
      * nutrients enter only as fertilizer, so fertilizer >= (sum(uptake_d * g_d) - N_start) / (1 - ballast);
      * growth needs transpiration in proportion, and water enters only as
        purchased mains or reserve water, so the water bill is at least the
        cheaper price times (transpired - stored above the dead volume).
    Profit rises in every g_d while a kg sells for more than its water and
    fertilizer, so the bound is largest at g = g*. If prices ever break that,
    the bound falls back to stress-free sales alone.
    """
    p, sales, fertilizer_cost, water_needed = sim.p, 0.0, 0.0, 0.0
    water_price = min(p.mains_price_per_l, p.reserve_price_per_l)
    growth_pays = True
    for spec in sim.instance.benches:
        growth = need_n = demand = 0.0
        for day, temp in enumerate(sim.instance.temps):
            h = best_condition(p, spec.condition, day)
            g = spec.growth_max_kg * h * heat_factor(p, temp)
            d = demand_l(p, spec.transp_base_l, temp, h)
            growth += g
            demand += d
            need_n += uptake_rate(p, day) * g
            per_kg = p.fertilizer_price_per_g * uptake_rate(p, day) / (1.0 - p.fertilizer_ballast)
            if g <= 0 or p.price_per_kg <= per_kg + water_price * d / g:
                growth_pays = False
        sales += p.price_per_kg * growth
        fertilizer_cost += p.fertilizer_price_per_g * max(0.0, need_n - spec.nutrient_g) / (1.0 - p.fertilizer_ballast)
        water_needed += max(0.0, demand - (spec.volume_l - p.dead_volume_l))
    if not growth_pays:
        return sales
    return sales - fertilizer_cost - water_price * water_needed


def floor(sim: Any) -> float:
    cached = getattr(sim, "_floor", None)
    if cached is None:
        shadow = type(sim)(sim.config, sim.instance.seed, sim.instance)
        shadow.finish()
        cached = sim._floor = profit(shadow)
    return cached


def informed_profit(sim: Any) -> float:
    """Profit of the informed planner on the same instance. Cached per simulator."""
    cached = getattr(sim, "_informed", None)
    if cached is None:
        from .planner import informed_run
        shadow = type(sim)(sim.config, sim.instance.seed, sim.instance)
        informed_run(shadow)
        cached = sim._informed = profit(shadow)
    return cached


def normalize(value: float, lo: float, hi: float) -> float:
    return clamp((value - lo) / (hi - lo)) if hi > lo else 0.0


def conservation(sim: Any) -> dict[str, float]:
    worst = {"water_l": 0.0, "nutrient_g": 0.0, "salt_g": 0.0}
    for b in sim.benches.values():
        s = b.spec
        worst["water_l"] = max(worst["water_l"], abs(s.volume_l + b.water_in - b.water_out - b.volume))
        worst["nutrient_g"] = max(worst["nutrient_g"], abs(s.nutrient_g + b.nutrient_in - b.nutrient_out - b.nutrient))
        worst["salt_g"] = max(worst["salt_g"], abs(s.salt_g + b.salt_in - b.salt_out - b.salt))
    worst["reserve_l"] = abs(sim.instance.reserve_l - sim.used["reserve_l"] - sim.reserve_l)
    drawn = sim.used["mains_l"] + sim.used["reserve_l"] + sim.used["flush_l"]
    worst["bench_intake_l"] = abs(drawn - sum(b.water_in for b in sim.benches.values()))
    return worst


def failure_modes(sim: Any) -> dict[str, Any]:
    """How a run lost value, from hidden state. Meaningful once the last day has been played.

    Crop lost on a bench-day is the gap between what the bench could have grown
    at its best reachable condition and what it grew. It is split into
      carried_damage  condition below the best reachable (earlier stress)
      and, of the rest, water / nutrient / salinity shares in proportion to
      -ln(factor), so the three shares add up exactly.
    """
    p, inst = sim.p, sim.instance
    after = inst.incident_day
    lost = {"carried_damage": 0.0, "water": 0.0, "nutrient": 0.0, "salinity": 0.0}
    counts = {"nutrient_short_bench_days": 0, "salt_stress_bench_days": 0, "water_short_bench_days": 0,
              "fed_less_while_short_bench_days": 0}
    flushed_after = 0.0
    for rec in sim.days:
        d = rec["day"]
        for bench_id, br in rec["benches"].items():
            spec = sim.benches[bench_id].spec
            t, o, plan = br["truth"], br["outcome"], br["plan"]
            best = spec.growth_max_kg * best_condition(p, spec.condition, d) * t["heat_factor"]
            today = spec.growth_max_kg * o["condition_before"] * t["heat_factor"]
            lost["carried_damage"] += max(0.0, best - today)
            factors = {"water": t["water_factor"], "nutrient": t["nutrient_factor"], "salinity": t["salinity_factor"]}
            gap = max(0.0, today - o["growth_kg"])
            logs = {k: -math.log(max(v, 1e-9)) for k, v in factors.items()}
            total = sum(logs.values())
            if gap > 0 and total > 0:
                for k in factors:
                    lost[k] += gap * logs[k] / total
            counts["nutrient_short_bench_days"] += t["nutrient_factor"] < SHORT
            counts["salt_stress_bench_days"] += t["salinity_factor"] < SHORT
            counts["water_short_bench_days"] += t["water_factor"] < SHORT
            if t["nutrient_factor"] < SHORT and plan["fertilizer_g"] < p.default_fertilizer_g:
                counts["fed_less_while_short_bench_days"] += 1
            if d >= after:
                flushed_after += plan["flush_l"]
    paid = [t for t in sim.tests if t["sampled_day"] >= after]
    mains = [t["sampled_day"] for t in paid if t["test_type"] == "mains_water"]
    first_test = min((t["sampled_day"] for t in paid), default=None)
    default_days = sum(1 for rec in sim.days if rec["plan_source"] == "default")
    lost_eur = {k: round(v * p.price_per_kg, 2) for k, v in lost.items()}
    dominant = max(lost_eur, key=lambda k: lost_eur[k]) if any(v > 0.5 for v in lost_eur.values()) else "none"
    return {
        "incident_day": after,
        "first_test_after_notice_day": first_test,
        "mains_test_day": min(mains) if mains else None,
        "days_to_first_test": None if first_test is None else first_test - after,
        "crop_lost_eur": lost_eur,
        "dominant_loss": dominant,
        **counts,
        "flushed_after_incident_l": round(flushed_after, 1),
        "reserve_used_l": round(sim.used["reserve_l"], 1),
        "reserve_left_l": round(sim.reserve_l, 1),
        "default_plan_days": default_days,
        "stopped_early": bool(sim.finished_by_player),
    }


def ledger(sim: Any) -> dict[str, Any]:
    """Terminal metrics. The reward reads only `normalized_profit`; the rest is evidence."""
    lo, hi, value = floor(sim), informed_profit(sim), profit(sim)
    balance = conservation(sim)
    ok = max(balance.values()) <= TOLERANCE and sim.reserve_l >= -TOLERANCE
    fm = failure_modes(sim)
    out = {
        "profit_eur": round(value, 2),
        "normalized_profit": round(normalize(value, lo, hi), 6),
        "profit_floor_eur": round(lo, 2),
        "profit_informed_eur": round(hi, 2),
        "profit_upper_bound_eur": round(ceiling(sim), 2),
        "revenue_eur": round(revenue(sim), 2),
        "crop_gain_kg": round(sum(b.harvest for b in sim.benches.values()), 2),
        "cost_total_eur": round(sum(sim.costs.values()), 2),
        "cost_mains_water_eur": round(sim.costs["mains_water"], 2),
        "cost_reserve_water_eur": round(sim.costs["reserve_water"], 2),
        "cost_fertilizer_eur": round(sim.costs["fertilizer"], 2),
        "cost_discharge_eur": round(sim.costs["discharge"], 2),
        "cost_tests_eur": round(sim.costs["tests"], 2),
        "tests_ordered": len(sim.tests),
        "days_with_a_submitted_plan": sim.plans_submitted,
        "days_played": sim.day,
        "conservation_ok": 1.0 if ok else 0.0,
        "conservation_max_error": round(max(balance.values()), 9),
    }
    for key in ("nutrient_short_bench_days", "salt_stress_bench_days", "water_short_bench_days",
                "fed_less_while_short_bench_days", "flushed_after_incident_l", "reserve_used_l", "reserve_left_l",
                "default_plan_days"):
        out[f"fm_{key}"] = float(fm[key])
    out["fm_days_to_first_test"] = None if fm["days_to_first_test"] is None else float(fm["days_to_first_test"])
    out["fm_mains_test_day"] = None if fm["mains_test_day"] is None else float(fm["mains_test_day"])
    for key, value in fm["crop_lost_eur"].items():
        out[f"fm_lost_{key}_eur"] = value
    return out


def report(sim: Any) -> dict[str, Any]:
    """The post-episode analysis view, hidden state included. Refuses to run
    before the last day has been played."""
    if not sim.done:
        from .sim import RuleError
        raise RuleError("The analysis view shows hidden state and is available only after the episode has ended.")
    days = []
    for rec in sim.days:
        d = rec["day"]
        benches = {}
        for bench_id, br in rec["benches"].items():
            t = sim.truth[d][bench_id]
            benches[bench_id] = {
                "morning": {k: v for k, v in sim.mornings[d][bench_id].items() if k != "day"},
                "hidden_morning": {"nutrient_g_l": round(t["nutrient_g_l"], 3), "salt_g_l": round(t["salt_g_l"], 3),
                                   "ec_ds_m": round(t["ec_ds_m"], 3)},
                "plan": {k: round(v, 1) for k, v in br["plan"].items()},
                "outcome": {k: round(v, 3) for k, v in br["outcome"].items()},
                "factors": {k: round(v, 4) for k, v in br["truth"].items()},
            }
        days.append({"day": d, "temp_c": rec["temp_c"], "plan_source": rec["plan_source"],
                     "mains_salt_g_l": sim.instance.mains_salt(d),
                     "mains_drawn_l": round(rec["mains_drawn_l"], 1), "reserve_used_l": round(rec["reserve_l"], 1),
                     "reserve_left_l": round(rec["reserve_left_l"], 1),
                     "cost": {k: round(v, 2) for k, v in rec["cost"].items()},
                     "tests_ordered": [t["test_id"] for t in sim.tests if t["sampled_day"] == d],
                     "benches": benches})
    return {
        "label": "Post-episode analysis. Includes hidden state that was not available during play.",
        "seed": sim.instance.seed,
        "incident": {"day": sim.instance.incident_day, "backup_salt_g_l": sim.instance.backup_salt_g_l,
                     "usual_salt_g_l": sim.p.mains_salt_g_l},
        "result": ledger(sim),
        "failure_modes": failure_modes(sim),
        "conservation": {k: round(v, 9) for k, v in conservation(sim).items()},
        "realized_temps_c": list(sim.instance.temps),
        "days": days,
        "tests": [{**sim.public_test(t), "result": dict(t["result"])} for t in sim.tests],
        "events": list(sim.events),
    }
