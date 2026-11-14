"""Seeded instances.

Everything exogenous is fixed here, before the first decision, from named
random streams: zone make-up, the weather of every day, every forecast that
will ever be issued, and every sensor error. Nothing a player does (an extra
read, an extra test, a different plan) can change the weather or the noise
they will see.

What a seed varies, within the ranges of `[env.generator]`:
  * each zone's growth potential, water demand, starting volume and condition;
  * each zone's hidden starting composition (nutrients and salts);
  * base temperature and the timing, length and strength of a hot spell;
  * the season's fresh-water allocation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from envkit.rng import Rng

from .model import Params

ZONE_IDS = ("A", "B", "C", "D")

# Starting composition types: (nutrient g/L range, salt g/L range). A seed
# deals four different types to the four zones, in a random order. Two of them
# ("salty_hungry" and "rich") overlap in EC although one is short of nutrients
# and the other has more than it needs.
COMPOSITIONS: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {
    "balanced":     ((1.05, 1.30), (0.55, 0.90)),
    "salty_hungry": ((0.40, 0.60), (1.60, 2.00)),
    "rich":         ((1.85, 2.20), (0.30, 0.50)),
    "lean":         ((0.45, 0.70), (0.45, 0.80)),
    "saline":       ((1.20, 1.50), (1.50, 1.90)),
}

GENERATOR_DEFAULTS: dict[str, Any] = {
    "growth_max_kg": (26.0, 34.0),        # per zone per day, at full condition
    "transp_base_l": (185.0, 235.0),      # per zone per day, at the reference temperature
    "start_volume_l": (1000.0, 1300.0),
    "start_condition": (0.85, 1.0),
    "base_temp_c": (24.0, 26.5),
    "temp_noise_c": 1.0,
    "wave_start_day": (3, 8),
    "wave_days": (3, 5),
    "wave_peak_c": (5.0, 10.0),
    # Allocation as a multiple of (sum of base demand x horizon). Transpiration
    # over a season runs about 1.15-1.3 times base demand, so the low end leaves
    # almost nothing for flushing and the high end a leaching fraction of ~20%.
    "fresh_water_factor": (1.15, 1.45),
    "compositions": list(COMPOSITIONS),
}


@dataclass(frozen=True)
class ZoneSpec:
    id: str
    name: str
    growth_max_kg: float
    transp_base_l: float
    volume_l: float
    nutrient_g: float
    salt_g: float
    condition: float
    composition: str        # hidden until the episode ends


@dataclass(frozen=True)
class Instance:
    seed: int
    params: Params
    zones: tuple[ZoneSpec, ...]
    fresh_water_l: float
    temps: tuple[float, ...]                    # realized temperature of each day
    forecasts: tuple[tuple[float, ...], ...]    # forecasts[t][k]: issued on day t for day t + k
    ec_noise: dict[str, tuple[float, ...]]      # sensor error at each morning, days 0..horizon


def _pair(value: Any) -> tuple[float, float]:
    lo, hi = value
    return float(lo), float(hi)


def generate(config: dict[str, Any], seed: int) -> Instance:
    """Build the instance for (config, seed). A pure function of both."""
    p = Params.from_mapping(config)
    g = {**GENERATOR_DEFAULTS, **dict(config.get("generator", {}))}
    rng = Rng(int(seed), "rootcause")
    n_days = p.horizon_days

    # -- zones: each attribute has its own stream, so adding one never shifts another
    kinds = [k for k in g["compositions"] if k in COMPOSITIONS]
    if len(kinds) < len(ZONE_IDS):
        raise ValueError(f"generator.compositions needs at least {len(ZONE_IDS)} known types")
    dealt = rng.stream("composition/deal").shuffled(kinds)[:len(ZONE_IDS)]
    zones = []
    for zone_id, kind in zip(ZONE_IDS, dealt):
        r = rng.stream(f"zone/{zone_id}")
        growth = round(r.uniform(*_pair(g["growth_max_kg"])), 1)
        transp = round(r.uniform(*_pair(g["transp_base_l"])), 0)
        volume = round(r.uniform(*_pair(g["start_volume_l"])), 0)
        condition = round(r.uniform(*_pair(g["start_condition"])), 2)
        (n_lo, n_hi), (s_lo, s_hi) = COMPOSITIONS[kind]
        c = rng.stream(f"composition/{zone_id}")
        nutrient_g_l = round(c.uniform(n_lo, n_hi), 3)
        salt_g_l = round(c.uniform(s_lo, s_hi), 3)
        zones.append(ZoneSpec(zone_id, f"Zone {zone_id}", growth, transp, volume,
                              round(nutrient_g_l * volume, 3), round(salt_g_l * volume, 3), condition, kind))

    # -- weather: a base level, day-to-day noise and one hot spell
    w = rng.stream("weather")
    base = w.uniform(*_pair(g["base_temp_c"]))
    start = w.randint(int(g["wave_start_day"][0]), int(g["wave_start_day"][1]))
    length = w.randint(int(g["wave_days"][0]), int(g["wave_days"][1]))
    peak = w.uniform(*_pair(g["wave_peak_c"]))
    noise = rng.stream("weather/noise")
    temps = []
    for day in range(n_days):
        k = day - start
        bump = 0.0
        if 0 <= k < length:   # triangular: ramps up to the peak and back down
            bump = peak * (1.0 - abs(k - (length - 1) / 2.0) / ((length + 1) / 2.0))
        temps.append(round(min(40.0, max(16.0, base + bump + noise.normal(0.0, float(g["temp_noise_c"])))), 1))

    # -- forecasts: the error for a target day is a random walk in lead time, so
    #    a forecast sharpens as its day approaches and consecutive issues agree.
    f = rng.stream("forecast")
    steps = [[f.normal() for _ in range(p.forecast_days)] for _ in range(n_days)]

    def error(day: int, lead: int) -> float:
        return 0.3 * steps[day][0] + 0.6 * sum(steps[day][1:lead + 1])

    forecasts = tuple(
        tuple(round(2.0 * (temps[d] + error(d, d - t))) / 2.0          # to the nearest half degree
              for d in range(t, min(t + p.forecast_days, n_days)))
        for t in range(n_days)
    )

    # -- sensors
    ec_noise = {}
    for zone_id in ZONE_IDS:
        s = rng.stream(f"sensor/ec/{zone_id}")
        ec_noise[zone_id] = tuple(round(s.normal(0.0, p.ec_sensor_sigma_ds_m), 4) for _ in range(n_days + 1))

    demand = sum(z.transp_base_l for z in zones) * n_days
    fresh = round(rng.stream("allocation").uniform(*_pair(g["fresh_water_factor"])) * demand / 100.0) * 100.0
    return Instance(int(seed), p, tuple(zones), float(fresh), tuple(temps), forecasts, ec_noise)
