"""The simulator: one authoritative state, one way to change it.

The agent's tools, the scripted policies and the verifier all drive this
class, and only through the methods below. Reads never change anything. A
request the rules do not allow raises `RuleError` before any state is touched,
so a rejected request costs nothing and changes nothing.

Order of one day (`advance`), identical for every caller:

  1. The plan in effect is fixed: the plan submitted for today, or the default
     plan if none was submitted.
  2. Each bench: flush, top-up (mains and reserve), fertilizer, then
     transpiration, growth and uptake (`model.step_bench`). Benches do not
     interact within a day except through the shared reserve tank.
  3. Mains water, fertilizer and discharge are charged.
  4. Next morning: tests that are due are delivered, sensors are read, a new
     forecast is issued, and any notice for that morning is posted.

Test fees are charged when a test is ordered.
"""
from __future__ import annotations

import math
from typing import Any

from . import views
from .generator import Instance, generate
from .model import Params, concentration, ec_of, step_bench

PLAN_FIELDS = ("mains_l", "reserve_l", "fertilizer_g", "flush_l")
MAINS = "mains"
SAMPLE_TIME = "morning, before that day's plan was applied"
INCIDENT_NOTICE = ("Notice from the water utility: because of maintenance at the treatment plant, the mains supply "
                   "to your site has been switched to a backup source from this morning until further notice.")


class RuleError(Exception):
    """A request the rules do not allow. Nothing was changed or charged."""


class _Bench:
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
        self.benches = {b.id: _Bench(b) for b in self.instance.benches}
        self.reserve_l = self.instance.reserve_l
        self.plan: dict[str, dict[str, float]] | None = None
        self.plans_submitted = 0
        self.tests: list[dict[str, Any]] = []
        self.days: list[dict[str, Any]] = []
        self.mornings: list[dict[str, dict[str, Any]]] = []
        self.truth: list[dict[str, dict[str, float]]] = []
        self.events: list[dict[str, Any]] = []
        self.costs = {"mains_water": 0.0, "reserve_water": 0.0, "fertilizer": 0.0, "discharge": 0.0, "tests": 0.0}
        self.used = {"mains_l": 0.0, "reserve_l": 0.0, "flush_l": 0.0, "fertilizer_g": 0.0, "discharge_l": 0.0}
        self.lab_report = {b.id: {"sampled_day": 0, "sample_time": SAMPLE_TIME,
                                  "nutrient_g_l": round(concentration(b.nutrient_g, b.volume_l), 3),
                                  "salt_g_l": round(concentration(b.salt_g, b.volume_l), 3),
                                  "volume_l": b.volume_l} for b in self.instance.benches}
        self._read_sensors()
        self._event("day", "Day 0 begins. This morning's routine lab report for every bench is in get_status.")
        self._morning_notices()

    # -- basic facts -----------------------------------------------------------------

    @property
    def horizon(self) -> int:
        return self.p.horizon_days

    @property
    def done(self) -> bool:
        return self.day >= self.horizon

    def pumpable_l(self, bench_id: str) -> float:
        return max(0.0, self.benches[bench_id].volume - self.p.dead_volume_l)

    def default_plan(self) -> dict[str, dict[str, float]]:
        p = self.p
        return {b: {"mains_l": p.default_mains_l, "reserve_l": p.default_reserve_l,
                    "fertilizer_g": p.default_fertilizer_g, "flush_l": p.default_flush_l} for b in self.benches}

    def effective_plan(self) -> tuple[dict[str, dict[str, float]], str]:
        if self.plan is not None:
            return self.plan, "submitted"
        plan = self.default_plan()
        for bench_id, bp in plan.items():
            bp["flush_l"] = min(bp["flush_l"], self.pumpable_l(bench_id))
        return plan, "default"

    # -- requests ----------------------------------------------------------------------

    def check_plan(self, bench_plans: Any) -> dict[str, dict[str, float]]:
        """Validate a whole-day plan and return it normalized. Raises RuleError
        listing every problem; never changes state."""
        self._require_open()
        p = self.p
        if not isinstance(bench_plans, dict):
            raise RuleError("Plan rejected; nothing was changed. bench_plans must be an object mapping each "
                            "bench id to its plan.")
        problems = []
        unknown = sorted(str(k) for k in bench_plans if k not in self.benches)
        missing = [b for b in self.benches if b not in bench_plans]
        if unknown:
            problems.append(f"unknown bench(es) {unknown}; benches are {list(self.benches)}")
        if missing:
            problems.append(f"missing bench(es) {missing}; a day plan must cover every bench")
        plan: dict[str, dict[str, float]] = {}
        for bench_id in self.benches:
            if bench_id in missing:
                continue
            raw = bench_plans.get(bench_id)
            if not isinstance(raw, dict):
                problems.append(f"bench {bench_id}: plan must be an object with {list(PLAN_FIELDS)}")
                continue
            extra = sorted(str(k) for k in raw if k not in PLAN_FIELDS)
            absent = [k for k in PLAN_FIELDS if k not in raw]
            if extra:
                problems.append(f"bench {bench_id}: unknown field(s) {extra}; fields are {list(PLAN_FIELDS)}")
            if absent:
                problems.append(f"bench {bench_id}: missing field(s) {absent}")
            values = {}
            for key in PLAN_FIELDS:
                if key not in raw:
                    continue
                v = raw[key]
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                    problems.append(f"bench {bench_id}: {key} must be a finite number")
                elif v < 0:
                    problems.append(f"bench {bench_id}: {key} must not be negative (got {v:g})")
                else:
                    values[key] = float(v)
            if "mains_l" in values and "reserve_l" in values:
                top_up = values["mains_l"] + values["reserve_l"]
                if top_up > p.top_up_max_l + 1e-6:
                    problems.append(f"bench {bench_id}: mains_l + reserve_l = {top_up:g} L exceeds the per-bench daily "
                                    f"top-up limit, {p.top_up_max_l:.0f} L")
            if values.get("fertilizer_g", 0.0) > p.fertilizer_max_g + 1e-6:
                problems.append(f"bench {bench_id}: fertilizer_g {values['fertilizer_g']:g} g exceeds the per-bench "
                                f"daily limit, {p.fertilizer_max_g:.0f} g")
            if values.get("flush_l", 0.0) > self.pumpable_l(bench_id) + 1e-6:
                problems.append(f"bench {bench_id}: flush_l {values['flush_l']:g} L exceeds the bench's pumpable "
                                f"volume (volume above the dead volume), {self.pumpable_l(bench_id):.1f} L")
            plan[bench_id] = values
        if problems:
            raise RuleError("Plan rejected; nothing was changed. " + "; ".join(problems) + ".")
        reserve = sum(bp["reserve_l"] for bp in plan.values())
        if reserve > self.reserve_l + 1e-6:
            raise RuleError(f"Plan rejected; nothing was changed. It draws {reserve:.1f} L from the reserve tank but "
                            f"only {self.reserve_l:.1f} L is left. Reduce reserve_l by at least "
                            f"{reserve - self.reserve_l:.1f} L in total.")
        return plan

    def submit_plan(self, bench_plans: Any) -> dict[str, Any]:
        plan = self.check_plan(bench_plans)
        if self.plan is None:
            self.plans_submitted += 1
        self.plan = plan
        return {"accepted": True, "day": self.day, "plan": self.plan_summary(plan, "submitted")}

    def order_test(self, bench_id: Any) -> dict[str, Any]:
        """Sample a bench's solution now. Charged once, now."""
        self._require_open()
        if bench_id not in self.benches:
            raise RuleError(f"unknown bench {bench_id!r}; benches are {list(self.benches)}. Nothing was charged.")
        self._refuse_duplicate(bench_id)
        b = self.benches[bench_id]
        result = {"nutrient_g_l": round(concentration(b.nutrient, b.volume), 3),
                  "salt_g_l": round(concentration(b.salt, b.volume), 3),
                  "volume_l": round(b.volume, 1),
                  "ec_ds_m": round(ec_of(self.p, b.nutrient, b.salt, b.volume), 3)}
        return self._add_test(bench_id, "composition", self.p.test_price, result,
                              f"Composition test ordered for bench {bench_id}")

    def order_water_test(self) -> dict[str, Any]:
        """Sample today's mains supply. Charged once, now."""
        self._require_open()
        self._refuse_duplicate(MAINS)
        salt = self.instance.mains_salt(self.day)
        result = {"salt_g_l": round(salt, 3), "ec_ds_m": round(self.p.ec_per_g_l * salt, 3)}
        return self._add_test(MAINS, "mains_water", self.p.water_test_price, result,
                              "Mains water test ordered")

    def advance(self) -> dict[str, Any]:
        """Apply the plan in effect, run one day, and move to the next morning."""
        self._require_open()
        p, day = self.p, self.day
        plan, source = self.effective_plan()
        temp = self.instance.temps[day]
        mains_salt = self.instance.mains_salt(day)
        record: dict[str, Any] = {"day": day, "temp_c": temp, "plan_source": source, "benches": {}}
        totals = {"mains_l": 0.0, "reserve_l": 0.0, "flush_l": 0.0, "fertilizer_g": 0.0, "discharge_l": 0.0}
        for bench_id, b in self.benches.items():
            bp = plan[bench_id]
            before = b.condition
            r = step_bench(p, b.spec.growth_max_kg, b.spec.transp_base_l, b.volume, b.nutrient, b.salt,
                           b.condition, bp["mains_l"], bp["reserve_l"], bp["fertilizer_g"], bp["flush_l"],
                           temp, day, mains_salt)
            b.water_in += bp["mains_l"] + bp["reserve_l"] + bp["flush_l"]
            b.water_out += r.transpired_l + r.overflow_l + bp["flush_l"]
            b.nutrient_in += bp["fertilizer_g"] * (1.0 - p.fertilizer_ballast)
            b.nutrient_out += r.uptake_g + r.nutrient_out_g
            b.salt_in += r.salt_in_g
            b.salt_out += r.salt_out_g
            b.volume, b.nutrient, b.salt, b.condition = r.volume_l, r.nutrient_g, r.salt_g, r.condition
            b.harvest += r.growth_kg
            for key in ("mains_l", "reserve_l", "flush_l", "fertilizer_g"):
                totals[key] += bp[key]
            totals["discharge_l"] += bp["flush_l"] + r.overflow_l
            record["benches"][bench_id] = {
                "plan": dict(bp),
                "outcome": {"growth_kg": r.growth_kg, "transpired_l": r.transpired_l, "overflow_l": r.overflow_l,
                            "condition_before": before, "condition_after": r.condition},
                "truth": {"water_factor": r.water_factor, "nutrient_factor": r.nutrient_factor,
                          "salinity_factor": r.salinity_factor, "heat_factor": r.heat_factor, "stress": r.stress,
                          "midday_ec_ds_m": r.midday_ec_ds_m, "midday_nutrient_g_l": r.midday_nutrient_g_l,
                          "uptake_g": r.uptake_g, "mains_salt_g_l": mains_salt},
            }
        self.reserve_l -= totals["reserve_l"]
        mains_drawn = totals["mains_l"] + totals["flush_l"]   # flushes are refilled from the mains
        cost = {"mains_water": mains_drawn * p.mains_price_per_l,
                "reserve_water": totals["reserve_l"] * p.reserve_price_per_l,
                "fertilizer": totals["fertilizer_g"] * p.fertilizer_price_per_g,
                "discharge": totals["discharge_l"] * p.discharge_price_per_l}
        for key, value in cost.items():
            self.costs[key] += value
        for key, value in totals.items():
            self.used[key] += value
        record.update(totals)
        record.update({"mains_drawn_l": mains_drawn, "cost": cost, "reserve_left_l": self.reserve_l})
        self.days.append(record)
        self.plan = None
        self.day += 1
        first_event = len(self.events)
        self._day_events(record)
        delivered = self._deliver_tests()
        self._read_sensors()
        self._morning_notices()
        return views.day_report(self, record, delivered, self.events[first_event:])

    def finish(self) -> None:
        """The player stops deciding. Every remaining day still runs, under the
        plan already submitted for today (if any) and the default plan after."""
        if self.done:
            return
        self.finished_by_player = True
        while not self.done:
            self.advance()

    # -- internals -----------------------------------------------------------------------

    def plan_summary(self, plan: dict[str, dict[str, float]], source: str) -> dict[str, Any]:
        """What a plan would draw and cost today. Says nothing about growth."""
        p = self.p
        tot = {k: sum(bp[k] for bp in plan.values()) for k in PLAN_FIELDS}
        # A flush is refilled to the same volume, so only the top-up can overflow.
        overflow = sum(max(0.0, self.benches[b].volume + bp["mains_l"] + bp["reserve_l"] - p.capacity_l)
                       for b, bp in plan.items())
        cost = {"mains_water_eur": round((tot["mains_l"] + tot["flush_l"]) * p.mains_price_per_l, 2),
                "reserve_water_eur": round(tot["reserve_l"] * p.reserve_price_per_l, 2),
                "fertilizer_eur": round(tot["fertilizer_g"] * p.fertilizer_price_per_g, 2),
                "discharge_eur": round((tot["flush_l"] + overflow) * p.discharge_price_per_l, 2)}
        cost["total_eur"] = round(sum(cost.values()), 2)
        return {"source": source,
                "benches": {b: {k: round(v, 1) for k, v in bp.items()} for b, bp in plan.items()},
                "mains_l": round(tot["mains_l"] + tot["flush_l"], 1), "reserve_l": round(tot["reserve_l"], 1),
                "fertilizer_g": round(tot["fertilizer_g"], 1), "overflow_to_waste_l": round(overflow, 1),
                "reserve_left_after_l": round(self.reserve_l - tot["reserve_l"], 1),
                "immediate_cost": cost}

    def _require_open(self) -> None:
        if self.done:
            raise RuleError(f"The episode is over: all {self.horizon} days have been played. "
                            "No further requests are possible.")

    def _refuse_duplicate(self, target: str) -> None:
        if any(t["target"] == target and t["sampled_day"] == self.day for t in self.tests):
            what = "the mains supply" if target == MAINS else f"bench {target}"
            raise RuleError(f"{what} was already sampled on day {self.day}; a second sample today would measure "
                            "the same water. Nothing was charged.")

    def _add_test(self, target: str, kind: str, price: float, result: dict[str, Any], label: str) -> dict[str, Any]:
        test = {"test_id": f"T{len(self.tests) + 1:02d}", "target": target, "test_type": kind,
                "sampled_day": self.day, "sample_time": SAMPLE_TIME,
                "delivery_day": self.day + self.p.test_delay_days, "cost_eur": price,
                "delivered": False, "result": result}
        self.tests.append(test)
        self.costs["tests"] += price
        self._event("test_ordered", f"{label}: sampled this morning, result on day {test['delivery_day']}. "
                    f"Charged €{price:.2f}.", None if target == MAINS else target)
        return self.public_test(test)

    def _event(self, kind: str, text: str, bench_id: str | None = None) -> None:
        self.events.append({"n": len(self.events), "day": self.day, "kind": kind, "bench_id": bench_id, "text": text})

    def _morning_notices(self) -> None:
        if not self.done and self.day == self.instance.incident_day:
            self._event("notice", INCIDENT_NOTICE)

    def _read_sensors(self) -> None:
        p, morning, truth = self.p, {}, {}
        for bench_id, b in self.benches.items():
            ec = ec_of(p, b.nutrient, b.salt, b.volume)
            morning[bench_id] = {
                "day": self.day,
                "ec_ds_m": round(max(0.0, ec + self.instance.ec_noise[bench_id][self.day]), 2),
                "volume_l": round(b.volume, 1),
                "condition": round(b.condition, 3),
                "crop_gain_kg": round(b.harvest, 1),
            }
            truth[bench_id] = {"nutrient_g_l": concentration(b.nutrient, b.volume),
                               "salt_g_l": concentration(b.salt, b.volume), "ec_ds_m": ec,
                               "nutrient_g": b.nutrient, "salt_g": b.salt}
        self.mornings.append(morning)
        self.truth.append(truth)

    def public_test(self, test: dict[str, Any]) -> dict[str, Any]:
        out = {k: test[k] for k in ("test_id", "test_type", "sampled_day", "sample_time", "delivery_day", "cost_eur")}
        out["bench_id"] = None if test["target"] == MAINS else test["target"]
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
                if test["target"] == MAINS:
                    text = (f"Mains water test (sampled day {test['sampled_day']}): salt {r['salt_g_l']:.3f} g/L, "
                            f"EC {r['ec_ds_m']:.2f} dS/m.")
                else:
                    text = (f"Test result for bench {test['target']} (sampled day {test['sampled_day']}, "
                            f"{SAMPLE_TIME}): nutrients {r['nutrient_g_l']:.3f} g/L, salts {r['salt_g_l']:.3f} g/L "
                            f"in {r['volume_l']:.0f} L.")
                self._event("test_result", text, None if test["target"] == MAINS else test["target"])
                out.append(self.public_test(test))
        return out

    def _day_events(self, record: dict[str, Any]) -> None:
        day, p = record["day"], self.p
        if record["plan_source"] == "default":
            self._event("plan", f"Day {day}: no plan was submitted, so the default plan was applied.")
        self._event("water", f"Day {day} ({record['temp_c']:.1f} °C): drew {record['mains_drawn_l']:.0f} L of mains "
                    f"water and {record['reserve_l']:.0f} L from the reserve ({record['reserve_left_l']:.0f} L left). "
                    f"Fertilizer {record['fertilizer_g']:.0f} g. Day cost €{sum(record['cost'].values()):.2f}.")
        for bench_id, br in record["benches"].items():
            o = br["outcome"]
            if o["overflow_l"] > 0.05:
                self._event("overflow", f"Bench {bench_id} overflowed {o['overflow_l']:.0f} L to waste on day {day}.",
                            bench_id)
            if o["condition_after"] - o["condition_before"] <= -0.005:
                self._event("stress", f"Bench {bench_id} crop condition fell from {o['condition_before']:.2f} to "
                            f"{o['condition_after']:.2f} after day {day}.", bench_id)
            if self.benches[bench_id].volume < p.comfort_volume_l - 1e-9:
                self._event("low_water", f"Bench {bench_id} solution volume is {self.benches[bench_id].volume:.0f} L, "
                            f"below the {p.comfort_volume_l:.0f} L at which the film breaks up.", bench_id)
