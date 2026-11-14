"""Scoring and the post-episode analysis.

Raw objective:   profit = price x harvest - water - fertilizer - discharge - tests
Reward in [0,1]: clamp((profit - floor) / (ceiling - floor))

Both bounds are properties of the scenario instance alone:

  floor    the profit of the default plan on this instance: what the greenhouse
           earns if nobody decides anything. Computed by running this same
           simulator with no requests.
  ceiling  an upper bound on the profit of any plan (derivation in `ceiling`):
           sales from stress-free growth on every day, minus the cheapest
           water and fertilizer such growth must consume beyond what the zones
           hold at the start. It ignores the day needed to learn a zone's
           composition, all flushing, all tests and every forecast error, so
           it is not attainable; it marks the top of the scale, not a target.

The conversion is monotonic in profit and never looks at who is playing.
Profit below the floor clips to 0, which is why raw profit is always reported
next to the reward.
"""
from __future__ import annotations

from typing import Any

from .model import best_condition, clamp, heat_factor, transpiration_factor, uptake_rate

TOLERANCE = 1e-6


def revenue(sim: Any) -> float:
    return sim.p.price_per_kg * sum(z.harvest for z in sim.zones.values())


def profit(sim: Any) -> float:
    return revenue(sim) - sum(sim.costs.values())


def ceiling(sim: Any) -> float:
    """An upper bound on profit for this instance, zone by zone.

    Write g_d for a zone's growth on day d and h*_d for the best condition the
    rules allow on that day (start condition plus the maximum recovery).

      * g_d <= growth_max * h*_d * heat_factor(temp_d) =: g*_d.
      * Growth on day d takes up `uptake_rate(d)` per kg, and nutrients enter a
        zone only as fertilizer, so fertilizer >= (sum(uptake_d * g_d) - N_start) / (1 - ballast).
      * Growth needs transpiration in proportion (water_factor = transpired /
        demand), and demand per kg is smallest at the best condition, so
        transpired_d >= g_d * demand(h*_d) / g*_d. Water enters a zone only
        from the allocation, so purchases >= sum(transpired) - (V_start - dead volume).

    Profit is therefore at most
        price * sum(g) - water_price * max(0, sum(g_d * demand*_d / g*_d) - stored)
                       - fertilizer_price * max(0, uptake * sum(g) - N_start) / (1 - ballast)
    which increases in every g_d whenever a kg sells for more than the water
    and fertilizer it needs, so it is largest at g = g*. If prices were ever
    set so that this fails, the bound falls back to stress-free sales alone.
    """
    p, total = sim.p, 0.0
    for spec in sim.instance.zones:
        growth = demand = needed = 0.0
        growth_pays = True
        for day, temp in enumerate(sim.instance.temps):
            h = best_condition(p, spec.condition, day)
            g = spec.growth_max_kg * h * heat_factor(p, temp)
            d = spec.transp_base_l * transpiration_factor(p, temp) * (p.canopy_floor + (1.0 - p.canopy_floor) * h)
            growth += g
            demand += d
            needed += uptake_rate(p, day) * g
            per_kg_fertilizer = p.fertilizer_price_per_g * uptake_rate(p, day) / (1.0 - p.fertilizer_ballast)
            if g <= 0 or p.price_per_kg <= per_kg_fertilizer + p.water_price_per_l * d / g:
                growth_pays = False
        bound = p.price_per_kg * growth
        if growth_pays:
            water = max(0.0, demand - (spec.volume_l - p.dead_volume_l))
            fertilizer = max(0.0, needed - spec.nutrient_g) / (1.0 - p.fertilizer_ballast)
            bound -= p.water_price_per_l * water + p.fertilizer_price_per_g * fertilizer
        total += bound
    return total


def floor(sim: Any) -> float:
    """Profit of the default plan on the same instance. Cached per simulator."""
    cached = getattr(sim, "_floor", None)
    if cached is None:
        shadow = type(sim)(sim.config, sim.instance.seed, sim.instance)
        shadow.finish()
        cached = sim._floor = profit(shadow)
    return cached


def normalize(value: float, lo: float, hi: float) -> float:
    return clamp((value - lo) / (hi - lo)) if hi > lo else 0.0


def conservation(sim: Any) -> dict[str, float]:
    """Largest imbalance of each tracked quantity. All should be ~0: what a zone
    holds must equal what it started with, plus what went in, minus what left."""
    worst = {"water_l": 0.0, "nutrient_g": 0.0, "salt_g": 0.0}
    for z in sim.zones.values():
        s = z.spec
        worst["water_l"] = max(worst["water_l"], abs(s.volume_l + z.water_in - z.water_out - z.volume))
        worst["nutrient_g"] = max(worst["nutrient_g"], abs(s.nutrient_g + z.nutrient_in - z.nutrient_out - z.nutrient))
        worst["salt_g"] = max(worst["salt_g"], abs(s.salt_g + z.salt_in - z.salt_out - z.salt))
    drawn = sim.used["irrigation_l"] + sim.used["flush_l"]
    worst["fresh_water_l"] = abs(sim.instance.fresh_water_l - drawn - sim.fresh_water_l)
    worst["zone_intake_l"] = abs(drawn - sum(z.water_in for z in sim.zones.values()))
    return worst


def ledger(sim: Any) -> dict[str, Any]:
    """Terminal metrics. Meaningful once the last day has been played."""
    lo, hi, value = floor(sim), ceiling(sim), profit(sim)
    balance = conservation(sim)
    ok = max(balance.values()) <= TOLERANCE and sim.fresh_water_l >= -TOLERANCE
    return {
        "profit_eur": round(value, 2),
        "normalized_profit": round(normalize(value, lo, hi), 6),
        "profit_floor_eur": round(lo, 2),
        "profit_ceiling_eur": round(hi, 2),
        "revenue_eur": round(revenue(sim), 2),
        "harvest_kg": round(sum(z.harvest for z in sim.zones.values()), 2),
        "cost_total_eur": round(sum(sim.costs.values()), 2),
        "cost_water_eur": round(sim.costs["water"], 2),
        "cost_fertilizer_eur": round(sim.costs["fertilizer"], 2),
        "cost_discharge_eur": round(sim.costs["discharge"], 2),
        "cost_tests_eur": round(sim.costs["tests"], 2),
        "fresh_water_used_l": round(sim.used["irrigation_l"] + sim.used["flush_l"], 1),
        "fresh_water_left_l": round(sim.fresh_water_l, 1),
        "fertilizer_used_g": round(sim.used["fertilizer_g"], 1),
        "tests_ordered": len(sim.tests),
        "days_with_a_submitted_plan": sim.plans_submitted,
        "days_played": sim.day,
        "conservation_ok": 1.0 if ok else 0.0,
        "conservation_max_error": round(max(balance.values()), 9),
    }


def report(sim: Any) -> dict[str, Any]:
    """The post-episode analysis view, hidden state included. Refuses to run
    before the last day has been played."""
    if not sim.done:
        from .sim import RuleError
        raise RuleError("The analysis view shows hidden state and is available only after the episode has ended.")
    p = sim.p
    days = []
    for rec in sim.days:
        d = rec["day"]
        zones = {}
        for zone_id, zr in rec["zones"].items():
            t = sim.truth[d][zone_id]
            zones[zone_id] = {
                "morning": {k: v for k, v in sim.mornings[d][zone_id].items() if k != "day"},
                "hidden_morning": {"nutrient_g_l": round(t["nutrient_g_l"], 3), "salt_g_l": round(t["salt_g_l"], 3),
                                   "ec_ds_m": round(t["ec_ds_m"], 3)},
                "plan": {k: round(v, 1) for k, v in zr["plan"].items()},
                "outcome": {k: round(v, 3) for k, v in zr["outcome"].items()},
                "factors": {k: round(v, 4) for k, v in zr["truth"].items()},
            }
        days.append({"day": d, "temp_c": rec["temp_c"], "plan_source": rec["plan_source"],
                     "forecast_issued": list(sim.instance.forecasts[d]),
                     "fresh_water_used_l": round(rec["irrigation_l"] + rec["flush_l"], 1),
                     "fresh_water_left_l": round(rec["fresh_water_left_l"], 1),
                     "fertilizer_g": round(rec["fertilizer_g"], 1), "discharge_l": round(rec["discharge_l"], 1),
                     "cost": {k: round(v, 2) for k, v in rec["cost"].items()},
                     "tests_ordered": [t["test_id"] for t in sim.tests if t["sampled_day"] == d],
                     "zones": zones})
    final = {}
    for zone_id, z in sim.zones.items():
        t = sim.truth[-1][zone_id]
        final[zone_id] = {"name": z.spec.name, "starting_composition_type": z.spec.composition,
                          "growth_max_kg_per_day": z.spec.growth_max_kg,
                          "transpiration_base_l_per_day": z.spec.transp_base_l,
                          "harvest_kg": round(z.harvest, 2), "revenue_eur": round(z.harvest * p.price_per_kg, 2),
                          "final_condition": round(z.condition, 3), "final_volume_l": round(z.volume, 1),
                          "final_nutrient_g_l": round(t["nutrient_g_l"], 3), "final_salt_g_l": round(t["salt_g_l"], 3),
                          "final_morning": {k: v for k, v in sim.mornings[-1][zone_id].items() if k != "day"}}
    return {
        "label": "Post-episode analysis. Includes hidden state that was not available during play.",
        "seed": sim.instance.seed,
        "finished_by_player": sim.finished_by_player,
        "result": ledger(sim),
        "conservation": {k: round(v, 9) for k, v in conservation(sim).items()},
        "fresh_water_allocation_l": sim.instance.fresh_water_l,
        "realized_temps_c": list(sim.instance.temps),
        "zones": final,
        "days": days,
        "tests": [{**{k: t[k] for k in ("test_id", "zone_id", "test_type", "sampled_day", "delivery_day", "cost_eur")},
                   "result": dict(t["result"])} for t in sim.tests],
        "events": list(sim.events),
    }
