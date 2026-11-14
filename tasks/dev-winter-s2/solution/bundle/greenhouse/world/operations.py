"""Operations: stock, orders, staff and tasks that need worker-hours. Owner: Rowan.

`world/sim.py` (Max) holds one `Operations` and calls `end_hour(hour)` at the end
of every simulated hour. Agent requests (`place_order`, `cancel_order`, `hire`,
`release`, `queue`) raise `OpsError` before touching any state, so a refused
request changes nothing and costs nothing.

Rules, all values from the market file:
  * Orders: at least the item's minimum quantity; arrive `lead_time_h` after they
    are placed; charged on arrival; cancellable (for a fee) until `dispatch_h`
    has passed. A late-delivery event pushes back the open order due soonest.
  * Spare parts (`part:<id>`, category "parts") are ordered like any item and held in
    stock until a contractor visit uses them (world/contractors.py); unused parts are
    worth nothing at the end. The lead time is fixed when the order is placed: the
    item's surge lead time while a regional storm surge lasts (`surge(hour)` returns
    the hour the surge ends, or None), else the normal one. `express=True` shortens it
    to `express_lead_fraction` of whichever applies, for the express price: the
    category is charged the normal price and "express" the difference.
  * CO2 (items of category "co2") is delivered into the facility's store, which
    the facility owns (contracts.py): it never enters this stock. The caller
    hands each delivered CO2 order to the facility.
  * Staff: wages are charged every hour from hour 0, whether or not anyone acts
    (crew x wage x shift hours / 24 per hour). Each worker gives one worker-hour
    per shift hour. Hiring is charged at once and the worker starts after the
    notice; a released worker is paid until the notice has passed.
  * Tasks (plant, harvest, repair) use worker-hours in queue order during shift
    hours. A task that does not get enough hours waits for the next shift hour.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

from envkit.rng import Rng

from ..config.base import Range
from ..config.market import ItemSpec, MarketSpec
from ..contracts import Alarm
from .ledger import Ledger

TASK_KINDS = ("plant", "harvest", "repair")


class OpsError(ValueError):
    """A request the rules do not allow. Nothing was changed or charged."""


@dataclass
class Order:
    id: str
    item: str
    quantity: float
    placed_hour: int
    eta_hour: int
    dispatch_hour: int                  # cancellable while hour < dispatch_hour
    status: str = "open"                # open | delivered | cancelled
    delayed_h: int = 0
    delivered_hour: int | None = None
    express: bool = False

    def view(self) -> dict[str, Any]:
        return {"order_id": self.id, "item": self.item, "quantity": self.quantity, "placed_hour": self.placed_hour,
                "expected_arrival_hour": self.eta_hour, "cancellable_until_hour": self.dispatch_hour,
                "status": self.status, "delayed_h": self.delayed_h, "express": self.express}


@dataclass
class Task:
    id: str
    kind: str
    target: str                         # batch id, compartment id or equipment id
    worker_hours: float
    queued_hour: int
    payload: dict[str, Any] = field(default_factory=dict)
    done_hours: float = 0.0
    done_hour: int | None = None
    first_work_hour: int | None = None

    def view(self) -> dict[str, Any]:
        return {"task_id": self.id, "kind": self.kind, "target": self.target, "queued_hour": self.queued_hour,
                "worker_hours_needed": self.worker_hours, "worker_hours_done": round(self.done_hours, 2),
                "status": "done" if self.done_hour is not None else "waiting"}


@dataclass
class HourResult:
    alarms: list[Alarm]
    completed: list[Task]
    delivered: list[Order]


def _value(param: float | Range, rng: Rng, key: str) -> float:
    """A fixed number, or a per-seed draw for a range (stream named after its key)."""
    return param.draw(rng.stream(key)) if isinstance(param, Range) else float(param)


class Operations:
    def __init__(self, market: MarketSpec, ledger: Ledger, rng: Rng,
                 surge: Callable[[int], int | None] | None = None):
        self.market, self.ledger = market, ledger
        self.surge = surge                          # hour -> hour the regional surge ends (None = no storm yet)
        self.items: dict[str, ItemSpec] = market.items
        # Per-seed lead times and prices (published ranges, hidden draws), fixed at the start.
        self.lead_time_h = {i: max(1, round(_value(s.lead_time_h, rng, f"market/lead_time/{i}"))) for i, s in self.items.items()}
        self.unit_price = {i: _value(s.price_eur_per_unit, rng, f"market/price/{i}") for i, s in self.items.items()}
        # Surge lead time: the same draw as the normal one when the file gives no separate figure.
        self.surge_lead_time_h = {
            i: self.lead_time_h[i] if s.surge_lead_time_h == s.lead_time_h
            else max(1, round(_value(s.surge_lead_time_h, rng, f"market/surge_lead_time/{i}")))
            for i, s in self.items.items()}
        self.express_price = {i: _value(s.express_price_eur_per_unit, rng, f"market/express_price/{i}")
                              for i, s in self.items.items() if s.express_price_eur_per_unit is not None}
        self.stock: dict[str, float] = {i: float(market.start_stock.get(i, 0.0)) for i, spec in self.items.items()
                                        if spec.category != "co2"}
        self.orders: list[Order] = []
        s = market.staff
        self.crew = s.start_crew                    # paid and working now
        self.arrivals: list[tuple[int, int]] = []   # (start hour, workers)
        self.departures: list[tuple[int, int]] = [] # (last paid hour + 1, workers): paid but not working
        self.leaving = 0                            # released, still paid, no longer working
        self.tasks: list[Task] = []
        self._low: set[str] = set()                 # items currently below their warning level
        # Evidence for failure modes.
        self.late_deliveries = 0
        self.task_wait_h: dict[str, float] = {k: 0.0 for k in TASK_KINDS}

    # -- orders ------------------------------------------------------------------------

    def in_surge(self, hour: int) -> bool:
        until = self.surge(hour) if self.surge is not None else None
        return until is not None and hour < until

    def lead_for(self, hour: int, item: str, express: bool = False) -> int:
        """The lead time an order placed at `hour` gets, fixed at that moment."""
        spec = self.items[item]
        lead = self.surge_lead_time_h[item] if self.in_surge(hour) else self.lead_time_h[item]
        if express:
            lead = max(1, round(spec.express_lead_fraction * lead))
        return lead

    def item_id(self, item: str) -> str:
        """The item id an order means. Some tool-call serializers escape or replace the
        ':' in 'seedlings:<crop>' (Gemini via OpenCode sent 'seedlings\\u003a<crop>'), so
        '\\u003a', '/' and '.' are read as ':'. An id that names no item is left as is."""
        if item in self.items:
            return item
        for sep in ("\\u003a", "\\u003A", "/", "."):
            fixed = item.replace(sep, ":")
            if fixed in self.items:
                return fixed
        return item

    def place_order(self, hour: int, item: str, quantity: float, express: bool = False) -> Order:
        item = self.item_id(item)
        spec = self.items.get(item)
        if spec is None:
            hint = (" If ':' was cut from your object keys, send order_list=[{item, quantity}] instead."
                    if item in {i.split(":")[0] for i in self.items} else "")
            raise OpsError(f"unknown item {item!r}; items are {list(self.items)}.{hint} Nothing was ordered.")
        if isinstance(quantity, bool) or not isinstance(quantity, (int, float)) or not math.isfinite(quantity):
            raise OpsError("quantity must be a finite number. Nothing was ordered.")
        if quantity < spec.min_quantity or quantity <= 0:
            raise OpsError(f"{item}: the minimum order is {spec.min_quantity:g}; got {quantity:g}. Nothing was ordered.")
        if express and spec.express_price_eur_per_unit is None:
            raise OpsError(f"{item} has no express option. Nothing was ordered.")
        order = Order(f"O{len(self.orders) + 1:03d}", item, float(quantity), hour,
                      hour + self.lead_for(hour, item, express), hour + spec.dispatch_h, express=bool(express))
        self.orders.append(order)
        return order

    def cancel_order(self, hour: int, order_id: str) -> Order:
        order = self._order(order_id)
        if order.status != "open":
            raise OpsError(f"order {order_id} is {order.status}; only open orders can be cancelled.")
        if hour >= order.dispatch_hour:
            raise OpsError(f"order {order_id} was dispatched at hour {order.dispatch_hour}; it can no longer be cancelled.")
        order.status = "cancelled"
        self.ledger.charge(hour, "orders", self.items[order.item].cancel_fee_eur, f"cancelled {order.id}")
        return order

    def delay(self, hour: int, delay_h: int, items: tuple[str, ...] = ()) -> list[Alarm]:
        """A late-delivery event: the open order due soonest (of the given items) arrives later."""
        open_orders = [o for o in self.orders if o.status == "open" and o.eta_hour > hour
                       and (not items or o.item in items)]
        if not open_orders:
            return []
        order = min(open_orders, key=lambda o: (o.eta_hour, o.id))
        order.eta_hour += delay_h
        order.delayed_h += delay_h
        self.late_deliveries += 1
        return [Alarm(hour, "delivery", order.id, f"Supplier reports order {order.id} ({order.quantity:g} {order.item}) "
                                                  f"is late: now expected at hour {order.eta_hour}.")]

    # -- stock -------------------------------------------------------------------------

    def take_seedlings(self, crop_id: str, plants: float) -> None:
        item = f"seedlings:{crop_id}"
        have = self.stock.get(item, 0.0)
        if item not in self.items:
            raise OpsError(f"no seedlings item for crop {crop_id!r}.")
        if plants > have + 1e-9:
            raise OpsError(f"planting needs {plants:g} {crop_id} seedlings but {have:g} are in stock. Nothing was planted.")
        self.stock[item] = have - plants

    def take_parts(self, item: str, count: float) -> None:
        """A contractor visit uses parts from stock."""
        have = self.stock.get(item, 0.0)
        if item not in self.items or self.items[item].category != "parts":
            raise OpsError(f"{item!r} is not a spare part.")
        if count > have + 1e-9:
            raise OpsError(f"the job needs {count:g} {item} but {have:g} are in stock.")
        self.stock[item] = have - count

    # -- staff -------------------------------------------------------------------------

    def hire(self, hour: int, workers: int) -> int:
        s = self.market.staff
        if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
            raise OpsError("workers must be a whole number of at least 1. Nobody was hired.")
        committed = self.crew + sum(n for _, n in self.arrivals)
        if committed + workers > s.max_crew:
            raise OpsError(f"the crew cannot exceed {s.max_crew}; {committed} are working or due. Nobody was hired.")
        start = hour + 24 * s.hire_notice_days
        self.arrivals.append((start, workers))
        self.ledger.charge(hour, "hiring", s.hiring_fee_eur * workers, f"hired {workers}, starting hour {start}")
        return start

    def release(self, hour: int, workers: int) -> int:
        s = self.market.staff
        if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
            raise OpsError("workers must be a whole number of at least 1. Nobody was released.")
        if workers > self.crew:
            raise OpsError(f"only {self.crew} workers are on the crew. Nobody was released.")
        self.crew -= workers
        self.leaving += workers
        end = hour + 24 * s.release_notice_days
        self.departures.append((end, workers))
        return end

    def is_shift_hour(self, hour: int) -> bool:
        s = self.market.staff
        return s.shift_start_h <= hour % 24 < s.shift_start_h + s.shift_hours

    # -- tasks -------------------------------------------------------------------------

    def queue(self, hour: int, kind: str, target: str, worker_hours: float, payload: dict[str, Any] | None = None) -> Task:
        if kind not in TASK_KINDS:
            raise OpsError(f"unknown task kind {kind!r}; kinds are {list(TASK_KINDS)}.")
        if not math.isfinite(worker_hours) or worker_hours < 0:
            raise OpsError("worker_hours must be a finite number >= 0.")
        task = Task(f"K{len(self.tasks) + 1:03d}", kind, target, float(worker_hours), hour, dict(payload or {}))
        self.tasks.append(task)
        return task

    def waiting(self) -> list[Task]:
        return [t for t in self.tasks if t.done_hour is None]

    # -- the clock ---------------------------------------------------------------------

    def end_hour(self, hour: int) -> HourResult:
        """Close `hour`: wages, staff changes, deliveries, task progress, stock alarms."""
        s = self.market.staff
        alarms: list[Alarm] = []
        # Staff who start this hour work from this hour on.
        for start, n in [a for a in self.arrivals if a[0] <= hour]:
            self.crew += n
            alarms.append(Alarm(hour, "staff", "crew", f"{n} new worker(s) started; crew is now {self.crew}."))
        self.arrivals = [a for a in self.arrivals if a[0] > hour]
        for end, n in [d for d in self.departures if d[0] <= hour]:
            self.leaving -= n
        self.departures = [d for d in self.departures if d[0] > hour]
        # Wages: everyone still paid, every hour, spread evenly over the day.
        paid = self.crew + self.leaving
        self.ledger.charge(hour, "wages", paid * s.wage_eur_per_worker_hour * s.shift_hours / 24.0,
                           f"{paid} worker(s)")
        # Deliveries.
        delivered = []
        for order in self.orders:
            if order.status == "open" and order.eta_hour <= hour:
                order.status, order.delivered_hour = "delivered", hour
                spec = self.items[order.item]
                if spec.category != "co2":          # CO2 goes to the facility's store
                    self.stock[order.item] = self.stock.get(order.item, 0.0) + order.quantity
                self.ledger.charge(hour, spec.category, order.quantity * self.unit_price[order.item],
                                   f"delivery {order.id}: {order.quantity:g} {order.item}")
                if order.express:                   # the express surcharge is its own category
                    extra = self.express_price[order.item] - self.unit_price[order.item]
                    self.ledger.charge(hour, "express", order.quantity * max(0.0, extra),
                                       f"express surcharge {order.id}: {order.quantity:g} {order.item}")
                delivered.append(order)
                alarms.append(Alarm(hour, "delivery", order.id, f"Order {order.id} arrived: {order.quantity:g} {order.item}."))
        # Tasks, in queue order, during shift hours.
        completed = []
        pool = float(self.crew) if self.is_shift_hour(hour) else 0.0
        for task in self.waiting():
            if pool <= 1e-12:
                break
            if task.first_work_hour is None:
                task.first_work_hour = hour
            used = min(pool, task.worker_hours - task.done_hours)
            task.done_hours += used
            pool -= used
            if task.done_hours >= task.worker_hours - 1e-9:
                task.done_hour = hour
                self.task_wait_h[task.kind] += hour - task.queued_hour
                completed.append(task)
        # Stock alarms, once each time an item falls below its warning level.
        for item, spec in self.items.items():
            if item not in self.stock:
                continue
            low = spec.warn_below > 0 and self.stock[item] < spec.warn_below
            if low and item not in self._low:
                alarms.append(Alarm(hour, "stock_low", item, f"{item} stock is {self.stock[item]:g}, below "
                                                             f"{spec.warn_below:g}."))
            (self._low.add if low else self._low.discard)(item)
        return HourResult(alarms, completed, delivered)

    # -- views -------------------------------------------------------------------------

    def view(self) -> dict[str, Any]:
        """What the agent may see: everything here is exact (stock is counted, not sensed)."""
        s = self.market.staff
        return {
            "stock": {i: round(q, 1) for i, q in self.stock.items()},
            "open_orders": [o.view() for o in self.orders if o.status == "open"],
            "staff": {"crew": self.crew, "leaving": self.leaving,
                      "arriving": [{"start_hour": h, "workers": n} for h, n in self.arrivals],
                      "worker_hours_per_day": self.crew * s.shift_hours,
                      "shift": f"{s.shift_start_h:02d}:00-{s.shift_start_h + s.shift_hours:02d}:00"},
            "task_queue": [t.view() for t in self.waiting()],
        }

    def _order(self, order_id: str) -> Order:
        for o in self.orders:
            if o.id == order_id:
                return o
        raise OpsError(f"unknown order {order_id!r}.")
