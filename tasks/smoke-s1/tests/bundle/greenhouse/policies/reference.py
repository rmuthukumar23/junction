"""Reference planner (spec 9): the strong scripted run the score is anchored on.

It plays through the tools only, like every policy here, and takes every fact about
the world from tool results: `get_rules` (crop rules, prices, lead times, staff, the
published ranges of hidden parameters), `get_status`, `get_forecast`. The class
attributes below are its own choices (how this grower behaves), tuned on development
seeds 1-6 only. It never sees a hidden parameter: what it needs it measures, e.g. the
lamps' light output from the lamp power the facility reports after the first hour.

What it does that the rule-based grower does not:

  * Light by the numbers. For a crop whose rules punish too much light (a stress
    counter on the day's light integral), it sets the lamp intensity each morning so
    that lamps plus the forecast sun land just under that limit, and spreads the light
    over as many hours as possible (the published photosynthesis curve saturates, so
    dim light for long is worth more than bright light for short). A crop with no such
    limit gets the lamps it can pay for. The dearest forecast hours are left dark.
  * Power from the CHP. Lamps are the big electricity user; the CHP makes that power
    from gas, and its heat and CO2 are used too. CO2 is dosed up to the level where the
    crop's published response stops rising.
  * Lead times. Seedlings (or seed) take days to arrive and a crop may only be planted
    while it can still finish, so seedlings for the space that will free in time are
    ordered in the first hour, and again each day for the space that frees within the
    lead time, so short cycles are resown all episode.
  * Harvest timing from the rules. A crop sold per unit is cut as soon as it is safely
    above its minimum sellable weight, which frees the space. A crop sold by weight and
    cut once is cut when it is ready: its weight grows until then. A crop sold by weight
    and cut repeatedly is left to grow for as long as it keeps its top grade, and each cut
    is queued so that the crew finishes it before the grade drops.
  * Labour ahead of time. Tasks run in queue order on the crew's worker-hours. It works
    out when the last harvests must start to finish inside the episode, and hires for
    that in advance (hiring has a notice period).
  * Nothing for an empty house: once a compartment holds no crop and none can be
    planted any more, its lamps, CO2 and heating are turned down.
"""
from __future__ import annotations

import math
from typing import Any

from envkit.policies import Client, Policy

from .common import import_prices, result

STANDING = ("growing", "ready")
_MOL_PER_UMOL_H = 3600.0 / 1e6      # umol m-2 s-1 held for one hour -> mol m-2 (unit conversion)


class Reference(Policy):
    name = "reference"

    # -- policy choices (tuned on development seeds 1-6; none is a fact about the world) --
    call_budget = 390             # the task allows 400 calls; keep a few in hand
    decision_hour = 6             # one planning round a day, before the crew's shift
    heat_day_frac = 0.5           # where in a crop's published day range the setpoint sits (0 = low, 1 = high)
    heat_night_frac = 1.0
    chp_load = 0.75
    light_limit_frac = 0.8        # share of a crop's light limit to aim for
    light_safety_mol = 1.0        # head-room under that for forecast error
    limited_dark_hours = 2        # dearest hours left dark, crop with a light limit
    free_dark_hours = 0           # dearest hours left dark, crop without one
    free_intensity_pct = 100.0    # lamp intensity for a crop without a light limit
    sell_margin = 0.22            # cut a per-unit crop at (1 + this) x its minimum sellable weight
    replant_weight_frac = 0.5     # order seedlings for batches at least this share of that weight at the start
    grade_margin_h = 30.0         # finish a repeated cut this long before the top grade is lost
    end_margin = 0.08             # spare crew capacity kept when timing the last harvests
    start_hires = 0               # workers hired in the first hour
    end_crew = 5                  # crew size for the last harvests
    end_hire_days = 7.0           # that crew is hired this many days before the end
    co2_reorder_kg = 1500.0       # reorder CO2 below this store level
    repair_faults = False         # the CHP and the buffer carry a boiler trip; the call-out costs more than it saves
    lamp_probe_pct = 100.0        # intensity used for the first hour, to measure the lamps

    # -- the loop --------------------------------------------------------------------------

    def run(self, client: Client) -> None:
        self.client = client
        self.calls = 0
        self.rules = result(self.call("get_rules"))
        status = result(self.call("get_status"))
        if not self.rules or not status:
            return
        self.read_rules(status)
        self.first_hour(status)
        guard = 0
        while not client.done and guard < 5000:
            guard += 1
            status = result(self.call("get_status"))
            if not status or client.done:
                return
            self.decide(status)
            if client.done:
                return
            clock = status["clock"]
            hours = (self.decision_hour - clock["hour_of_day"]) % 24 or 24
            if not self.call("advance", hours=max(1, min(hours, clock["hours_left"]))).get("ok"):
                return

    def call(self, tool: str, **args: Any) -> dict[str, Any]:
        self.calls += 1
        return self.client.call(tool, **args)

    # -- reading the rules -------------------------------------------------------------------

    def read_rules(self, status: dict[str, Any]) -> None:
        r = self.rules
        self.horizon = int(status["clock"]["hours_total"])
        self.crops: dict[str, dict[str, Any]] = r.get("crops", {})
        facility = r.get("facility", {})
        self.compartments: dict[str, dict[str, Any]] = facility.get("compartments", {})
        self.crop_in = {c: spec.get("crop") for c, spec in self.compartments.items()}
        self.min_heat = float(facility.get("climate_limits", {}).get("min_heat_c", 0.0))
        self.max_co2 = float(facility.get("climate_limits", {}).get("max_co2_ppm", 1000.0))
        self.items: dict[str, dict[str, Any]] = r.get("business", {}).get("items", {})
        staff = r.get("business", {}).get("staff", {})
        shift = str(staff.get("shift", "00:00-24:00"))
        self.shift_start, self.shift_end = (int(part.split(":")[0]) for part in shift.split("-"))
        self.max_crew = int(staff.get("max_crew", 0))
        self.hire_notice_h = 24 * float(staff.get("hire_notice_days", 0))
        # Hidden ranges: plan with the cautious end where a value is not measured.
        ranges = r.get("hidden_parameter_ranges", {}).get("facility", {})
        self.transmission = {c: float(max(ranges.get(f"compartments[{i}].cover_transmission", (1.0, 1.0))))
                             for i, c in enumerate(self.compartments)}
        self.area = {c: float(status["free_area_m2"].get(c, 0.0))
                     + sum(b["area_m2"] for b in status["batches"] if b["compartment"] == c)
                     for c in self.compartments}
        self.lamp_par: dict[str, float] = {}      # umol m-2 s-1 at 100 % intensity, measured
        self.ready_hour: dict[str, int] = {}      # batch id -> hour it became ready
        self.cuts_seen: dict[str, int] = {}
        self.repairs_asked: set[tuple[str, int]] = set()
        self.planned_day = -1
        self.shut: set[str] = set()
        self.end_hired = False

    def crop(self, compartment: str) -> dict[str, Any]:
        return self.crops.get(self.crop_in.get(compartment, ""), {})

    def co2_setpoint(self, compartment: str) -> float:
        """Dose up to the level where the crop's published CO2 response stops rising, within
        what the equipment accepts; without such a level, the top of its target range."""
        crop = self.crop(compartment)
        level = crop.get("growth", {}).get("co2_saturation_ppm")
        if not isinstance(level, (int, float)):
            level = self.within(crop.get("climate_targets", {}).get("co2_ppm"), 1.0, 800.0)
        return min(float(level), self.max_co2)

    @staticmethod
    def within(pair: Any, frac: float, fallback: float) -> float:
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            return float(pair[0]) + frac * (float(pair[1]) - float(pair[0]))
        return fallback

    def light_limit(self, crop: dict[str, Any]) -> float | None:
        """The day's light integral above which the crop's rules take quality away."""
        limits = [float(c["threshold"]) for c in crop.get("stress", {}).get("counters", [])
                  if c.get("signal") == "dli_excess" and c.get("curve") == "linear_above"]
        return min(limits) if limits else None

    def plants(self, batch: dict[str, Any]) -> float:
        return float(self.crops[batch["crop"]]["planting"]["density_per_m2"]) * batch["area_m2"]

    def harvest_hours(self, batch: dict[str, Any]) -> float:
        return self.plants(batch) / 1000.0 * float(self.crops[batch["crop"]]["planting"]["harvest_worker_hours_per_1000"])

    def plant_weight_g(self, batch: dict[str, Any]) -> float:
        """Estimated fresh weight per plant that a harvest would take now."""
        est = batch.get("estimate", {})
        if self.crops[batch["crop"]]["market"]["unit"] == "kg":      # `units` is the kg a cut would yield
            return 1000.0 * float(est.get("units", 0.0)) / max(1.0, self.plants(batch))
        return float(est.get("fresh_weight_g_per_unit", 0.0))

    # -- the first hour ------------------------------------------------------------------------

    def first_hour(self, status: dict[str, Any]) -> None:
        for c in self.compartments:
            t = self.crop(c).get("climate_targets", {})
            self.call("set_climate", compartment=c, screen="auto",
                      heat_day_c=self.within(t.get("day_temp_c"), self.heat_day_frac, 18.0),
                      heat_night_c=self.within(t.get("night_temp_c"), self.heat_night_frac, 15.0),
                      co2_ppm=self.co2_setpoint(c),
                      lamp_hours=list(range(24)), lamp_intensity_pct=self.lamp_probe_pct)
        if self.chp_load > 0:
            self.call("set_energy", chp_load=self.chp_load)
        self.order_seedlings(status)
        if self.start_hires > 0:
            self.call("hire", workers=self.start_hires)
        # One hour with the lamps on tells what they deliver per m2.
        r = result(self.call("advance", hours=1))
        readings = r.get("status", {}).get("readings", {}).get("compartments", {})
        for c, spec in self.compartments.items():
            lamp_kw = readings.get(c, {}).get("actuators", {}).get("lamp_kw")
            if isinstance(lamp_kw, (int, float)) and lamp_kw > 0 and self.area[c] > 0:
                self.lamp_par[c] = (lamp_kw * 1000.0 / self.area[c] * float(spec.get("lamp_umol_per_j", 0.0))
                                    / (self.lamp_probe_pct / 100.0))

    def order_seedlings(self, status: dict[str, Any]) -> None:
        """Seedlings for the space that will be free while planting is still allowed."""
        for c in self.compartments:
            crop_id, crop = self.crop_in[c], self.crop(c)
            item = f"seedlings:{crop_id}"
            if item not in self.items or crop.get("cycle", {}).get("harvest_mode") != "single":
                continue
            lead_h = self.items[item].get("lead_time_h", 0)
            lead_h = max(lead_h) if isinstance(lead_h, list) else float(lead_h)
            if lead_h >= self.plant_deadline(crop):
                continue
            floor_g = float(crop["market"]["min_sellable_fresh_weight_g"]) * self.replant_weight_frac
            area = sum(b["area_m2"] for b in status["batches"]
                       if b["compartment"] == c and self.plant_weight_g(b) >= floor_g)
            area += float(status["free_area_m2"].get(c, 0.0))
            plants = math.ceil(area * float(crop["planting"]["density_per_m2"]))
            if plants > 0:
                self.call("place_order", item=item,
                          quantity=max(plants, math.ceil(float(self.items[item].get("min_quantity", 0)))))

    def plant_deadline(self, crop: dict[str, Any]) -> float:
        """Last episode hour at which planting this crop is still accepted."""
        return self.horizon - 24.0 * float(crop.get("cycle", {}).get("min_days_before_end", 0))

    # -- one planning round ----------------------------------------------------------------------

    def decide(self, status: dict[str, Any]) -> None:
        clock = status["clock"]
        hour = int(clock["hour"])
        batches = status.get("batches", [])
        for alarm in status.get("alarms_last_24h", []):
            if alarm.get("kind") == "batch_ready":
                self.ready_hour[alarm["target"]] = int(alarm["hour"])
        for b in batches:                      # a cut starts a new growth round
            if b.get("cuts", 0) != self.cuts_seen.get(b["id"], 0):
                self.cuts_seen[b["id"]] = b.get("cuts", 0)
                if b["status"] != "ready":
                    self.ready_hour.pop(b["id"], None)

        if self.repair_faults:
            for outage in status["business"].get("outages", []):
                key = (outage["equipment"], int(outage["since_hour"]))
                if not outage.get("repair_requested") and key not in self.repairs_asked:
                    self.repairs_asked.add(key)
                    self.call("repair", equipment_id=outage["equipment"])

        self.staff(status, hour)
        self.harvests(status, hour, batches)
        self.planting(status, hour)
        self.reorder_seedlings(status, hour)
        self.co2(status)
        if clock["day"] != self.planned_day and self.calls < self.call_budget - 2 * clock["hours_left"] / 24 - 30:
            self.planned_day = clock["day"]
            self.light(status, hour, batches)
        self.shut_empty(status, hour, batches)

    # -- labour ------------------------------------------------------------------------------------

    def crew_at(self, staff: dict[str, Any], hour: int) -> int:
        return int(staff.get("crew", 0)) + sum(a["workers"] for a in staff.get("arriving", []) if a["start_hour"] <= hour)

    def capacity(self, staff: dict[str, Any], start: int, end: int) -> float:
        """Worker-hours the crew can give in hours start..end-1."""
        return float(sum(self.crew_at(staff, h) for h in range(max(0, start), end)
                         if self.shift_start <= h % 24 < self.shift_end))

    def finish_hour(self, staff: dict[str, Any], start: int, work: float) -> int:
        """The hour in which `work` worker-hours queued at `start` are done."""
        for h in range(start, self.horizon + 24 * 30):
            if self.shift_start <= h % 24 < self.shift_end:
                work -= self.crew_at(staff, h)
                if work <= 1e-9:
                    return h
        return self.horizon + 24 * 30

    @staticmethod
    def backlog(status: dict[str, Any]) -> float:
        return sum(t.get("worker_hours_needed", 0.0) - t.get("worker_hours_done", 0.0)
                   for t in status["business"].get("task_queue", []))

    def staff(self, status: dict[str, Any], hour: int) -> None:
        staff = status["business"].get("staff", {})
        committed = int(staff.get("crew", 0)) + sum(a["workers"] for a in staff.get("arriving", []))
        hours_left = self.horizon - hour
        if (not self.end_hired and hours_left <= 24 * self.end_hire_days
                and hours_left > self.hire_notice_h + 24):
            self.end_hired = True
            extra = min(self.end_crew, self.max_crew) - committed
            if extra > 0:
                self.call("hire", workers=extra)

    # -- harvests ----------------------------------------------------------------------------------

    def harvests(self, status: dict[str, Any], hour: int, batches: list[dict[str, Any]]) -> None:
        staff = status["business"].get("staff", {})
        backlog = self.backlog(status)
        step = 24                                   # the next planning round is at most a day away
        standing = [b for b in batches if b["status"] in STANDING and not b.get("harvest_queued")]

        # Cut once. Sold per unit: once safely above the minimum sellable weight. Sold by
        # weight: when ready, since the weight grows until then.
        for b in standing:
            crop = self.crops[b["crop"]]
            if crop["cycle"]["harvest_mode"] != "single":
                continue
            if crop["market"]["unit"] == "kg":
                due = b["status"] == "ready"
            else:
                due = self.plant_weight_g(b) >= float(crop["market"]["min_sellable_fresh_weight_g"]) * (1 + self.sell_margin)
            if due:
                if self.call("harvest", batch_id=b["id"]).get("ok"):
                    backlog += self.harvest_hours(b)
                    b["harvest_queued"] = True

        # Sold by weight, cut repeatedly: wait while the top grade lasts, then cut in time.
        repeated = [b for b in standing if self.crops[b["crop"]]["cycle"]["harvest_mode"] == "repeated"
                    and not b.get("harvest_queued")]
        for b in sorted(repeated, key=lambda b: self.ready_hour.get(b["id"], 10 ** 9)):
            crop = self.crops[b["crop"]]
            if b["status"] != "ready" or b["id"] not in self.ready_hour:
                continue
            grades = crop["market"]["grades"]
            loss = float(crop["stress"].get("ready_loss_per_day", 0.0))
            if loss <= 0:
                continue
            top_until = self.ready_hour[b["id"]] + 24.0 * (1.0 - float(grades[0]["min_quality"])) / loss
            done_if_next_round = self.finish_hour(staff, hour + step, backlog + self.harvest_hours(b))
            if done_if_next_round > top_until - self.grade_margin_h:
                if self.call("harvest", batch_id=b["id"]).get("ok"):
                    backlog += self.harvest_hours(b)
                    b["harvest_queued"] = True

        # The last harvests: start them when waiting another round would leave too little crew time.
        last = [b for b in standing if not b.get("harvest_queued")
                and self.plant_weight_g(b) >= self.last_cut_floor(b)]
        need = sum(self.harvest_hours(b) for b in last)
        if last and self.capacity(staff, hour + step, self.horizon) < (backlog + need) * (1 + self.end_margin):
            # Per-unit crops first (their price does not grow), the heaviest by-weight crop last.
            order = sorted(last, key=lambda b: (self.crops[b["crop"]]["market"]["unit"] == "kg",
                                                self.plant_weight_g(b) * self.plants(b)))
            for b in order:
                self.call("harvest", batch_id=b["id"])

    def last_cut_floor(self, batch: dict[str, Any]) -> float:
        crop = self.crops[batch["crop"]]
        floor = float(crop["market"]["min_sellable_fresh_weight_g"])
        return floor * (1 + self.sell_margin) if crop["cycle"]["harvest_mode"] == "single" else floor * 1.5

    # -- planting, stock ---------------------------------------------------------------------------

    def planting(self, status: dict[str, Any], hour: int) -> None:
        stock = status["business"].get("stock", {})
        for c, free in status.get("free_area_m2", {}).items():
            crop_id, crop = self.crop_in.get(c), self.crop(c)
            have = float(stock.get(f"seedlings:{crop_id}", 0.0))
            if free <= 0.5 or have <= 0 or hour > self.plant_deadline(crop):
                continue
            area = min(float(free), math.floor(have / float(crop["planting"]["density_per_m2"]) * 10) / 10)
            if area > 0.5:
                self.call("plant", compartment=c, area_m2=area)

    def reorder_seedlings(self, status: dict[str, Any], hour: int) -> None:
        """Each day: order seedlings for the space that is free or frees within the lead time,
        less what is in stock, while a planting on arrival can still finish. Compartments that
        grow the same crop share one item, so the need is summed per item."""
        business = status["business"]
        stock = business.get("stock", {})
        on_order = {o.get("item") for o in business.get("open_orders", [])}
        need: dict[str, float] = {}
        for c in self.compartments:
            crop_id, crop = self.crop_in[c], self.crop(c)
            item = f"seedlings:{crop_id}"
            if item not in self.items or item in on_order or crop.get("cycle", {}).get("harvest_mode") != "single":
                continue
            lead_h = self.items[item].get("lead_time_h", 0)
            lead_h = max(lead_h) if isinstance(lead_h, list) else float(lead_h)
            if hour + lead_h > self.plant_deadline(crop):
                continue
            area = float(status["free_area_m2"].get(c, 0.0)) + sum(
                b["area_m2"] for b in status["batches"] if b["compartment"] == c and b["status"] in STANDING
                and (b.get("estimate", {}).get("days_to_ready") or 0.0) <= lead_h / 24.0 + 1.0)
            need[item] = need.get(item, 0.0) + area * float(crop["planting"]["density_per_m2"])
        for item, plants in need.items():
            short = math.ceil(plants - float(stock.get(item, 0.0)))
            if short > 0:
                self.call("place_order", item=item,
                          quantity=max(short, math.ceil(float(self.items[item].get("min_quantity", 0)))))

    def co2(self, status: dict[str, Any]) -> None:
        store = status.get("readings", {}).get("energy_centre", {}).get("co2_store_kg")
        item = self.items.get("co2_kg")
        if not isinstance(store, (int, float)) or item is None or store >= self.co2_reorder_kg:
            return
        if any(o.get("item") == "co2_kg" for o in status["business"].get("open_orders", [])):
            return
        self.call("place_order", item="co2_kg", quantity=math.ceil(float(item.get("min_quantity", 1.0))))

    # -- light ---------------------------------------------------------------------------------------

    def light(self, status: dict[str, Any], hour: int, batches: list[dict[str, Any]]) -> None:
        forecast = result(self.call("get_forecast", hours=24)).get("forecast", {})
        prices = import_prices(forecast, hour)
        dear = [h % 24 for h, _ in sorted(prices, key=lambda row: (-row[1], row[0]))]
        weather = forecast.get("weather", [])
        for c, spec in self.compartments.items():
            if c in self.shut or not any(b["compartment"] == c and b["status"] in STANDING for b in batches):
                continue
            limit = self.light_limit(self.crop(c))
            par = self.lamp_par.get(c, 0.0)
            if limit is None or par <= 0:
                dark = set(dear[:self.free_dark_hours])
                self.call("set_climate", compartment=c, lamp_hours=[h for h in range(24) if h not in dark],
                          lamp_intensity_pct=self.free_intensity_pct)
                continue
            dark = set(dear[:self.limited_dark_hours])
            hours_on = [h for h in range(24) if h not in dark]
            sun = sum(float(w.get("solar_w_m2", 0.0)) for w in weather) * self.transmission[c] \
                * float(spec.get("solar_umol_per_j", 0.0)) * _MOL_PER_UMOL_H
            room = limit * self.light_limit_frac - self.light_safety_mol - sun
            full = len(hours_on) * par * _MOL_PER_UMOL_H           # lamp light in a day at 100 %
            pct = 0.0 if full <= 0 else max(0.0, min(100.0, 100.0 * room / full))
            self.call("set_climate", compartment=c, lamp_hours=hours_on if pct > 0 else [],
                      lamp_intensity_pct=round(pct, 1))

    # -- an empty house costs nothing -------------------------------------------------------------------

    def shut_empty(self, status: dict[str, Any], hour: int, batches: list[dict[str, Any]]) -> None:
        for c in self.compartments:
            if c in self.shut or any(b["compartment"] == c and b["status"] in STANDING for b in batches):
                continue
            if any(t.get("kind") == "plant" and t.get("target") == c for t in status["business"].get("task_queue", [])):
                continue
            item = f"seedlings:{self.crop_in[c]}"
            coming = (float(status["business"].get("stock", {}).get(item, 0.0)) > 0
                      or any(o.get("item") == item for o in status["business"].get("open_orders", [])))
            if coming and hour <= self.plant_deadline(self.crop(c)):
                continue
            self.shut.add(c)
            self.call("set_climate", compartment=c, lamp_hours=[], lamp_intensity_pct=0.0, co2_ppm=0.0,
                      heat_day_c=self.min_heat, heat_night_c=self.min_heat)
