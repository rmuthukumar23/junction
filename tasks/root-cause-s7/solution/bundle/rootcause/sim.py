"""The simulator: one authoritative state, one way to change it.

The browser, the agent's tools, the scripted policies and the verifier all
drive this class, and only through the methods below. Reads never change
anything. A request the rules do not allow raises `RuleError` before any state
is touched, so a rejected request costs nothing and changes nothing.

Order of one day (`advance`), identical for every caller:

  1. The plan in effect is fixed: the plan submitted for today, or the default
     operating plan if none was submitted (scaled equally across zones if
     fresh water cannot cover it).
  2. Fresh water for irrigation and flushing is drawn from the shared
     allocation, for all zones at once.
  3. Each zone: flush, irrigation and mixing, fertilizer, then transpiration,
     growth and nutrient uptake, then overflow and flush water go to waste
     (`model.step_zone`). Zones do not interact within a day, so the order in
     which they are computed cannot favor any of them.
  4. Crop condition for tomorrow is set from today's stress.
  5. The day's water, fertilizer and discharge are charged.
  6. The calendar moves to the next morning: tests whose delivery day has
     come are delivered, sensors are read, and a new forecast is issued.

Test fees are charged at the moment a test is ordered.
"""
from __future__ import annotations

import math
from typing import Any

from . import views
from .generator import Instance, generate
from .model import Params, concentration, ec_of, step_zone

TEST_TYPES = ("composition",)
PLAN_FIELDS = ("irrigation_l", "fertilizer_g", "flush_l")
SAMPLE_TIME = "morning, before that day's plan was applied"


class RuleError(Exception):
    """A request the rules do not allow. Nothing was changed or charged."""


class _Zone:
    __slots__ = ("spec", "volume", "nutrient", "salt", "condition", "harvest",
                 "water_in", "water_out", "nutrient_in", "nutrient_out", "salt_in", "salt_out")

    def __init__(self, spec: Any):
        self.spec = spec
        self.volume, self.nutrient, self.salt = spec.volume_l, spec.nutrient_g, spec.salt_g
        self.condition, self.harvest = spec.condition, 0.0
        self.water_in = self.water_out = 0.0
        self.nutrient_in = self.nutrient_out = 0.0
        self.salt_in = self.salt_out = 0.0


class Greenhouse:
    def __init__(self, config: dict[str, Any], seed: int, instance: Instance | None = None):
        self.config = config
        self.instance = instance or generate(config, seed)
        self.p: Params = self.instance.params
        self.day = 0
        self.finished_by_player = False
        self.zones = {z.id: _Zone(z) for z in self.instance.zones}
        self.fresh_water_l = self.instance.fresh_water_l
        self.plan: dict[str, dict[str, float]] | None = None      # submitted for today, if any
        self.plans_submitted = 0
        self.tests: list[dict[str, Any]] = []
        self.days: list[dict[str, Any]] = []                      # one record per completed day
        self.mornings: list[dict[str, dict[str, Any]]] = []       # sensor readings, days 0..horizon
        self.truth: list[dict[str, dict[str, float]]] = []        # hidden composition at each morning
        self.events: list[dict[str, Any]] = []
        self.costs = {"water": 0.0, "fertilizer": 0.0, "discharge": 0.0, "tests": 0.0}
        self.used = {"irrigation_l": 0.0, "flush_l": 0.0, "fertilizer_g": 0.0, "discharge_l": 0.0}
        self._read_sensors()
        self._event("day", f"Day 0 begins. Forecast for today: {self.instance.forecasts[0][0]:.1f} °C.")

    # -- basic facts -----------------------------------------------------------------

    @property
    def horizon(self) -> int:
        return self.p.horizon_days

    @property
    def done(self) -> bool:
        return self.day >= self.horizon

    def available_today_l(self) -> float:
        """Fresh water that can be delivered today: the allocation left, up to the daily cap."""
        return max(0.0, min(self.fresh_water_l, self.p.daily_fresh_water_cap_l))

    def pumpable_l(self, zone_id: str) -> float:
        """The most that can be flushed from a zone: everything above the dead volume."""
        return max(0.0, self.zones[zone_id].volume - self.p.dead_volume_l)

    def default_plan(self) -> dict[str, dict[str, float]]:
        p = self.p
        return {z: {"irrigation_l": p.default_irrigation_l, "fertilizer_g": p.default_fertilizer_g,
                    "flush_l": p.default_flush_l} for z in self.zones}

    def effective_plan(self) -> tuple[dict[str, dict[str, float]], str]:
        """The plan that `advance` would apply now, and where it comes from."""
        if self.plan is not None:
            return self.plan, "submitted"
        plan = self.default_plan()
        for zone_id, zp in plan.items():   # a default flush can never exceed what is pumpable
            zp["flush_l"] = min(zp["flush_l"], self.pumpable_l(zone_id))
        need = sum(zp["irrigation_l"] + zp["flush_l"] for zp in plan.values())
        available = self.available_today_l()
        if need <= available + 1e-9:
            return plan, "default"
        scale = available / need if need > 0 else 0.0
        for zp in plan.values():           # every zone is cut by the same factor
            zp["irrigation_l"] *= scale
            zp["flush_l"] *= scale
        return plan, "default_scaled"

    # -- requests ----------------------------------------------------------------------

    def check_plan(self, zone_plans: Any) -> dict[str, dict[str, float]]:
        """Validate a whole-day plan and return it normalized. Raises RuleError
        listing every problem; never changes state."""
        self._require_open()
        p = self.p
        if not isinstance(zone_plans, dict):
            raise RuleError("Plan rejected; nothing was changed. zone_plans must be an object mapping each "
                            "zone id to its plan.")
        problems = []
        unknown = sorted(str(k) for k in zone_plans if k not in self.zones)
        missing = [z for z in self.zones if z not in zone_plans]
        if unknown:
            problems.append(f"unknown zone(s) {unknown}; zones are {list(self.zones)}")
        if missing:
            problems.append(f"missing zone(s) {missing}; a day plan must cover every zone")
        plan: dict[str, dict[str, float]] = {}
        for zone_id in self.zones:
            raw = zone_plans.get(zone_id)
            if zone_id in missing:
                continue
            if not isinstance(raw, dict):
                problems.append(f"zone {zone_id}: plan must be an object with {list(PLAN_FIELDS)}")
                continue
            extra = sorted(str(k) for k in raw if k not in PLAN_FIELDS)
            absent = [k for k in PLAN_FIELDS if k not in raw]
            if extra:
                problems.append(f"zone {zone_id}: unknown field(s) {extra}; fields are {list(PLAN_FIELDS)}")
            if absent:
                problems.append(f"zone {zone_id}: missing field(s) {absent}")
            values = {}
            for key in PLAN_FIELDS:
                if key not in raw:
                    continue
                v = raw[key]
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                    problems.append(f"zone {zone_id}: {key} must be a finite number")
                elif v < 0:
                    problems.append(f"zone {zone_id}: {key} must not be negative (got {v:g})")
                else:
                    values[key] = float(v)
            limits = {"irrigation_l": (p.irrigation_max_l, "the per-zone daily irrigation limit"),
                      "fertilizer_g": (p.fertilizer_max_g, "the per-zone daily fertilizer limit"),
                      "flush_l": (self.pumpable_l(zone_id), "the zone's pumpable volume (volume above the dead volume)")}
            for key, (limit, what) in limits.items():
                unit = "g" if key.endswith("_g") else "L"
                if key in values and values[key] > limit + 1e-6:
                    problems.append(f"zone {zone_id}: {key} {values[key]:g} {unit} exceeds {what}, {limit:.1f} {unit}")
            plan[zone_id] = values
        if problems:
            raise RuleError("Plan rejected; nothing was changed. " + "; ".join(problems) + ".")
        need = sum(zp["irrigation_l"] + zp["flush_l"] for zp in plan.values())
        available = self.available_today_l()
        if need > available + 1e-6:
            raise RuleError(
                f"Plan rejected; nothing was changed. It needs {need:.1f} L of fresh water today "
                f"(irrigation + flush, all zones) but only {available:.1f} L can be delivered "
                f"(daily cap {p.daily_fresh_water_cap_l:.0f} L; {self.fresh_water_l:.1f} L left in the allocation). "
                f"Reduce irrigation or flush by at least {need - available:.1f} L in total.")
        return plan

    def submit_plan(self, zone_plans: Any) -> dict[str, Any]:
        """Set today's plan for all zones at once. Replaces any plan already
        submitted today. Costs nothing until the day is advanced."""
        plan = self.check_plan(zone_plans)
        if self.plan is None:
            self.plans_submitted += 1
        self.plan = plan
        return {"accepted": True, "day": self.day, "plan": self.plan_summary(plan, "submitted")}

    def order_test(self, zone_id: Any, test_type: Any) -> dict[str, Any]:
        """Take a sample now and send it to the lab. Charged once, now."""
        self._require_open()
        if zone_id not in self.zones:
            raise RuleError(f"unknown zone {zone_id!r}; zones are {list(self.zones)}. Nothing was charged.")
        if test_type not in TEST_TYPES:
            raise RuleError(f"unknown test type {test_type!r}; test types are {list(TEST_TYPES)}. Nothing was charged.")
        if any(t["zone_id"] == zone_id and t["test_type"] == test_type and t["sampled_day"] == self.day
               for t in self.tests):
            raise RuleError(f"a {test_type} sample for zone {zone_id} was already taken on day {self.day}; "
                            "a second one today would measure the same solution. Nothing was charged.")
        z = self.zones[zone_id]
        test = {
            "test_id": f"T{len(self.tests) + 1:02d}", "zone_id": zone_id, "test_type": test_type,
            "sampled_day": self.day, "sample_time": SAMPLE_TIME,
            "delivery_day": self.day + self.p.test_delay_days, "cost_eur": self.p.test_price,
            "delivered": False,
            "result": {   # hidden until delivery
                "nutrient_g_l": round(concentration(z.nutrient, z.volume), 3),
                "salt_g_l": round(concentration(z.salt, z.volume), 3),
                "volume_l": round(z.volume, 1),
                "ec_ds_m": round(ec_of(self.p, z.nutrient, z.salt, z.volume), 2),
            },
        }
        self.tests.append(test)
        self.costs["tests"] += self.p.test_price
        self._event("test_ordered", f"Composition test ordered for zone {zone_id}: sampled this morning, result "
                    f"on day {test['delivery_day']}. Charged €{self.p.test_price:.2f}.", zone_id)
        return self._public_test(test)

    def advance(self) -> dict[str, Any]:
        """Apply the plan in effect, run one day, and move to the next morning."""
        self._require_open()
        p, day = self.p, self.day
        plan, source = self.effective_plan()
        temp = self.instance.temps[day]
        irrigation = sum(zp["irrigation_l"] for zp in plan.values())
        flush = sum(zp["flush_l"] for zp in plan.values())
        fertilizer = sum(zp["fertilizer_g"] for zp in plan.values())
        self.fresh_water_l -= irrigation + flush

        record: dict[str, Any] = {"day": day, "temp_c": temp, "plan_source": source, "zones": {}}
        discharge = 0.0
        for zone_id, z in self.zones.items():
            zp = plan[zone_id]
            before = z.condition
            r = step_zone(p, z.spec.growth_max_kg, z.spec.transp_base_l, z.volume, z.nutrient, z.salt,
                          z.condition, zp["irrigation_l"], zp["fertilizer_g"], zp["flush_l"], temp, day)
            z.water_in += zp["irrigation_l"] + zp["flush_l"]
            z.water_out += r.transpired_l + r.overflow_l + zp["flush_l"]
            z.nutrient_in += zp["fertilizer_g"] * (1.0 - p.fertilizer_ballast)
            z.nutrient_out += r.uptake_g + r.nutrient_out_g
            z.salt_in += r.salt_in_g
            z.salt_out += r.salt_out_g
            z.volume, z.nutrient, z.salt, z.condition = r.volume_l, r.nutrient_g, r.salt_g, r.condition
            z.harvest += r.growth_kg
            discharge += zp["flush_l"] + r.overflow_l
            record["zones"][zone_id] = {
                "plan": dict(zp),
                "outcome": {"growth_kg": r.growth_kg, "transpired_l": r.transpired_l, "overflow_l": r.overflow_l,
                            "condition_before": before, "condition_after": r.condition},
                "truth": {"water_factor": r.water_factor, "nutrient_factor": r.nutrient_factor,
                          "salinity_factor": r.salinity_factor, "heat_factor": r.heat_factor, "stress": r.stress,
                          "midday_ec_ds_m": r.midday_ec_ds_m, "midday_nutrient_g_l": r.midday_nutrient_g_l,
                          "uptake_g": r.uptake_g},
            }
        cost = {"water": (irrigation + flush) * p.water_price_per_l, "fertilizer": fertilizer * p.fertilizer_price_per_g,
                "discharge": discharge * p.discharge_price_per_l}
        for key, value in cost.items():
            self.costs[key] += value
        self.used["irrigation_l"] += irrigation
        self.used["flush_l"] += flush
        self.used["fertilizer_g"] += fertilizer
        self.used["discharge_l"] += discharge
        record.update({"irrigation_l": irrigation, "flush_l": flush, "fertilizer_g": fertilizer,
                       "discharge_l": discharge, "cost": cost, "fresh_water_left_l": self.fresh_water_l})
        self.days.append(record)
        self.plan = None
        self.day += 1
        first_event = len(self.events)
        self._day_events(record)
        delivered = self._deliver_tests()
        self._read_sensors()
        self._forecast_events()
        return views.day_report(self, record, delivered, self.events[first_event:])

    def finish(self) -> None:
        """The player stops deciding. Every remaining day still runs, under the
        plan already submitted for today (if any) and the default plan after."""
        if self.done:
            return   # every day has been played: there is nothing left to stop
        self.finished_by_player = True
        while not self.done:
            self.advance()

    # -- internals -----------------------------------------------------------------------

    def plan_summary(self, plan: dict[str, dict[str, float]], source: str) -> dict[str, Any]:
        """What a plan would draw and cost today. Uses only what the player can
        already see; says nothing about growth."""
        p = self.p
        irrigation = sum(zp["irrigation_l"] for zp in plan.values())
        flush = sum(zp["flush_l"] for zp in plan.values())
        fertilizer = sum(zp["fertilizer_g"] for zp in plan.values())
        overflow = sum(max(0.0, self.zones[z].volume + zp["irrigation_l"] - p.capacity_l) for z, zp in plan.items())
        cost = {"water_eur": round((irrigation + flush) * p.water_price_per_l, 2),
                "fertilizer_eur": round(fertilizer * p.fertilizer_price_per_g, 2),
                "discharge_eur": round((flush + overflow) * p.discharge_price_per_l, 2)}
        cost["total_eur"] = round(sum(cost.values()), 2)
        return {
            "source": source,
            "zones": {z: {k: round(v, 1) for k, v in zp.items()} for z, zp in plan.items()},
            "fresh_water_l": round(irrigation + flush, 1), "irrigation_l": round(irrigation, 1),
            "flush_l": round(flush, 1), "fertilizer_g": round(fertilizer, 1),
            "overflow_to_waste_l": round(overflow, 1),
            "fresh_water_left_after_l": round(self.fresh_water_l - irrigation - flush, 1),
            "immediate_cost": cost,
        }

    def _require_open(self) -> None:
        if self.done:
            raise RuleError(f"The episode is over: all {self.horizon} days have been played. "
                            "No further requests are possible.")

    def _event(self, kind: str, text: str, zone_id: str | None = None) -> None:
        self.events.append({"n": len(self.events), "day": self.day, "kind": kind, "zone_id": zone_id, "text": text})

    def _read_sensors(self) -> None:
        p, morning, truth = self.p, {}, {}
        for zone_id, z in self.zones.items():
            ec = ec_of(p, z.nutrient, z.salt, z.volume)
            morning[zone_id] = {
                "day": self.day,
                "ec_ds_m": round(max(0.0, ec + self.instance.ec_noise[zone_id][self.day]), 2),
                "volume_l": round(z.volume, 1),
                "condition": round(z.condition, 3),
                "harvest_kg": round(z.harvest, 1),
            }
            truth[zone_id] = {"nutrient_g_l": concentration(z.nutrient, z.volume),
                              "salt_g_l": concentration(z.salt, z.volume), "ec_ds_m": ec,
                              "nutrient_g": z.nutrient, "salt_g": z.salt}
        self.mornings.append(morning)
        self.truth.append(truth)

    def _public_test(self, test: dict[str, Any]) -> dict[str, Any]:
        out = {k: test[k] for k in ("test_id", "zone_id", "test_type", "sampled_day", "sample_time",
                                    "delivery_day", "cost_eur")}
        out["status"] = "delivered" if test["delivered"] else "pending"
        if test["delivered"]:
            out["result"] = dict(test["result"])
        return out

    def _deliver_tests(self) -> list[dict[str, Any]]:
        out = []
        for test in self.tests:
            if not test["delivered"] and test["delivery_day"] <= self.day:
                test["delivered"] = True
                r = test["result"]
                self._event("test_result", f"Test result for zone {test['zone_id']} (sampled day {test['sampled_day']}, "
                            f"{SAMPLE_TIME}): nutrients {r['nutrient_g_l']:.2f} g/L, salts {r['salt_g_l']:.2f} g/L "
                            f"in {r['volume_l']:.0f} L.", test["zone_id"])
                out.append(self._public_test(test))
        return out

    def _day_events(self, record: dict[str, Any]) -> None:
        day, p = record["day"], self.p
        if record["plan_source"] == "default":
            self._event("plan", f"Day {day}: no plan was submitted, so the default plan was applied.")
        elif record["plan_source"] == "default_scaled":
            self._event("plan", f"Day {day}: no plan was submitted and fresh water could not cover the default plan; "
                        "every zone's default irrigation was cut by the same factor.")
        self._event("water", f"Day {day} ({record['temp_c']:.1f} °C): used {record['irrigation_l']:.0f} L for irrigation "
                    f"and {record['flush_l']:.0f} L for flushing; {record['fresh_water_left_l']:.0f} L of fresh water left. "
                    f"Fertilizer {record['fertilizer_g']:.0f} g. Day cost €{sum(record['cost'].values()):.2f}.")
        for zone_id, zr in record["zones"].items():
            o = zr["outcome"]
            if o["overflow_l"] > 0.05:
                self._event("overflow", f"Zone {zone_id} overflowed {o['overflow_l']:.0f} L to waste on day {day}.", zone_id)
            change = o["condition_after"] - o["condition_before"]
            if change <= -0.005:
                self._event("stress", f"Zone {zone_id} crop condition fell from {o['condition_before']:.2f} to "
                            f"{o['condition_after']:.2f} after day {day}.", zone_id)
            if self.zones[zone_id].volume < p.comfort_volume_l - 1e-9:
                self._event("low_water", f"Zone {zone_id} solution volume is {self.zones[zone_id].volume:.0f} L, below "
                            f"the {p.comfort_volume_l:.0f} L at which water uptake becomes limited.", zone_id)

    def _forecast_events(self) -> None:
        """Report forecasts that moved by 2 °C or more since yesterday's issue."""
        if self.done:
            return
        old, new = self.instance.forecasts[self.day - 1], self.instance.forecasts[self.day]
        for k, temp in enumerate(new):
            if k + 1 < len(old) and abs(temp - old[k + 1]) >= 2.0:
                self._event("forecast", f"Forecast for day {self.day + k} changed from {old[k + 1]:.1f} to {temp:.1f} °C.")
