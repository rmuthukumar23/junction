"""Rule-based grower (spec 9): practitioner rules without a model of the future.

  * Climate: crop-file targets; energy screen on automatic (closed at night).
  * Lamps: on in the cheapest hours of the electricity forecast, if one is offered.
  * CO2: reorder at a level that covers the lead time at the recent use rate, so the
    store never runs dry; no dosing target while it is empty.
  * Seedlings: ordered a lead time before a batch is due, so freed space is replanted.
  * Harvest when ready; repair any fault once, and run the CHP while the boiler is
    out; hire when the task queue is longer than a day's worker-hours.
  * Plant only what can still finish: seedlings are ordered only while the crop's
    published cycle fits in the time left.
It does not plan energy against prices beyond the lamp hours; the reference adds that.
"""
from __future__ import annotations

import math
from typing import Any

from .common import ToolPolicy, midpoint, result


class RuleBased(ToolPolicy):
    # Policy choices, used only when the rules or forecast do not say otherwise.
    default_day_c = 18.0
    default_night_c = 14.0
    default_co2_ppm = 800.0
    lamp_hours_per_day = 6        # how many cheapest hours the lamps run
    lamp_intensity_pct = 100.0
    safety_days = 2.0             # extra days of CO2 on top of the lead time
    cover_days = 7.0              # an order covers this many days of use
    fallback_lead_h = 72.0
    fallback_min_order = 1.0
    max_hires = 2                 # a cap on how far it grows the crew

    def setup(self, status: dict[str, Any]) -> None:
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
        requested = {o.get("equipment") for o in self.business(status).get("outages", []) if o.get("repair_requested")}
        for fault in faults:
            if fault not in requested and not self._repair_queued(status, fault):
                self.call("repair", equipment_id=fault)
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
            needed = sum(b.get("estimate", {}).get("units", 0.0) for b in due)
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
        forecast = result(self.call("get_forecast", hours=24)).get("forecast", {})
        series = next((v for k, v in forecast.items() if "price" in k and isinstance(v, list)), None)
        if not series:
            return
        # The real facility gives one dict per hour ({"import_eur_kwh": ..., "export_eur_kwh": ...});
        # a plain list of numbers is accepted too.
        prices = [p.get("import_eur_kwh") if isinstance(p, dict) else p for p in series]
        if not all(isinstance(p, (int, float)) for p in prices):
            return
        hour0 = status.get("clock", {}).get("hour_of_day", 0)
        cheapest = sorted(range(len(prices)), key=lambda i: (prices[i], i))[:self.lamp_hours_per_day]
        hours = sorted((hour0 + i) % 24 for i in cheapest)
        for compartment in self.crop_of(status):
            self.call("set_climate", compartment=compartment, lamp_hours=hours,
                      lamp_intensity_pct=self.lamp_intensity_pct)

    @staticmethod
    def _repair_queued(status: dict[str, Any], equipment_id: str) -> bool:
        return any(t.get("kind") == "repair" and t.get("target") == equipment_id
                   for t in status.get("business", {}).get("task_queue", []))
