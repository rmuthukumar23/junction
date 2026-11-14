"""Contractors: booked visits that repair persistent damage (spec 14.2). Owner: Rowan.

A repair needs three things at once (context 0.7): the contractor on site, the parts on
site and day-shift time. `book(hour, trade, target)` is free and records a booking with
an earliest visit hour (booking + the trade's response time; the surge response time
while a regional storm surge lasts). At the end of each hour a booking that is due:
  * waits while the needed parts are not in stock (status "waiting_for_parts");
  * waits for a site hour (clock hour in [site_start_h, site_end_h));
  * otherwise starts the visit: it takes the parts from stock, charges the call-out and
    goes on site. Each site hour on site works one job hour and charges the hourly rate.
    When the job hours are done the outage is repaired and the target is reported in
    `HourEnd.repaired`.
A booking needs the parts as they were broken when it was made. Damage added later (a
second storm on broken glass) needs a new booking after this repair.
All prices, response times and job hours come from the market file's
`[contractors.<trade>]`; per-seed ranges are drawn on streams `contractors/<trade>/...`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from envkit.rng import Rng

from ..config.base import Range
from ..config.market import ContractorSpec, MarketSpec
from ..contracts import Alarm, EquipmentEffect
from .events import Events, Outage
from .ledger import Ledger
from .operations import Operations, OpsError


def _value(param: float | Range, rng: Rng, key: str) -> float:
    return param.draw(rng.stream(key)) if isinstance(param, Range) else float(param)


def _published(param: float | Range) -> float | list[float]:
    return [param.min, param.max] if isinstance(param, Range) else param


@dataclass
class Booking:
    id: str
    trade: str
    target: str
    booked_hour: int
    earliest_visit_hour: int
    parts_needed: dict[str, int]
    job_hours: float
    callout_eur: float
    rate_eur_per_h: float
    outage: Outage
    status: str = "waiting"                 # waiting | waiting_for_parts | on_site | done
    hours_done: float = 0.0
    visit_hour: int | None = None
    done_hour: int | None = None


class Contractors:
    def __init__(self, market: MarketSpec, events: Events, ops: Operations, ledger: Ledger, rng: Rng):
        self.market, self.events, self.ops, self.ledger = market, events, ops, ledger
        self.specs: dict[str, ContractorSpec] = market.contractors
        draw = lambda t, field_: _value(getattr(self.specs[t], field_), rng, f"contractors/{t}/{field_}")  # noqa: E731
        self.callout = {t: draw(t, "callout_eur") for t in self.specs}
        self.rate = {t: draw(t, "rate_eur_per_h") for t in self.specs}
        self.response_h = {t: max(0, round(draw(t, "response_h"))) for t in self.specs}
        self.surge_response_h = {t: max(0, round(draw(t, "surge_response_h"))) for t in self.specs}
        self.bookings: list[Booking] = []
        self.visits = 0

    # -- requests ----------------------------------------------------------------------

    def book(self, hour: int, trade: str, target: str) -> dict[str, Any]:
        spec = self.specs.get(trade)
        if spec is None:
            raise OpsError(f"unknown trade {trade!r}; trades are {list(self.specs)}. Nothing was booked.")
        if not isinstance(target, str) or not spec.fixes_target(target):
            raise OpsError(f"the {trade} does not fix {target!r}; it fixes {list(spec.fixes)}. Nothing was booked.")
        outage = self.events.active(target, hour)
        if outage is None:
            raise OpsError(f"nothing is broken on {target}. Nothing was booked.")
        if not outage.persistent:
            raise OpsError(f"the fault on {target} clears by itself; no contractor is needed. Nothing was booked.")
        if outage.trade != trade:
            raise OpsError(f"the fault on {target} is repaired by the {outage.trade}, not the {trade}. "
                           "Nothing was booked.")
        open_booking = self._open(target)
        if open_booking is not None:
            raise OpsError(f"a visit is already booked for {target} ({open_booking.id}). Nothing was booked.")
        needed = outage.parts_needed()
        surge = self.events.surge_until(hour)
        response = self.surge_response_h[trade] if surge is not None and hour < surge else self.response_h[trade]
        booking = Booking(f"C{len(self.bookings) + 1:03d}", trade, target, hour, hour + response, needed,
                          spec.job_hours_base + spec.job_hours_per_part * sum(needed.values()),
                          self.callout[trade], self.rate[trade], outage)
        self.bookings.append(booking)
        if outage.booked_hour is None:
            outage.booked_hour = hour
        outage.booked_panes = outage.panes
        return self._view(booking)

    # -- the clock ---------------------------------------------------------------------

    def end_hour(self, hour: int) -> tuple[list[Alarm], list[str], list[EquipmentEffect]]:
        """Progress the visits. Returns alarms, the targets repaired this hour, and effects that changed
        (damage left over after a repair)."""
        alarms: list[Alarm] = []
        repaired: list[str] = []
        effects: list[EquipmentEffect] = []
        on_site_hour = self.market.site_start_h <= hour % 24 < self.market.site_end_h
        for b in self.bookings:
            if b.status == "done" or not on_site_hour:
                continue
            if b.status != "on_site":
                if hour < b.earliest_visit_hour or self._missing(b):
                    continue
                for item, n in b.parts_needed.items():
                    self.ops.take_parts(item, n)
                b.status, b.visit_hour = "on_site", hour
                self.visits += 1
                self.ledger.charge(hour, "contractors", b.callout_eur, f"{b.trade} call-out for {b.target}")
                alarms.append(Alarm(hour, "contractor", b.target, f"The {b.trade} has arrived and started on {b.target}."))
            worked = min(1.0, b.job_hours - b.hours_done)
            b.hours_done += worked
            self.ledger.charge(hour, "contractors", b.rate_eur_per_h * worked, f"{b.trade} labour on {b.target}")
            if b.hours_done >= b.job_hours - 1e-9:
                b.status, b.done_hour = "done", hour
                done_alarms, effect = self.events.complete_repair(hour, b.outage)
                alarms += done_alarms
                if effect is None:
                    repaired.append(b.target)
                else:
                    effects.append(effect)
        return alarms, repaired, effects

    # -- views -------------------------------------------------------------------------

    def open_booking(self, target: str) -> Booking | None:
        return self._open(target)

    def view(self, hour: int) -> list[dict[str, Any]]:
        return [self._view(b) for b in self.bookings if b.status != "done"]

    def booking_view(self, target: str) -> dict[str, Any] | None:
        b = self._open(target)
        return self._view(b) if b is not None else None

    def rules(self) -> dict[str, Any]:
        m = self.market
        return {trade: {"fixes": list(s.fixes), "part": s.part,
                        "callout_eur": _published(s.callout_eur), "rate_eur_per_h": _published(s.rate_eur_per_h),
                        "job_hours": {"base": s.job_hours_base, "per_part": s.job_hours_per_part},
                        "response_h": _published(s.response_h), "surge_response_h": _published(s.surge_response_h),
                        "on_site_hours": f"{m.site_start_h:02d}:00-{m.site_end_h:02d}:00"}
                for trade, s in self.specs.items()}

    # -- internals ---------------------------------------------------------------------

    def _open(self, target: str) -> Booking | None:
        return next((b for b in self.bookings if b.target == target and b.status != "done"), None)

    def _missing(self, b: Booking) -> dict[str, float]:
        return {i: n - self.ops.stock.get(i, 0.0) for i, n in b.parts_needed.items()
                if self.ops.stock.get(i, 0.0) < n - 1e-9}

    def _view(self, b: Booking) -> dict[str, Any]:
        status = b.status if b.status in ("on_site", "done") else ("waiting_for_parts" if self._missing(b) else "waiting")
        return {"booking_id": b.id, "trade": b.trade, "target": b.target, "booked_hour": b.booked_hour,
                "earliest_visit_hour": b.earliest_visit_hour, "status": status, "parts_needed": dict(b.parts_needed)}
