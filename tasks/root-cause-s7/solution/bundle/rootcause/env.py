"""Root Cause served by the envkit backend.

`Greenhouse` stays the single authority on rules. This binding names the
tools, turns a `RuleError` into the error an agent sees, and maps envkit's
clock onto days: one window is one day, and `advance_day` is the only call
that spends the window's single operation. Reads, plans and tests are free in
operations, so looking never moves time.

When the player stops for any reason (calls `finish_episode`, reaches the call
limit, or the agent process ends) every remaining day still runs under the
default plan, so every run is scored at the end of the same last day.
"""
from __future__ import annotations

from typing import Annotated, Any, Optional

from envkit.core import Environment, ToolError, tool
from envkit.rng import Rng

from . import outcome, views
from .sim import Greenhouse, RuleError

BenchPlans = dict[str, dict[str, float]]


class RootCause(Environment):
    builtin_tools = ()   # the contract names its own tools; `advance_day` replaces `end_window`

    def setup(self) -> None:
        self.sim = Greenhouse(dict(self.config), self.rng.seed)
        if self.shift.windows != self.sim.horizon or self.shift.ops_per_window != 1:
            raise ValueError(f"[shift] must be windows = {self.sim.horizon}, ops_per_window = 1")

    # -- reads: free, and they change nothing ----------------------------------------

    @tool(cost=0)
    def get_rules(self) -> dict[str, Any]:
        """Every rule of the simulator: objective, units, prices, limits, the water supply, the order of a day, the response formulas with their parameters, each bench's growth potential and water demand, tests, and how the result is scored. Read this first. Free; changes nothing."""
        return views.rules(self.sim)

    @tool(cost=0)
    def get_status(self) -> dict[str, Any]:
        """This morning's readings for all three benches (EC, solution volume, crop condition, crop gained so far, pumpable volume, yesterday's plan and outcome, latest test), the day-0 lab report, notices, reserve water left, costs so far, the temperature forecast, and the plan currently in effect for today with what it will draw and cost. EC is the total of nutrients and salts; it does not show which. Free; changes nothing."""
        return views.status(self.sim)

    @tool(cost=0)
    def get_history(self, bench_id: Annotated[str, "Bench id: A, B or C."],
                    first_day: Annotated[int, "First day to return (0 = the first day)."] = 0,
                    last_day: Annotated[Optional[int], "Last day to return; omit for up to today."] = None) -> dict[str, Any]:
        """One bench's record for a range of days: each morning's sensor readings, the plan that was applied, and the outcome (growth, water transpired, overflow) with the temperature that occurred. Free; changes nothing."""
        self._bench(bench_id)
        if first_day < 0 or (last_day is not None and last_day < first_day):
            raise ToolError("first_day must be 0 or more, and last_day must not be before first_day")
        return views.history(self.sim, bench_id, first_day, last_day)

    @tool(cost=0)
    def get_tests(self) -> dict[str, Any]:
        """All tests ordered: those still at the lab (with their delivery day) and those delivered, each with the day its sample was taken and its result. Free; changes nothing."""
        return views.tests(self.sim)

    @tool(cost=0)
    def get_events(self, since_day: Annotated[int, "Return events from this day on."] = 0) -> dict[str, Any]:
        """The event log: notices, water and fertilizer used each day, plans applied, test orders and results, overflow and drops in crop condition. Free; changes nothing."""
        if since_day < 0:
            raise ToolError("since_day must be 0 or more")
        return views.events(self.sim, since_day)

    # -- requests ----------------------------------------------------------------------

    @tool(cost=0)
    def order_test(self, bench_id: Annotated[str, "Bench id: A, B or C."]) -> dict[str, Any]:
        """Order a lab composition test of one bench's solution. The sample is taken now (this morning, before today's plan) and the result, nutrients and salts in g/L at the sample time, arrives the next morning. The fee is charged once, now. One sample per bench per day."""
        return self._ask(self.sim.order_test, bench_id)

    @tool(cost=0)
    def order_water_test(self) -> dict[str, Any]:
        """Order a lab test of today's mains water. The sample is taken now and the result, salt in g/L and EC, arrives the next morning. The fee is charged once, now. One sample per day."""
        return self._ask(self.sim.order_water_test)

    @tool(cost=0)
    def submit_day_plan(self, bench_plans: Annotated[BenchPlans, "One entry per bench, all three required, e.g. {\"A\": {\"mains_l\": 230, \"reserve_l\": 0, \"fertilizer_g\": 90, \"flush_l\": 0}, \"B\": {...}, \"C\": {...}}. Amounts are for today only."]) -> dict[str, Any]:
        """Set today's plan for all three benches at once: litres of mains water and of reserve water to top up with, grams of fertilizer, and litres to flush (bleed to waste; the tank is refilled with the same volume of mains water). The whole plan is accepted or rejected together; a rejected plan changes nothing and the error says what to fix. Submitting again today replaces the earlier plan. Nothing is applied or charged until advance_day. A plan lasts one day: a day with no submitted plan runs the default plan."""
        return self._ask(self.sim.submit_plan, bench_plans)

    @tool(cost=1)
    def advance_day(self, bench_plans: Annotated[Optional[BenchPlans], "Optional: today's plan for all three benches, in the same form as submit_day_plan. Given here, it is checked and applied in one call; if it is rejected, nothing happens and the day does not move. Omitted: the plan already submitted today runs, else the default plan."] = None) -> dict[str, Any]:
        """Run today and move to the next morning. Pass today's plan as bench_plans to set and apply it in one call, or omit it to apply the plan already submitted (else the default plan). Returns what happened, tests delivered, new notices and the new status, and after the last day the final result. This is the only tool that moves time."""
        if bench_plans is not None:
            try:
                self.sim.submit_plan(bench_plans)
            except RuleError as e:
                raise ToolError(f"{e} The day was not advanced.", spend=False) from None
        report = self._ask(self.sim.advance)
        if self.sim.done:
            report["final_result"] = outcome.ledger(self.sim)
        return report

    @tool(cost=0)
    def finish_episode(self) -> dict[str, Any]:
        """Stop deciding. All remaining days still run: today under the plan in effect, later days under the default plan, and the result is taken at the end of the last day. Returns the final result. Cannot be undone."""
        self.sim.finish()
        return {"final_result": outcome.ledger(self.sim)}

    # -- engine hooks ------------------------------------------------------------------

    def on_window_end(self, window: int) -> None:
        if self.sim.day <= window:
            self.sim.advance()

    def terminated(self) -> str | None:
        return "finished" if self.sim.finished_by_player else None

    def on_finish(self) -> None:
        self.sim.finish()

    def header(self) -> dict[str, Any]:
        s = self.sim
        return {"day": s.day, "days_total": s.horizon, "reserve_left_l": round(s.reserve_l, 1),
                "plan_for_today": "none" if s.done else ("submitted" if s.plan is not None else "default")}

    def snapshot(self) -> dict[str, Any]:
        s = self.sim
        return {"day": s.day, "profit_so_far": round(outcome.profit(s), 2), "reserve_left_l": round(s.reserve_l, 1),
                "benches": {z: {"volume_l": round(b.volume, 1), "nutrient_g": round(b.nutrient, 1),
                                "salt_g": round(b.salt, 1), "condition": round(b.condition, 3),
                                "crop_gain_kg": round(b.harvest, 2)} for z, b in s.benches.items()}}

    def ledger(self) -> dict[str, float | None]:
        result = outcome.ledger(self.sim)
        if result["conservation_ok"] != 1.0:
            raise RuntimeError(f"resource conservation failed: {outcome.conservation(self.sim)}")
        return result

    # -- scripted policies -------------------------------------------------------------

    @classmethod
    def policies(cls) -> dict[str, Any]:
        from .planner import Blind, Reference
        from .policies import Attend, ECRules
        return {"reference": Reference, "blind": Blind, "ec-rules": ECRules, "absentee": Attend}

    @classmethod
    def fuzz_args(cls, tool_name: str, rng: Rng) -> dict[str, Any] | None:
        bench = rng.choice(["A", "B", "C", "D"])
        if tool_name == "order_test":
            return {"bench_id": bench}
        if tool_name == "get_history":
            return {"bench_id": bench, "first_day": rng.randint(0, 6)}
        if tool_name == "get_events":
            return {"since_day": rng.randint(0, 6)}
        if tool_name == "submit_day_plan":
            def amount(top: float) -> float:
                return 0.0 if rng.bernoulli(0.3) else round(rng.uniform(0.0, top), 1)
            return {"bench_plans": {z: {"mains_l": amount(400), "reserve_l": amount(300), "fertilizer_g": amount(400),
                                        "flush_l": amount(300)} for z in "ABC"}}
        return None

    def _bench(self, bench_id: str) -> None:
        if bench_id not in self.sim.benches:
            raise ToolError(f"unknown bench {bench_id!r}; benches are {list(self.sim.benches)}")

    @staticmethod
    def _ask(fn: Any, *args: Any) -> Any:
        try:
            return fn(*args)
        except RuleError as e:
            raise ToolError(str(e)) from None
