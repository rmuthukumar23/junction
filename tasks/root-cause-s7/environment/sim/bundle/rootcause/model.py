"""The public physics.

Everything here is known to the player: `Greenhouse.rules()` publishes every
parameter, and the reference planner runs these same functions on its own
*estimate* of a zone. Nothing in this module holds state.

Units: water in litres (L), dissolved material in grams (g), concentration in
g/L, electrical conductivity in dS/m, temperature in degrees C, harvest in kg,
money in EUR. Masses are stored; concentrations and EC are always derived.

A zone is one well-mixed volume: the substrate slabs and the drain return tank
of a closed recirculating loop, counted once. Useful nutrients and unwanted
salts are separate masses dissolved in it.

Simplifications (see docs/GREENHOUSE.md for the full list): a single lumped
"nutrient" and a single lumped "salt"; EC linear in total dissolved mass;
perfect mixing; no pH, no specific-ion toxicity, no disease; one decision and
one update per day.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, NamedTuple


@dataclass(frozen=True)
class Params:
    horizon_days: int = 14

    # -- water -------------------------------------------------------------------
    capacity_l: float = 1500.0          # most solution a zone's loop can hold; more overflows to waste
    dead_volume_l: float = 300.0        # bound in the substrate: cannot be transpired or pumped out
    comfort_volume_l: float = 750.0     # below this, plants cannot take up all the water they demand
    transp_ref_temp_c: float = 24.0     # transpiration demand is the zone's base rate at this temperature
    transp_heat_slope: float = 0.06     # + fraction of base demand per degree above the reference
    transp_cool_slope: float = 0.02     # - fraction of base demand per degree below the reference
    transp_min_factor: float = 0.7
    canopy_floor: float = 0.4           # a crop at condition 0 still transpires this fraction of demand

    # -- chemistry ---------------------------------------------------------------
    ec_per_g_l: float = 1.5             # dS/m per g/L of dissolved nutrients + salts (both count equally)
    source_salt_g_l: float = 0.15       # unwanted salts in every litre of fresh water
    fertilizer_ballast: float = 0.08    # fraction of fertilizer mass that is unwanted salt
    nutrient_full_g_l: float = 1.2      # nutrient concentration at and above which nutrition is not limiting
    ec_threshold_ds_m: float = 3.5      # salinity stress starts above this EC
    ec_slope_per_ds_m: float = 0.12     # growth lost per dS/m above the threshold
    uptake_g_per_kg: float = 5.0        # nutrient taken up per kg of growth on day 0
    uptake_rise_per_day: float = 1.1    # + g/kg each later day: fruit filling needs more nutrient per kg

    # -- growth and crop condition -------------------------------------------------
    growth_heat_onset_c: float = 30.0   # growth is unaffected by temperature up to here
    growth_heat_slope: float = 0.04     # growth lost per degree above the onset
    growth_heat_floor: float = 0.5
    stress_tolerance: float = 0.10      # daily stress at or below this causes no damage
    damage_rate: float = 0.25           # condition lost per unit of stress above the tolerance
    recovery_per_day: float = 0.03      # condition regained on a day with stress within tolerance
    condition_floor: float = 0.2

    # -- prices --------------------------------------------------------------------
    price_per_kg: float = 2.0
    water_price_per_l: float = 0.02
    fertilizer_price_per_g: float = 0.02
    discharge_price_per_l: float = 0.01  # every litre flushed or overflowed to waste
    test_price: float = 25.0
    test_delay_days: int = 1

    # -- limits --------------------------------------------------------------------
    irrigation_max_l: float = 600.0     # per zone per day
    fertilizer_max_g: float = 1500.0    # per zone per day
    daily_fresh_water_cap_l: float = 1600.0  # all zones together, irrigation + flush

    # -- default operating plan (applies to every zone on any day with no plan) -----
    default_irrigation_l: float = 230.0
    default_fertilizer_g: float = 120.0
    default_flush_l: float = 0.0

    # -- sensors and forecast --------------------------------------------------------
    ec_sensor_sigma_ds_m: float = 0.06
    forecast_days: int = 7              # today plus the next six days
    normal_temp_c: float = 26.0         # seasonal normal, for days beyond the forecast

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "Params":
        """Build from a config or a published rules table, ignoring other keys."""
        known = {f.name: f.type for f in fields(cls)}
        picked = {}
        for key, value in data.items():
            if key in known:
                picked[key] = int(value) if known[key] == "int" else float(value)
        return cls(**picked)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ZoneDay(NamedTuple):
    """One zone, one day: the new state and everything that happened."""
    volume_l: float
    nutrient_g: float
    salt_g: float
    condition: float
    growth_kg: float
    transpired_l: float
    overflow_l: float
    uptake_g: float
    nutrient_out_g: float     # removed by flush and overflow
    salt_in_g: float          # from fresh water and fertilizer ballast
    salt_out_g: float         # removed by flush and overflow
    water_factor: float
    nutrient_factor: float
    salinity_factor: float
    heat_factor: float
    stress: float
    midday_ec_ds_m: float
    midday_nutrient_g_l: float


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def concentration(mass_g: float, volume_l: float) -> float:
    """g/L, with an empty volume treated as holding nothing dissolved."""
    return mass_g / volume_l if volume_l > 1e-9 else 0.0


def ec_of(p: Params, nutrient_g: float, salt_g: float, volume_l: float) -> float:
    """EC counts nutrients and salts alike, so it cannot tell them apart."""
    return p.ec_per_g_l * concentration(nutrient_g + salt_g, volume_l)


def transpiration_factor(p: Params, temp_c: float) -> float:
    """Heat raises water demand; cool days lower it, down to a floor."""
    d = temp_c - p.transp_ref_temp_c
    if d >= 0:
        return 1.0 + p.transp_heat_slope * d
    return max(p.transp_min_factor, 1.0 + p.transp_cool_slope * d)


def heat_factor(p: Params, temp_c: float) -> float:
    """Growth multiplier from temperature alone. Nothing the player does changes it."""
    return clamp(1.0 - p.growth_heat_slope * max(0.0, temp_c - p.growth_heat_onset_c), p.growth_heat_floor, 1.0)


def nutrient_factor(p: Params, nutrient_g_l: float) -> float:
    """Smooth saturation: 0 with no nutrient, 1 at `nutrient_full_g_l` and above,
    flat where it meets 1 so slightly lean solution costs little."""
    short = 1.0 - clamp(nutrient_g_l / p.nutrient_full_g_l)
    return 1.0 - short * short


def salinity_factor(p: Params, ec_ds_m: float) -> float:
    """Threshold-slope response to total EC: no loss up to the threshold, then
    a linear loss per dS/m (the form of Maas and Hoffman, 1977)."""
    return clamp(1.0 - p.ec_slope_per_ds_m * max(0.0, ec_ds_m - p.ec_threshold_ds_m))


def water_supply_fraction(p: Params, volume_l: float) -> float:
    """Share of water demand the plants can meet from this much solution."""
    return clamp((volume_l - p.dead_volume_l) / (p.comfort_volume_l - p.dead_volume_l))


def uptake_rate(p: Params, day: int) -> float:
    """Grams of nutrient taken up per kg grown on `day` (a published schedule)."""
    return p.uptake_g_per_kg + p.uptake_rise_per_day * day


def best_condition(p: Params, start: float, days: int) -> float:
    """The highest condition reachable after `days` stress-free days."""
    return min(1.0, start + p.recovery_per_day * days)


def step_zone(p: Params, growth_max_kg: float, transp_base_l: float,
              volume_l: float, nutrient_g: float, salt_g: float, condition: float,
              irrigation_l: float, fertilizer_g: float, flush_l: float, temp_c: float, day: int = 0) -> ZoneDay:
    """Advance one zone by one day. The order below is the order of the day.

    1. Flush: `flush_l` litres of solution go to waste, carrying nutrients and
       salts in proportion to their concentration, and the same volume of
       fresh water (with its source salts) replaces them.
    2. Irrigation: fresh water is added. Anything above capacity overflows to
       waste at the mixed concentration.
    3. Fertilizer: dissolved into the loop. It adds mass, never water.
    4. Plants: transpire water (which leaves the solutes behind), grow, and
       take up `uptake_rate(p, day)` grams of nutrient per kg grown. Stress is
       judged at the mid-day volume, half way through the day's transpiration.
    5. Crop condition for tomorrow: lost in proportion to today's stress above
       the tolerance, or regained by a fixed small step on a calm day.
    """
    v, n, s = volume_l, nutrient_g, salt_g
    n_out = s_out = 0.0

    # 1. Flush: bleed, then refill with the same volume of fresh water.
    if flush_l > 0.0:
        share = min(1.0, flush_l / v) if v > 1e-9 else 0.0
        n_out += n * share
        s_out += s * share
        n -= n * share
        s -= s * share
    # 2. Irrigation. Fresh water from the flush refill and from irrigation
    #    brings its source salts with it.
    v += irrigation_l
    s_in = p.source_salt_g_l * (flush_l + irrigation_l)
    s += s_in
    overflow = 0.0
    if v > p.capacity_l:
        overflow = v - p.capacity_l
        share = overflow / v
        n_out += n * share
        s_out += s * share
        n -= n * share
        s -= s * share
        v = p.capacity_l
    # 3. Fertilizer.
    ballast = fertilizer_g * p.fertilizer_ballast
    n += fertilizer_g - ballast
    s += ballast
    s_in += ballast

    demand = transp_base_l * transpiration_factor(p, temp_c) * (p.canopy_floor + (1.0 - p.canopy_floor) * condition)
    transpired = min(demand * water_supply_fraction(p, v), max(0.0, v - p.dead_volume_l))
    f_w = transpired / demand if demand > 1e-9 else 1.0
    v_mid = v - 0.5 * transpired
    c_n = concentration(n, v_mid)
    ec = ec_of(p, n, s, v_mid)
    f_n = nutrient_factor(p, c_n)
    f_s = salinity_factor(p, ec)
    f_t = heat_factor(p, temp_c)
    # Growth always takes up its nutrient, so it can never exceed what is dissolved.
    rate = uptake_rate(p, day)
    growth = min(growth_max_kg * condition * f_t * f_w * f_n * f_s, n / rate)
    uptake = rate * growth
    v -= transpired
    n -= uptake

    # 5. Tomorrow's condition. Today's growth above already used this morning's.
    stress = 1.0 - f_w * f_n * f_s
    if stress > p.stress_tolerance:
        # The floor stops further loss; it never lifts a crop that is below it.
        lowest = min(condition, p.condition_floor)
        new_condition = max(lowest, condition - p.damage_rate * (stress - p.stress_tolerance))
    else:
        new_condition = min(1.0, condition + p.recovery_per_day)

    return ZoneDay(v, n, s, new_condition, growth, transpired, overflow, uptake, n_out, s_in, s_out,
                   f_w, f_n, f_s, f_t, stress, ec, c_n)
