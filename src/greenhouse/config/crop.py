"""Schema for crop data files (`data/crops/*.toml`, spec 3.1).

`parse_crop(raw, source)` turns one TOML document into a frozen `CropSpec`.
Every key is read through `Table`, so a missing key, a stray key or an
out-of-range value fails with the file and key named. No crop value lives
here: this module only says which keys exist and what makes them valid.

The `[growth]` table belongs to the growth model named by `growth_model`.
Each model registers its own parameter parser in `GROWTH_PARAMS`; the model
classes themselves live in `world/crop.py` under the same names.

`dataclasses.asdict(spec)` is plain JSON, which `get_rules` publishes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from .base import ConfigError, Table
from .curves import Curve, parse_curve

SCHEMA = "crop/1"
HARVEST_MODES = ("single", "repeated")
UNITS = ("head", "kg")
# Daily climate signals a stress counter can watch (computed in world/crop.py):
#   dli_excess     the day's light integral, mol m-2 d-1 (the curve's threshold sets the excess)
#   temp_day_mean  mean air temperature during the photoperiod, C
#   temp_min       lowest air temperature of the day, C
SIGNALS = ("dli_excess", "temp_day_mean", "temp_min")


# -- sections ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Cycle:
    harvest_mode: Literal["single", "repeated"]
    nominal_days: float               # transplant -> ready under the target climate (published)
    min_days_before_end: int          # planting is refused if fewer days remain
    ready_fresh_weight_g: float       # per plant; the batch becomes "ready" at this weight
    regrow_fraction: float | None = None   # repeated only: share of the weight left after a cut
    regrow_days: float | None = None       # repeated only: cut -> ready again under the target climate
    max_cuts: int | None = None            # repeated only


@dataclass(frozen=True)
class Planting:
    density_per_m2: float
    transplant_dry_weight_g: float    # per plant, at planting
    seedling_cost_eur: float          # per plant
    plant_worker_hours_per_1000: float
    harvest_worker_hours_per_1000: float


@dataclass(frozen=True)
class Transpiration:
    """Van Henten (1994) canopy transpiration: conductance times the vapour
    concentration deficit, with the saturation concentration in his form
    c1 / (R (T + c_T)) * exp(c2 T / (T + c3))."""
    canopy_conductance_m_s: float
    vapour_c1_j_m3: float
    gas_constant_j_kmol_k: float
    celsius_to_kelvin: float
    vapour_c2: float
    vapour_c3_c: float


@dataclass(frozen=True)
class LeafyVanHentenParams:
    """Parameters of the `leafy_vanhenten` model; symbols from Van Henten (1994)."""
    dry_matter_fraction: float               # dry / fresh weight
    yield_factor: float                      # c_alpha_beta, kg dry matter per kg CO2
    light_use_efficiency_kg_j: float         # c_epsilon
    radiation_j_per_umol: float              # PAR umol at crop level -> the model's radiation input
    canopy_closure_m2_kg: float              # c_pl,d
    boundary_conductance_m_s: float          # g_bnd
    stomatal_conductance_m_s: float          # g_stm
    carboxylation_conductance_max_m_s: float # peak of g_car
    temperature: Curve                       # g_car = max * temperature(T)
    co2_kg_m3_per_ppm: float
    co2_saturation_ppm: float                # CO2 above this adds no growth
    co2_compensation_kg_m3: float            # c_Gamma at the reference temperature
    co2_compensation_q10: float
    co2_compensation_ref_c: float
    respiration_dry_per_s: float             # c_resp,d
    respiration_co2_per_s: float             # c_resp,c
    respiration_q10: float
    respiration_ref_c: float
    transpiration: Transpiration


GrowthParams = LeafyVanHentenParams


@dataclass(frozen=True)
class ClimateTargets:
    """Advice published to the agent; not enforced. Also the climate under which
    `nominal_days` holds, and the one used to pre-grow batches older than the episode."""
    day_temp_c: tuple[float, float]
    night_temp_c: tuple[float, float]
    co2_ppm: tuple[float, float]
    dli_mol_m2_d: tuple[float, float]
    rh_pct: tuple[float, float]
    photoperiod_h: float


@dataclass(frozen=True)
class StressCounter:
    name: str                          # as written in the crop file, e.g. "tipburn"
    signal: str                        # one of SIGNALS
    curve: Curve                       # signal -> stress added per day


@dataclass(frozen=True)
class Stress:
    counters: tuple[StressCounter, ...]
    frost_kill_c: float                # the batch is lost below this air temperature
    ready_loss_per_day: float          # quality lost per day a ready batch waits


@dataclass(frozen=True)
class Grade:
    name: str
    min_quality: float
    price_factor: float


@dataclass(frozen=True)
class Market:
    unit: Literal["head", "kg"]
    min_sellable_fresh_weight_g: float  # per plant harvested (per cut for repeated crops)
    grades: tuple[Grade, ...]           # descending min_quality, the last at 0

    def grade(self, quality: float) -> Grade:
        for g in self.grades:
            if quality >= g.min_quality:
                return g
        return self.grades[-1]


@dataclass(frozen=True)
class EstimateNoise:
    """Error of what `get_batches` shows, drawn from the caller's stream."""
    weight_rel_sigma: float            # multiplicative, on fresh weight
    quality_sigma: float               # additive, on quality


@dataclass(frozen=True)
class CropSpec:
    schema: str
    id: str
    name: str
    growth_model: str
    cycle: Cycle
    planting: Planting
    growth: GrowthParams
    climate_targets: ClimateTargets
    stress: Stress
    market: Market
    estimate: EstimateNoise


# -- growth-model parameter parsers -----------------------------------------------------

def _parse_transpiration(t: Table) -> Transpiration:
    tr = Transpiration(
        canopy_conductance_m_s=_pos(t, "canopy_conductance_m_s"),
        vapour_c1_j_m3=_pos(t, "vapour_c1_j_m3"),
        gas_constant_j_kmol_k=_pos(t, "gas_constant_j_kmol_k"),
        celsius_to_kelvin=_pos(t, "celsius_to_kelvin"),
        vapour_c2=_pos(t, "vapour_c2"),
        vapour_c3_c=_pos(t, "vapour_c3_c"),
    )
    t.done()
    return tr


def _parse_leafy_vanhenten(t: Table) -> LeafyVanHentenParams:
    p = LeafyVanHentenParams(
        dry_matter_fraction=_fraction(t, "dry_matter_fraction"),
        yield_factor=_pos(t, "yield_factor"),
        light_use_efficiency_kg_j=_pos(t, "light_use_efficiency_kg_j"),
        radiation_j_per_umol=_pos(t, "radiation_j_per_umol"),
        canopy_closure_m2_kg=_pos(t, "canopy_closure_m2_kg"),
        boundary_conductance_m_s=_pos(t, "boundary_conductance_m_s"),
        stomatal_conductance_m_s=_pos(t, "stomatal_conductance_m_s"),
        carboxylation_conductance_max_m_s=_pos(t, "carboxylation_conductance_max_m_s"),
        temperature=parse_curve(t.sub("temperature")),
        co2_kg_m3_per_ppm=_pos(t, "co2_kg_m3_per_ppm"),
        co2_saturation_ppm=_pos(t, "co2_saturation_ppm"),
        co2_compensation_kg_m3=t.num("co2_compensation_kg_m3", lo=0),
        co2_compensation_q10=_pos(t, "co2_compensation_q10"),
        co2_compensation_ref_c=t.num("co2_compensation_ref_c"),
        respiration_dry_per_s=t.num("respiration_dry_per_s", lo=0),
        respiration_co2_per_s=t.num("respiration_co2_per_s", lo=0),
        respiration_q10=_pos(t, "respiration_q10"),
        respiration_ref_c=t.num("respiration_ref_c"),
        transpiration=_parse_transpiration(t.sub("transpiration")),
    )
    t.done()
    return p


# Growth model name -> parser for its [growth] table. world/crop.py registers the
# model class under the same name; a test checks the two registries agree.
GROWTH_PARAMS: dict[str, Callable[[Table], GrowthParams]] = {
    "leafy_vanhenten": _parse_leafy_vanhenten,
}


# -- the file ---------------------------------------------------------------------------

def parse_crop(raw: dict[str, Any], source: str) -> CropSpec:
    t = Table(raw, source)
    schema = t.str("schema", choices=(SCHEMA,))
    crop_id = t.str("id")
    name = t.str("name")
    model = t.str("growth_model", choices=tuple(GROWTH_PARAMS))
    spec = CropSpec(
        schema=schema,
        id=crop_id,
        name=name,
        growth_model=model,
        cycle=_parse_cycle(t.sub("cycle")),
        planting=_parse_planting(t.sub("planting")),
        growth=GROWTH_PARAMS[model](t.sub("growth")),
        climate_targets=_parse_targets(t.sub("climate_targets")),
        stress=_parse_stress(t.sub("stress")),
        market=_parse_market(t.sub("market")),
        estimate=_parse_estimate(t.sub("estimate")),
    )
    t.done()
    return spec


def _parse_cycle(t: Table) -> Cycle:
    mode = t.str("harvest_mode", choices=HARVEST_MODES)
    common = dict(
        harvest_mode=mode,
        nominal_days=_pos(t, "nominal_days"),
        min_days_before_end=t.int("min_days_before_end", lo=0),
        ready_fresh_weight_g=_pos(t, "ready_fresh_weight_g"),
    )
    if mode == "repeated":
        regrow = _fraction(t, "regrow_fraction")
        if regrow >= 1:
            raise _fail(t, "regrow_fraction", f"must be < 1, got {regrow}")
        cycle = Cycle(**common, regrow_fraction=regrow, regrow_days=_pos(t, "regrow_days"),
                      max_cuts=t.int("max_cuts", lo=1))
    else:
        cycle = Cycle(**common)       # repeated-only keys stay unread, so done() rejects them
    t.done()
    return cycle


def _parse_planting(t: Table) -> Planting:
    p = Planting(
        density_per_m2=_pos(t, "density_per_m2"),
        transplant_dry_weight_g=_pos(t, "transplant_dry_weight_g"),
        seedling_cost_eur=t.num("seedling_cost_eur", lo=0),
        plant_worker_hours_per_1000=t.num("plant_worker_hours_per_1000", lo=0),
        harvest_worker_hours_per_1000=t.num("harvest_worker_hours_per_1000", lo=0),
    )
    t.done()
    return p


def _parse_targets(t: Table) -> ClimateTargets:
    c = ClimateTargets(
        day_temp_c=_pair(t, "day_temp_c"),
        night_temp_c=_pair(t, "night_temp_c"),
        co2_ppm=_pair(t, "co2_ppm"),
        dli_mol_m2_d=_pair(t, "dli_mol_m2_d"),
        rh_pct=_pair(t, "rh_pct"),
        photoperiod_h=t.num("photoperiod_h", lo=0, hi=24),
    )
    if c.photoperiod_h <= 0:
        raise _fail(t, "photoperiod_h", f"must be > 0, got {c.photoperiod_h}")
    t.done()
    return c


def _parse_stress(t: Table) -> Stress:
    counters = []
    for key, value in t.raw.items():           # TOML order, so the counter order is stable
        if not isinstance(value, dict):
            continue                           # scalars are read below; done() catches strays
        sub = t.sub(key)
        signal = sub.str("signal", choices=SIGNALS)
        counters.append(StressCounter(name=key, signal=signal, curve=parse_curve(sub)))
    s = Stress(
        counters=tuple(counters),
        frost_kill_c=t.num("frost_kill_c"),
        ready_loss_per_day=t.num("ready_loss_per_day", lo=0),
    )
    t.done()
    return s


def _parse_market(t: Table) -> Market:
    unit = t.str("unit", choices=UNITS)
    min_sellable = t.sub("min_sellable")
    weight = _pos(min_sellable, "fresh_weight_g")
    min_sellable.done()
    grades = []
    for i, g in enumerate(t.list("grades")):
        gt = Table(g, t.source, f"{_full(t, 'grades')}[{i}]")
        grades.append(Grade(name=gt.str("name"), min_quality=_fraction(gt, "min_quality"),
                            price_factor=gt.num("price_factor", lo=0)))
        gt.done()
    qualities = [g.min_quality for g in grades]
    if not grades or qualities != sorted(qualities, reverse=True) or len(set(qualities)) != len(qualities) \
            or qualities[-1] != 0:
        raise _fail(t, "grades", "needs strictly descending min_quality ending at 0")
    m = Market(unit=unit, min_sellable_fresh_weight_g=weight, grades=tuple(grades))
    t.done()
    return m


def _parse_estimate(t: Table) -> EstimateNoise:
    e = EstimateNoise(weight_rel_sigma=t.num("weight_rel_sigma", lo=0),
                      quality_sigma=t.num("quality_sigma", lo=0))
    t.done()
    return e


# -- helpers ----------------------------------------------------------------------------

def _fail(t: Table, key: str, msg: str) -> ConfigError:
    return ConfigError(f"{t.source}: '{_full(t, key)}' {msg}")


def _full(t: Table, key: str) -> str:
    return f"{t.prefix}.{key}" if t.prefix else key


def _pos(t: Table, key: str) -> float:
    """A strictly positive number."""
    v = t.num(key, lo=0)
    if v <= 0:
        raise _fail(t, key, f"must be > 0, got {v}")
    return v


def _fraction(t: Table, key: str) -> float:
    return t.num(key, lo=0, hi=1)


def _pair(t: Table, key: str) -> tuple[float, float]:
    """`[low, high]` with low <= high."""
    v = t.list(key)
    if len(v) != 2 or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in v) or v[0] > v[1]:
        raise _fail(t, key, f"must be [low, high] numbers with low <= high, got {v!r}")
    return float(v[0]), float(v[1])
