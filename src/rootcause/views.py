"""What a player may see during play.

Every function here is a pure read of the simulator. None of them returns the
split between nutrients and salts (only a delivered test does), the weather of
a day that has not happened, or anything computed from either. The browser and
the agent get exactly these views; the post-episode analysis lives in
`outcome.report`.
"""
from __future__ import annotations

from typing import Any

SAMPLE_NOTE = ("A result describes the solution at the sample time, one day before delivery. The rules are "
               "public, so it can be rolled forward: mass = concentration x volume at the sample, then apply "
               "the plan and the plant uptake of the day in between.")

DAY_ORDER = [
    "1. The plan in effect is fixed: the plan submitted for today, or the default plan if none was submitted. "
    "If fresh water cannot cover the default plan, every zone's default irrigation is cut by the same factor.",
    "2. Fresh water for irrigation and flushing is drawn from the shared allocation for all zones at once.",
    "3. Flush: flush_l litres of the zone's solution go to waste carrying nutrients and salts in proportion to "
    "their concentration; the same volume of fresh water replaces them.",
    "4. Irrigation: irrigation_l litres of fresh water are added. Volume above capacity overflows to waste at "
    "the mixed concentration. Every litre of fresh water brings source_salt_g_l of salt.",
    "5. Fertilizer: fertilizer_g grams dissolve into the solution; the share fertilizer_ballast is salt, the "
    "rest is nutrient. Fertilizer adds no water.",
    "6. Plants: transpire, grow and take up nutrients (formulas below). Transpiration removes water only, so "
    "it concentrates what is dissolved.",
    "7. Crop condition for the next day is set from today's stress.",
    "8. Water, fertilizer and discharge are charged. Test fees were charged when the test was ordered.",
    "9. Next morning: tests due are delivered, sensors are read, a new forecast is issued.",
]

FORMULAS = {
    "ec_ds_m": "ec_per_g_l * (nutrient_g + salt_g) / volume_l",
    "transpiration_demand_l": "transpiration_base * temp_factor * (canopy_floor + (1 - canopy_floor) * condition); "
                              "temp_factor = 1 + transp_heat_slope * (temp - transp_ref_temp_c) above the reference, "
                              "max(transp_min_factor, 1 + transp_cool_slope * (temp - transp_ref_temp_c)) below it",
    "transpired_l": "min(demand * supply, volume - dead_volume_l); supply = clamp((volume - dead_volume_l) / "
                    "(comfort_volume_l - dead_volume_l), 0, 1), with volume taken after irrigation",
    "water_factor": "transpired_l / demand",
    "midday_volume_l": "volume after irrigation - transpired_l / 2 (concentrations for stress use this volume)",
    "nutrient_factor": "1 - (1 - min(1, nutrient_g_l / nutrient_full_g_l))^2",
    "salinity_factor": "clamp(1 - ec_slope_per_ds_m * max(0, ec - ec_threshold_ds_m), 0, 1)",
    "heat_factor": "clamp(1 - growth_heat_slope * max(0, temp - growth_heat_onset_c), growth_heat_floor, 1)",
    "growth_kg": "min(growth_max * condition * heat_factor * water_factor * nutrient_factor * salinity_factor, "
                 "nutrient_g / uptake_rate)",
    "uptake_rate_g_per_kg": "uptake_g_per_kg + uptake_rise_per_day * day: fruit filling needs more nutrient per kg "
                            "as the season goes on",
    "nutrient_uptake_g": "uptake_rate * growth_kg",
    "stress": "1 - water_factor * nutrient_factor * salinity_factor",
    "condition_next_day": "if stress > stress_tolerance: condition - damage_rate * (stress - stress_tolerance), "
                          "not below condition_floor; otherwise min(1, condition + recovery_per_day)",
    "profit_eur": "price_per_kg * total harvest - water - fertilizer - discharge - tests",
}

UNITS = {"water": "L", "nutrients and salts": "g", "concentration": "g/L", "EC": "dS/m",
         "temperature": "°C", "harvest": "kg", "money": "EUR", "time": "days, numbered from 0"}


def rules(sim: Any) -> dict[str, Any]:
    p = sim.p
    return {
        "objective": f"Maximize net profit at the end of day {p.horizon_days - 1}: harvest sales minus all operating "
                     "costs. Unused water and fertilizer have no value.",
        "horizon_days": p.horizon_days,
        "units": UNITS,
        "zones": [{"zone_id": z.spec.id, "name": z.spec.name,
                   "growth_max_kg_per_day": z.spec.growth_max_kg,
                   "transpiration_base_l_per_day": z.spec.transp_base_l} for z in sim.zones.values()],
        "fresh_water_allocation_l": sim.instance.fresh_water_l,
        "parameters": p.as_dict(),
        "default_plan": sim.default_plan(),
        "plan_limits": {"irrigation_l": [0, p.irrigation_max_l], "fertilizer_g": [0, p.fertilizer_max_g],
                        "flush_l": "0 to the zone's pumpable volume (volume_l - dead_volume_l)",
                        "fresh_water_per_day_l": "irrigation + flush over all zones must not exceed the smaller of "
                                                 "daily_fresh_water_cap_l and the allocation left"},
        "tests": {"types": ["composition"], "price_eur": p.test_price, "delay_days": p.test_delay_days,
                  "reveals": "nutrient_g_l and salt_g_l of the zone's solution, its volume and exact EC, at the sample time",
                  "sample_time": "the moment the test is ordered: the morning state, before that day's plan is applied",
                  "note": SAMPLE_NOTE},
        "sensors": {"ec_ds_m": f"read every morning; error standard deviation {p.ec_sensor_sigma_ds_m} dS/m",
                    "volume_l": "exact", "condition": "exact", "harvest_kg": "exact",
                    "not_measured": "the split of EC between nutrients and salts"},
        "forecast": {"days": p.forecast_days, "normal_temp_c": p.normal_temp_c,
                     "note": "Forecasts are estimates and sharpen as the day approaches. The realized temperature "
                             "of a day appears in the history once that day has passed."},
        "day_order": DAY_ORDER,
        "formulas": FORMULAS,
        "evaluation": {
            "raw": "profit_eur at the end of the last day, whatever the player did or did not do",
            "reward": "clamp((profit - floor) / (ceiling - floor), 0, 1)",
            "floor": "the profit the default plan alone earns on this same scenario",
            "ceiling": "an upper bound on profit: sales if every zone grew free of water, nutrient and salinity "
                       "stress every day, minus the cheapest water and fertilizer that such growth must consume "
                       "beyond what the zones already hold. Flushing, tests and any stress only lower profit "
                       "from there, so no plan reaches it",
            "note": "Both bounds are fixed by the scenario, not by any player, and are shown after the episode. "
                    "Stopping early does not end the season: remaining days run under the default plan.",
        },
    }


def _zone_view(sim: Any, zone_id: str) -> dict[str, Any]:
    z = sim.zones[zone_id]
    out = {"zone_id": zone_id, "name": z.spec.name, "observed_day": sim.day, **sim.mornings[-1][zone_id]}
    del out["day"]
    out["pumpable_l"] = round(max(0.0, int(sim.pumpable_l(zone_id) * 10) / 10.0), 1)
    out["growth_max_kg_per_day"] = z.spec.growth_max_kg
    out["transpiration_base_l_per_day"] = z.spec.transp_base_l
    if sim.days:
        last = sim.days[-1]["zones"][zone_id]
        out["yesterday"] = {"day": sim.days[-1]["day"], "plan": _round_plan(last["plan"]), **_outcome(last["outcome"])}
    else:
        out["yesterday"] = None
    delivered = [t for t in sim.tests if t["delivered"] and t["zone_id"] == zone_id]
    out["latest_test"] = sim._public_test(delivered[-1]) if delivered else None
    return out


def _round_plan(plan: dict[str, float]) -> dict[str, float]:
    return {k: round(v, 1) for k, v in plan.items()}


def _outcome(o: dict[str, float]) -> dict[str, float]:
    return {"growth_kg": round(o["growth_kg"], 2), "transpired_l": round(o["transpired_l"], 1),
            "overflow_l": round(o["overflow_l"], 1)}


def costs(sim: Any) -> dict[str, float]:
    c = {f"{k}_eur": round(v, 2) for k, v in sim.costs.items()}
    c["total_eur"] = round(sum(sim.costs.values()), 2)
    return c


def status(sim: Any) -> dict[str, Any]:
    p = sim.p
    harvest = sum(z.harvest for z in sim.zones.values())
    out: dict[str, Any] = {
        "day": sim.day, "days_total": p.horizon_days, "days_left": max(0, p.horizon_days - sim.day), "done": sim.done,
        "fresh_water": {"left_l": round(sim.fresh_water_l, 1), "allocation_l": sim.instance.fresh_water_l,
                        "daily_cap_l": p.daily_fresh_water_cap_l,
                        "available_today_l": round(int(sim.available_today_l() * 10) / 10.0, 1)},
        "costs_so_far": costs(sim),
        "harvest_so_far_kg": round(harvest, 1),
        "harvest_value_so_far_eur": round(harvest * p.price_per_kg, 2),
        "zones": [_zone_view(sim, z) for z in sim.zones],
        "tests_pending": sum(1 for t in sim.tests if not t["delivered"]),
        "tests_delivered_today": [sim._public_test(t) for t in sim.tests
                                  if t["delivered"] and t["delivery_day"] == sim.day],
        "yesterday_plan": ({"source": sim.days[-1]["plan_source"],
                            "zones": {z: _round_plan(r["plan"]) for z, r in sim.days[-1]["zones"].items()}}
                           if sim.days else None),
    }
    if not sim.done:
        plan, source = sim.effective_plan()
        out["forecast_today_temp_c"] = sim.instance.forecasts[sim.day][0]
        out["plan_for_today"] = sim.plan_summary(plan, source)
    return out


def history(sim: Any, zone_id: str, first_day: int, last_day: int | None) -> dict[str, Any]:
    last = sim.day if last_day is None else min(last_day, sim.day)
    rows = []
    for day in range(max(0, first_day), last + 1):
        row: dict[str, Any] = {"day": day, "morning": {k: v for k, v in sim.mornings[day][zone_id].items() if k != "day"}}
        if day < len(sim.days):
            rec = sim.days[day]
            row["temp_c"] = rec["temp_c"]
            row["plan_source"] = rec["plan_source"]
            row["plan"] = _round_plan(rec["zones"][zone_id]["plan"])
            row["outcome"] = _outcome(rec["zones"][zone_id]["outcome"])
        rows.append(row)
    return {"zone_id": zone_id, "current_day": sim.day, "days": rows,
            "note": "morning = sensor readings at the start of the day, before that day's plan. A day without "
                    "plan and outcome has not been played yet."}


def forecast(sim: Any) -> dict[str, Any]:
    p = sim.p
    if sim.done:
        return {"issued_day": sim.day, "days": [], "normal_temp_c": p.normal_temp_c}
    issued = sim.instance.forecasts[sim.day]
    return {"issued_day": sim.day,
            "days": [{"day": sim.day + k, "lead_days": k, "temp_c": t} for k, t in enumerate(issued)],
            "normal_temp_c": p.normal_temp_c,
            "note": "Estimates. Error grows with lead time. Days beyond the forecast have no estimate; "
                    "normal_temp_c is the seasonal normal."}


def tests(sim: Any) -> dict[str, Any]:
    return {"current_day": sim.day,
            "pending": [sim._public_test(t) for t in sim.tests if not t["delivered"]],
            "delivered": [sim._public_test(t) for t in sim.tests if t["delivered"]],
            "note": SAMPLE_NOTE}


def events(sim: Any, since_day: int) -> dict[str, Any]:
    return {"current_day": sim.day, "events": [e for e in sim.events if e["day"] >= since_day]}


def day_report(sim: Any, record: dict[str, Any], delivered: list[dict[str, Any]],
               new_events: list[dict[str, Any]]) -> dict[str, Any]:
    """What `advance` returns: the day just played, and the new morning."""
    return {
        "completed_day": record["day"], "day": sim.day, "done": sim.done,
        "temp_c": record["temp_c"], "plan_source": record["plan_source"],
        "fresh_water_used_l": round(record["irrigation_l"] + record["flush_l"], 1),
        "fertilizer_used_g": round(record["fertilizer_g"], 1),
        "day_cost_eur": round(sum(record["cost"].values()), 2),
        "zones": [{"zone_id": z, "plan": _round_plan(r["plan"]), **_outcome(r["outcome"])}
                  for z, r in record["zones"].items()],
        "tests_delivered": delivered,
        "events": new_events,
        "status": status(sim),
    }
