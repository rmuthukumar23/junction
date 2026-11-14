"""Root Cause served by the envkit backend.

`Greenhouse` stays the single authority on rules. This binding only names the
tools, turns a `RuleError` into the error an agent sees, and maps envkit's
clock onto the simulator's days: one window is one day, and `advance_day` is
the only call that spends the window's single operation. Reads, plans and
tests are free in operations, so looking never moves time.

When the player stops for any reason (calls `finish_episode`, closes the
browser, or the agent process ends), every remaining day still runs under the
default plan: envkit's `finalize()` closes each remaining window and
`on_window_end` advances the simulator, or `finish_episode` does it at once.
Both paths end in the same state.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from envkit.core import Environment, ToolError, tool
from envkit.rng import Rng

from . import outcome, views
from .sim import Greenhouse, RuleError

ZonePlans = dict[str, dict[str, float]]


class RootCause(Environment):
    builtin_tools = ()   # the contract names its own tools; `advance_day` replaces `end_window`

    def setup(self) -> None:
        self.sim = Greenhouse(dict(self.config), self.rng.seed)
        if self.shift.windows != self.sim.horizon or self.shift.ops_per_window != 1:
            raise ValueError(f"[shift] must be windows = {self.sim.horizon}, ops_per_window = 1")

    # -- reads: free, and they change nothing ----------------------------------------

    @tool(cost=0)
    def get_rules(self) -> dict[str, Any]:
        """Every rule of the simulator: objective, units, prices, limits, capacities, the order of a day, the response formulas with their parameters, each zone's growth potential and water demand, test price and delay, and how the result is scored. Read this first. Free; changes nothing."""
        return views.rules(self.sim)

    @tool(cost=0)
    def get_status(self) -> dict[str, Any]:
        """This morning's readings for all four zones (EC, solution volume, crop condition, harvest so far, pumpable volume, yesterday's plan and outcome, latest test), fresh water left, costs so far, and the plan currently in effect for today with what it will draw and cost. EC is the total of nutrients and salts; it does not show which. Free; changes nothing."""
        return views.status(self.sim)

    @tool(cost=0)
    def get_history(self, zone_id: Annotated[str, "Zone id: A, B, C or D."],
                    first_day: Annotated[int, "First day to return (0 = the first day)."] = 0,
                    last_day: Annotated[Optional[int], "Last day to return; omit for up to today."] = None) -> dict[str, Any]:
        """One zone's record for a range of days: each morning's sensor readings, the plan that was applied, and the outcome (growth, water transpired, overflow) with the temperature that actually occurred. Free; changes nothing."""
        self._zone(zone_id)
        if first_day < 0 or (last_day is not None and last_day < first_day):
            raise ToolError("first_day must be 0 or more, and last_day must not be before first_day")
        return views.history(self.sim, zone_id, first_day, last_day)

    @tool(cost=0)
    def get_forecast(self) -> dict[str, Any]:
        """The temperature forecast issued this morning for today and the following days. Forecasts are estimates and can change from one morning to the next. Free; changes nothing."""
        return views.forecast(self.sim)

    @tool(cost=0)
    def get_pending_tests(self) -> dict[str, Any]:
        """All tests: those still at the lab (with their delivery day) and those delivered, each with the day its sample was taken and its result. Free; changes nothing."""
        return views.tests(self.sim)

    @tool(cost=0)
    def get_events(self, since_day: Annotated[int, "Return events from this day on."] = 0) -> dict[str, Any]:
        """The factual event log: resources used each day, plans applied, test orders and results, forecast changes, overflow and observed drops in crop condition. Free; changes nothing."""
        if since_day < 0:
            raise ToolError("since_day must be 0 or more")
        return views.events(self.sim, since_day)

    # -- requests ----------------------------------------------------------------------

    @tool(cost=0)
    def order_test(self, zone_id: Annotated[str, "Zone id: A, B, C or D."],
                   test_type: Annotated[Literal["composition"], "The only test offered."] = "composition") -> dict[str, Any]:
        """Order a lab test of one zone's solution. The sample is taken now (this morning, before today's plan is applied) and the result, nutrients and salts in g/L at the sample time, arrives one day later. The fee is charged once, now, and is never refunded. One sample per zone per day."""
        return self._ask(self.sim.order_test, zone_id, test_type)

    @tool(cost=0)
    def submit_day_plan(self, zone_plans: Annotated[ZonePlans, "One entry per zone, all four required, e.g. {\"A\": {\"irrigation_l\": 220, \"fertilizer_g\": 120, \"flush_l\": 0}, \"B\": {...}, \"C\": {...}, \"D\": {...}}. All amounts are for today only."]) -> dict[str, Any]:
        """Set today's plan for all four zones at once: litres of irrigation, grams of fertilizer and litres to flush (bleed to waste and replace with fresh water) per zone. The whole plan is accepted or rejected together; a rejected plan changes nothing and the error says what to fix. Submitting again today replaces the earlier plan. Nothing is applied or charged until advance_day. A plan lasts one day: a day with no submitted plan runs the default plan."""
        return self._ask(self.sim.submit_plan, zone_plans)

    @tool(cost=1)
    def advance_day(self) -> dict[str, Any]:
        """Apply the plan in effect (the plan submitted today, else the default plan), run the day, and move to the next morning. Returns what happened and the new status, and after the last day the final result. This is the only tool that moves time."""
        report = self._ask(self.sim.advance)
        if self.sim.done:   # the last day has been played: the result is final
            report["final_result"] = outcome.ledger(self.sim)
        return report

    @tool(cost=0)
    def finish_episode(self) -> dict[str, Any]:
        """Stop deciding. All remaining days still run: today under the plan in effect, later days under the default plan, and the result is taken at the end of the last day. Returns the final result. Cannot be undone."""
        self.sim.finish()
        return {"final_result": outcome.ledger(self.sim)}

    # -- engine hooks ------------------------------------------------------------------

    def on_window_end(self, window: int) -> None:
        # `advance_day` has already moved the simulator past this window. A window
        # that closes with nobody acting (the player stopped) is advanced here.
        if self.sim.day <= window:
            self.sim.advance()

    def terminated(self) -> str | None:
        return "finished" if self.sim.finished_by_player else None

    def on_finish(self) -> None:
        self.sim.finish()   # no effect if every day has already been played

    def header(self) -> dict[str, Any]:
        s = self.sim
        return {"day": s.day, "days_total": s.horizon, "fresh_water_left_l": round(s.fresh_water_l, 1),
                "plan_for_today": "none" if s.done else ("submitted" if s.plan is not None else "default")}

    def snapshot(self) -> dict[str, Any]:
        s = self.sim
        return {"day": s.day, "profit_so_far": round(outcome.profit(s), 2),
                "fresh_water_left_l": round(s.fresh_water_l, 1),
                "zones": {z: {"volume_l": round(zone.volume, 1), "nutrient_g": round(zone.nutrient, 1),
                              "salt_g": round(zone.salt, 1), "condition": round(zone.condition, 3),
                              "harvest_kg": round(zone.harvest, 2)} for z, zone in s.zones.items()}}

    def ledger(self) -> dict[str, float | None]:
        result = outcome.ledger(self.sim)
        if result["conservation_ok"] != 1.0:
            # Refuse to score a run whose balances do not close: the verifier
            # then reports an infrastructure failure instead of a reward.
            raise RuntimeError(f"resource conservation failed: {outcome.conservation(self.sim)}")
        return result

    # -- scripted policies -------------------------------------------------------------

    @classmethod
    def policies(cls) -> dict[str, Any]:
        from .planner import Reference
        from .policies import Attend, RuleBased
        return {"reference": Reference, "rule-based": RuleBased, "absentee": Attend}

    @classmethod
    def fuzz_args(cls, tool_name: str, rng: Rng) -> dict[str, Any] | None:
        zone = rng.choice(["A", "B", "C", "D", "E"])
        if tool_name == "order_test":
            return {"zone_id": zone}
        if tool_name == "get_history":
            return {"zone_id": zone, "first_day": rng.randint(0, 14)}
        if tool_name == "get_events":
            return {"since_day": rng.randint(0, 14)}
        if tool_name == "submit_day_plan":
            def amount(top: float) -> float:
                return 0.0 if rng.bernoulli(0.3) else round(rng.uniform(0.0, top), 1)
            return {"zone_plans": {z: {"irrigation_l": amount(500), "fertilizer_g": amount(600),
                                       "flush_l": amount(300)} for z in "ABCD"}}
        return None

    # -- internals ---------------------------------------------------------------------

    def _zone(self, zone_id: str) -> None:
        if zone_id not in self.sim.zones:
            raise ToolError(f"unknown zone {zone_id!r}; zones are {list(self.sim.zones)}")

    @staticmethod
    def _ask(fn: Any, *args: Any) -> Any:
        try:
            return fn(*args)
        except RuleError as e:
            raise ToolError(str(e)) from None
