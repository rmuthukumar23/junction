"""Greenhouse: composes the facility, the business and the crop models.

The simulator owns the clock, the batches, the standing settings and the
alarm log. Everything physical is delegated through the interfaces in
`contracts.py`, so this file never holds a crop, equipment or price value.

One hour (spec 4.2):
  1. expired equipment effects are cleared; events due now are applied;
  2. `substeps_per_hour` sub-steps: the facility runs climate and energy for the
     standing settings and the crops' load, then every standing batch grows;
  3. the facility closes the hour (metered flows, alarms); the business prices
     them, pays wages, progresses tasks and delivers orders;
  4. deliveries and completed tasks are applied; sensor readings are recorded.

Every action is checked before anything changes and raises RuleError on a
problem, so a refused action changes nothing.
"""
from __future__ import annotations

import dataclasses
from dataclasses import asdict, dataclass
from typing import Any

from envkit.rng import Rng

from ..contracts import (Alarm, BatchState, ClimateSetpoints, CropLoad, EnergySettings, EquipmentEffect,
                         RuleError, Task)
from .modules import Modules

STANDING = ("growing", "ready")
AREA_ROUNDING_M2 = 0.05      # half of the 0.1 m2 step in which views report areas; not a game value


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
        self.finished_by_player = False
        self.climate: dict[str, ClimateSetpoints] = dict(self.facility.fallback_climate())
        self.energy: EnergySettings = self.facility.fallback_energy()
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
        return self.hour >= self.horizon_h

    def hours_left(self) -> int:
        return max(0, self.horizon_h - self.hour)

    def run_hour(self) -> list[Alarm]:
        """Run the current hour with the standing settings; return its new alarms."""
        if self.done:
            raise RuleError("the episode is over")
        h = self.hour
        new: list[Alarm] = []
        for target, eff in sorted(self.effects.items()):
            if eff.until_hour is not None and eff.until_hour <= h:
                self.facility.clear_effect(target)
                del self.effects[target]
        effects, alarms = self.business.start_hour(h)
        for eff in effects:
            self.facility.apply_effect(eff)
            self.effects[eff.target] = eff
        new += alarms

        dt = 1.0 / self.substeps
        before = {b.id: b.status for b in self.batches.values()}
        for _ in range(self.substeps):
            samples = self.facility.substep(h, dt, self.climate, self.energy, self._loads)
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

        self.hour = h + 1
        self.readings = self.facility.view(self.hour, self.rng.stream(f"readings/{self.hour}"))
        self.history.append(HourRecord(h, self.readings, {c: asdict(s) for c, s in self.climate.items()},
                                       asdict(self.energy), asdict(metered)))
        self.alarms += new
        return new

    def advance(self, hours: int) -> dict[str, Any]:
        """Run up to `hours` hours; stop at the end of an hour with a new alarm."""
        if self.done:
            raise RuleError("the episode is over")
        if not 1 <= hours <= 24:
            raise RuleError("hours must be between 1 and 24")
        start, alarms = self.hour, []
        while self.hour - start < hours and not self.done:
            alarms = self.run_hour()
            if alarms:
                break
        ran = self.hour - start
        return {"hours_run": ran, "stopped_early": ran < hours and not self.done,
                "stop_reason": "alarm" if alarms else ("end of episode" if self.done else None),
                "alarms": [asdict(a) for a in alarms]}

    def go_unattended(self) -> None:
        """Nobody is deciding any more. Nothing is touched: the standing settings stay,
        nothing is ordered, planted or harvested (D5). Stopping is therefore the same
        as advancing without acting, so stopping early can never pay."""
        self.unattended = True

    def finish(self) -> None:
        self.finished_by_player = True
        self.go_unattended()
        while not self.done:
            self.run_hour()

    # -- actions ---------------------------------------------------------------------

    def set_climate(self, compartment_id: str, changes: dict[str, Any]) -> ClimateSetpoints:
        self._compartment(compartment_id)
        if "lamp_hours" in changes:
            hours = changes["lamp_hours"]
            if any(not isinstance(x, int) or not 0 <= x <= 23 for x in hours) or len(set(hours)) != len(hours):
                raise RuleError("lamp_hours must be distinct hours of the day, 0 to 23")
            changes = {**changes, "lamp_hours": tuple(sorted(hours))}
        new = dataclasses.replace(self.climate[compartment_id], **changes)
        self.facility.check_climate(compartment_id, new)
        self.climate[compartment_id] = new
        return new

    def set_energy(self, changes: dict[str, Any]) -> EnergySettings:
        for key in ("priority", "heat_cap_kw", "co2_cap_kg_h"):
            if key in changes:
                unknown = sorted(set(changes[key]) - set(self.facility.compartment_ids))
                if unknown:
                    raise RuleError(f"{key}: unknown compartment(s) {unknown}")
                changes = {**changes, key: {**getattr(self.energy, key), **changes[key]}}
        new = dataclasses.replace(self.energy, **changes)
        self.facility.check_energy(new)
        self.energy = new
        return new

    def plant(self, compartment_id: str, area_m2: float) -> Task:
        self._compartment(compartment_id)
        if area_m2 <= 0:
            raise RuleError("area_m2 must be positive")
        crop_id = self.facility.crop_id(compartment_id)
        model = self.growth[crop_id]
        free = self.free_area_m2(compartment_id)
        # get_status shows the free area to one decimal, so that figure must be plantable:
        # a request within that rounding plants what is actually free.
        if area_m2 > free + AREA_ROUNDING_M2:
            raise RuleError(f"only {free:.1f} m2 is free in {compartment_id}")
        area_m2 = min(area_m2, free)
        if area_m2 <= 0:
            raise RuleError(f"no area is free in {compartment_id}")
        days_left = self.hours_left() / 24
        if days_left < model.min_days_before_end():
            raise RuleError(f"too late to plant {crop_id}: {days_left:.1f} days left, "
                            f"it needs at least {model.min_days_before_end():g}")
        count = model.seedlings_needed(area_m2)
        self.business.take_seedlings(self.hour, crop_id, count)
        task = self.business.queue_task(self.hour, "plant", compartment_id, model.labour_hours("plant", area_m2),
                                        {"area_m2": area_m2, "crop_id": crop_id, "seedlings": count})
        self.pending_plant_m2[compartment_id] += area_m2
        self.tasks.append(task)
        return task

    def harvest(self, batch_id: str) -> Task:
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

    def repair(self, equipment_id: str) -> Task:
        if equipment_id not in self.facility.equipment_ids():
            raise RuleError(f"unknown equipment {equipment_id!r}; ids are {list(self.facility.equipment_ids())}")
        if equipment_id not in self.effects:
            raise RuleError(f"{equipment_id} is working normally; nothing to repair")
        if any(t.kind == "repair" and t.target == equipment_id and t.id not in self.completed_task_ids
               for t in self.tasks):
            raise RuleError(f"a repair of {equipment_id} is already queued")
        task = self.business.queue_task(self.hour, "repair", equipment_id, None, {})
        self.tasks.append(task)
        return task

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

    def _compartment(self, compartment_id: str) -> None:
        if compartment_id not in self.facility.compartment_ids:
            raise RuleError(f"unknown compartment {compartment_id!r}; compartments are "
                            f"{list(self.facility.compartment_ids)}")
