"""Events: a schedule drawn per seed, and what each occurrence does. Owner: Rowan.

The whole schedule is drawn when the episode starts, from one stream per event
type (`events/<id>`), so nothing the agent does can move, add or remove an
occurrence. Each hour has probability rate_per_day / 24 of an occurrence;
`pinned_hours` adds fixed ones for demo seeds. Durations and delays drawn from
a published range use their own per-occurrence stream; the drawn values are
hidden from the agent.

Kinds:
  * `equipment`: a fault on one piece of equipment. With `duration_h` it clears by
    itself. With `persistent = true` it stays until a contractor repairs it
    (world/contractors.py), the effect has `until_hour=None`.
  * `late_delivery`: the open order due soonest arrives later (`Operations.delay`).
  * `storm` (spec 14.2): fires at the first hour of a spell in which the recorded
    wind reaches `wind_threshold_m_s`, at least `min_gap_h` after the previous storm.
    The recorded weather is known at build time, so the storm hours are computed once
    (`storm_hours`), which is the same answer as watching each hour's weather. Each
    compartment's glass loses a number of panes drawn on its own stream
    (`events/<id>/<n>/<compartment>`); the damage persists, and a second storm on
    broken glass adds panes. A storm also starts a regional surge (`surge_until`).

`world/sim.py` calls `due(hour)` at the start of each hour (through the business) and
applies what it returns: `EquipmentEffect`s for the facility, `Alarm`s for the agent,
`DeliveryDelay`s for `Operations.delay`. `effects_in_force(hour)` lists every outage
active in that hour.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from envkit.rng import Rng

from ..config.base import Range
from ..config.market import EventSpec
from ..contracts import Alarm, EquipmentEffect, Recorded, WeatherNow

GLASS = ".glass"


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
    damage: tuple[tuple[str, int], ...] = ()    # storms: (glass id, panes broken)


@dataclass
class Outage:
    target: str
    event_id: str
    start_hour: int
    until_hour: int | None    # exclusive: works again from this hour; None = until a contractor repairs it
    capacity_factor: float
    leakage_factor: float
    trade: str = ""                                       # persistent: the trade that fixes it
    parts: dict[str, float] = field(default_factory=dict)   # persistent: parts per job (glass: per pane)
    panes: int = 0                                        # glass: panes broken
    leakage_per_pane: float = 0.0
    booked_hour: int | None = None                        # first contractor booking for this outage
    booked_panes: int = 0                                 # panes the open booking covers
    repaired_hour: int | None = None

    @property
    def persistent(self) -> bool:
        return self.until_hour is None

    def effect(self) -> EquipmentEffect:
        return EquipmentEffect(self.target, self.capacity_factor, self.leakage_factor, self.until_hour)

    def parts_needed(self) -> dict[str, int]:
        scale = self.panes if self.panes else 1
        return {item: round(qty * scale) for item, qty in self.parts.items()}


def storm_hours(spec: EventSpec, weather: Sequence[WeatherNow], horizon_h: int) -> list[int]:
    """Hours a storm fires on the recorded weather: the first hour of a spell at or above the
    wind threshold, at least `min_gap_h` after the previous storm. Pinned hours are added."""
    hours: list[int] = []
    last: int | None = None
    for h, w in enumerate(weather[:horizon_h]):
        windy = w.wind_m_s >= spec.wind_threshold_m_s
        started = windy and (h == 0 or weather[h - 1].wind_m_s < spec.wind_threshold_m_s)
        if started and (last is None or h - last >= spec.min_gap_h):
            hours.append(h)
            last = h
    return sorted(set(hours) | {h for h in spec.pinned_hours if h < horizon_h})


class Events:
    def __init__(self, specs: list[EventSpec], horizon_h: int, rng: Rng,
                 equipment_ids: Sequence[str] = (), recorded: Recorded | None = None):
        ids = [s.id for s in specs]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate event ids in {ids}")
        self.specs = {s.id: s for s in specs}
        self.horizon_h = horizon_h
        self.schedule: list[Occurrence] = []
        self.storms: list[tuple[int, int]] = []          # (start hour, surge length in hours)
        glass = sorted(e for e in equipment_ids if e.endswith(GLASS))
        for spec in specs:
            if spec.kind == "storm":
                weather = recorded.weather if recorded is not None else ()
                for n, h in enumerate(storm_hours(spec, weather, horizon_h)):
                    damage = tuple((g, rng.stream(f"events/{spec.id}/{n}/{g[:-len(GLASS)]}")
                                    .randint(round(spec.panes_min), round(spec.panes_max))) for g in glass)
                    self.schedule.append(Occurrence(spec.id, n, h, "storm", 0, damage=damage))
                    self.storms.append((h, round(24 * spec.surge_days)))
                continue
            stream = rng.stream(f"events/{spec.id}")
            p = spec.rate_per_day / 24.0
            hours = [h for h in range(horizon_h) if stream.bernoulli(p)]
            hours = sorted(dict.fromkeys([*hours, *(h for h in spec.pinned_hours if h < horizon_h)]))
            for n, h in enumerate(hours):
                raw = spec.duration_h if spec.kind == "equipment" else spec.delay_h
                value = raw.draw(rng.stream(f"events/{spec.id}/{n}")) if isinstance(raw, Range) else float(raw)
                self.schedule.append(Occurrence(spec.id, n, h, spec.kind, max(1, round(value)), spec.target))
        self.schedule.sort(key=lambda o: (o.start_hour, o.event_id, o.n))
        self.storms.sort()
        self.outages: list[Outage] = []

    # -- the clock ---------------------------------------------------------------------

    def due(self, hour: int) -> list[EquipmentEffect | Alarm | DeliveryDelay]:
        """What starts or ends at the start of `hour`."""
        out: list[EquipmentEffect | Alarm | DeliveryDelay] = []
        for outage in self.outages:
            if outage.until_hour == hour and outage.repaired_hour is None:
                out.append(Alarm(hour, "equipment", outage.target, f"{outage.target} is working again."))
        for occ in (o for o in self.schedule if o.start_hour == hour):
            spec = self.specs[occ.event_id]
            if occ.kind == "late_delivery":
                out.append(DeliveryDelay(hour, occ.value_h, spec.items))
            elif occ.kind == "storm":
                out += self._storm(hour, occ, spec)
            else:
                out += self._fault(hour, occ, spec)
        return out

    def _storm(self, hour: int, occ: Occurrence, spec: EventSpec) -> list[EquipmentEffect | Alarm]:
        out: list[EquipmentEffect | Alarm] = []
        found = []
        for target, panes in occ.damage:
            if panes <= 0:
                continue
            outage = self._active(target, hour)
            if outage is None:
                outage = Outage(target, spec.id, hour, None, 1.0, 1.0, spec.repair.trade, dict(spec.repair.parts),
                                0, spec.leakage_per_pane)
                self.outages.append(outage)
            outage.panes += panes                  # a second storm on broken glass adds panes
            outage.leakage_factor = 1.0 + outage.panes * outage.leakage_per_pane
            out.append(outage.effect())
            found.append(f"{target[:-len(GLASS)]}: {panes} pane(s) broken")
        surge = (f" Regional surge: for about {spec.surge_days:g} days parts take longer to arrive and "
                 "contractors are slow to come.")
        out.append(Alarm(hour, "storm", spec.id, "Storm over the site. "
                         + ("Damage: " + "; ".join(found) + "." if found else "No damage found.") + surge))
        return out

    def _fault(self, hour: int, occ: Occurrence, spec: EventSpec) -> list[EquipmentEffect | Alarm]:
        current = self._active(occ.target, hour)
        if spec.persistent:
            if current is not None:                # already broken: nothing new to break
                return []
            outage = Outage(occ.target, spec.id, hour, None, spec.capacity_factor, spec.leakage_factor,
                            spec.repair.trade, dict(spec.repair.parts))
            self.outages.append(outage)
            return [outage.effect(),
                    Alarm(hour, "equipment", occ.target,
                          f"{occ.target} fault ({spec.id}): capacity {spec.capacity_factor:.0%} of normal. "
                          "It stays out until a contractor repairs it (book_contractor).")]
        if current is not None:                    # already out: the new fault extends it
            if current.until_hour is not None:
                current.until_hour = max(current.until_hour, hour + occ.value_h)
            return [current.effect()]
        outage = Outage(occ.target, spec.id, hour, hour + occ.value_h, spec.capacity_factor, spec.leakage_factor)
        self.outages.append(outage)
        return [outage.effect(),
                Alarm(hour, "equipment", occ.target,
                      f"{occ.target} fault ({spec.id}): capacity {spec.capacity_factor:.0%} of normal. "
                      "It clears by itself.")]

    def surge_until(self, hour: int) -> int | None:
        """The hour the regional storm surge ends, from the latest storm that has happened by
        `hour`; None before the first storm."""
        ends = [start + length for start, length in self.storms if start <= hour]
        return max(ends) if ends else None

    def storm_starts(self) -> list[int]:
        return [start for start, _ in self.storms]

    def outage_effect(self, target: str, hour: int) -> EquipmentEffect | None:
        """The effect of the outage on `target` in force at `hour`, if any."""
        outage = self._active(target, hour)
        return outage.effect() if outage is not None else None

    def effects_in_force(self, hour: int) -> list[EquipmentEffect]:
        return [o.effect() for o in self.outages if self._in_force(o, hour)]

    def active(self, target: str, hour: int) -> Outage | None:
        return self._active(target, hour)

    # -- repairs (called by world/contractors.py) ---------------------------------------

    def complete_repair(self, hour: int, outage: Outage) -> tuple[list[Alarm], EquipmentEffect | None]:
        """A contractor finished the job on `outage` at the end of `hour`. Panes broken by a later
        storm than the booking covered stay broken and need a new booking: then the reduced
        effect is returned; otherwise the equipment is repaired (None)."""
        extra = outage.panes - outage.booked_panes if outage.panes else 0
        if extra > 0:
            outage.panes = extra
            outage.leakage_factor = 1.0 + extra * outage.leakage_per_pane
            outage.booked_panes = 0
            return ([Alarm(hour, "contractor", outage.target,
                           f"{outage.target} repaired, but {extra} more pane(s) broke after the booking and "
                           "need a new booking.")], outage.effect())
        outage.repaired_hour = hour
        return ([Alarm(hour, "contractor", outage.target, f"{outage.target} is repaired.")], None)

    # -- views -------------------------------------------------------------------------

    def view(self, hour: int) -> dict[str, Any]:
        """What the agent may see: current outages, not the schedule or hidden durations."""
        rows = []
        for o in self.outages:
            if not self._in_force(o, hour) or (o.repaired_hour is not None):
                continue
            row: dict[str, Any] = {"equipment": o.target, "since_hour": o.start_hour,
                                   "persistent": o.persistent, "parts_needed": o.parts_needed()}
            if o.panes:
                row["panes_broken"] = o.panes
            rows.append(row)
        return {"outages": rows}

    def rules(self) -> list[dict[str, Any]]:
        """Published event types for get_rules: rates and ranges, never the schedule."""
        out = []
        for s in self.specs.values():
            row: dict[str, Any] = {"id": s.id, "kind": s.kind}
            if s.kind == "storm":
                row.update(wind_threshold_m_s=s.wind_threshold_m_s, min_gap_h=s.min_gap_h,
                           panes_per_compartment=[s.panes_min, s.panes_max], leakage_per_pane=s.leakage_per_pane,
                           surge_days=s.surge_days,
                           repair={"trade": s.repair.trade, "parts_per_pane": dict(s.repair.parts)})
                out.append(row)
                continue
            row["rate_per_day"] = s.rate_per_day
            rng_range = s.duration_h if s.kind == "equipment" else s.delay_h
            # Only a range is published. The loader draws each range once per seed before
            # the business is built, so a plain number here is that hidden draw: it is
            # left out, and its range is in get_rules under hidden_parameter_ranges.
            length = {"duration_h" if s.kind == "equipment" else "delay_h": [rng_range.min, rng_range.max]} \
                if isinstance(rng_range, Range) else {}
            if s.kind == "equipment":
                row.update(target=s.target, capacity_factor=s.capacity_factor, leakage_factor=s.leakage_factor,
                           persistent=s.persistent, **length)
                if s.persistent:
                    row["repair"] = {"trade": s.repair.trade, "parts": dict(s.repair.parts)}
            else:
                row.update(**length, items=list(s.items))
            out.append(row)
        return out

    # -- internals ---------------------------------------------------------------------

    @staticmethod
    def _in_force(o: Outage, hour: int) -> bool:
        return (o.start_hour <= hour and (o.until_hour is None or hour < o.until_hour)
                and (o.repaired_hour is None or hour <= o.repaired_hour))

    def _active(self, target: str, hour: int) -> Outage | None:
        return next((o for o in self.outages if o.target == target and self._in_force(o, hour)), None)
