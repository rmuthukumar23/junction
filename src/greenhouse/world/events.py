"""Events: a schedule drawn per seed, and what each occurrence does. Owner: Rowan.

The whole schedule is drawn when the episode starts, from one stream per event
type (`events/<id>`), so nothing the agent does can move, add or remove an
occurrence. Each hour has probability rate_per_day / 24 of an occurrence;
`pinned_hours` adds fixed ones for demo seeds. Durations and delays drawn from
a published range use their own per-occurrence stream; the drawn values are
hidden from the agent.

`world/sim.py` calls `due(hour)` at the start of each hour and applies what it
returns:
  * `EquipmentEffect`s for world/energy.py and world/climate.py (Emre) to honour;
  * `Alarm`s for the agent;
  * `DeliveryDelay`s for `Operations.delay`.
`effects_in_force(hour)` lists every outage active in that hour.

Repairs: `request_repair` returns the cost and worker-hours; the sim charges the
cost and queues the work with `Operations.queue("repair", ...)`. When the task
completes, `complete_repair` shortens the outage to end `shortens_to_h` later.
A repair of equipment that is not broken still costs money and worker-hours,
and does nothing, so spamming repairs cannot pay.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from envkit.rng import Rng

from ..config.base import Range
from ..config.market import EventSpec
from ..contracts import Alarm, EquipmentEffect


@dataclass(frozen=True)
class DeliveryDelay:
    """A late-delivery occurrence, applied by `Operations.delay`."""
    hour: int
    delay_h: int
    items: tuple[str, ...]


@dataclass(frozen=True)
class Occurrence:
    event_id: str
    n: int                    # occurrence index within its event type
    start_hour: int
    kind: str
    value_h: int              # outage duration or delivery delay, in whole hours
    target: str = ""


@dataclass
class Outage:
    target: str
    event_id: str
    start_hour: int
    until_hour: int           # exclusive: the equipment works again from this hour
    capacity_factor: float
    leakage_factor: float
    repair_requested_hour: int | None = None
    repaired_hour: int | None = None

    def effect(self) -> EquipmentEffect:
        return EquipmentEffect(self.target, self.capacity_factor, self.leakage_factor, self.until_hour)


@dataclass(frozen=True)
class RepairRequest:
    equipment_id: str
    cost_eur: float
    worker_hours: float
    broken: bool              # whether there was anything to repair when requested


class Events:
    def __init__(self, specs: list[EventSpec], horizon_h: int, rng: Rng):
        ids = [s.id for s in specs]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate event ids in {ids}")
        self.specs = {s.id: s for s in specs}
        self.horizon_h = horizon_h
        self.schedule: list[Occurrence] = []
        for spec in specs:
            stream = rng.stream(f"events/{spec.id}")
            p = spec.rate_per_day / 24.0
            hours = [h for h in range(horizon_h) if stream.bernoulli(p)]
            hours = sorted(dict.fromkeys([*hours, *(h for h in spec.pinned_hours if h < horizon_h)]))
            for n, h in enumerate(hours):
                raw = spec.duration_h if spec.kind == "equipment" else spec.delay_h
                value = raw.draw(rng.stream(f"events/{spec.id}/{n}")) if isinstance(raw, Range) else float(raw)
                self.schedule.append(Occurrence(spec.id, n, h, spec.kind, max(1, round(value)), spec.target))
        self.schedule.sort(key=lambda o: (o.start_hour, o.event_id, o.n))
        self.outages: list[Outage] = []
        self.repairs_requested = 0
        self.repairs_wasted = 0

    # -- the clock ---------------------------------------------------------------------

    def due(self, hour: int) -> list[EquipmentEffect | Alarm | DeliveryDelay]:
        """What starts or ends at the start of `hour`."""
        out: list[EquipmentEffect | Alarm | DeliveryDelay] = []
        for outage in self.outages:
            if outage.until_hour == hour:
                out.append(Alarm(hour, "equipment", outage.target, f"{outage.target} is working again."))
        for occ in (o for o in self.schedule if o.start_hour == hour):
            spec = self.specs[occ.event_id]
            if occ.kind == "late_delivery":
                out.append(DeliveryDelay(hour, occ.value_h, spec.items))
                continue
            current = self._active(occ.target, hour)
            if current is not None:          # already out: the new fault extends it
                current.until_hour = max(current.until_hour, hour + occ.value_h)
                out.append(current.effect())
                continue
            outage = Outage(occ.target, occ.event_id, hour, hour + occ.value_h, spec.capacity_factor,
                            spec.leakage_factor)
            self.outages.append(outage)
            out.append(outage.effect())
            out.append(Alarm(hour, "equipment", occ.target,
                             f"{occ.target} fault ({spec.id}): capacity {spec.capacity_factor:.0%} of normal. "
                             f"Repair: €{spec.repair.cost_eur:g} and {spec.repair.worker_hours:g} worker-hours, "
                             f"back within {spec.repair.shortens_to_h:g} h of the repair."))
        return out

    def outage_effect(self, target: str, hour: int) -> EquipmentEffect | None:
        """The effect of the outage on `target` in force at `hour`, if any."""
        outage = self._active(target, hour)
        return outage.effect() if outage is not None else None

    def effects_in_force(self, hour: int) -> list[EquipmentEffect]:
        return [o.effect() for o in self.outages if o.start_hour <= hour < o.until_hour]

    # -- repairs -----------------------------------------------------------------------

    def repair_quote(self, hour: int, equipment_id: str) -> RepairRequest:
        """Cost and worker-hours of a repair. Pure: changes nothing (refusals stay free)."""
        spec = self._repair_spec(equipment_id)
        broken = self._active(equipment_id, hour) is not None
        return RepairRequest(equipment_id, spec.repair.cost_eur, spec.repair.worker_hours, broken)

    def record_repair(self, hour: int, equipment_id: str) -> RepairRequest:
        """Note that a repair was requested and queued. Call only once the work is queued."""
        quote = self.repair_quote(hour, equipment_id)
        outage = self._active(equipment_id, hour)
        self.repairs_requested += 1
        if outage is None:
            self.repairs_wasted += 1
        elif outage.repair_requested_hour is None:
            outage.repair_requested_hour = hour
        return quote

    def request_repair(self, hour: int, equipment_id: str) -> RepairRequest:
        """Quote and record in one step (for callers that cannot fail in between)."""
        return self.record_repair(hour, equipment_id)

    def complete_repair(self, hour: int, equipment_id: str) -> list[Alarm]:
        """The repair task finished at the end of `hour`."""
        outage = self._active(equipment_id, hour)
        if outage is None:
            return [Alarm(hour, "equipment", equipment_id, f"Repair of {equipment_id} done; nothing was wrong.")]
        spec = self.specs[outage.event_id]
        outage.until_hour = min(outage.until_hour, hour + 1 + round(spec.repair.shortens_to_h))
        outage.repaired_hour = hour
        return [Alarm(hour, "equipment", equipment_id,
                      f"Repair of {equipment_id} done; working again from hour {outage.until_hour}.")]

    def repairable(self) -> list[str]:
        """Equipment ids a repair can be requested for (every equipment event target)."""
        return list(dict.fromkeys(s.target for s in self.specs.values() if s.kind == "equipment"))

    # -- views -------------------------------------------------------------------------

    def view(self, hour: int) -> dict[str, Any]:
        """What the agent may see: current outages, not the schedule or hidden durations."""
        return {"outages": [{"equipment": o.target, "since_hour": o.start_hour,
                             "repair_requested": o.repair_requested_hour is not None}
                            for o in self.outages if o.start_hour <= hour < o.until_hour]}

    def rules(self) -> list[dict[str, Any]]:
        """Published event types for get_rules: rates and ranges, never the schedule."""
        out = []
        for s in self.specs.values():
            rng_range = s.duration_h if s.kind == "equipment" else s.delay_h
            value = [rng_range.min, rng_range.max] if isinstance(rng_range, Range) else rng_range
            row: dict[str, Any] = {"id": s.id, "kind": s.kind, "rate_per_day": s.rate_per_day}
            if s.kind == "equipment":
                row.update(target=s.target, capacity_factor=s.capacity_factor, leakage_factor=s.leakage_factor,
                           duration_h=value, repair={"cost_eur": s.repair.cost_eur,
                                                     "worker_hours": s.repair.worker_hours,
                                                     "shortens_to_h": s.repair.shortens_to_h})
            else:
                row.update(delay_h=value, items=list(s.items))
            out.append(row)
        return out

    # -- internals ---------------------------------------------------------------------

    def _active(self, target: str, hour: int) -> Outage | None:
        return next((o for o in self.outages if o.target == target and o.start_hour <= hour < o.until_hour), None)

    def _repair_spec(self, equipment_id: str) -> EventSpec:
        spec = next((s for s in self.specs.values() if s.kind == "equipment" and s.target == equipment_id), None)
        if spec is None:
            from .operations import OpsError
            raise OpsError(f"no repair is defined for {equipment_id!r}; repairable: {self.repairable()}.")
        return spec
