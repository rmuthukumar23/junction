"""Rule-based grower (spec 9): practitioner rules without a model of the future.

  * Climate: crop-file targets; energy screen on automatic (closed at night).
  * Lamps: on for the crop file's photoperiod, in the cheapest hours of the electricity
    forecast, if one is offered. The intensity stays at the facility's baseline.
  * CO2: reorder at a level that covers the lead time at the recent use rate, so the
    store never runs dry; no dosing target while it is empty.
  * Seedlings: ordered a lead time before a batch is due, so freed space is replanted.
  * Harvest when ready; book the contractor for any damage and order the parts it
    needs, and run the CHP while the boiler is out; hire when the task queue is longer
    than a day's worker-hours.
  * Nights run on the day settings (committed every morning).
  * Plant only what can still finish: seedlings are ordered only while the crop's
    published cycle fits in the time left.
It does not plan energy against prices beyond the lamp hours; the reference adds that.
"""
from __future__ import annotations

import math
from typing import Any

from .common import ToolPolicy, import_prices, midpoint, repair_damage, result


class RuleBased(ToolPolicy):
    # Policy choices, used only when the rules or forecast do not say otherwise.
    default_day_c = 18.0
    default_night_c = 14.0
    default_co2_ppm = 800.0
    lamp_hours_per_day = 12       # cheapest hours the lamps run when a crop publishes no photoperiod
    safety_days = 2.0             # extra days of CO2 on top of the lead time
    cover_days = 7.0              # an order covers this many days of use
    fallback_lead_h = 72.0
    fallback_min_order = 1.0
    max_hires = 2                 # a cap on how far it grows the crew

    def setup(self, status: dict[str, Any]) -> None:
        self.lamps_set: dict[str, list[int]] = {}
        self.last_store: float | None = self.co2_store(status)
        self.use_per_day = 0.0
        self.hired = 0
        for compartment, crop in self.crop_of(status).items():
            t = self.targets(crop)
            self.call("set_climate", compartment=compartment, screen="auto",
                      heat_day_c=midpoint(t.get("day_temp_c"), self.default_day_c),
                      heat_night_c=midpoint(t.get("night_temp_c"), self.default_night_c),
                      co2_ppm=midpoint(t.get("co2_ppm"), self.default_co2_ppm))
        self.set_lamps(status)

    def decide(self, status: dict[str, Any]) -> None:
        faults = status.get("equipment_faults", [])
        repair_damage(self, status)
        if "boiler" in faults:                       # the CHP is the other heat source
            self.call("set_energy", chp_load=1.0)
            self.chp_for_boiler = True
        elif getattr(self, "chp_for_boiler", False):
            self.call("set_energy", chp_load=0.0)
            self.chp_for_boiler = False
        self.harvest_ready(status)
        self.manage_co2(status)
        self.manage_seedlings(status)
        self.manage_staff(status)
        self.set_lamps(status)

    # -- rules -------------------------------------------------------------------------

    def manage_co2(self, status: dict[str, Any]) -> None:
        store = self.co2_store(status)
        if store is None:
            return
        if self.last_store is not None and store < self.last_store:
            self.use_per_day = max(self.use_per_day * 0.5, self.last_store - store)   # recent use, smoothed
        self.last_store = store
        on_order = sum(o.get("quantity", 0.0) for o in self.open_orders(status, "co2_kg"))
        lead_days = self.lead_time_h("co2_kg", self.fallback_lead_h) / 24.0
        if self.use_per_day > 0 and store + on_order < self.use_per_day * (lead_days + self.safety_days):
            qty = max(self.min_order("co2_kg", self.fallback_min_order), self.use_per_day * self.cover_days)
            self.call("place_order", item="co2_kg", quantity=math.ceil(qty))

    def manage_seedlings(self, status: dict[str, Any]) -> None:
        crops = self.crop_of(status)
        for compartment, free in status.get("free_area_m2", {}).items():
            crop = crops.get(compartment)
            if not crop:
                continue
            if free > 0 and self.seedlings(status, crop) > 0:
                self.call("plant", compartment=compartment, area_m2=free)
            item = f"seedlings:{crop}"
            if not self.item_rule(item) or self.open_orders(status, item):
                continue
            lead_days = self.lead_time_h(item, self.fallback_lead_h) / 24.0
            cycle = self.rules.get("crops", {}).get(crop, {}).get("cycle", {}).get("nominal_days")
            days_left = status.get("clock", {}).get("hours_left", 0) / 24.0
            if not isinstance(cycle, (int, float)) or lead_days + cycle > days_left:
                continue                              # it could not finish before the end
            due = [b for b in status.get("batches", []) if b["compartment"] == compartment
                   and b.get("status") in ("growing", "ready") and b.get("cuts", 0) == 0
                   and (b.get("estimate", {}).get("days_to_ready") or 0.0) <= lead_days + 1.0]
            # Plants, not sale units: a crop sold by the kg reports kg in `units`.
            density = self.rules.get("crops", {}).get(crop, {}).get("planting", {}).get("density_per_m2")
            needed = (sum(b["area_m2"] for b in due) * float(density) if isinstance(density, (int, float))
                      else sum(b.get("estimate", {}).get("units", 0.0) for b in due))
            if due and self.seedlings(status, crop) < needed:
                self.call("place_order", item=item,
                          quantity=math.ceil(max(needed, self.min_order(item, self.fallback_min_order))))

    def manage_staff(self, status: dict[str, Any]) -> None:
        queue = self.business(status).get("task_queue", [])
        backlog = sum(t.get("worker_hours_needed", 0.0) - t.get("worker_hours_done", 0.0) for t in queue)
        per_day = self.business(status).get("staff", {}).get("worker_hours_per_day", 0.0)
        if per_day and backlog > per_day and self.hired < self.max_hires:
            if self.call("hire", workers=1).get("ok"):
                self.hired += 1

    def set_lamps(self, status: dict[str, Any]) -> None:
        now = status.get("clock", {}).get("hour", 0)
        prices = import_prices(result(self.call("get_forecast", hours=24)).get("forecast", {}), now)
        if not prices:
            return
        by_price = sorted(prices, key=lambda row: (row[1], row[0]))
        for compartment, crop in self.crop_of(status).items():
            # The crop file's photoperiod, in the cheapest hours; the intensity is left as it stands.
            wanted = self.targets(crop).get("photoperiod_h")
            count = round(wanted) if isinstance(wanted, (int, float)) and wanted > 0 else self.lamp_hours_per_day
            hours = sorted({hour % 24 for hour, _ in by_price[:count]})
            if hours != self.lamps_set.get(compartment):
                self.lamps_set[compartment] = hours
                self.call("set_climate", compartment=compartment, lamp_hours=hours)

