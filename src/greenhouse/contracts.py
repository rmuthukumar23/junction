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


class GrowthModel(Protocol):
    """A crop growth model, registered by name and selected by `growth_model`
    in a crop data file. One instance per crop spec."""

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


AlarmKind = Literal["equipment", "delivery", "frost_risk", "batch_ready", "stock_low", "staff", "price"]


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
