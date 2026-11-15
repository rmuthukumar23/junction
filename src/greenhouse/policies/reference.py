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
  * The shift rules (spec 14.1): one planning round each morning at 06:00, the night
    schedule set to the day settings, then submit the day. Damage is always repaired: the
    contractor is booked and the parts ordered the morning it is seen.
  * Sow to the market. Buyers take a published volume a week at full price and the price
    falls beyond it, so it keeps only the bench area sown whose output meets that demand
    (demand x cycle length / (ready weight x sowing density)) and leaves the rest dark.
  * Seed in hand. Seed is ordered for the beds that free within the lead time plus a few
    days, with several orders in flight, so a harvested bed is resown the next morning.
  * Nothing for an empty house: once a compartment holds no crop and none can be
    planted any more, its lamps, CO2 and heating are turned down.
"""
from __future__ import annotations

import math
from typing import Any

from .common import ToolPolicy, import_prices, repair_damage, result

STANDING = ("growing", "ready")
_MOL_PER_UMOL_H = 3600.0 / 1e6      # umol m-2 s-1 held for one hour -> mol m-2 (unit conversion)


class Reference(ToolPolicy):
    name = "reference"

    # -- policy choices (tuned on development seeds 1-6; none is a fact about the world) --
    call_budget = 390             # the task allows 400 calls; keep a few in hand
    decision_hour = 6             # one planning round a day, at the start of the duty shift (06:00)
    heat_day_frac = 0.5           # where in a crop's published day range the setpoint sits (0 = low, 1 = high)
    heat_night_frac = 1.0
    chp_load = 0.75
    light_limit_frac = 0.8        # share of a crop's light limit to aim for
    light_safety_mol = 1.0        # head-room under that for forecast error
    limited_dark_hours = 2        # dearest hours left dark, crop with a light limit
    free_dark_hours = 0           # dearest hours left dark, crop without one
    free_intensity_pct = 100.0    # lamp intensity for a crop without a light limit
    sell_margin = 0.22            # cut a per-unit crop at (1 + this) x its minimum sellable weight
    replant_weight_frac = 0.0     # order seedlings for batches at least this share of that weight at the start
    grade_margin_h = 30.0         # finish a repeated cut this long before the top grade is lost
    end_margin = 0.08             # spare crew capacity kept when timing the last harvests
    start_hires = 0               # workers hired in the first hour
    end_crew = 5                  # crew size for the last harvests
    end_hire_days = 7.0           # that crew is hired this many days before the end
    co2_reorder_kg = 1500.0       # reorder CO2 below this store level
    early_crew = 3                # crew to hire up to on the first morning (3 = the starting crew, no hire)
    early_hired = False
    sell_point = 0.85             # where in the sow-to-sale cycle the sale is expected (1 = at the end)
    hold_frac = 1.0               # hold ready batches while week sales + this batch exceed this share of demand (0 = off)
    hold_margin_days = 1.5        # ... and only while the top grade lasts this many days more
    stagger = 99.0                # at most this many cycles' worth of the demand area sown a day (99 = off)
    demand_target = 1.0           # sow for this share of the published demand
    yield_factor = 0.55           # expected harvest per m2 as a share of ready weight x sowing density
    cycle_factor = 0.75           # expected sow-to-sale time as a share of the crop's nominal days
    cut_weight_frac = 1.0
    cut_age_frac = 1.0            # ... or once its age reaches this share of the crop's nominal days         # a by-weight single crop is cut at this share of its ready weight
    seed_cover_days = 3.0         # seed ordered for beds that free within the lead time plus this many days
    repair_faults = True          # damage persists until repaired (round 3), so it is always fixed
    lamp_probe_pct = 100.0        # intensity used for the first hour, to measure the lamps

    # -- the daily turn ----------------------------------------------------------------------
    # ToolPolicy runs the loop: the first morning `setup`, then every morning `decide`;
    # the day's actions are merged and sent within the day's limit, the night entry copies
    # the day settings when they changed, and the day ends.

    def setup(self, status: dict[str, Any]) -> None:
        self.read_rules(status)
        self.first_hour(status)

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

    def measure_lamps(self, status: dict[str, Any]) -> None:
        """The last hour's lamp power, at the intensity that was set, tells what the lamps
        deliver per m2 (the night copies the day's lamps, so 05:00 had them on)."""
        readings = status.get("readings", {}).get("compartments", {})
        night = status.get("settings", {}).get("night_schedule", [])
        for c, spec in self.compartments.items():
            if c in self.lamp_par:
                continue
            lamp_kw = readings.get(c, {}).get("actuators", {}).get("lamp_kw")
            pct = next((float(e["climate"][c]["lamp_intensity_pct"]) for e in reversed(night)
                        if c in e.get("climate", {})), 0.0)
            if isinstance(lamp_kw, (int, float)) and lamp_kw > 0 and pct > 0 and self.area[c] > 0:
                self.lamp_par[c] = (lamp_kw * 1000.0 / self.area[c] * float(spec.get("lamp_umol_per_j", 0.0))
                                    / (pct / 100.0))

    def order_seedlings(self, status: dict[str, Any]) -> None:
        """Seedlings for the space that will be free while planting is still allowed."""
        for c in self.compartments:
            crop_id, crop = self.crop_in[c], self.crop(c)
            item = f"seedlings:{crop_id}"
            if item not in self.items or crop.get("cycle", {}).get("harvest_mode") != "single":
                continue
            lead_h = self.items[item].get("lead_time_h", 0)
            lead_h = max(lead_h) if isinstance(lead_h, list) else float(lead_h)
            if lead_h >= self.plant_deadline(crop) or self.daily_area(crop_id, 0) is not None:
                continue                         # demand crops are ordered by the daily plan
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
        self.measure_lamps(status)
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
            repair_damage(self, status)

        self.staff(status, hour)
        self.harvests(status, hour, batches)
        self.planting(status, hour)
        self.reorder_seedlings(status, hour)
        self.co2(status)
        if clock["day"] != self.planned_day and self.calls < self.call_budget - 3 * clock["hours_left"] / 24 - 30:
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
        if not self.early_hired and self.early_crew > committed and hours_left > 24 * self.end_hire_days:
            # Ready crops wait for the crew: a bigger crew from the start frees benches sooner.
            self.early_hired = True
            self.call("hire", workers=min(self.early_crew, self.max_crew) - committed)
            return
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
                # Sold by weight: growth slows as the canopy closes, so cutting a little before
                # "ready" and resowing at once earns more per day of bench space.
                ready_g = float(crop["cycle"].get("ready_fresh_weight_g") or 0.0)
                nominal = float(crop["cycle"].get("nominal_days") or 0.0)
                due = b["status"] == "ready" or (nominal > 0 and b.get("age_days", 0.0) >= self.cut_age_frac * nominal) or (self.cut_weight_frac < 1 and ready_g > 0 and self.plant_weight_g(b) >= ready_g * self.cut_weight_frac
                                                 and self.plant_weight_g(b) >= float(crop["market"]["min_sellable_fresh_weight_g"]))
            else:
                due = self.plant_weight_g(b) >= float(crop["market"]["min_sellable_fresh_weight_g"]) * (1 + self.sell_margin)
            if due and crop["market"]["unit"] == "kg" and self.hold_for_market(status, b, crop, hour):
                continue
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

    def hold_for_market(self, status: dict[str, Any], b: dict[str, Any], crop: dict[str, Any], hour: int) -> bool:
        """Hold a ready batch while this week's sales already meet the published demand and
        its top grade lasts: selling into a full market only lowers the price."""
        demand = (self.rules.get("business", {}).get("demand", {}).get("demand_per_week", {}) or {}).get(b["crop"])
        if not demand or self.hold_frac <= 0:
            return False
        demand = sum(demand) / 2 if isinstance(demand, list) else float(demand)
        sold = float(status["business"].get("sold_last_7_days", {}).get(b["crop"], 0.0))
        queued = sum(self.batch_kg(x) for x in status.get("batches", []) if x.get("harvest_queued") and x["crop"] == b["crop"])
        if sold + queued + self.batch_kg(b) <= demand * self.hold_frac:
            return False
        loss = float(crop["stress"].get("ready_loss_per_day", 0.0))
        top = float(crop["market"]["grades"][0]["min_quality"])
        quality = float(b.get("estimate", {}).get("quality") or 1.0)
        days_left = (quality - top) / loss if loss > 0 else 0.0
        return days_left > self.hold_margin_days          # still top grade by tomorrow's round

    def batch_kg(self, b: dict[str, Any]) -> float:
        crop = self.crops[b["crop"]]
        return float(b["area_m2"]) * float(crop["cycle"]["ready_fresh_weight_g"]) * float(crop["planting"]["density_per_m2"]) / 1000.0

    def last_cut_floor(self, batch: dict[str, Any]) -> float:
        crop = self.crops[batch["crop"]]
        floor = float(crop["market"]["min_sellable_fresh_weight_g"])
        return floor * (1 + self.sell_margin) if crop["cycle"]["harvest_mode"] == "single" else floor * 1.5

    # -- planting, stock ---------------------------------------------------------------------------

    @property
    def sown_today(self) -> dict:
        if not hasattr(self, "_sown"):
            self._sown = {}
        return self._sown

    def demand_area(self, crop_id: str, hour: float | None = None) -> float | None:
        """Bench area (m2) whose output meets the crop's published weekly demand: demand per
        week x cycle length in weeks / yield per m2 (ready weight x sowing density). None if
        the crop has no demand limit."""
        demand = (self.rules.get("business", {}).get("demand", {}).get("demand_per_week", {}) or {}).get(crop_id)
        crop = self.crops[crop_id]
        if not demand or crop["market"]["unit"] != "kg":
            return None
        demand = sum(demand) / 2 if isinstance(demand, list) else float(demand)
        kg_m2 = float(crop["cycle"]["ready_fresh_weight_g"]) * float(crop["planting"]["density_per_m2"]) / 1000.0
        cycle_days = float(crop["cycle"]["nominal_days"]) * self.cycle_factor
        factors = (self.rules.get("business", {}).get("demand", {}).get("week_factors", {}) or {}).get(crop_id)
        if factors and hour is not None:
            # Sow for the demand in the week this sowing will be sold, not this week's.
            week = int((hour + 24.0 * cycle_days * self.sell_point) // 168)
            demand *= float(factors[min(week, len(factors) - 1)])
        return self.demand_target * demand * cycle_days / 7.0 / kg_m2

    def daily_area(self, crop_id: str, hour: float) -> float | None:
        """Bench area (m2) to sow on the day starting at `hour`, for a crop sold against a
        published weekly demand: the harvest of this sowing comes about one cycle later, so
        sow 1/7 of the demand of that future week, divided by the yield per m2 (ready weight
        x sowing density). None if the crop has no demand limit."""
        crop = self.crops[crop_id]
        demand = (self.rules.get("business", {}).get("demand", {}).get("demand_per_week", {}) or {}).get(crop_id)
        if not demand or crop["market"]["unit"] != "kg":
            return None
        demand = sum(demand) / 2 if isinstance(demand, list) else float(demand)
        cycle_days = float(crop["cycle"]["nominal_days"]) * self.cycle_factor
        factors = (self.rules.get("business", {}).get("demand", {}).get("week_factors", {}) or {}).get(crop_id)
        if factors:
            week = int((hour + 24.0 * cycle_days * self.sell_point) // 168)
            demand *= float(factors[min(week, len(factors) - 1)])
        kg_m2 = float(crop["cycle"]["ready_fresh_weight_g"]) * float(crop["planting"]["density_per_m2"]) / 1000.0
        return self.demand_target * demand / 7.0 / (kg_m2 * self.yield_factor)

    def planting(self, status: dict[str, Any], hour: int) -> None:
        """A crop sold against a weekly demand gets a daily sowing that tracks the demand one
        cycle ahead (an even stream of harvests); any other crop fills its free bench."""
        stock = status["business"].get("stock", {})
        planned: dict[str, float] = {}
        for c, free in status.get("free_area_m2", {}).items():
            crop_id, crop = self.crop_in.get(c), self.crop(c)
            have = float(stock.get(f"seedlings:{crop_id}", 0.0))
            if free <= 0.5 or have <= 0 or hour > self.plant_deadline(crop):
                continue
            room = float(free)
            want = self.daily_area(crop_id, hour)
            if want is not None:
                room = min(room, want - planned.get(crop_id, 0.0))
            seeds_for = math.floor((have - planned.get(crop_id, 0.0) * float(crop["planting"]["density_per_m2"]))
                                   / float(crop["planting"]["density_per_m2"]) * 10) / 10
            area = min(room, seeds_for)
            if area > 0.5:
                planned[crop_id] = planned.get(crop_id, 0.0) + area
                self.call("plant", compartment=c, area_m2=area)

    def reorder_seedlings(self, status: dict[str, Any], hour: int) -> None:
        """Each day: order seedlings for the space that is free or frees within the lead time,
        less what is in stock, while a planting on arrival can still finish. Compartments that
        grow the same crop share one item, so the need is summed per item."""
        business = status["business"]
        stock = business.get("stock", {})
        on_order: dict[str, float] = {}
        for o in business.get("open_orders", []):
            on_order[o.get("item")] = on_order.get(o.get("item"), 0.0) + float(o.get("quantity", 0.0))
        need: dict[str, float] = {}
        for c in self.compartments:
            crop_id, crop = self.crop_in[c], self.crop(c)
            item = f"seedlings:{crop_id}"
            if item not in self.items or crop.get("cycle", {}).get("harvest_mode") != "single":
                continue
            lead_h = self.items[item].get("lead_time_h", 0)
            lead_h = max(lead_h) if isinstance(lead_h, list) else float(lead_h)
            if hour + lead_h > self.plant_deadline(crop):
                continue
            density = float(crop["planting"]["density_per_m2"])
            if self.daily_area(crop_id, hour) is not None:
                # The sowing plan from today until a new order would land, plus a few days' cover.
                days = int(lead_h // 24 + self.seed_cover_days) + 1
                plan = sum(self.daily_area(crop_id, hour + 24 * k) for k in range(days)
                           if hour + 24 * k <= self.plant_deadline(crop))
                need[item] = max(need.get(item, 0.0), plan * density)       # one plan per crop
                continue
            area = float(status["free_area_m2"].get(c, 0.0)) + sum(
                b["area_m2"] for b in status["batches"] if b["compartment"] == c and b["status"] in STANDING
                and (b.get("estimate", {}).get("days_to_ready") or 0.0) <= lead_h / 24.0 + self.seed_cover_days)
            need[item] = need.get(item, 0.0) + area * density
        for item, plants in need.items():
            short = math.ceil(plants - float(stock.get(item, 0.0)) - on_order.get(item, 0.0))
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
