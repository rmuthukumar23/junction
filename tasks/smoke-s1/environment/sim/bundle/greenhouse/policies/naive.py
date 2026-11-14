"""Naive grower (spec 9): crop-file target setpoints, CHP on when it is cold, CO2
ordered only once the store is empty, harvest when ready, replant when seedlings
happen to be in stock. It ignores lead times, which is the point: it shows that
ordering ahead and timing energy matter.
"""
from __future__ import annotations

from typing import Any

from .common import ToolPolicy, midpoint


class Naive(ToolPolicy):
    # Policy choices, used only when a crop file publishes no climate target.
    default_day_c = 18.0
    default_night_c = 14.0
    default_co2_ppm = 800.0
    cold_outside_c = 0.0          # "cold": run the CHP below this outside temperature
    fallback_min_order = 1.0      # if get_rules shows no minimum, order the smallest amount

    def setup(self, status: dict[str, Any]) -> None:
        for compartment, crop in self.crop_of(status).items():
            t = self.targets(crop)
            self.call("set_climate", compartment=compartment,
                      heat_day_c=midpoint(t.get("day_temp_c"), self.default_day_c),
                      heat_night_c=midpoint(t.get("night_temp_c"), self.default_night_c),
                      co2_ppm=midpoint(t.get("co2_ppm"), self.default_co2_ppm))

    def decide(self, status: dict[str, Any]) -> None:
        outside = status.get("readings", {}).get("outside_temp_c")
        if isinstance(outside, (int, float)):
            self.call("set_energy", chp_load=1.0 if outside < self.cold_outside_c else 0.0)
        store = self.co2_store(status)
        if store is not None and store <= 0 and not self.open_orders(status, "co2_kg"):
            self.call("place_order", item="co2_kg", quantity=self.min_order("co2_kg", self.fallback_min_order))
        self.harvest_ready(status)
        crops = self.crop_of(status)
        for compartment, free in status.get("free_area_m2", {}).items():
            crop = crops.get(compartment)
            if crop and free > 0 and self.seedlings(status, crop) > 0:
                self.call("plant", compartment=compartment, area_m2=free)
