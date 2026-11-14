"""What a player may see during play.

Every function here is a pure read of the simulator. None returns the split
between nutrients and salts after day 0 (only a delivered test does), the salt
in the backup water (only a delivered mains test does), the weather of a day
that has not happened, or anything computed from these. The post-episode
analysis lives in `outcome.report`.
"""
from __future__ import annotations

from typing import Any

SAMPLE_NOTE = ("A result describes the solution at the sample time, one day before delivery. The rules are "
               "public, so it can be rolled forward: mass = concentration x volume at the sample, then apply "
               "the plan and the plant uptake of each day in between.")

DAY_ORDER = [
    "1. The plan in effect is fixed: the plan submitted for today, or the default plan if none was submitted.",
    "2. Flush: flush_l litres of the bench's solution go to waste carrying nutrients and salts in proportion to "
    "their concentration; the tank is refilled with the same volume of mains water.",
    "3. Top-up: mains_l litres of mains water and reserve_l litres from the reserve tank are added. Volume above "
    "capacity overflows to waste at the mixed concentration. Each litre of mains water brings that day's mains "
    "salt; reserve water brings reserve_salt_g_l.",
    "4. Fertilizer: fertilizer_g grams dissolve; the share fertilizer_ballast is salt, the rest is nutrient. "
    "Fertilizer adds no water.",
    "5. Plants transpire, grow and take up nutrients (formulas below). Transpiration removes water only, so it "
    "concentrates what is dissolved.",
    "6. Crop condition for the next day is set from today's stress.",
    "7. Mains water (top-up and flush refill), fertilizer and discharge are charged. Test fees were charged at "
    "order time. Reserve water is charged at reserve_price_per_l; the tank is not refilled.",
    "8. Next morning: tests due are delivered, sensors are read, a new forecast is issued, notices are posted.",
]

FORMULAS = {
    "ec_ds_m": "ec_per_g_l * (nutrient_g + salt_g) / volume_l",
    "transpiration_demand_l": "transpiration_base * temp_factor * (canopy_floor + (1 - canopy_floor) * condition); "
                              "temp_factor = 1 + transp_heat_slope * (temp - transp_ref_temp_c) above the reference, "
                              "max(transp_min_factor, 1 + transp_cool_slope * (temp - transp_ref_temp_c)) below it",
    "transpired_l": "min(demand * supply, volume - dead_volume_l); supply = clamp((volume - dead_volume_l) / "
                    "(comfort_volume_l - dead_volume_l), 0, 1), with volume taken after the top-up",
    "water_factor": "transpired_l / demand",
    "midday_volume_l": "volume after the top-up - transpired_l / 2 (concentrations for stress use this volume)",
    "nutrient_factor": "1 - (1 - min(1, nutrient_g_l / nutrient_full_g_l))^2",
    "salinity_factor": "clamp(1 - ec_slope_per_ds_m * max(0, ec - ec_threshold_ds_m), 0, 1)",
    "heat_factor": "clamp(1 - growth_heat_slope * max(0, temp - growth_heat_onset_c), growth_heat_floor, 1)",
    "growth_kg": "min(growth_max * condition * heat_factor * water_factor * nutrient_factor * salinity_factor, "
                 "nutrient_g / uptake_rate)",
    "uptake_rate_g_per_kg": "uptake_g_per_kg + uptake_rise_per_day * day",
    "nutrient_uptake_g": "uptake_rate * growth_kg",
    "stress": "1 - water_factor * nutrient_factor * salinity_factor",
    "condition_next_day": "if stress > stress_tolerance: condition - damage_rate * (stress - stress_tolerance), "
                          "not below condition_floor; otherwise min(1, condition + recovery_per_day)",
    "profit_eur": "price_per_kg * total crop gain - mains water - reserve water - fertilizer - discharge - tests",
}

UNITS = {"water": "L", "nutrients and salts": "g", "concentration": "g/L", "EC": "dS/m (= mS/cm)",
         "temperature": "°C", "crop": "kg of head fresh weight", "money": "EUR", "time": "days, numbered from 0"}

WATER_SUPPLY = {
    "mains": "Unlimited and charged per litre. Its salt content is mains_salt_g_l from the usual source. The utility "
             "can switch the supply to another source at short notice; water from another source can carry "
             "several times as much salt. A notice is posted when that happens. A mains water test measures it.",
    "reserve": "A tank of clean reverse-osmosis water (reserve_salt_g_l) shared by all benches, charged at "
               "reserve_price_per_l. Limited and never refilled.",
}


def rules(sim: Any) -> dict[str, Any]:
    p = sim.p
    return {
        "objective": f"Maximize net profit at the end of day {p.horizon_days - 1}, when the crop is cut and sold: "
                     "the value of the head weight the benches add, minus all operating costs. Unused water and "
                     "fertilizer have no value.",
        "horizon_days": p.horizon_days,
        "units": UNITS,
        "benches": [{"bench_id": b.spec.id, "name": b.spec.name,
                     "growth_max_kg_per_day": b.spec.growth_max_kg,
                     "transpiration_base_l_per_day": b.spec.transp_base_l} for b in sim.benches.values()],
        "water_supply": WATER_SUPPLY,
        "reserve_tank_l": sim.instance.reserve_l,
        "parameters": p.as_dict(),
        "default_plan": sim.default_plan(),
        "plan_limits": {"mains_l + reserve_l": [0, p.top_up_max_l], "fertilizer_g": [0, p.fertilizer_max_g],
                        "flush_l": "0 to the bench's pumpable volume (volume_l - dead_volume_l)",
                        "reserve_l over all benches": "at most the reserve left"},
        "tests": {"composition": {"price_eur": p.test_price, "delay_days": p.test_delay_days,
                                  "reveals": "nutrient_g_l and salt_g_l of the bench's solution, its volume and "
                                             "exact EC, at the sample time"},
                  "mains_water": {"price_eur": p.water_test_price, "delay_days": p.test_delay_days,
                                  "reveals": "salt_g_l and EC of the mains water at the sample time"},
                  "sample_time": "the moment the test is ordered: the morning state, before that day's plan",
                  "note": SAMPLE_NOTE},
        "sensors": {"ec_ds_m": f"read every morning; error standard deviation {p.ec_sensor_sigma_ds_m} dS/m",
                    "volume_l": "exact", "condition": "exact", "crop_gain_kg": "exact",
                    "not_measured": "the split of EC between nutrients and salts; the salt in the mains water"},
        "forecast": {"days": p.forecast_days,
                     "note": "Estimates; the realized temperature of a day appears in the history once it has passed."},
        "day_order": DAY_ORDER,
        "formulas": FORMULAS,
        "evaluation": {
            "raw": "profit_eur at the end of the last day, whatever the player did or did not do",
            "reward": "clamp((profit - floor) / (ceiling - floor), 0, 1)",
            "floor": "the profit the default plan alone earns on this same scenario",
            "ceiling": "an upper bound on profit: sales if every bench grew free of water, nutrient and salinity "
                       "stress every day, minus the cheapest water and fertilizer such growth must consume. "
                       "No plan reaches it",
            "note": "Both bounds are fixed by the scenario. Stopping early does not end the season: remaining days "
                    "run under the default plan.",
        },
    }


def _round(plan: dict[str, float]) -> dict[str, float]:
    return {k: round(v, 1) for k, v in plan.items()}


def _outcome(o: dict[str, float]) -> dict[str, float]:
    return {"growth_kg": round(o["growth_kg"], 2), "transpired_l": round(o["transpired_l"], 1),
            "overflow_l": round(o["overflow_l"], 1)}


def _bench_view(sim: Any, bench_id: str) -> dict[str, Any]:
    b = sim.benches[bench_id]
    out = {"bench_id": bench_id, "name": b.spec.name, "observed_day": sim.day, **sim.mornings[-1][bench_id]}
    del out["day"]
    out["pumpable_l"] = round(int(sim.pumpable_l(bench_id) * 10) / 10.0, 1)
    out["growth_max_kg_per_day"] = b.spec.growth_max_kg
    out["transpiration_base_l_per_day"] = b.spec.transp_base_l
    if sim.days:
        last = sim.days[-1]["benches"][bench_id]
        out["yesterday"] = {"day": sim.days[-1]["day"], "plan": _round(last["plan"]), **_outcome(last["outcome"])}
    else:
        out["yesterday"] = None
    delivered = [t for t in sim.tests if t["delivered"] and t["target"] == bench_id]
    out["latest_test"] = sim.public_test(delivered[-1]) if delivered else None
    return out


def costs(sim: Any) -> dict[str, float]:
    c = {f"{k}_eur": round(v, 2) for k, v in sim.costs.items()}
    c["total_eur"] = round(sum(sim.costs.values()), 2)
    return c


def status(sim: Any) -> dict[str, Any]:
    p = sim.p
    gain = sum(b.harvest for b in sim.benches.values())
    out: dict[str, Any] = {
        "day": sim.day, "days_total": p.horizon_days, "days_left": max(0, p.horizon_days - sim.day), "done": sim.done,
        "reserve_left_l": round(sim.reserve_l, 1),
        "costs_so_far": costs(sim),
        "crop_gain_so_far_kg": round(gain, 1),
        "crop_value_so_far_eur": round(gain * p.price_per_kg, 2),
        "benches": [_bench_view(sim, b) for b in sim.benches],
        "lab_report_day_0": {z: dict(r) for z, r in sim.lab_report.items()},
        "notices": [e["text"] for e in sim.events if e["kind"] == "notice"],
        "tests_pending": sum(1 for t in sim.tests if not t["delivered"]),
        "tests_delivered_today": [sim.public_test(t) for t in sim.tests
                                  if t["delivered"] and t["delivery_day"] == sim.day],
    }
    if not sim.done:
        plan, source = sim.effective_plan()
        out["forecast_c"] = [{"day": sim.day + k, "temp_c": t} for k, t in enumerate(sim.instance.forecasts[sim.day])]
        out["plan_for_today"] = sim.plan_summary(plan, source)
    return out


def history(sim: Any, bench_id: str, first_day: int, last_day: int | None) -> dict[str, Any]:
    last = sim.day if last_day is None else min(last_day, sim.day)
    rows = []
    for day in range(max(0, first_day), last + 1):
        row: dict[str, Any] = {"day": day,
                               "morning": {k: v for k, v in sim.mornings[day][bench_id].items() if k != "day"}}
        if day < len(sim.days):
            rec = sim.days[day]
            row["temp_c"] = rec["temp_c"]
            row["plan_source"] = rec["plan_source"]
            row["plan"] = _round(rec["benches"][bench_id]["plan"])
            row["outcome"] = _outcome(rec["benches"][bench_id]["outcome"])
        rows.append(row)
    return {"bench_id": bench_id, "current_day": sim.day, "days": rows,
            "note": "morning = sensor readings at the start of the day, before that day's plan. A day without "
                    "plan and outcome has not been played yet."}


def tests(sim: Any) -> dict[str, Any]:
    return {"current_day": sim.day,
            "pending": [sim.public_test(t) for t in sim.tests if not t["delivered"]],
            "delivered": [sim.public_test(t) for t in sim.tests if t["delivered"]],
            "note": SAMPLE_NOTE}


def events(sim: Any, since_day: int) -> dict[str, Any]:
    return {"current_day": sim.day, "events": [e for e in sim.events if e["day"] >= since_day]}


def day_report(sim: Any, record: dict[str, Any], delivered: list[dict[str, Any]],
               new_events: list[dict[str, Any]]) -> dict[str, Any]:
    """What `advance` returns: the day just played, and the new morning."""
    return {
        "completed_day": record["day"], "day": sim.day, "done": sim.done,
        "temp_c": record["temp_c"], "plan_source": record["plan_source"],
        "mains_drawn_l": round(record["mains_drawn_l"], 1), "reserve_used_l": round(record["reserve_l"], 1),
        "fertilizer_used_g": round(record["fertilizer_g"], 1),
        "day_cost_eur": round(sum(record["cost"].values()), 2),
        "benches": [{"bench_id": b, "plan": _round(r["plan"]), **_outcome(r["outcome"])}
                    for b, r in record["benches"].items()],
        "tests_delivered": delivered,
        "events": new_events,
        "status": status(sim),
    }
