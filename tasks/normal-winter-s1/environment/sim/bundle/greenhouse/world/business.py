"""The business the simulator talks to: `BusinessModel` (contracts.py) over Rowan's
operations, events and ledger. Owner: Rowan (adapter written by Max to wire
operations.py into sim.py).

`build_business(market, events, crop_ids, equipment_ids, horizon_h, rng)` is the
factory `world/modules.py` calls. Everything here is plumbing: every price, lead
time, wage and event rate comes from the market and event files through
`Operations`, `Events` and `Ledger`.

Two rules decided by the contract, not by operations.py:
  * The CO2 store lives in the facility (Emre). Operations never puts CO2 in its
    stock; a delivered CO2 order is returned as a `Delivery`, which sim.py hands to
    `facility.receive_co2`. The facility file holds the store's start level, and the
    market file refuses a CO2 start stock.
  * A harvest's grade and `price_factor` come from the crop model (Lucas). The sale
    is units x the market's crop price x price_factor.

Requests that the rules refuse raise `RuleError` before anything changes.
"""
from __future__ import annotations

from typing import Any

from envkit.rng import Rng

from ..config.base import ConfigError, Range
from ..config.market import EventSpec, MarketSpec
from ..contracts import Alarm, Delivery, HarvestResult, HourEnd, LedgerEntry, Metered, RuleError, Task, TaskKind
from .events import DeliveryDelay, Events
from .ledger import EnergyPrices, Grade, Ledger
from .operations import Operations, OpsError



def _value(param: float | Range, rng: Rng, key: str) -> float:
    return param.draw(rng.stream(key)) if isinstance(param, Range) else float(param)


def _published(param: float | Range) -> float | list[float]:
    return [param.min, param.max] if isinstance(param, Range) else param


class Business:
    def __init__(self, market: MarketSpec, events: list[EventSpec], crop_ids: tuple[str, ...],
                 horizon_h: int, rng: Rng):
        self.market = market
        self.ledger = Ledger(market.start_cash_eur)
        self.ops = Operations(market, self.ledger, rng.stream("operations"))
        self.events = Events(events, horizon_h, rng.stream("events"))
        self.crop_price = {c: _value(market.crops[c].price_eur_per_unit, rng, f"market/crop_price/{c}")
                           for c in crop_ids}
        self.external_co2_eur_per_kg = _value(market.external_co2_eur_per_kg, rng, "market/external_co2")
        self.tasks: dict[str, Task] = {}          # ops task id -> contract task

    # -- the clock ---------------------------------------------------------------------

    def start_hour(self, hour: int):
        effects, alarms = [], []
        for item in self.events.due(hour):
            if isinstance(item, DeliveryDelay):
                alarms += self.ops.delay(hour, item.delay_h, item.items)
            elif isinstance(item, Alarm):
                alarms.append(item)
            else:
                effects.append(item)
        return effects, alarms

    def end_hour(self, hour: int, metered: Metered) -> HourEnd:
        prices = EnergyPrices(metered.gas_eur_per_m3, metered.import_eur_per_kwh, metered.export_eur_per_kwh)
        self.ledger.price_metered(metered, prices, self.external_co2_eur_per_kg)
        result = self.ops.end_hour(hour)
        deliveries = [Delivery(o.id, o.item, o.quantity, hour) for o in result.delivered]
        alarms = list(result.alarms)
        completed, effects = [], []
        for t in result.completed:
            task = self.tasks.pop(t.id)
            completed.append(task)
            if task.kind == "repair":
                alarms += self.events.complete_repair(hour, task.target)
                effect = self.events.outage_effect(task.target, hour + 1)
                if effect is not None:
                    effects.append(effect)
        return HourEnd(tuple(deliveries), tuple(completed), tuple(alarms), tuple(effects))

    # -- requests ----------------------------------------------------------------------

    def place_order(self, hour: int, item: str, quantity: float) -> dict[str, Any]:
        return self._ask(lambda: self.ops.place_order(hour, item, quantity).view())

    def cancel_order(self, hour: int, order_id: str) -> dict[str, Any]:
        def cancel():
            order = self.ops.cancel_order(hour, order_id)
            return {**order.view(), "cancel_fee_eur": self.market.items[order.item].cancel_fee_eur}
        return self._ask(cancel)

    def hire(self, hour: int, workers: int) -> dict[str, Any]:
        def hire():
            start = self.ops.hire(hour, workers)
            return {"hired": workers, "start_hour": start, "crew": self.ops.crew,
                    "fee_eur": self.market.staff.hiring_fee_eur * workers}
        return self._ask(hire)

    def release(self, hour: int, workers: int) -> dict[str, Any]:
        def release():
            end = self.ops.release(hour, workers)
            return {"released": workers, "paid_until_hour": end, "crew": self.ops.crew}
        return self._ask(release)

    def take_seedlings(self, hour: int, crop_id: str, count: int) -> None:
        self._ask(lambda: self.ops.take_seedlings(crop_id, count))

    def queue_task(self, hour: int, kind: TaskKind, target: str, worker_hours: float | None,
                   detail: dict[str, Any]) -> Task:
        def queue():
            hours = worker_hours
            if kind == "repair":
                quote = self.events.repair_quote(hour, target)     # pure: a refusal below changes nothing
                hours = quote.worker_hours
            if hours is None:
                raise OpsError(f"{kind} needs worker_hours")
            t = self.ops.queue(hour, kind, target, float(hours), detail)
            if kind == "repair":                                 # recorded and charged only once queued
                self.events.record_repair(hour, target)
                self.ledger.charge(hour, "repairs", quote.cost_eur, f"repair of {target}")
            task = Task(t.id, kind, target, t.worker_hours, hour, dict(detail))
            self.tasks[t.id] = task
            return task
        return self._ask(queue)

    def sell(self, hour: int, harvest: HarvestResult) -> LedgerEntry:
        grade = Grade(harvest.grade or "graded", 0.0, harvest.price_factor)
        entry, _ = self.ledger.price_harvest(hour, harvest, self.crop_price[harvest.crop_id], [grade])
        return entry or LedgerEntry(hour, "harvest_revenue", 0.0, f"{harvest.batch_id}: nothing sold")

    # -- reading -----------------------------------------------------------------------

    def cash_eur(self) -> float:
        return self.ledger.cash_eur

    def profit_eur(self) -> float:
        return self.ledger.profit_eur

    def totals(self) -> dict[str, float]:
        return self.ledger.totals()

    def view(self, hour: int, rng: Rng) -> dict[str, Any]:
        return {**self.ops.view(), "money": self.ledger.view(), **self.events.view(hour)}

    def rules(self) -> dict[str, Any]:
        m, s = self.market, self.market.staff
        return {
            "crop_prices_eur_per_unit": {c: _published(m.crops[c].price_eur_per_unit) for c in self.crop_price},
            "external_co2_eur_per_kg": _published(m.external_co2_eur_per_kg),
            "items": {i.id: {"price_eur_per_unit": _published(i.price_eur_per_unit),
                             "lead_time_h": _published(i.lead_time_h), "min_quantity": i.min_quantity,
                             "cancellable_for_h": i.dispatch_h, "cancel_fee_eur": i.cancel_fee_eur}
                      for i in m.items.values()},
            "staff": {"wage_eur_per_worker_hour": s.wage_eur_per_worker_hour,
                      "shift": f"{s.shift_start_h:02d}:00-{s.shift_start_h + s.shift_hours:02d}:00",
                      "start_crew": s.start_crew, "max_crew": s.max_crew, "hiring_fee_eur": s.hiring_fee_eur,
                      "hire_notice_days": s.hire_notice_days, "release_notice_days": s.release_notice_days},
            "events": self.events.rules(),
        }

    @staticmethod
    def _ask(fn):
        try:
            return fn()
        except OpsError as e:
            raise RuleError(str(e)) from None


def build_business(market: MarketSpec, events: list[EventSpec], crop_ids: tuple[str, ...],
                   equipment_ids: tuple[str, ...], horizon_h: int, rng: Rng) -> Business:
    missing = [c for c in crop_ids if c not in market.crops]
    if missing:
        raise ConfigError(f"{market.source}: no price in 'crops' for {missing}")
    for e in events:
        if e.kind == "equipment" and e.target not in equipment_ids:
            raise ConfigError(f"{e.source}: effect.target {e.target!r} is not facility equipment "
                              f"{list(equipment_ids)}")
    return Business(market, events, crop_ids, horizon_h, rng)
