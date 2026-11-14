"""Greenhouse Bench served by envkit: the tools (spec 5).

One window is one simulated hour. `advance(hours)` is the only tool that costs
an operation and moves time: it runs the hours itself, stops after an hour with
a new alarm, then asks the engine to close that many windows. Every other tool
is free and never moves time.

Hours that nobody ran (after `finish_episode`, the call limit, a timeout or a
dead agent) still run, with the standing settings and nobody acting, so every
run is scored at the end of the same last hour.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any, Literal, Optional

from envkit.core import Environment, ToolError, tool
from envkit.rng import Rng

from . import views
from .config.loader import data_files
from .contracts import RuleError
from .world.modules import builder
from .world.sim import Greenhouse


class GreenhouseBench(Environment):
    builtin_tools = ()

    def setup(self) -> None:
        modules = builder(self.config)(dict(self.config), self.rng.stream("world"))
        s = self.shift
        if s.window_hours != 1 or s.ops_per_window != 1 or s.windows != modules.horizon_h:
            raise ValueError(f"[shift] must be window_hours = 1, ops_per_window = 1 and windows = "
                             f"{modules.horizon_h} (horizon_days x 24)")
        self.sim = Greenhouse(modules, self.rng.stream("sim"))

    @classmethod
    def data_files(cls, config: dict[str, Any]) -> list[str]:
        return data_files(config)

    # -- reads: free, change nothing ----------------------------------------------------

    @tool(cost=0)
    def get_rules(self) -> dict[str, Any]:
        """Every rule: the objective, the clock, the facility's mechanisms and equipment limits, each crop's growth, stress, harvest and market rules, prices, lead times, wages, event types and rates, and the published ranges of hidden facility parameters. Read this first. Free; changes nothing."""
        return views.rules(self.sim)

    @tool(cost=0)
    def get_status(self) -> dict[str, Any]:
        """The clock, the latest sensor readings per compartment and the energy centre, the standing settings, equipment faults, free area, stock, open orders, staff, task queue, money, alarms of the last 24 hours, and every batch with its estimate. Free; changes nothing."""
        return views.status(self.sim)

    @tool(cost=0)
    def get_batches(self) -> dict[str, Any]:
        """Every batch: crop, compartment, area, age, status, whether a harvest is queued, and its estimated weight, days to ready and quality. Free; changes nothing."""
        return views.batches(self.sim)

    @tool(cost=0)
    def get_forecast(self, hours: Annotated[int, "Hours ahead, 1 to 72."] = 72) -> dict[str, Any]:
        """Weather and energy-price forecast from now. Forecast error grows with lead time. Free; changes nothing."""
        if not 1 <= hours <= 72:
            raise ToolError("hours must be 1 to 72", spend=False)
        return views.forecast(self.sim, hours)

    @tool(cost=0)
    def get_history(self, compartment: Annotated[str, "Compartment id."],
                    from_hour: Annotated[int, "First hour."] = 0,
                    to_hour: Annotated[Optional[int], "Last hour; omit for the latest."] = None) -> dict[str, Any]:
        """Hourly sensor readings, settings and metered energy for one compartment, at most 168 hours per call. Free; changes nothing."""
        self._ask(self.sim._compartment, compartment)
        if from_hour < 0 or (to_hour is not None and to_hour < from_hour):
            raise ToolError("from_hour must be 0 or more and to_hour not before it", spend=False)
        return views.history(self.sim, compartment, from_hour, to_hour)

    # -- standing settings ---------------------------------------------------------------

    @tool(cost=0)
    def set_climate(self, compartment: Annotated[str, "Compartment id."],
                    heat_day_c: Annotated[Optional[float], "Heating setpoint by day, C."] = None,
                    heat_night_c: Annotated[Optional[float], "Heating setpoint by night, C."] = None,
                    vent_min_pct: Annotated[Optional[float], "Minimum vent opening, %."] = None,
                    vent_max_pct: Annotated[Optional[float], "Maximum vent opening, %."] = None,
                    co2_ppm: Annotated[Optional[float], "CO2 dosing target, ppm; 0 = no dosing."] = None,
                    screen: Annotated[Optional[Literal["auto", "open", "closed"]], "Energy screen mode."] = None,
                    lamp_hours: Annotated[Optional[list[int]], "Hours of the day (0-23) the lamps are on."] = None,
                    lamp_intensity_pct: Annotated[Optional[float], "Lamp intensity, %."] = None) -> dict[str, Any]:
        """Change a compartment's standing climate setpoints. Give only the fields to change; the rest stay. Checked against equipment limits; a rejected change changes nothing. Takes effect from the next sub-step."""
        changes = {k: v for k, v in {"heat_day_c": heat_day_c, "heat_night_c": heat_night_c,
                                     "vent_min_pct": vent_min_pct, "vent_max_pct": vent_max_pct, "co2_ppm": co2_ppm,
                                     "screen": screen, "lamp_hours": lamp_hours,
                                     "lamp_intensity_pct": lamp_intensity_pct}.items() if v is not None}
        if not changes:
            raise ToolError("give at least one setting to change", spend=False)
        new = self._ask(self.sim.set_climate, compartment, changes)
        return {"compartment": compartment, "climate": asdict(new)}

    @tool(cost=0)
    def set_energy(self, chp_load: Annotated[Optional[float], "CHP load: 0 = off, else its minimum load to 1."] = None,
                   boiler: Annotated[Optional[Literal["auto", "off"]], "Boiler mode."] = None,
                   buffer: Annotated[Optional[Literal["auto", "charge", "hold", "discharge"]], "Heat buffer mode."] = None,
                   external_co2_kg_h: Annotated[Optional[float], "External CO2 purchase rate, kg/h."] = None,
                   priority: Annotated[Optional[dict[str, int]], "Compartment -> priority level when supply is short; higher is served first."] = None,
                   heat_cap_kw: Annotated[Optional[dict[str, float]], "Compartment -> heat cap, kW, when supply is short."] = None,
                   co2_cap_kg_h: Annotated[Optional[dict[str, float]], "Compartment -> CO2 cap, kg/h, when supply is short."] = None) -> dict[str, Any]:
        """Change the energy centre's standing settings. Give only the fields to change; maps are merged into the current ones. Checked against equipment limits; a rejected change changes nothing."""
        changes = {k: v for k, v in {"chp_load": chp_load, "boiler": boiler, "buffer": buffer,
                                     "external_co2_kg_h": external_co2_kg_h, "priority": priority,
                                     "heat_cap_kw": heat_cap_kw, "co2_cap_kg_h": co2_cap_kg_h}.items()
                   if v is not None}
        if not changes:
            raise ToolError("give at least one setting to change", spend=False)
        return {"energy": asdict(self._ask(self.sim.set_energy, changes))}

    # -- operations ----------------------------------------------------------------------

    @tool(cost=0)
    def place_order(self, item: Annotated[str, "'co2_kg' or 'seedlings:<crop id>'."],
                    quantity: Annotated[float, "Amount: kg of CO2, or number of seedlings."]) -> dict[str, Any]:
        """Order stock. Minimum quantities and lead times apply (get_rules); the result shows the expected arrival. Charged on delivery."""
        return self._ask(self.sim.business.place_order, self.sim.hour, item, quantity)

    @tool(cost=0)
    def cancel_order(self, order_id: Annotated[str, "Order id."]) -> dict[str, Any]:
        """Cancel an order that has not been dispatched; a fee may apply (get_rules)."""
        return self._ask(self.sim.business.cancel_order, self.sim.hour, order_id)

    @tool(cost=0)
    def hire(self, workers: Annotated[int, "Number of workers."]) -> dict[str, Any]:
        """Hire workers. They start after the notice period; a hiring fee and daily wages apply (get_rules)."""
        return self._ask(self.sim.business.hire, self.sim.hour, workers)

    @tool(cost=0)
    def release(self, workers: Annotated[int, "Number of workers."]) -> dict[str, Any]:
        """Release workers after the notice period (get_rules)."""
        return self._ask(self.sim.business.release, self.sim.hour, workers)

    @tool(cost=0)
    def plant(self, compartment: Annotated[str, "Compartment id."],
              area_m2: Annotated[float, "Area to plant, m2; at most the free area."]) -> dict[str, Any]:
        """Queue planting of the compartment's crop. Uses seedlings from stock now and worker-hours when the task runs. Refused if too few days remain for the crop to finish."""
        return {"task": asdict(self._ask(self.sim.plant, compartment, area_m2))}

    @tool(cost=0)
    def harvest(self, batch_id: Annotated[str, "Batch id."]) -> dict[str, Any]:
        """Queue a batch's harvest. It uses worker-hours and is sold when the task runs. Produce below the crop's minimum sellable weight sells for nothing."""
        return {"task": asdict(self._ask(self.sim.harvest, batch_id))}

    @tool(cost=0)
    def repair(self, equipment_id: Annotated[str, "Equipment id with a fault (get_status)."]) -> dict[str, Any]:
        """Queue a repair of faulty equipment. Costs money now and worker-hours when it runs (get_rules)."""
        return {"task": asdict(self._ask(self.sim.repair, equipment_id))}

    # -- time ----------------------------------------------------------------------------

    @tool(cost=1)
    def advance(self, hours: Annotated[int, "Hours to run, 1 to 24."]) -> dict[str, Any]:
        """Run time forward with the standing settings. Stops at the end of the first hour in which a new alarm appears (equipment fault, delivery, frost risk, batch ready, low stock, ...). Returns what happened and the new status. The only tool that moves time."""
        report = self._ask(self.sim.advance, hours, spend=False)
        self.close_windows(max(1, report["hours_run"]))
        report["status"] = views.status(self.sim)
        if self.sim.done:
            report["final_result"] = self._result()
        return report

    @tool(cost=0)
    def finish_episode(self) -> dict[str, Any]:
        """Stop deciding. All remaining hours run with the current settings and nobody acting (no orders, planting or harvests), and the result is taken at the end of the last hour. Cannot be undone."""
        self.sim.finish()
        return {"final_result": self._result()}

    # -- engine hooks ----------------------------------------------------------------------

    def on_window_end(self, window: int) -> None:
        if self.sim.hour <= window and not self.sim.done:
            self.sim.go_unattended()
            self.sim.run_hour()

    def terminated(self) -> str | None:
        return "finished" if self.sim.finished_by_player else None

    def on_finish(self) -> None:
        self.sim.go_unattended()
        while not self.sim.done:
            self.sim.run_hour()

    def header(self) -> dict[str, Any]:
        c = views.clock(self.sim)
        return {"hour": c["hour"], "day": c["day"], "hours_left": c["hours_left"],
                "cash_eur": round(self.sim.business.cash_eur(), 2)}

    def snapshot(self) -> dict[str, Any]:
        s = self.sim
        return {"hour": s.hour, "profit_eur": round(s.business.profit_eur(), 2), "unattended": s.unattended,
                "batches": {b.id: {"status": b.status, **{k: round(v, 3) for k, v in b.model_state.items()}}
                            for b in s.batches.values()}}

    def ledger(self) -> dict[str, float | None]:
        s = self.sim
        out: dict[str, float | None] = {"profit_eur": round(s.business.profit_eur(), 4)}
        out.update({f"eur_{k}": round(v, 4) for k, v in sorted(s.business.totals().items())})
        out["harvests"] = float(len(s.harvests))
        out["unsellable_harvests"] = float(sum(not h["sellable"] for h in s.harvests))
        return out

    def _result(self) -> dict[str, Any]:
        return {"profit_eur": round(self.sim.business.profit_eur(), 2), "totals": self.sim.business.totals(),
                "harvests": len(self.sim.harvests)}

    # -- scripted policies -------------------------------------------------------------------

    @classmethod
    def policies(cls) -> dict[str, Any]:
        return {}

    @classmethod
    def fuzz_args(cls, tool_name: str, rng: Rng) -> dict[str, Any] | None:
        if tool_name == "advance":
            return {"hours": rng.randint(1, 24)}
        return None

    @staticmethod
    def _ask(fn: Any, *args: Any, spend: bool = True) -> Any:
        try:
            return fn(*args)
        except RuleError as e:
            raise ToolError(str(e), spend=spend) from None
