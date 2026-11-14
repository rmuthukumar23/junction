"""What the agent may see. Every function is a pure read of the simulator.

Sensor readings are the ones recorded at the end of the last hour (so reading
twice gives the same numbers); estimates and business views draw from streams
named after what they observe and the hour (contracts.py).
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .world.sim import Greenhouse

HISTORY_MAX_HOURS = 168


def clock(sim: Greenhouse) -> dict[str, Any]:
    h = min(sim.hour, sim.horizon_h)
    return {"hour": h, "day": h // 24, "hour_of_day": h % 24, "hours_total": sim.horizon_h,
            "hours_left": sim.hours_left(), "done": sim.done}


def status(sim: Greenhouse) -> dict[str, Any]:
    recent = [asdict(a) for a in sim.alarms if a.hour >= sim.hour - 24]
    return {
        "clock": clock(sim),
        "readings": sim.readings,
        "settings": {"climate": {c: asdict(s) for c, s in sim.climate.items()}, "energy": asdict(sim.energy),
                     "fallback_active": sim.unattended},
        "equipment_faults": sorted(sim.effects),
        "free_area_m2": {c: round(sim.free_area_m2(c), 1) for c in sim.facility.compartment_ids},
        "business": sim.business.view(sim.hour, sim.rng.stream(f"business/{sim.hour}")),
        "alarms_last_24h": recent,
        "batches": sim.batch_views(),
    }


def rules(sim: Greenhouse) -> dict[str, Any]:
    return {
        "objective": ("Maximise net profit in EUR at the end of the last hour: harvest revenue plus electricity "
                      "sold, minus gas, electricity bought, CO2, wages, hiring, repairs, seedlings and other "
                      "orders. Crop still standing at the end is worth nothing."),
        "clock": {"hours_total": sim.horizon_h, "substeps_per_hour": sim.substeps,
                  "advance": "advance(hours) runs 1-24 hours with the standing settings and stops at the end "
                             "of any hour in which a new alarm appears. It is the only call that moves time."},
        "settings": "Climate and energy settings stand until changed. Before any change, and for every hour "
                    "after you stop, the facility's fallback settings are in effect (see facility.fallback).",
        "facility": sim.facility.rules(),
        "crops": {cid: m.describe() for cid, m in sim.growth.items()},
        "business": sim.business.rules(),
        "hidden_parameter_ranges": sim.m.published_ranges,
    }


def batches(sim: Greenhouse) -> dict[str, Any]:
    return {"clock": clock(sim), "batches": sim.batch_views()}


def forecast(sim: Greenhouse, hours: int) -> dict[str, Any]:
    return {"clock": clock(sim), "forecast": sim.facility.forecast(sim.hour, hours)}


def history(sim: Greenhouse, compartment_id: str, from_hour: int, to_hour: int | None) -> dict[str, Any]:
    last = sim.hour - 1 if to_hour is None else min(to_hour, sim.hour - 1)
    first = max(from_hour, last - HISTORY_MAX_HOURS + 1)
    rows = []
    for rec in sim.history[first:last + 1] if last >= 0 else []:
        rows.append({"hour": rec.hour, "readings": rec.readings.get("compartments", {}).get(compartment_id, {}),
                     "settings": rec.climate.get(compartment_id, {}), "metered": rec.metered})
    return {"compartment": compartment_id, "from_hour": first, "to_hour": last, "rows": rows,
            "note": f"at most {HISTORY_MAX_HOURS} hours per call"}
