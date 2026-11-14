"""Greenhouse: composes the facility, the business and the crop models.

The simulator owns the clock, the batches, the standing settings and the
alarm log. Everything physical is delegated through the interfaces in
`contracts.py`, so this file never holds a crop, equipment or price value.

One hour (spec 4.2):
  1. expired equipment effects are cleared; events due now are applied (the
     business gets the hour's recorded weather, so storms follow the wind);
  2. `substeps_per_hour` sub-steps: the facility runs climate and energy for the
     settings in force at that clock hour and the crops' load, then every standing
     batch grows;
  3. the facility closes the hour (metered flows, alarms); the business prices
     them, pays wages, progresses tasks, runs contractor visits and delivers orders;
  4. deliveries, completed tasks and finished repairs are applied; sensor readings
     are recorded.

The daily turn (round 3, spec 14.1 as decided 14 Nov 2026). The agent acts once a
day, at 06:00. From 06:00 to 18:00 the day settings apply (the crew works its shift
inside these hours); from 18:00 to 06:00 the night schedule does: hourly entries of
fixed values that repeat every night until replaced. `end_shift` runs the whole day
and night until the next 06:00 inside one call, and nothing stops it. The hours
00:00-06:00 of day 1 (the handover night) run on the baseline before the agent's
first call, so every day starts at 06:00 with a morning report.

Every action is checked before anything changes and raises RuleError on a
problem, so a refused action changes nothing.
"""
from __future__ import annotations

import dataclasses
from dataclasses import asdict, dataclass
from typing import Any

from envkit.rng import Rng

from ..contracts import (Alarm, BatchState, ClimateSetpoints, CropLoad, EnergySettings, EquipmentEffect,
                         NightHour, RuleError, Task, WeatherNow)
from .modules import Modules

STANDING = ("growing", "ready")
AREA_ROUNDING_M2 = 0.05      # half of the 0.1 m2 step in which views report areas; not a game value
# The duty window is a rule of the benchmark (spec 14.1, context 0.2), not a facility value.
DUTY_START_H = 6
DUTY_END_H = 18
NIGHT_HOURS = tuple(range(DUTY_END_H, 24)) + tuple(range(0, DUTY_START_H))   # in night order


def night_order(clock_hour: int) -> int:
    """Position of a clock hour in the night: 18:00 -> 0, ..., 05:00 -> 11."""
    return (clock_hour - DUTY_END_H) % 24


def on_duty_hour(hour: int) -> bool:
    return DUTY_START_H <= hour % 24 < DUTY_END_H


@dataclass
class HourRecord:
    hour: int
    readings: dict[str, Any]
    climate: dict[str, dict[str, Any]]
    energy: dict[str, Any]
    metered: dict[str, Any]


class Greenhouse:
    def __init__(self, modules: Modules, rng: Rng):
        self.m = modules
        self.facility = modules.facility
        self.business = modules.business
        self.growth = modules.growth
        self.horizon_h = modules.horizon_h
        self.substeps = modules.substeps_per_hour
        self.rng = rng
        self.hour = 0
        self.unattended = False
        self.bankrupt_hour: int | None = None   # the hour cash first fell below 0; the episode ends there
        self.climate: dict[str, ClimateSetpoints] = dict(self.facility.fallback_climate())
        self.energy: EnergySettings = self.facility.fallback_energy()
        # D5: the night schedule is handed over as the baseline too: one entry for the whole night.
        self.night: list[NightHour] = [NightHour(DUTY_END_H, dict(self.climate), self.energy)]
        self.night_changed = False            # whether the agent ever set a night entry
        self.nights_on_handover = 0           # nights run on the handover schedule (evidence)
        self.last_night: dict[str, Any] | None = None
        self._night_open: dict[str, Any] | None = None
        self._recorded = self.facility.recorded()
        self.batches: dict[str, BatchState] = {}
        self.alarms: list[Alarm] = []
        self.history: list[HourRecord] = []
        self.effects: dict[str, EquipmentEffect] = {}
        self.pending_plant_m2: dict[str, float] = {c: 0.0 for c in self.facility.compartment_ids}
        self.queued_harvests: set[str] = set()
        self.tasks: list[Task] = []
        self.completed_task_ids: set[str] = set()
        self.harvests: list[dict[str, Any]] = []
        self._loads: dict[str, CropLoad] = {c: CropLoad(0.0, 0.0, 0.0) for c in self.facility.compartment_ids}
        self._batch_seq = 0
        for sb in self.facility.start_batches():
            if sb.crop_id not in self.growth:
                raise ValueError(f"start batch in {sb.compartment_id} grows '{sb.crop_id}', which no crop file defines")
            self._new_batch(sb.compartment_id, sb.crop_id, sb.area_m2, -round(sb.age_days * 24), sb.age_days)
        self.readings = self.facility.view(0, self.rng.stream("readings/0"))

    # -- clock -----------------------------------------------------------------------

    @property
    def done(self) -> bool:
        return self.hour >= self.horizon_h or self.bankrupt_hour is not None

    def hours_left(self) -> int:
        return max(0, self.horizon_h - self.hour)

    def run_hour(self) -> list[Alarm]:
        """Run the current hour with the standing settings; return its new alarms."""
        if self.done:
            raise RuleError("the episode is over")
        h = self.hour
        new: list[Alarm] = []
        if h % 24 == DUTY_END_H:
            self._open_night(h)
        climate, energy = self.settings_at(h)
        for target, eff in sorted(self.effects.items()):
            if eff.until_hour is not None and eff.until_hour <= h:
                self.facility.clear_effect(target)
                del self.effects[target]
        effects, alarms = self.business.start_hour(h, self._weather(h))
        for eff in effects:
            self.facility.apply_effect(eff)
            self.effects[eff.target] = eff
        new += alarms

        dt = 1.0 / self.substeps
        before = {b.id: b.status for b in self.batches.values()}
        for _ in range(self.substeps):
            samples = self.facility.substep(h, dt, climate, energy, self._loads)
            loads = {c: [0.0, 0.0, 0.0] for c in self.facility.compartment_ids}
            for b in self.batches.values():
                if b.status not in STANDING:
                    continue
                model, sample = self.growth[b.crop_id], samples[b.compartment_id]
                model.step(b, sample)
                acc = loads[b.compartment_id]
                acc[0] += b.area_m2
                acc[1] += model.transpiration_kg_h(b, sample)
                acc[2] += model.co2_uptake_kg_h(b, sample)
            self._loads = {c: CropLoad(*v) for c, v in loads.items()}
        for b in self.batches.values():
            if before.get(b.id) != b.status and b.status in ("ready", "lost"):
                if b.status == "ready" and b.ready_hour is None:
                    b.ready_hour = h
                new.append(Alarm(h, "batch_ready" if b.status == "ready" else "batch_lost", b.id,
                                 f"Batch {b.id} in {b.compartment_id} is {b.status}."))

        metered, alarms = self.facility.end_hour(h)
        new += alarms
        end = self.business.end_hour(h, metered)
        new += end.alarms
        for d in end.deliveries:
            if d.item == "co2_kg":
                self.facility.receive_co2(d.quantity)
        changed = {e.target for e in end.effects}
        for task in end.completed:
            self._complete(task, h, keep_effect=task.target in changed)
        for eff in end.effects:
            self.facility.apply_effect(eff)
            self.effects[eff.target] = eff
        for target in getattr(end, "repaired", ()):
            if target in self.effects:
                self.facility.clear_effect(target)
                del self.effects[target]

        self.hour = h + 1
        self.readings = self.facility.view(self.hour, self.rng.stream(f"readings/{self.hour}"))
        self.history.append(HourRecord(h, self.readings, {c: asdict(s) for c, s in climate.items()},
                                       asdict(energy), asdict(metered)))
        if self.business.cash_eur() < 0:
            # Bankrupt: no credit, so the business stops here and the loss is final.
            self.bankrupt_hour = h
            new.append(Alarm(h, "bankrupt", "business", "Cash fell below zero: the business is bankrupt "
                                                         "and the episode ends."))
        self.alarms += new
        if self._night_open is not None and (self.hour % 24 == DUTY_START_H or self.done):
            self._close_night()
        return new

    # -- the shift ---------------------------------------------------------------------

    @property
    def off_duty(self) -> bool:
        return not on_duty_hour(self.hour)

    def check_on_duty(self) -> None:
        """Actions need an open episode. Under the daily turn the agent only ever acts at
        06:00 (env.py), so the clock needs no check here; tests may drive the simulator
        directly at any hour."""
        if self.done:
            raise RuleError("the episode is over")

    def end_shift(self) -> dict[str, Any]:
        """End the turn: the day runs on the day settings and the night on the night
        schedule, until the next 06:00. Alarms are logged and never stop anything."""
        if self.done:
            raise RuleError("the episode is over")
        start = self.hour
        while not self.done:
            self.run_hour()
            if self.hour % 24 == DUTY_START_H:
                break
        return {"hours_run": self.hour - start, "night_over": not self.done}

    def settings_at(self, hour: int) -> tuple[dict[str, ClimateSetpoints], EnergySettings]:
        """The settings in force at an episode hour: the day settings on duty, else the
        night entry that covers that clock hour."""
        if on_duty_hour(hour):
            return self.climate, self.energy
        entry = self.night_entry(hour % 24)
        return entry.climate, entry.energy

    def night_entry(self, clock_hour: int) -> NightHour:
        """The entry in force at a night clock hour (the 18:00 entry always exists)."""
        k = night_order(clock_hour)
        return [e for e in self.night if night_order(e.hour) <= k][-1]

    def set_night_entry(self, hour: int, compartments: list[str] | None, climate: dict[str, Any],
                        energy: dict[str, Any], copy_day: bool = False, remove: bool = False) -> NightHour | None:
        """Set (or remove) the night entry starting at clock `hour`. The entry starts from
        what is in force at that hour (itself, or the previous entry), or from the day
        settings as they are now with `copy_day`; the given fields change it. Every value
        is checked like a day setting; a refused change changes nothing."""
        self.check_on_duty()
        if hour not in NIGHT_HOURS:
            raise RuleError(f"a night entry starts at a night hour: {DUTY_END_H}-23 or 0-{DUTY_START_H - 1}")
        entries = {e.hour: e for e in self.night}
        if remove:
            if climate or energy or copy_day:
                raise RuleError("remove takes no settings")
            if hour == DUTY_END_H:
                raise RuleError(f"the {DUTY_END_H:02d}:00 entry starts the night and cannot be removed")
            if hour not in entries:
                raise RuleError(f"there is no night entry at {hour:02d}:00")
            del entries[hour]
            self.night = sorted(entries.values(), key=lambda e: night_order(e.hour))
            self.night_changed = True
            return None
        targets = self._compartments(compartments)
        base = self.night_entry(hour)
        base_climate, base_energy = (self.climate, self.energy) if copy_day else (base.climate, base.energy)
        new_climate = dict(base_climate)
        if climate:
            for c in targets:
                new_climate[c] = self._merge_climate(c, base_climate[c], climate)
        new_energy = self._merge_energy(base_energy, energy) if energy else base_energy
        entry = NightHour(hour, new_climate, new_energy)
        entries[hour] = entry
        self.night = sorted(entries.values(), key=lambda e: night_order(e.hour))
        self.night_changed = True
        return entry

    def _open_night(self, hour: int) -> None:
        if not self.night_changed:
            self.nights_on_handover += 1
        self._night_open = {"from_hour": hour, "batches": self._batch_snapshot(hour),
                            "money": dict(self.business.totals())}

    def _close_night(self) -> None:
        night, self._night_open = self._night_open, None
        night.update(to_hour=self.hour, batches_after=self._batch_snapshot(self.hour),
                     money_after=dict(self.business.totals()))
        self.last_night = night

    def _batch_snapshot(self, hour: int) -> dict[str, dict[str, Any]]:
        """Estimated weight and quality per standing batch, as get_batches would show them."""
        out = {}
        for b in self.batches.values():
            if b.status not in STANDING:
                continue
            est = self.growth[b.crop_id].estimate(b, hour, self.rng.stream(f"estimate/{b.id}/{hour}"))
            out[b.id] = {"compartment": b.compartment_id, "status": b.status, "units": est.units,
                         "fresh_weight_g_per_unit": est.fresh_weight_g_per_unit, "quality": est.quality}
        return out

    def _weather(self, hour: int) -> WeatherNow:
        rows = self._recorded.weather
        return rows[min(hour, len(rows) - 1)]

    def go_unattended(self) -> None:
        """Nobody is deciding any more. Nothing is touched: the standing settings stay,
        nothing is ordered, planted or harvested (D5). Stopping is therefore the same
        as advancing without acting, so stopping early can never pay."""
        self.unattended = True

    # -- actions ---------------------------------------------------------------------

    def set_climate(self, compartment_id: str, changes: dict[str, Any]) -> ClimateSetpoints:
        self.check_on_duty()
        self._compartment(compartment_id)
        new = self._merge_climate(compartment_id, self.climate[compartment_id], changes)
        self.climate[compartment_id] = new
        return new

    def set_climate_many(self, compartments: list[str] | None, changes: dict[str, Any]) -> dict[str, ClimateSetpoints]:
        """The same changes for several compartments (None = all), all checked first."""
        self.check_on_duty()
        new = {c: self._merge_climate(c, self.climate[c], changes) for c in self._compartments(compartments)}
        self.climate.update(new)
        return new

    def set_energy(self, changes: dict[str, Any]) -> EnergySettings:
        self.check_on_duty()
        self.energy = self._merge_energy(self.energy, changes)
        return self.energy

    def _merge_climate(self, compartment_id: str, base: ClimateSetpoints, changes: dict[str, Any]) -> ClimateSetpoints:
        if "lamp_hours" in changes:
            hours = changes["lamp_hours"]
            if any(not isinstance(x, int) or not 0 <= x <= 23 for x in hours) or len(set(hours)) != len(hours):
                raise RuleError("lamp_hours must be distinct hours of the day, 0 to 23")
            changes = {**changes, "lamp_hours": tuple(sorted(hours))}
        new = dataclasses.replace(base, **changes)
        self.facility.check_climate(compartment_id, new)
        return new

    def _merge_energy(self, base: EnergySettings, changes: dict[str, Any]) -> EnergySettings:
        for key in ("priority", "heat_cap_kw", "co2_cap_kg_h"):
            if key in changes:
                unknown = sorted(set(changes[key]) - set(self.facility.compartment_ids))
                if unknown:
                    raise RuleError(f"{key}: unknown compartment(s) {unknown}")
                changes = {**changes, key: {**getattr(base, key), **changes[key]}}
        new = dataclasses.replace(base, **changes)
        self.facility.check_energy(new)
        return new

    def plant(self, compartment_id: str, area_m2: float) -> Task:
        self.check_on_duty()
        self._compartment(compartment_id)
        if area_m2 <= 0:
            raise RuleError("area_m2 must be positive")
        crop_id = self.facility.crop_id(compartment_id)
        model = self.growth[crop_id]
        days_left = self.hours_left() / 24
        if days_left < model.min_days_before_end():
            raise RuleError(f"too late to plant {crop_id}: {days_left:.1f} days left, "
                            f"it needs at least {model.min_days_before_end():g}")
        free = self.free_area_m2(compartment_id)
        # get_status shows the free area to one decimal, so that figure must be plantable:
        # a request within that rounding plants what is actually free.
        if area_m2 > free + AREA_ROUNDING_M2:
            raise RuleError(f"only {free:.1f} m2 is free in {compartment_id}")
        area_m2 = min(area_m2, free)
        if area_m2 <= 0:
            raise RuleError(f"no area is free in {compartment_id}")
        count = model.seedlings_needed(area_m2)
        self.business.take_seedlings(self.hour, crop_id, count)
        task = self.business.queue_task(self.hour, "plant", compartment_id, model.labour_hours("plant", area_m2),
                                        {"area_m2": area_m2, "crop_id": crop_id, "seedlings": count})
        self.pending_plant_m2[compartment_id] += area_m2
        self.tasks.append(task)
        return task

    def harvest(self, batch_id: str) -> Task:
        self.check_on_duty()
        b = self.batches.get(batch_id)
        if b is None:
            raise RuleError(f"unknown batch {batch_id!r}")
        if b.status not in STANDING:
            raise RuleError(f"batch {batch_id} is {b.status}")
        if batch_id in self.queued_harvests:
            raise RuleError(f"batch {batch_id} is already queued for harvest")
        task = self.business.queue_task(self.hour, "harvest", batch_id,
                                        self.growth[b.crop_id].labour_hours("harvest", b.area_m2), {})
        self.queued_harvests.add(batch_id)
        self.tasks.append(task)
        return task

    def book_contractor(self, trade: str, target: str) -> dict[str, Any]:
        """Book a contractor to repair `target` (spec 14.2). The business checks the trade,
        the damage and existing bookings, and runs the visit when the parts are on site."""
        self.check_on_duty()
        if target not in self.facility.equipment_ids():
            raise RuleError(f"unknown equipment {target!r}; ids are {list(self.facility.equipment_ids())}")
        return self.business.book_contractor(self.hour, trade, target)

    def failure_evidence(self) -> dict[str, float]:
        """Shift evidence for outcome.py: nights run on the handover schedule."""
        return {"fm_nights_on_handover_schedule": float(self.nights_on_handover)}

    # -- reads -----------------------------------------------------------------------

    def free_area_m2(self, compartment_id: str) -> float:
        used = sum(b.area_m2 for b in self.batches.values()
                   if b.compartment_id == compartment_id and b.status in STANDING)
        return max(0.0, self.facility.floor_area_m2(compartment_id) - used - self.pending_plant_m2[compartment_id])

    def batch_views(self) -> list[dict[str, Any]]:
        out = []
        for b in self.batches.values():
            est = self.growth[b.crop_id].estimate(b, self.hour, self.rng.stream(f"estimate/{b.id}/{self.hour}"))
            out.append({"id": b.id, "crop": b.crop_id, "compartment": b.compartment_id,
                        "area_m2": round(b.area_m2, 1), "age_days": round((self.hour - b.planted_hour) / 24, 2),
                        "status": b.status, "harvest_queued": b.id in self.queued_harvests, "cuts": b.cuts,
                        "estimate": asdict(est)})
        return out

    # -- internals -------------------------------------------------------------------

    def _new_batch(self, compartment_id: str, crop_id: str, area_m2: float, planted_hour: int,
                   age_days: float = 0.0) -> BatchState:
        self._batch_seq += 1
        bid = f"{compartment_id}{self._batch_seq}"
        batch = self.growth[crop_id].new_batch(bid, compartment_id, area_m2, planted_hour, age_days)
        self.batches[bid] = batch
        return batch

    def _complete(self, task: Task, hour: int, keep_effect: bool = False) -> None:
        self.completed_task_ids.add(task.id)
        if task.kind == "plant":
            area = float(task.detail["area_m2"])
            self.pending_plant_m2[task.target] -= area
            self._new_batch(task.target, str(task.detail["crop_id"]), area, hour + 1)
        elif task.kind == "harvest":
            b = self.batches[task.target]
            self.queued_harvests.discard(b.id)
            if b.status not in STANDING:
                return
            result = self.growth[b.crop_id].harvest(b, hour)
            entry = self.business.sell(hour, result)
            self.harvests.append({**asdict(result), "hour": hour, "eur": entry.eur})
        elif task.kind == "repair":
            if task.target in self.effects and not keep_effect:
                self.facility.clear_effect(task.target)
                del self.effects[task.target]

    def _compartments(self, ids: list[str] | None) -> list[str]:
        if not ids:
            return list(self.facility.compartment_ids)
        for c in ids:
            self._compartment(c)
        return list(dict.fromkeys(ids))

    def _compartment(self, compartment_id: str) -> None:
        if compartment_id not in self.facility.compartment_ids:
            raise RuleError(f"unknown compartment {compartment_id!r}; compartments are "
                            f"{list(self.facility.compartment_ids)}")
