"""Test doubles for the three subsystems, so sim.py and the tools run end to end
before the real modules exist. Selected by `[env] modules = "fakes:build"`.

These are deliberately crude toys with their numbers in code. They live under
tests/ and are never bundled into a task. Replace nothing here with real
physics: the real modules belong to their owners (docs/collaboration/).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from envkit.rng import Rng
from greenhouse.contracts import (Alarm, BatchEstimate, BatchState, ClimateSample, ClimateSetpoints, CropLoad,
                                  Delivery, EnergySettings, EquipmentEffect, HarvestResult, HourEnd, LedgerEntry,
                                  Metered, RuleError, StartBatch, Task)
from greenhouse.world.modules import Modules


class FakeCrop:
    """Dry weight grows with temperature and light; ready at 100 g per head."""

    def __init__(self, crop_id: str, repeated: bool = False):
        self.crop_id = crop_id
        self.repeated = repeated

    def new_batch(self, batch_id, compartment_id, area_m2, planted_hour, age_days=0.0):
        return BatchState(batch_id, self.crop_id, compartment_id, area_m2, planted_hour,
                          model_state={"g_per_head": 4.0 * age_days})

    def step(self, batch, climate: ClimateSample):
        rate = max(0.0, min(1.0, (climate.temp_c - 5.0) / 15.0)) * (0.5 + min(1.0, climate.par_umol_m2_s / 400.0))
        batch.model_state["g_per_head"] += 0.25 * rate * climate.dt_h
        if climate.temp_c < -1.0:
            batch.status = "lost"
        elif batch.status == "growing" and batch.model_state["g_per_head"] >= 100.0:
            batch.status = "ready"

    def estimate(self, batch, hour, rng: Rng):
        g = batch.model_state["g_per_head"] * (1 + rng.normal(0, 0.02))
        return BatchEstimate(round(g, 1), batch.area_m2 * 20, None if batch.status != "growing" else
                             max(0.0, (100 - g) / 3.0), 1.0)

    def harvest(self, batch, hour):
        g = batch.model_state["g_per_head"]
        sellable = g >= 80.0
        res = HarvestResult(batch.id, self.crop_id, batch.area_m2 * 20, "head", g, 1.0, sellable,
                            "A" if sellable else "waste", 1.0 if sellable else 0.0)
        if self.repeated:
            batch.model_state["g_per_head"] = 30.0
            batch.status = "growing"
            batch.cuts += 1
        else:
            batch.status = "harvested"
        return res

    def transpiration_kg_h(self, batch, climate):
        return 0.0001 * batch.area_m2 * climate.par_umol_m2_s

    def co2_uptake_kg_h(self, batch, climate):
        return 0.00001 * batch.area_m2 * climate.par_umol_m2_s

    def labour_hours(self, action, area_m2):
        return area_m2 / 200.0

    def seedlings_needed(self, area_m2):
        return math.ceil(area_m2 * 20)

    def min_days_before_end(self):
        return 3.0

    def describe(self):
        return {"crop_id": self.crop_id, "note": "fake crop"}


class FakeFacility:
    """Two 1000 m2 compartments; inside temperature relaxes towards the setpoint
    if the boiler can supply the heat, else towards outside."""
    compartment_ids = ("A", "B")

    def __init__(self, rng: Rng):
        self.offset_c = rng.stream("weather").uniform(-2, 2)
        self.temp = {c: 8.0 for c in self.compartment_ids}
        self.co2_store_kg = 500.0
        self.boiler_factor = 1.0
        self._gas = 0.0
        self._heat: dict[str, float] = {}

    def outside_c(self, hour: float) -> float:
        return 3.0 + self.offset_c + 4.0 * math.sin(2 * math.pi * ((hour % 24) - 9) / 24)

    def sun(self, hour: float) -> float:
        h = hour % 24
        return max(0.0, 300.0 * math.sin(math.pi * (h - 8) / 8)) if 8 <= h <= 16 else 0.0

    def floor_area_m2(self, c):
        return 1000.0

    def crop_id(self, c):
        return "fake_lettuce" if c == "A" else "fake_basil"

    def start_batches(self):
        return [StartBatch("A", "fake_lettuce", age, 250.0) for age in (24.0, 16.0, 8.0, 0.0)] + \
               [StartBatch("B", "fake_basil", age, 500.0) for age in (20.0, 5.0)]

    def equipment_ids(self):
        return ("boiler", "A.vents", "B.vents")

    def fallback_climate(self):
        sp = ClimateSetpoints(5.0, 5.0, 0.0, 0.0, 0.0, "closed", (), 0.0)
        return {c: sp for c in self.compartment_ids}

    def fallback_energy(self):
        return EnergySettings(0.0, "auto", "auto", 0.0)

    def check_climate(self, c, sp: ClimateSetpoints):
        if not -5 <= sp.heat_day_c <= 35 or not -5 <= sp.heat_night_c <= 35:
            raise RuleError("heating setpoints must be -5 to 35 C")
        if not 0 <= sp.vent_min_pct <= sp.vent_max_pct <= 100:
            raise RuleError("need 0 <= vent_min_pct <= vent_max_pct <= 100")
        if not 0 <= sp.co2_ppm <= 1500:
            raise RuleError("co2_ppm must be 0 to 1500")

    def check_energy(self, s: EnergySettings):
        if s.chp_load != 0:
            raise RuleError("the fake facility has no CHP")

    def apply_effect(self, e: EquipmentEffect):
        if e.target == "boiler":
            self.boiler_factor = e.capacity_factor

    def clear_effect(self, target):
        if target == "boiler":
            self.boiler_factor = 1.0

    def receive_co2(self, kg):
        self.co2_store_kg = min(2000.0, self.co2_store_kg + kg)

    def substep(self, hour, dt_h, climate, energy, loads: dict[str, CropLoad]):
        out = {}
        t_out = self.outside_c(hour)
        for c in self.compartment_ids:
            sp = climate[c]
            day = 8 <= hour % 24 < 16
            target = sp.heat_day_c if day else sp.heat_night_c
            demand_kw = max(0.0, 6.0 * (target - t_out))
            supplied = min(demand_kw, 150.0 * self.boiler_factor)
            goal = t_out + supplied / 6.0 + self.sun(hour) / 100.0
            self.temp[c] += (goal - self.temp[c]) * min(1.0, dt_h * 2.0)
            self._heat[c] = self._heat.get(c, 0.0) + supplied * dt_h
            self._gas += supplied * dt_h * 0.105
            dosing = sp.co2_ppm > 0 and self.co2_store_kg > 0
            if dosing:
                self.co2_store_kg = max(0.0, self.co2_store_kg - 2.0 * dt_h)
            lamps = (hour % 24) in sp.lamp_hours
            out[c] = ClimateSample(hour, dt_h, self.temp[c], 75.0, sp.co2_ppm if dosing else 420.0,
                                   self.sun(hour) * 0.7 + (200.0 * sp.lamp_intensity_pct / 100 if lamps else 0.0), day)
        return out

    def end_hour(self, hour):
        m = Metered(hour, gas_m3=self._gas, heat_produced_kwh=sum(self._heat.values()),
                    heat_delivered_kwh=dict(self._heat), gas_eur_per_m3=0.6)
        self._gas, self._heat = 0.0, {}
        alarms = [Alarm(hour, "frost_risk", c, f"{c} is at {t:.1f} C") for c, t in self.temp.items() if t < 2.0]
        if self.co2_store_kg <= 0:
            alarms.append(Alarm(hour, "stock_low", "co2_store", "CO2 store is empty"))
        return m, alarms

    def view(self, hour, rng: Rng):
        return {"compartments": {c: {"temp_c": round(self.temp[c] + rng.stream(c).normal(0, 0.2), 2)}
                                 for c in self.compartment_ids},
                "energy_centre": {"co2_store_kg": round(self.co2_store_kg, 1), "boiler_factor": self.boiler_factor},
                "outside_temp_c": round(self.outside_c(hour), 2)}

    def forecast(self, hour, hours):
        return {"outside_temp_c": [round(self.outside_c(hour + i), 1) for i in range(hours)]}

    def rules(self):
        return {"note": "fake facility", "fallback": asdict(self.fallback_climate()["A"])}


@dataclass
class _Order:
    id: str
    item: str
    quantity: float
    arrives: int


@dataclass
class FakeBusiness:
    rng: Rng
    crop_ids: tuple[str, ...]
    cash: float = 10_000.0
    start_cash: float = 10_000.0
    workers: int = 3
    seedlings: dict[str, int] = field(default_factory=dict)
    orders: list[_Order] = field(default_factory=list)
    queue: list[Task] = field(default_factory=list)
    progress: dict[str, float] = field(default_factory=dict)
    entries: list[LedgerEntry] = field(default_factory=list)
    seq: int = 0
    boiler_trip_hour: int = 0

    def __post_init__(self):
        self.seedlings = {c: 20_000 for c in self.crop_ids}
        self.boiler_trip_hour = self.rng.stream("events").randint(30, 60)

    def _charge(self, hour, category, eur, note=""):
        e = LedgerEntry(hour, category, eur, note)
        self.entries.append(e)
        self.cash += eur
        return e

    def start_hour(self, hour):
        if hour == self.boiler_trip_hour:
            return [EquipmentEffect("boiler", 0.0, until_hour=hour + 12)], [Alarm(hour, "equipment", "boiler", "Boiler tripped")]
        return [], []

    def end_hour(self, hour, metered: Metered):
        self._charge(hour, "gas", -metered.gas_m3 * metered.gas_eur_per_m3)
        self._charge(hour, "wages", -self.workers * 2.0)
        deliveries, done, alarms = [], [], []
        for o in [o for o in self.orders if o.arrives == hour]:
            self.orders.remove(o)
            deliveries.append(Delivery(o.id, o.item, o.quantity, hour))
            self._charge(hour, "co2" if o.item == "co2_kg" else "seedlings", -0.2 * o.quantity)
            alarms.append(Alarm(hour, "delivery", o.id, f"Order {o.id} delivered"))
        hours = float(self.workers) if 8 <= hour % 24 < 16 else 0.0
        while self.queue and hours > 0:
            t = self.queue[0]
            need = t.worker_hours - self.progress.get(t.id, 0.0)
            use = min(need, hours)
            self.progress[t.id] = self.progress.get(t.id, 0.0) + use
            hours -= use
            if self.progress[t.id] >= t.worker_hours - 1e-9:
                done.append(self.queue.pop(0))
        return HourEnd(tuple(deliveries), tuple(done), tuple(alarms))

    def place_order(self, hour, item, quantity):
        if item != "co2_kg" and not (item.startswith("seedlings:") and item.split(":", 1)[1] in self.crop_ids):
            raise RuleError(f"unknown item {item!r}")
        if quantity < 100:
            raise RuleError("minimum order is 100")
        self.seq += 1
        o = _Order(f"O{self.seq}", item, quantity, hour + 48)
        self.orders.append(o)
        return {"order_id": o.id, "arrives_hour": o.arrives}

    def cancel_order(self, hour, order_id):
        raise RuleError("the fake business cannot cancel")

    def hire(self, hour, workers):
        if workers < 1:
            raise RuleError("workers must be at least 1")
        self.workers += workers
        self._charge(hour, "hiring", -100.0 * workers)
        return {"workers": self.workers}

    def release(self, hour, workers):
        if not 1 <= workers <= self.workers:
            raise RuleError("cannot release that many")
        self.workers -= workers
        return {"workers": self.workers}

    def take_seedlings(self, hour, crop_id, count):
        if self.seedlings.get(crop_id, 0) < count:
            raise RuleError(f"only {self.seedlings.get(crop_id, 0)} {crop_id} seedlings in stock")
        self.seedlings[crop_id] -= count

    def queue_task(self, hour, kind, target, worker_hours, detail):
        self.seq += 1
        if kind == "repair":
            worker_hours = 2.0
            self._charge(hour, "repairs", -300.0)
        t = Task(f"T{self.seq}", kind, target, float(worker_hours), hour, dict(detail))
        self.queue.append(t)
        return t

    def sell(self, hour, h: HarvestResult):
        return self._charge(hour, "harvest_revenue", h.units * 0.5 * h.price_factor if h.sellable else 0.0)

    def cash_eur(self):
        return self.cash

    def profit_eur(self):
        return self.cash - self.start_cash

    def totals(self):
        out: dict[str, float] = {}
        for e in self.entries:
            out[e.category] = out.get(e.category, 0.0) + e.eur
        return out

    def view(self, hour, rng):
        return {"cash_eur": round(self.cash, 2), "workers": self.workers, "seedlings": dict(self.seedlings),
                "open_orders": [asdict(o) for o in self.orders], "task_queue": [t.id for t in self.queue]}

    def rules(self):
        return {"note": "fake business"}


def build(env: dict[str, Any], rng: Rng) -> Modules:
    horizon_h = round(float(env.get("horizon_days", 42)) * 24)
    facility = FakeFacility(rng.stream("facility"))
    growth = {"fake_lettuce": FakeCrop("fake_lettuce"), "fake_basil": FakeCrop("fake_basil", repeated=True)}
    business = FakeBusiness(rng.stream("business"), tuple(growth))
    return Modules(facility, business, growth, horizon_h, int(env.get("substeps_per_hour", 12)),
                   {"facility": {"floor_m2": (900.0, 1100.0)}})
