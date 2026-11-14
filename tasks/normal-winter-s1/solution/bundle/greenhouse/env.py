"""Greenhouse Bench served by envkit: the tools (spec 5 and 14).

One window is one simulated hour. The agent plays one turn a day, at 06:00
(round 3, the daily turn decided 14 Nov 2026):

  * There are no read tools. Before its first call the agent is shown every rule
    and the first morning's briefing (status, last night, news, forecast): they are
    in the task instruction (`opening`). Every later briefing comes back in the
    result of the call that ends the day.
  * Its whole turn is one call: `submit_day(actions)`, the only tool, with at most
    `actions_per_day` actions (scenario `[env]`, 5 by default). One call is one day,
    so the server enforces one submission per day. Lists are accepted where work
    comes in numbers (harvest several batches, plant several compartments, order
    several items, set several compartments), and each counts as one action. A
    refused action changes nothing and the others still apply.
  * The call then runs the whole day (06:00-18:00 on the day settings, crew at work)
    and the night (18:00-06:00 on the night schedule), nobody acting and nothing
    stopping it.

The handover night (00:00-06:00 of day 1) runs before the first call as envkit
prelude windows, so day 1 starts at 06:00 like every other day. Hours nobody ran
(the agent quit, the call limit, a timeout or a dead agent) still run, with the
day settings and the night schedule and nobody acting, so every run is scored at
the end of the same last hour.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any, Literal, Optional, Required, TypedDict

from envkit.core import Environment, ToolError, tool
from envkit.rng import Rng
from envkit.schema import ArgumentError, params_of, validate

from . import outcome, views
from .config.loader import data_files
from .contracts import RuleError
from .world.modules import builder
from .world.sim import DUTY_START_H, Greenhouse

DEFAULT_ACTIONS_PER_DAY = 5
ACTION_NAMES = ("set_climate", "set_energy", "set_night_schedule", "place_orders", "cancel_order", "hire", "release",
                "plant", "harvest", "book_contractor")
_ScreenMode = Literal["auto", "open", "closed"]
_BufferMode = Literal["auto", "charge", "hold", "discharge"]


class OrderLine(TypedDict, total=False):
    """One line of place_orders.order_list: the item id is a value, so no tool layer can cut it."""
    item: Required[Annotated[str, "'co2_kg', 'seedlings:<crop id>' or 'part:<part id>'."]]
    quantity: Required[Annotated[float, "Amount: kg of CO2, seeds or plants, or parts."]]


class Action(TypedDict, total=False):
    """One action of submit_day: `tool` names it, the other fields are its arguments
    (see rules.turn.actions for what each takes). Fields another tool uses are refused."""
    tool: Required[Annotated[Literal["set_climate", "set_energy", "set_night_schedule", "place_orders",
                                     "cancel_order", "hire", "release", "plant", "harvest", "book_contractor"],
                             "The action."]]
    compartments: Annotated[list[str], "set_climate, set_night_schedule: compartment ids; omit for all."]
    heat_day_c: Annotated[float, "set_climate: heating setpoint while the sun is up, C."]
    heat_night_c: Annotated[float, "set_climate: heating setpoint while it is dark, C."]
    heat_c: Annotated[float, "set_night_schedule: heating setpoint, C."]
    vent_min_pct: Annotated[float, "Minimum vent opening, %."]
    vent_max_pct: Annotated[float, "Maximum vent opening, %."]
    co2_ppm: Annotated[float, "CO2 dosing target, ppm; 0 = no dosing."]
    screen: Annotated[_ScreenMode, "Energy screen mode."]
    lamp_hours: Annotated[list[int], "set_climate: hours of the day (0-23) the lamps are on."]
    lamps_on: Annotated[bool, "set_night_schedule: lamps on for the hours of this entry."]
    lamp_intensity_pct: Annotated[float, "Lamp intensity, %."]
    from_hour: Annotated[int, "set_night_schedule: clock hour the entry starts, 18-23 or 0-5."]
    copy_day: Annotated[bool, "set_night_schedule: start the entry from the day settings now."]
    remove: Annotated[bool, "set_night_schedule: remove the entry at from_hour."]
    chp_load: Annotated[float, "CHP load: 0 = off, else its minimum load to 1."]
    boiler: Annotated[Literal["auto", "off"], "set_energy: boiler mode."]
    boiler_max_fraction: Annotated[float, "Highest boiler level the thermostat may use, 0 (off) to 1."]
    buffer: Annotated[_BufferMode, "Heat buffer mode."]
    buffer_draw_max_kw: Annotated[float, "Highest heat drawn from the buffer, kW."]
    external_co2_kg_h: Annotated[float, "External CO2 purchase rate, kg/h."]
    priority: Annotated[dict[str, int], "Compartment -> priority level when supply is short."]
    heat_cap_kw: Annotated[dict[str, float], "Compartment -> heat cap, kW, when supply is short."]
    co2_cap_kg_h: Annotated[dict[str, float], "Compartment -> CO2 cap, kg/h, when supply is short."]
    orders: Annotated[dict[str, float], "place_orders: item -> quantity."]
    order_list: Annotated[list[OrderLine], "place_orders: the same as orders, as a list of {item, quantity}."]
    express: Annotated[list[str], "place_orders: items to send express."]
    order_id: Annotated[str, "cancel_order: order id."]
    workers: Annotated[int, "hire, release: number of workers."]
    areas_m2: Annotated[dict[str, float], "plant: compartment -> area, m2."]
    batch_ids: Annotated[list[str], "harvest: batch ids."]
    trade: Annotated[str, "book_contractor: trade."]
    target: Annotated[str, "book_contractor: damaged equipment id."]


class GreenhouseBench(Environment):
    builtin_tools = ()

    def setup(self) -> None:
        modules = builder(self.config)(dict(self.config), self.rng.stream("world"))
        s = self.shift
        if s.window_hours != 1 or s.ops_per_window != 1 or s.windows != modules.horizon_h:
            raise ValueError(f"[shift] must be window_hours = 1, ops_per_window = 1 and windows = "
                             f"{modules.horizon_h} (horizon_days x 24)")
        self.sim = Greenhouse(modules, self.rng.stream("sim"))
        self.handover_h = min(DUTY_START_H, modules.horizon_h)
        self.actions_per_day = int(self.config.get("actions_per_day", DEFAULT_ACTIONS_PER_DAY))
        if self.actions_per_day < 1:
            raise ValueError("[env] actions_per_day must be at least 1")

    def prelude_windows(self) -> int:
        return self.handover_h

    @classmethod
    def data_files(cls, config: dict[str, Any]) -> list[str]:
        return data_files(config)

    # -- what the player is shown: no read tools ------------------------------------------

    def opening(self) -> dict[str, Any]:
        """Shown before the first call (in the task instruction, and to scripted policies):
        every rule, and the first morning's briefing. There are no read tools."""
        return {"rules": {**views.rules(self.sim), "turn": self._turn_rules()}, "briefing": self._briefing()}

    # -- actions: each counts once toward today's limit ------------------------------------------

    def set_climate(self, compartments: Annotated[Optional[list[str]], "Compartment ids; omit for every compartment."] = None,
                    heat_day_c: Annotated[Optional[float], "Heating setpoint while the sun is up, C."] = None,
                    heat_night_c: Annotated[Optional[float], "Heating setpoint while it is dark, C."] = None,
                    vent_min_pct: Annotated[Optional[float], "Minimum vent opening, %."] = None,
                    vent_max_pct: Annotated[Optional[float], "Maximum vent opening, %."] = None,
                    co2_ppm: Annotated[Optional[float], "CO2 dosing target, ppm; 0 = no dosing."] = None,
                    screen: Annotated[Optional[Literal["auto", "open", "closed"]], "Energy screen mode."] = None,
                    lamp_hours: Annotated[Optional[list[int]], "Hours of the day (0-23) the lamps are on."] = None,
                    lamp_intensity_pct: Annotated[Optional[float], "Lamp intensity, %."] = None) -> dict[str, Any]:
        """Change the day settings (06:00-18:00) of one or more compartments; give only the fields to change. Checked against equipment limits; a rejected change changes nothing and does not count. The night runs on the night schedule (set_night_schedule), not on these."""
        changes = {k: v for k, v in {"heat_day_c": heat_day_c, "heat_night_c": heat_night_c,
                                     "vent_min_pct": vent_min_pct, "vent_max_pct": vent_max_pct, "co2_ppm": co2_ppm,
                                     "screen": screen, "lamp_hours": lamp_hours,
                                     "lamp_intensity_pct": lamp_intensity_pct}.items() if v is not None}
        if not changes:
            raise ToolError("give at least one setting to change", spend=False)
        new = self._ask(self.sim.set_climate_many, compartments, changes)
        return self._acted({"climate": {c: asdict(sp) for c, sp in new.items()}})

    def set_energy(self, chp_load: Annotated[Optional[float], "CHP load: 0 = off, else its minimum load to 1."] = None,
                   boiler: Annotated[Optional[Literal["auto", "off"]], "Boiler mode."] = None,
                   buffer: Annotated[Optional[Literal["auto", "charge", "hold", "discharge"]], "Heat buffer mode."] = None,
                   external_co2_kg_h: Annotated[Optional[float], "External CO2 purchase rate, kg/h."] = None,
                   priority: Annotated[Optional[dict[str, int]], "Compartment -> priority level when supply is short; higher is served first."] = None,
                   heat_cap_kw: Annotated[Optional[dict[str, float]], "Compartment -> heat cap, kW, when supply is short."] = None,
                   co2_cap_kg_h: Annotated[Optional[dict[str, float]], "Compartment -> CO2 cap, kg/h, when supply is short."] = None,
                   boiler_max_fraction: Annotated[Optional[float], "Highest boiler level the thermostat may use, 0 (off) to 1 (full)."] = None,
                   buffer_draw_max_kw: Annotated[Optional[float], "Highest heat the thermostat may draw from the buffer, kW."] = None) -> dict[str, Any]:
        """Change the energy centre's day settings (06:00-18:00); give only the fields to change; maps are merged into the current ones. The thermostat takes heat from the CHP at its load, then the buffer up to its draw cap, then the boiler up to its level. A rejected change changes nothing and does not count."""
        changes = _energy_changes(chp_load, boiler, buffer, external_co2_kg_h, priority, heat_cap_kw, co2_cap_kg_h,
                                  boiler_max_fraction, buffer_draw_max_kw)
        if not changes:
            raise ToolError("give at least one setting to change", spend=False)
        return self._acted({"energy": asdict(self._ask(self.sim.set_energy, changes))})

    def set_night_schedule(
            self, from_hour: Annotated[int, "Clock hour the entry starts: 18-23 or 0-5. It applies until the next entry."],
            compartments: Annotated[Optional[list[str]], "Compartments for the climate fields; omit for every compartment."] = None,
            copy_day: Annotated[Optional[bool], "Start the entry from your day settings as they are now."] = None,
            remove: Annotated[Optional[bool], "Remove the entry at from_hour (not the 18:00 one)."] = None,
            heat_c: Annotated[Optional[float], "Heating setpoint, C."] = None,
            vent_min_pct: Annotated[Optional[float], "Minimum vent opening, %."] = None,
            vent_max_pct: Annotated[Optional[float], "Maximum vent opening, %."] = None,
            co2_ppm: Annotated[Optional[float], "CO2 dosing target, ppm; 0 = no dosing."] = None,
            screen: Annotated[Optional[Literal["auto", "open", "closed"]], "Energy screen mode."] = None,
            lamps_on: Annotated[Optional[bool], "Lamps on for the hours of this entry."] = None,
            lamp_intensity_pct: Annotated[Optional[float], "Lamp intensity, %."] = None,
            chp_load: Annotated[Optional[float], "CHP load: 0 = off, else its minimum load to 1."] = None,
            boiler_max_fraction: Annotated[Optional[float], "Highest boiler level the thermostat may use, 0 (off) to 1."] = None,
            buffer: Annotated[Optional[Literal["auto", "charge", "hold", "discharge"]], "Heat buffer mode."] = None,
            buffer_draw_max_kw: Annotated[Optional[float], "Highest heat drawn from the buffer, kW."] = None,
            external_co2_kg_h: Annotated[Optional[float], "External CO2 purchase rate, kg/h."] = None,
            priority: Annotated[Optional[dict[str, int]], "Compartment -> priority level when supply is short."] = None,
            heat_cap_kw: Annotated[Optional[dict[str, float]], "Compartment -> heat cap, kW, when supply is short."] = None,
            co2_cap_kg_h: Annotated[Optional[dict[str, float]], "Compartment -> CO2 cap, kg/h, when supply is short."] = None) -> dict[str, Any]:
        """Set one entry of the night schedule (18:00-06:00): fixed values from from_hour until the next entry, every night until you change it. Nobody acts at night: there are no conditions or triggers, only these values. The entry starts from what is in force at that hour (or from your day settings with copy_day) and the fields you give change it. At hour 0 the schedule is the facility's baseline. Returns the whole schedule."""
        climate = {k: v for k, v in {"heat_day_c": heat_c, "heat_night_c": heat_c, "vent_min_pct": vent_min_pct,
                                     "vent_max_pct": vent_max_pct, "co2_ppm": co2_ppm, "screen": screen,
                                     "lamp_intensity_pct": lamp_intensity_pct}.items() if v is not None}
        if lamps_on is not None:
            climate["lamp_hours"] = list(range(24)) if lamps_on else []
        energy = _energy_changes(chp_load, None, buffer, external_co2_kg_h, priority, heat_cap_kw, co2_cap_kg_h,
                                 boiler_max_fraction, buffer_draw_max_kw)
        if "boiler_max_fraction" in energy:          # a level above 0 makes the boiler available
            energy["boiler"] = "auto" if energy["boiler_max_fraction"] > 0 else "off"
        if not (climate or energy or copy_day or remove):
            raise ToolError("give copy_day, remove or at least one setting", spend=False)
        self._ask(self.sim.set_night_entry, from_hour, compartments, climate, energy, bool(copy_day), bool(remove))
        return self._acted({"night_schedule": views.night_schedule(self.sim)})

    def place_orders(self, orders: Annotated[Optional[dict[str, float]], "Item -> quantity: 'co2_kg' (kg), 'seedlings:<crop id>' (seeds or plants), 'part:<part id>' (parts). 'seedlings/<crop id>' is the same item."] = None,
                     order_list: Annotated[Optional[list[OrderLine]], "The same as `orders`, as a list of {item, quantity}. Use it if your tool layer cuts or changes ':' in object keys."] = None,
                     express: Annotated[Optional[list[str]], "Items from `orders` to send express, at a higher price, where offered."] = None) -> dict[str, Any]:
        """Order stock. Minimum quantities and lead times apply (the rules); the lead time is fixed when you order, and is longer while a storm surge lasts. Each item is ordered on its own: the result lists what was ordered and what was refused. Charged on delivery. Unused parts are worth nothing at the end."""
        orders = dict(orders or {})
        for line in order_list or ():
            orders[line["item"]] = orders.get(line["item"], 0.0) + float(line["quantity"])
        if not orders:
            raise ToolError("give at least one item in orders or order_list", spend=False)
        fix = getattr(getattr(self.sim.business, "ops", None), "item_id", lambda k: k)   # the test fakes have no ops
        orders = {fix(k): v for k, v in orders.items()}
        rush = {fix(k) for k in (express or ())}
        unknown = sorted(rush - set(orders))
        if unknown:
            raise ToolError(f"express names items that are not in orders: {unknown}", spend=False)
        return self._each(orders.items(), lambda kv: self.sim.business.place_order(
            self.sim.hour, kv[0], kv[1], kv[0] in rush), key=lambda kv: kv[0])

    def cancel_order(self, order_id: Annotated[str, "Order id."]) -> dict[str, Any]:
        """Cancel an order that has not been dispatched; a fee may apply (the rules)."""
        return self._acted(self._ask(self.sim.business.cancel_order, self.sim.hour, order_id))

    def hire(self, workers: Annotated[int, "Number of workers."]) -> dict[str, Any]:
        """Hire workers. They start after the notice period; a hiring fee and daily wages apply (the rules)."""
        return self._acted(self._ask(self.sim.business.hire, self.sim.hour, workers))

    def release(self, workers: Annotated[int, "Number of workers."]) -> dict[str, Any]:
        """Release workers after the notice period (the rules)."""
        return self._acted(self._ask(self.sim.business.release, self.sim.hour, workers))

    def plant(self, areas_m2: Annotated[dict[str, float], "Compartment -> area to plant, m2 (at most its free area)."]) -> dict[str, Any]:
        """Queue planting of each compartment's crop. Uses seedlings (seed) from stock now and worker-hours when the crew does it. A compartment is refused if too few days remain for its crop to finish; the result lists what was queued and what was refused."""
        if not areas_m2:
            raise ToolError("give at least one compartment", spend=False)
        return self._each(areas_m2.items(), lambda kv: asdict(self.sim.plant(kv[0], kv[1])), key=lambda kv: kv[0])

    def harvest(self, batch_ids: Annotated[list[str], "Batch ids to harvest."]) -> dict[str, Any]:
        """Queue the harvest of each batch. It uses worker-hours and is sold when the crew does it. Produce below the crop's minimum sellable weight sells for nothing. The result lists what was queued and what was refused."""
        if not batch_ids:
            raise ToolError("give at least one batch id", spend=False)
        return self._each(dict.fromkeys(batch_ids), lambda b: asdict(self.sim.harvest(b)), key=lambda b: b)

    def book_contractor(self, trade: Annotated[str, "Trade, e.g. 'glazier' or 'heating_installer' (the rules)."],
                        target: Annotated[str, "Damaged equipment id (the briefing), e.g. 'A.glass' or 'boiler'."]) -> dict[str, Any]:
        """Book a contractor to repair damaged equipment. The visit happens in the first day-shift hour after the response time in which the parts the job needs are on site (order them with place_orders); call-out, hourly rate and parts are charged then. Damage stays until a repair is done. Response times are longer while a storm surge lasts (the rules)."""
        return self._acted({"booking": self._ask(self.sim.book_contractor, trade, target)})

    # -- the end of the day ------------------------------------------------------------------

    @tool(cost=1)
    def submit_day(self, actions: Annotated[list[Action], "Today's actions, applied in order; at most actions_per_day of them. An empty list does nothing today."]) -> dict[str, Any]:
        """Submit today's turn: your actions for today, in one call. They are applied in order; each one that is refused changes nothing and the rest still apply. Then the day (06:00-18:00 on the day settings, the crew at work) and the night (18:00-06:00 on the night schedule) run with nobody acting and nothing stopping it. Returns what each action did and tomorrow morning's briefing. This is the only tool: one call is one day."""
        if len(actions) > self.actions_per_day:
            raise ToolError(f"at most {self.actions_per_day} actions a day; got {len(actions)}. Nothing was done; "
                            "submit the day again with fewer.", spend=False)
        results = []
        for action in actions:
            name = action["tool"]
            args = {k: v for k, v in action.items() if k != "tool"}
            try:
                kwargs = validate(params_of(getattr(type(self), name)), args, strict=self.strict_arguments)
                results.append({"tool": name, "ok": True, "result": getattr(self, name)(**kwargs)})
            except (ArgumentError, ToolError) as e:
                results.append({"tool": name, "ok": False, "error": str(e)})
        return {"results": results, **self._end_day()}

    # -- engine hooks ----------------------------------------------------------------------

    def on_window_end(self, window: int) -> None:
        if self.sim.hour <= window and not self.sim.done:
            if window >= self.handover_h:          # the handover night is nobody's absence
                self.sim.go_unattended()
            self.sim.run_hour()

    def terminated(self) -> str | None:
        if self.sim.bankrupt_hour is not None:
            return "bankrupt"
        return None

    def on_finish(self) -> None:
        self.sim.go_unattended()
        while not self.sim.done:
            self.sim.run_hour()

    def header(self) -> dict[str, Any]:
        c = views.clock(self.sim)
        return {"hour": c["hour"], "day": c["day"], "time": c["time"], "hours_left": c["hours_left"],
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
        # The real business also reports money by category and failure-mode evidence
        # (`fm_*`), and refuses a run whose money does not balance. None of it is scored:
        # the score reads `profit_eur` only. The test fakes have no ledger to read.
        if all(hasattr(s.business, part) for part in ("ledger", "ops", "events")):
            evidence = outcome.ledger(s)
            out.update({k: v for k, v in evidence.items() if k != "profit_eur"})
        out["bankrupt"] = float(s.bankrupt_hour is not None)
        return out

    # -- the daily turn ----------------------------------------------------------------------

    def _turn_rules(self) -> dict[str, Any]:
        return {"actions_per_day": self.actions_per_day,
                "rule": (f"One turn a day at 06:00: one submit_day call with at most {self.actions_per_day} "
                         "actions, after reading the morning briefing. A list of harvests, plantings or orders is "
                         "one action. A refused action changes nothing and the others still apply. The call then "
                         "runs the day and the night with nobody acting, and returns the next morning's briefing."),
                "actions": {name: (getattr(GreenhouseBench, name).__doc__ or "").strip()
                            for name in ACTION_NAMES}}

    def _briefing(self) -> dict[str, Any]:
        return views.briefing(self.sim, self.actions_per_day)

    @staticmethod
    def _acted(result: dict[str, Any]) -> dict[str, Any]:
        return result

    def _each(self, items: Any, fn: Any, key: Any) -> dict[str, Any]:
        """Apply `fn` to each entry; one action if any entry was accepted. Every entry is
        checked before it changes anything, so a refused entry changes nothing."""
        done, refused = {}, {}
        for item in items:
            try:
                done[key(item)] = fn(item)
            except RuleError as e:
                refused[key(item)] = str(e)
        if not done:
            raise ToolError("nothing was accepted: " + "; ".join(f"{k}: {v}" for k, v in refused.items()),
                            spend=False)
        return self._acted({"accepted": done, "refused": refused})

    def _end_day(self) -> dict[str, Any]:
        report = self._ask(self.sim.end_shift, spend=False)
        self.close_windows(max(1, report["hours_run"]))
        if self.sim.done:
            return {"final_result": self._result()}
        return {"briefing": self._briefing()}

    def _result(self) -> dict[str, Any]:
        return {"profit_eur": round(self.sim.business.profit_eur(), 2), "totals": self.sim.business.totals(),
                "harvests": len(self.sim.harvests)}

    # -- scripted policies -------------------------------------------------------------------

    @classmethod
    def policies(cls) -> dict[str, Any]:
        """The ladder of spec 9. Every policy plays through the tools only. `absentee`
        replaces envkit's, which ends windows with a tool the greenhouse does not offer."""
        from .policies.common import Absentee
        from .policies.exploiter import EXPLOITS
        from .policies.naive import Naive
        from .policies.reference import Reference
        from .policies.rule_based import RuleBased
        return {"absentee": Absentee, "naive": Naive, "rule-based": RuleBased, "reference": Reference,
                **EXPLOITS}

    @classmethod
    def fuzz_args(cls, tool_name: str, rng: Rng) -> dict[str, Any] | None:
        return None

    @staticmethod
    def _ask(fn: Any, *args: Any, spend: bool = True) -> Any:
        try:
            return fn(*args)
        except RuleError as e:
            raise ToolError(str(e), spend=spend) from None


def _energy_changes(chp_load, boiler, buffer, external_co2_kg_h, priority, heat_cap_kw, co2_cap_kg_h,
                    boiler_max_fraction, buffer_draw_max_kw) -> dict[str, Any]:
    return {k: v for k, v in {"chp_load": chp_load, "boiler": boiler, "buffer": buffer,
                              "external_co2_kg_h": external_co2_kg_h, "priority": priority,
                              "heat_cap_kw": heat_cap_kw, "co2_cap_kg_h": co2_cap_kg_h,
                              "boiler_max_fraction": boiler_max_fraction,
                              "buffer_draw_max_kw": buffer_draw_max_kw}.items() if v is not None}
