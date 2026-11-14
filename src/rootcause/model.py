"""The public physics of one NFT lettuce bench.

Everything here is known to the player: `Greenhouse.rules()` publishes every
parameter, and the reference planner runs these same functions on its own
estimate of a bench. Nothing in this module holds state.

Units: water in litres (L), dissolved material in grams (g), concentration in
g/L, electrical conductivity in dS/m (= mS/cm), temperature in degrees C, crop
in kg of head fresh weight, money in EUR. Masses are stored; concentrations
and EC are always derived.

A bench is a nutrient-film (NFT) bench of butterhead lettuce: gullies fed from
one recirculating tank. The solution in the gullies and the tank is treated as
one well-mixed volume. Useful nutrients and unwanted salts are two separate
masses dissolved in it; EC counts both.

Simplifications (see docs/GREENHOUSE.md): one lumped nutrient and one lumped
salt; EC linear in dissolved mass; perfect mixing; no pH, no ion toxicity, no
disease; one decision and one update per day.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, NamedTuple


@dataclass(frozen=True)
class Params:
    horizon_days: int = 6

    # -- water -------------------------------------------------------------------
    capacity_l: float = 1200.0          # most solution a bench's tank and gullies hold; more overflows
    dead_volume_l: float = 250.0        # held in gullies and tank bottom: cannot be transpired or pumped out
    comfort_volume_l: float = 600.0     # below this the film is incomplete and plants cannot meet demand
    transp_ref_temp_c: float = 22.0     # transpiration demand is the bench's base rate at this temperature
    transp_heat_slope: float = 0.05     # + fraction of base demand per degree above the reference
    transp_cool_slope: float = 0.02     # - fraction of base demand per degree below the reference
    transp_min_factor: float = 0.7
    canopy_floor: float = 0.4           # a crop at condition 0 still transpires this fraction of demand

    # -- chemistry ---------------------------------------------------------------
    ec_per_g_l: float = 1.5             # dS/m per g/L of dissolved nutrients + salts (both count equally)
    mains_salt_g_l: float = 0.10        # salt in mains water from the usual source
    reserve_salt_g_l: float = 0.0       # the clean reserve tank (rainwater after reverse osmosis)
    fertilizer_ballast: float = 0.05    # fraction of fertilizer mass that is unwanted salt
    nutrient_full_g_l: float = 0.75     # nutrient concentration at and above which nutrition is not limiting
    ec_threshold_ds_m: float = 1.8      # salinity stress starts above this EC
    ec_slope_per_ds_m: float = 0.25     # growth lost per dS/m above the threshold (lettuce is salt-sensitive)
    uptake_g_per_kg: float = 4.0        # nutrient taken up per kg of head growth on day 0
    uptake_rise_per_day: float = 0.2    # + g/kg each later day: older heads need more nutrient per kg

    # -- growth and crop condition -------------------------------------------------
    growth_heat_onset_c: float = 26.0   # growth is unaffected by temperature up to here
    growth_heat_slope: float = 0.05     # growth lost per degree above the onset
    growth_heat_floor: float = 0.5
    stress_tolerance: float = 0.10      # daily stress at or below this causes no damage
    damage_rate: float = 0.30           # condition lost per unit of stress above the tolerance (tipburn, wilting)
    recovery_per_day: float = 0.03      # condition regained on a day with stress within tolerance
    condition_floor: float = 0.2

    # -- prices --------------------------------------------------------------------
    price_per_kg: float = 2.5           # head fresh weight
    mains_price_per_l: float = 0.01
    reserve_price_per_l: float = 0.04    # reverse-osmosis water: clean but four times the price of mains
    fertilizer_price_per_g: float = 0.03
    discharge_price_per_l: float = 0.01  # every litre flushed or overflowed to waste
    test_price: float = 15.0             # a bench composition test
    water_test_price: float = 15.0       # a test of today's mains supply
    test_delay_days: int = 1

    # -- limits --------------------------------------------------------------------
    top_up_max_l: float = 500.0          # mains + reserve per bench per day
    fertilizer_max_g: float = 600.0      # per bench per day

    # -- default operating plan (applies to every bench on any day with no plan) ----
    default_mains_l: float = 230.0
    default_reserve_l: float = 0.0
    default_fertilizer_g: float = 90.0
    default_flush_l: float = 0.0

    # -- sensors and forecast --------------------------------------------------------
    ec_sensor_sigma_ds_m: float = 0.04
    forecast_days: int = 3              # today plus the next two days

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


class BenchDay(NamedTuple):
    """One bench, one day: the new state and everything that happened."""
    volume_l: float
    nutrient_g: float
    salt_g: float
    condition: float
    growth_kg: float
    transpired_l: float
    overflow_l: float
    uptake_g: float
    nutrient_out_g: float     # removed by flush and overflow
    salt_in_g: float          # from mains, reserve and fertilizer ballast
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
    d = temp_c - p.transp_ref_temp_c
    if d >= 0:
        return 1.0 + p.transp_heat_slope * d
    return max(p.transp_min_factor, 1.0 + p.transp_cool_slope * d)


def demand_l(p: Params, transp_base_l: float, temp_c: float, condition: float) -> float:
    return transp_base_l * transpiration_factor(p, temp_c) * (p.canopy_floor + (1.0 - p.canopy_floor) * condition)


def heat_factor(p: Params, temp_c: float) -> float:
    return clamp(1.0 - p.growth_heat_slope * max(0.0, temp_c - p.growth_heat_onset_c), p.growth_heat_floor, 1.0)


def nutrient_factor(p: Params, nutrient_g_l: float) -> float:
    """0 with no nutrient, 1 at `nutrient_full_g_l` and above, flat where it meets 1."""
    short = 1.0 - clamp(nutrient_g_l / p.nutrient_full_g_l)
    return 1.0 - short * short


def salinity_factor(p: Params, ec_ds_m: float) -> float:
    """Threshold-slope response to total EC (the form of Maas and Hoffman, 1977)."""
    return clamp(1.0 - p.ec_slope_per_ds_m * max(0.0, ec_ds_m - p.ec_threshold_ds_m))


def water_supply_fraction(p: Params, volume_l: float) -> float:
    return clamp((volume_l - p.dead_volume_l) / (p.comfort_volume_l - p.dead_volume_l))


def uptake_rate(p: Params, day: int) -> float:
    return p.uptake_g_per_kg + p.uptake_rise_per_day * day


def best_condition(p: Params, start: float, days: int) -> float:
    return min(1.0, start + p.recovery_per_day * days)


def step_bench(p: Params, growth_max_kg: float, transp_base_l: float,
               volume_l: float, nutrient_g: float, salt_g: float, condition: float,
               mains_l: float, reserve_l: float, fertilizer_g: float, flush_l: float,
               temp_c: float, day: int, mains_salt_g_l: float) -> BenchDay:
    """Advance one bench by one day. The order below is the order of the day.

    1. Flush: `flush_l` litres go to waste with nutrients and salts in
       proportion; the tank is refilled with the same volume of mains water.
    2. Top-up: `mains_l` of mains water and `reserve_l` of reserve water are
       added. Anything above capacity overflows to waste at the mixed concentration.
    3. Fertilizer dissolves. It adds mass, never water.
    4. Plants transpire (water only leaves, so the solution concentrates), grow
       and take up nutrient. Stress is judged at the mid-day volume.
    5. Condition for tomorrow is set from today's stress.

    `mains_salt_g_l` is the salt in today's mains water. It is a parameter of
    the day, not of the model, because the supply can change.
    """
    v, n, s = volume_l, nutrient_g, salt_g
    n_out = s_out = 0.0

    if flush_l > 0.0:
        share = min(1.0, flush_l / v) if v > 1e-9 else 0.0
        n_out += n * share
        s_out += s * share
        n -= n * share
        s -= s * share
    v += mains_l + reserve_l
    s_in = mains_salt_g_l * (flush_l + mains_l) + p.reserve_salt_g_l * reserve_l
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
    ballast = fertilizer_g * p.fertilizer_ballast
    n += fertilizer_g - ballast
    s += ballast
    s_in += ballast

    demand = demand_l(p, transp_base_l, temp_c, condition)
    transpired = min(demand * water_supply_fraction(p, v), max(0.0, v - p.dead_volume_l))
    f_w = transpired / demand if demand > 1e-9 else 1.0
    v_mid = v - 0.5 * transpired
    c_n = concentration(n, v_mid)
    ec = ec_of(p, n, s, v_mid)
    f_n = nutrient_factor(p, c_n)
    f_s = salinity_factor(p, ec)
    f_t = heat_factor(p, temp_c)
    rate = uptake_rate(p, day)
    growth = min(growth_max_kg * condition * f_t * f_w * f_n * f_s, n / rate)
    uptake = rate * growth
    v -= transpired
    n -= uptake

    stress = 1.0 - f_w * f_n * f_s
    if stress > p.stress_tolerance:
        lowest = min(condition, p.condition_floor)
        new_condition = max(lowest, condition - p.damage_rate * (stress - p.stress_tolerance))
    else:
        new_condition = min(1.0, condition + p.recovery_per_day)

    return BenchDay(v, n, s, new_condition, growth, transpired, overflow, uptake, n_out, s_in, s_out,
                    f_w, f_n, f_s, f_t, stress, ec, c_n)
