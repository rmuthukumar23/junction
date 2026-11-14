"""The shared types between the greenhouse modules.

Everything that crosses a module boundary owned by a different person is
defined here, so the crop, climate/energy and operations workstreams can be
built in parallel and composed by `world/sim.py` without editing each other's
files. Owners are in docs/collaboration/README.md.

Changing this file changes everyone's interface: open a PR that touches only
this file, tag every owner, and merge it before code that depends on it.

Conventions:
  * Time is an integer hour since episode start (`hour`), plus `dt_h` (hours,
    float) for sub-steps. No datetimes and no wall-clock time.
  * SI-ish units, written into every field name: _c, _pct, _ppm, _kw, _kwh,
    _kg, _m2, _eur, _h. Money is EUR; income positive, cost negative.
  * Randomness only from `envkit.rng.Rng` streams passed in by the caller.
    A read must never change the world, so a noisy observation draws from a
    stream named after what it observes, e.g.
    `rng.stream(f"estimate/{batch.id}/{hour}")`. `Rng.stream` is a pure
    function of (seed, name), so reading twice gives the same value and an
    extra read call shifts no other draw.
  * No values in code: every number a module needs comes from a spec object
    built from a data file.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from envkit.rng import Rng

# -- crop <-> climate -------------------------------------------------------------------

@dataclass(frozen=True)
class ClimateSample:
    """The true climate a batch experiences during one sub-step.
    Produced by world/climate.py (Emre), consumed by world/crop.py (Lucas)."""
    hour: int
    dt_h: float
    temp_c: float
    rh_pct: float
    co2_ppm: float
    par_umol_m2_s: float      # at crop level: sun through the cover plus lamps
    is_day: bool              # the photoperiod as the controller defines it


BatchStatus = Literal["growing", "ready", "harvested", "lost"]


@dataclass
class BatchState:
    """One planted batch. Created and advanced by the crop's GrowthModel.
    Generic fields are here; anything model-specific goes in `model_state`."""
    id: str
    crop_id: str
    compartment_id: str
    area_m2: float
    planted_hour: int                     # may be negative for batches older than the episode
    status: BatchStatus = "growing"
    stress: dict[str, float] = field(default_factory=dict)       # counter name -> value, as named in the crop file
    model_state: dict[str, float] = field(default_factory=dict)  # e.g. {"dry_weight_g_m2": ...}
    cuts: int = 0                         # repeated-harvest crops
    ready_hour: int | None = None         # hour it first became ready


@dataclass(frozen=True)
class BatchEstimate:
    """What the agent may see about a batch (noisy where the crop file says so)."""
    fresh_weight_g_per_unit: float
    units: float                          # heads, or kg for kg-sold crops
    days_to_ready: float | None           # None once ready, harvested or lost
    quality: float                        # 0..1


@dataclass(frozen=True)
class HarvestResult:
    """Produced by GrowthModel.harvest, priced by operations/ledger (Rowan)."""
    batch_id: str
    crop_id: str
    units: float
    unit: str                             # "head" | "kg", from the crop file
    fresh_weight_g_per_unit: float
    quality: float                        # 0..1, sets the grade via the crop file
    sellable: bool                        # False below the crop's minimum sellable weight
    grade: str = ""                       # grade name from the crop file
    price_factor: float = 0.0             # the grade's factor on the market base price; 0 if not sellable


class GrowthModel(Protocol):
    """A crop growth model, registered by name and selected by `growth_model`
    in a crop data file. One instance per crop spec, built by
    `greenhouse.world.crop.model_for(spec)` (Lucas)."""

    crop_id: str

    def new_batch(self, batch_id: str, compartment_id: str, area_m2: float,
                  planted_hour: int, age_days: float = 0.0) -> BatchState: ...

    def step(self, batch: BatchState, climate: ClimateSample) -> None:
        """Advance growth and stress by climate.dt_h; may set status to ready or lost."""

    def estimate(self, batch: BatchState, hour: int, rng: Rng) -> BatchEstimate:
        """`rng` is a fresh stream for this batch and hour (see module notes)."""

    def harvest(self, batch: BatchState, hour: int) -> HarvestResult:
        """Single-cut crops become 'harvested'; repeated crops regrow per the crop file."""

    def transpiration_kg_h(self, batch: BatchState, climate: ClimateSample) -> float:
        """Water vapour the batch adds to the compartment air (for the humidity balance)."""

    def co2_uptake_kg_h(self, batch: BatchState, climate: ClimateSample) -> float:
        """CO2 the batch takes from the compartment air (for the CO2 balance)."""

    def labour_hours(self, action: Literal["plant", "harvest"], area_m2: float) -> float:
        """Worker-hours to plant or harvest this area, from the crop file."""

    def seedlings_needed(self, area_m2: float) -> int:
        """Seedlings consumed by planting this area (density from the crop file)."""

    def min_days_before_end(self) -> float:
        """Planting is refused when fewer days than this remain in the episode."""

    def describe(self) -> dict[str, Any]:
        """The crop's published rules for get_rules: JSON-ready, no hidden values."""


# -- money -------------------------------------------------------------------------------

LedgerCategory = Literal[
    "harvest_revenue", "electricity_sold",
    "gas", "electricity_bought", "co2", "wages", "hiring", "repairs",
    "seedlings", "orders", "fines",
]


@dataclass(frozen=True)
class LedgerEntry:
    """One money movement. Every module that costs or earns money produces these;
    world/ledger.py (Rowan) records them. Income positive, cost negative."""
    hour: int
    category: LedgerCategory
    eur: float
    note: str = ""


@dataclass(frozen=True)
class Metered:
    """Physical energy and CO2 flows over one hour, from world/energy.py (Emre).
    The ledger prices them; conservation tests check them."""
    hour: int
    gas_m3: float = 0.0
    electricity_import_kwh: float = 0.0
    electricity_export_kwh: float = 0.0
    external_co2_kg: float = 0.0
    co2_from_store_kg: float = 0.0
    heat_produced_kwh: float = 0.0
    heat_delivered_kwh: dict[str, float] = field(default_factory=dict)  # compartment id -> kWh
    heat_lost_kwh: float = 0.0
    buffer_change_kwh: float = 0.0
    # that hour's energy prices, from the energy-price series (Emre), so the ledger
    # (Rowan) can price the flows without reading the series itself
    gas_eur_per_m3: float = 0.0
    import_eur_per_kwh: float = 0.0
    export_eur_per_kwh: float = 0.0


# -- equipment, events, alarms -------------------------------------------------------------

@dataclass(frozen=True)
class EquipmentEffect:
    """A change to one piece of equipment, applied by world/events.py (Rowan) and
    honoured by world/energy.py and world/climate.py (Emre). Equipment ids are
    "chp", "boiler", "buffer", "external_co2", "grid", or "<compartment>.<part>"
    for compartment equipment ("A.vents", "A.lamps", "A.screen", "A.cover")."""
    target: str
    capacity_factor: float = 1.0          # 0 = failed, 1 = normal
    leakage_factor: float = 1.0           # for cover damage
    until_hour: int | None = None         # None = until repaired


AlarmKind = Literal["equipment", "delivery", "frost_risk", "batch_ready", "batch_lost", "stock_low", "staff",
                    "price"]


@dataclass(frozen=True)
class Alarm:
    """Something the agent should notice. Any alarm raised during an `advance`
    stops it at the end of that hour (spec 4)."""
    hour: int
    kind: AlarmKind
    target: str
    text: str


# -- what a module may expose to the agent --------------------------------------------------

class Observable(Protocol):
    """A module that contributes to get_status. `view` returns JSON-ready data with
    only what an operator could see (sensor values, not true hidden state).
    `rng` is a fresh stream for this module and hour (see module notes)."""

    def view(self, hour: int, rng: Rng) -> dict[str, Any]: ...


class RuleError(ValueError):
    """An agent action is not allowed. Raise it before changing anything; the
    message is shown to the agent and should say what to fix."""


# -- standing settings the agent controls (spec 5) -------------------------------------------

ScreenMode = Literal["auto", "open", "closed"]
BoilerMode = Literal["auto", "off"]
BufferMode = Literal["auto", "charge", "hold", "discharge"]


@dataclass(frozen=True)
class ClimateSetpoints:
    """One compartment's standing setpoints (`set_climate`). The controller (Emre)
    turns them into actuator positions every sub-step."""
    heat_day_c: float
    heat_night_c: float
    vent_min_pct: float
    vent_max_pct: float
    co2_ppm: float                        # dosing target; 0 = no dosing
    screen: ScreenMode
    lamp_hours: tuple[int, ...]           # hours of the day (0-23) the lamps are on
    lamp_intensity_pct: float


@dataclass(frozen=True)
class EnergySettings:
    """The energy centre's standing settings (`set_energy`)."""
    chp_load: float                       # 0 = off, else the CHP's min_load to 1
    boiler: BoilerMode
    buffer: BufferMode
    external_co2_kg_h: float
    priority: dict[str, int] = field(default_factory=dict)       # compartment -> level; higher is served first
    heat_cap_kw: dict[str, float] = field(default_factory=dict)  # compartment -> cap when supply is short
    co2_cap_kg_h: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class StartBatch:
    compartment_id: str
    crop_id: str
    age_days: float
    area_m2: float


@dataclass(frozen=True)
class CropLoad:
    """What the crops in one compartment do to its air, summed over batches."""
    planted_m2: float
    transpiration_kg_h: float
    co2_uptake_kg_h: float


# -- the two subsystems sim.py composes ---------------------------------------------------------

class FacilityModel(Protocol):
    """Weather, compartments, controller and energy centre (Emre).

    Built by `greenhouse.world.energy.build_facility(facility, climate,
    energy_prices, rng)` from the resolved specs. sim.py calls, every hour:
    `substep` (12 times by default), then `end_hour`."""

    compartment_ids: tuple[str, ...]

    def floor_area_m2(self, compartment_id: str) -> float: ...

    def crop_id(self, compartment_id: str) -> str:
        """The crop this compartment grows (facility file)."""

    def start_batches(self) -> list[StartBatch]:
        """Batches standing at hour 0 (facility file `start_batches`)."""

    def equipment_ids(self) -> tuple[str, ...]:
        """Every id an EquipmentEffect or a repair may target."""

    def fallback_climate(self) -> dict[str, ClimateSetpoints]:
        """The facility file's [fallback]: the baseline the facility is handed over
        with at hour 0, and so what a player who never changes anything runs on (D5).
        Settings stand until changed, also after a stop."""

    def fallback_energy(self) -> EnergySettings: ...

    def check_climate(self, compartment_id: str, setpoints: ClimateSetpoints) -> None:
        """Raise RuleError if a setpoint is outside equipment limits."""

    def check_energy(self, settings: EnergySettings) -> None: ...

    def apply_effect(self, effect: EquipmentEffect) -> None: ...

    def clear_effect(self, target: str) -> None:
        """A repair finished: the equipment works normally again."""

    def receive_co2(self, kg: float) -> None:
        """A CO2 delivery arrived: add it to the store (capped by its capacity)."""

    def substep(self, hour: int, dt_h: float, climate: dict[str, ClimateSetpoints],
                energy: EnergySettings, loads: dict[str, CropLoad]) -> dict[str, ClimateSample]:
        """Run the controller, the energy centre and every compartment's balances
        for dt_h; return the true climate per compartment."""

    def end_hour(self, hour: int) -> tuple[Metered, list[Alarm]]:
        """Close the hour: metered flows with that hour's prices, and any alarms
        (equipment state, frost risk, CO2 store low)."""

    def view(self, hour: int, rng: Rng) -> dict[str, Any]:
        """Sensor readings (with noise) and exact equipment state, per compartment
        and for the energy centre."""

    def forecast(self, hour: int, hours: int) -> dict[str, Any]:
        """Weather and energy-price forecast issued at `hour`; a pure function of (seed, hour)."""

    def rules(self) -> dict[str, Any]:
        """Published mechanisms, equipment limits and hidden-parameter ranges."""


TaskKind = Literal["plant", "harvest", "repair"]


@dataclass(frozen=True)
class Task:
    """Work that needs worker-hours. Queued by sim.py, scheduled by the business (Rowan)."""
    id: str
    kind: TaskKind
    target: str                           # compartment (plant), batch id (harvest), equipment id (repair)
    worker_hours: float
    queued_hour: int
    detail: dict[str, Any] = field(default_factory=dict)   # e.g. {"area_m2": 500.0, "crop_id": "broccoli_micro"}


@dataclass(frozen=True)
class Delivery:
    order_id: str
    item: str                             # "co2_kg" or "seedlings:<crop_id>"
    quantity: float
    hour: int


@dataclass(frozen=True)
class HourEnd:
    """What the business did at the end of an hour."""
    deliveries: tuple[Delivery, ...] = ()
    completed: tuple[Task, ...] = ()
    alarms: tuple[Alarm, ...] = ()
    # Equipment effects that changed this hour, e.g. a finished repair that ends an
    # outage a few hours later instead of at once. sim.py applies them after the
    # completed tasks; a completed repair whose target is not listed here is cleared.
    effects: tuple[EquipmentEffect, ...] = ()


class BusinessModel(Protocol):
    """Market, orders, stock, staff, tasks, events and the ledger (Rowan).

    Built by `greenhouse.world.business.build_business(market, events,
    crop_ids, equipment_ids, horizon_h, rng)` from the resolved specs. sim.py calls, every
    hour: `start_hour` (events due), the facility's sub-steps, then `end_hour`.
    sim.py routes CO2 deliveries to the facility and runs completed tasks."""

    def start_hour(self, hour: int) -> tuple[list[EquipmentEffect], list[Alarm]]:
        """Events that start now, as equipment effects for the facility and alarms."""

    def end_hour(self, hour: int, metered: Metered) -> HourEnd:
        """Price the metered energy, charge wages, progress the task queue with this
        hour's worker-hours, deliver arriving orders."""

    def place_order(self, hour: int, item: str, quantity: float) -> dict[str, Any]: ...

    def cancel_order(self, hour: int, order_id: str) -> dict[str, Any]: ...

    def hire(self, hour: int, workers: int) -> dict[str, Any]: ...

    def release(self, hour: int, workers: int) -> dict[str, Any]: ...

    def take_seedlings(self, hour: int, crop_id: str, count: int) -> None:
        """Consume seedlings from stock; RuleError if there are not enough."""

    def queue_task(self, hour: int, kind: TaskKind, target: str, worker_hours: float | None,
                   detail: dict[str, Any]) -> Task:
        """Queue work. worker_hours None means the business sets it (repairs, from the
        market file); a repair's fee is charged here."""

    def sell(self, hour: int, harvest: HarvestResult) -> LedgerEntry:
        """Record a harvest's revenue (0 if not sellable) and return the entry."""

    def cash_eur(self) -> float: ...

    def profit_eur(self) -> float: ...

    def totals(self) -> dict[str, float]:
        """Money by LedgerCategory since the start."""

    def view(self, hour: int, rng: Rng) -> dict[str, Any]:
        """Stock, open orders with expected arrival, staff, task queue, money."""

    def rules(self) -> dict[str, Any]:
        """Published prices, lead times, minimum orders, wages, event types and rates."""
