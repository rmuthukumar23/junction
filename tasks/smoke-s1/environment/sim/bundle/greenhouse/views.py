"""What the agent may see. Every function is a pure read of the simulator.

Sensor readings are the ones recorded at the end of the last hour (so reading
twice gives the same numbers); estimates and business views draw from streams
named after what they observe and the hour (contracts.py).
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .world.sim import DUTY_END_H, DUTY_START_H, Greenhouse, on_duty_hour

HISTORY_MAX_HOURS = 168
BRIEFING_FORECAST_H = 72      # how far ahead the morning briefing forecasts


def clock(sim: Greenhouse) -> dict[str, Any]:
    h = min(sim.hour, sim.horizon_h)
    return {"hour": h, "day": h // 24, "hour_of_day": h % 24, "time": f"{h % 24:02d}:00",
            "on_duty": on_duty_hour(h) and not sim.done, "hours_total": sim.horizon_h,
            "hours_left": sim.hours_left(), "done": sim.done}


def night_schedule(sim: Greenhouse) -> list[dict[str, Any]]:
    return [{"from_hour": e.hour, "climate": {c: asdict(s) for c, s in e.climate.items()},
             "energy": asdict(e.energy)} for e in sim.night]


def status(sim: Greenhouse) -> dict[str, Any]:
    recent = [asdict(a) for a in sim.alarms if a.hour >= sim.hour - 24]
    return {
        "clock": clock(sim),
        "readings": sim.readings,
        "settings": {"climate": {c: asdict(s) for c, s in sim.climate.items()}, "energy": asdict(sim.energy),
                     "night_schedule": night_schedule(sim), "unattended": sim.unattended},
        "equipment_faults": sorted(sim.effects),
        "free_area_m2": {c: round(sim.free_area_m2(c), 1) for c in sim.facility.compartment_ids},
        "business": sim.business.view(sim.hour, sim.rng.stream(f"business/{sim.hour}")),
        "alarms_last_24h": recent,
        "batches": sim.batch_views(),
    }


def rules(sim: Greenhouse) -> dict[str, Any]:
    return {
        "objective": ("Maximise net profit in EUR at the end of the last hour: harvest revenue plus electricity "
                      "sold, minus gas, electricity bought, CO2, wages, hiring, contractors, spare parts, express "
                      "surcharges, seedlings and other orders. Crop still standing and parts left in stock at the "
                      "end are worth nothing."),
        "day": {
            "turn": (f"You act once a day, at {DUTY_START_H:02d}:00 (see turn). The day runs "
                     f"{DUTY_START_H:02d}:00-{DUTY_END_H:02d}:00 on your day settings, with the crew at work; "
                     f"the night runs {DUTY_END_H:02d}:00-{DUTY_START_H:02d}:00 on your night schedule. Nobody "
                     "acts in between and nothing responds to alarms: they are logged with their hour and shown "
                     "in the next morning's briefing."),
            "night_schedule": ("set_night_schedule sets hourly entries of fixed values (climate per compartment "
                               "and the energy centre). An entry applies from its hour until the next one and the "
                               "schedule repeats every night until you change it. It holds values only: no "
                               "conditions or triggers."),
            "handover": (f"Day 1 starts at {DUTY_START_H:02d}:00: the night before ran on the baseline. At hour 0 "
                         "the day settings and the night schedule are both the facility's baseline "
                         "(facility.fallback)."),
            "staff": "The crew works its shift inside the day; planting and harvesting progress only then.",
        },
        "clock": {"hours_total": sim.horizon_h, "substeps_per_hour": sim.substeps,
                  "end_shift": "end_shift runs until 06:00 the next day (or the end of the episode)."},
        "repairs": ("Damage (a failed boiler, broken glass) persists until repaired. A repair needs three things "
                    "at once: the right contractor booked (book_contractor), the parts on site (place_orders "
                    "'part:<id>'), and a day-shift hour. After a regional storm, parts ordered get the surge "
                    "lead time and contractors the surge response time (business.contractors, business.items)."),
        "settings": "Day settings and the night schedule stand until changed. After you stop, both keep running "
                    "and nobody acts: nothing is ordered, planted, harvested or repaired.",
        "facility": sim.facility.rules(),
        "crops": {cid: m.describe() for cid, m in sim.growth.items()},
        "business": sim.business.rules(),
        "hidden_parameter_ranges": sim.m.published_ranges,
    }


def batches(sim: Greenhouse) -> dict[str, Any]:
    return {"clock": clock(sim), "batches": sim.batch_views()}


def forecast(sim: Greenhouse, hours: int) -> dict[str, Any]:
    return {"clock": clock(sim), "forecast": sim.facility.forecast(sim.hour, hours)}


def news(sim: Greenhouse, days: int) -> dict[str, Any]:
    feed = getattr(sim.business, "news", None)
    return {"clock": clock(sim), "headlines": feed(sim.hour, days) if callable(feed) else []}


def briefing(sim: Greenhouse, actions_left: int) -> dict[str, Any]:
    """The morning briefing: everything the player is shown at 06:00, in one compact
    result (there are no read tools). It comes back when a day ends; day 1's is in the
    task instruction."""
    night = night_report(sim)
    summary: dict[str, Any] = {"night": night.get("night")}
    if night.get("night"):
        summary["alarms_and_events"] = night["alarms_and_events"]
        summary["climate"] = {c: _span(rows) for c, rows in night["hourly_climate"].items()}
        summary["batches"] = [{k: v for k, v in b.items() if k in ("id", "status_now", "units_change",
                                                                  "quality_change")} for b in night["batches"]]
        summary["money_over_night_eur"] = night["money_over_night_eur"]
    else:
        summary["note"] = night.get("note")
    try:
        weather = columns(sim.facility.forecast(sim.hour, BRIEFING_FORECAST_H))
    except ValueError:                     # past the end of the recorded series
        weather = {}
    return _compact({"clock": clock(sim), "actions_left_today": actions_left, "status": status(sim),
                     "last_night": summary, "news_last_3_days": news(sim, 3)["headlines"],
                     "forecast": weather})


def columns(forecast: dict[str, Any]) -> dict[str, Any]:
    """Hourly rows as one list per field ({"hour": [...], "temp_c": [...]}): the same
    numbers in a third of the text."""
    out: dict[str, Any] = {}
    for key, rows in forecast.items():
        if isinstance(rows, list) and rows and all(isinstance(r, dict) for r in rows):
            out[key] = {f: [r.get(f) for r in rows] for f in rows[0]}
        else:
            out[key] = rows
    return out


def rows(table: dict[str, Any]) -> dict[str, Any]:
    """The inverse of `columns`."""
    out: dict[str, Any] = {}
    for key, cols in table.items():
        if isinstance(cols, dict) and cols and all(isinstance(v, list) for v in cols.values()):
            n = min(len(v) for v in cols.values())
            out[key] = [{f: v[i] for f, v in cols.items()} for i in range(n)]
        else:
            out[key] = cols
    return out


def _span(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("temp_c", "rh_pct", "co2_ppm"):
        values = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        if values:
            out[key] = {"min": min(values), "max": max(values)}
    return out


def _compact(value: Any) -> Any:
    """Round floats to 2 decimals so the briefing stays short; integers and text unchanged."""
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, dict):
        return {k: _compact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_compact(v) for v in value]
    return value


def night_report(sim: Greenhouse) -> dict[str, Any]:
    """The morning report (spec 14.1): built from the hourly history and the ledger."""
    night = sim.last_night
    if night is None or night.get("to_hour") is None:
        return {"clock": clock(sim), "night": None,
                "note": "No night has run under your schedule yet: the handover night ran on the baseline."}
    first, last = night["from_hour"], night["to_hour"]
    alarms = [asdict(a) for a in sim.alarms if first <= a.hour < last]
    climate: dict[str, list[dict[str, Any]]] = {c: [] for c in sim.facility.compartment_ids}
    for rec in sim.history[first:last]:
        for c in climate:
            r = rec.readings.get("compartments", {}).get(c, {})
            climate[c].append({"hour": rec.hour + 1, "temp_c": _r(r.get("temp_c")), "rh_pct": _r(r.get("rh_pct")),
                               "co2_ppm": _r(r.get("co2_ppm"), 0)})
    before, after = night["batches"], night["batches_after"]
    crops = []
    for bid, b0 in before.items():
        b1 = after.get(bid)
        batch = sim.batches.get(bid)
        row = {"id": bid, "compartment": b0["compartment"], "status_at_18": b0["status"],
               "status_now": batch.status if batch else "unknown",
               "estimated_units_at_18": _r(b0["units"]), "estimated_quality_at_18": _r(b0["quality"], 3)}
        if b1 is not None:
            row.update(estimated_units_now=_r(b1["units"]), estimated_quality_now=_r(b1["quality"], 3),
                       units_change=_r(b1["units"] - b0["units"]), quality_change=_r(b1["quality"] - b0["quality"], 3))
        crops.append(row)
    money = {k: round(night["money_after"].get(k, 0.0) - v, 2) for k, v in night["money"].items()
             if round(night["money_after"].get(k, 0.0) - v, 2) != 0}
    view = sim.business.view(sim.hour, sim.rng.stream(f"business/{sim.hour}"))
    return {
        "clock": clock(sim),
        "night": {"from_hour": first, "to_hour": last},
        "alarms_and_events": alarms,
        "deliveries": [a for a in alarms if a["kind"] == "delivery"],
        "hourly_climate": climate,
        "batches": crops,
        "losses": [a for a in alarms if a["kind"] == "batch_lost"],
        "stock": view.get("stock", {}),
        "money_over_night_eur": money,
    }


def history(sim: Greenhouse, compartment_id: str, from_hour: int, to_hour: int | None) -> dict[str, Any]:
    last = sim.hour - 1 if to_hour is None else min(to_hour, sim.hour - 1)
    first = max(from_hour, last - HISTORY_MAX_HOURS + 1)
    rows = []
    for rec in sim.history[first:last + 1] if last >= 0 else []:
        rows.append({"hour": rec.hour, "readings": rec.readings.get("compartments", {}).get(compartment_id, {}),
                     "settings": rec.climate.get(compartment_id, {}), "metered": rec.metered})
    return {"compartment": compartment_id, "from_hour": first, "to_hour": last, "rows": rows,
            "note": f"at most {HISTORY_MAX_HOURS} hours per call"}


def _r(value: Any, digits: int = 1) -> Any:
    return round(value, digits) if isinstance(value, (int, float)) else value
