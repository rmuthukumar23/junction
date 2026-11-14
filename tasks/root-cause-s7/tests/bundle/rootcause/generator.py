"""Seeded instances.

Everything exogenous is fixed here, before the first decision, from named
random streams: the benches, the weather of every day and every forecast,
every sensor error, and the incident. Nothing a player does (an extra read, an
extra test, a different plan) can change any of it.

The scenario is one incident: on the morning of `incident_day` the water
utility moves the mains supply to a backup source whose water carries
`backup_salt_g_l` of salt. The player is told that the source changed, not
what the new water holds. The day is fixed by the scenario; the salinity is
drawn per seed from a range and is never published.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from envkit.rng import Rng

from .model import Params

BENCH_IDS = ("A", "B", "C")

GENERATOR_DEFAULTS: dict[str, Any] = {
    "growth_max_kg": (18.0, 24.0),       # per bench per day at full condition (about 2,000 heads)
    "transp_base_l": (200.0, 250.0),     # per bench per day at the reference temperature
    "start_volume_l": (850.0, 1000.0),
    "start_condition": (0.92, 1.0),
    "start_nutrient_g_l": (0.75, 0.95),  # a healthy, well-fed solution
    "start_salt_g_l": (0.20, 0.35),
    "base_temp_c": (21.0, 23.0),
    "temp_noise_c": 0.8,
    "incident_day": 1,
    "backup_salt_g_l": (1.20, 1.50),     # brackish backup well: twelve to fifteen times the usual mains salt
    "reserve_l": 2400.0,                 # clean reserve tank, shared by all benches, not refilled
}


@dataclass(frozen=True)
class BenchSpec:
    id: str
    name: str
    growth_max_kg: float
    transp_base_l: float
    volume_l: float
    nutrient_g: float
    salt_g: float
    condition: float


@dataclass(frozen=True)
class Instance:
    seed: int
    params: Params
    benches: tuple[BenchSpec, ...]
    reserve_l: float
    temps: tuple[float, ...]                    # realized temperature of each day
    forecasts: tuple[tuple[float, ...], ...]    # forecasts[t][k]: issued on day t for day t + k
    ec_noise: dict[str, tuple[float, ...]]      # sensor error at each morning, days 0..horizon
    incident_day: int                           # first day whose mains water comes from the backup source
    backup_salt_g_l: float                      # hidden: salt in the backup water

    def mains_salt(self, day: int) -> float:
        """Salt in mains water drawn on `day` (hidden after the incident)."""
        return self.backup_salt_g_l if day >= self.incident_day else self.params.mains_salt_g_l


def _pair(value: Any) -> tuple[float, float]:
    lo, hi = value
    return float(lo), float(hi)


def generate(config: dict[str, Any], seed: int) -> Instance:
    """Build the instance for (config, seed). A pure function of both."""
    p = Params.from_mapping(config)
    g = {**GENERATOR_DEFAULTS, **dict(config.get("generator", {}))}
    rng = Rng(int(seed), "rootcause")
    n_days = p.horizon_days

    benches = []
    for bench_id in BENCH_IDS:
        r = rng.stream(f"bench/{bench_id}")
        growth = round(r.uniform(*_pair(g["growth_max_kg"])), 1)
        transp = round(r.uniform(*_pair(g["transp_base_l"])), 0)
        volume = round(r.uniform(*_pair(g["start_volume_l"])), 0)
        condition = round(r.uniform(*_pair(g["start_condition"])), 2)
        c = rng.stream(f"composition/{bench_id}")
        nutrient = round(c.uniform(*_pair(g["start_nutrient_g_l"])), 3)
        salt = round(c.uniform(*_pair(g["start_salt_g_l"])), 3)
        benches.append(BenchSpec(bench_id, f"Bench {bench_id}", growth, transp, volume,
                                 round(nutrient * volume, 3), round(salt * volume, 3), condition))

    w = rng.stream("weather")
    base = w.uniform(*_pair(g["base_temp_c"]))
    noise = rng.stream("weather/noise")
    temps = tuple(round(base + noise.normal(0.0, float(g["temp_noise_c"])), 1) for _ in range(n_days))

    f = rng.stream("forecast")
    steps = [[f.normal() for _ in range(p.forecast_days)] for _ in range(n_days)]

    def error(day: int, lead: int) -> float:
        return 0.2 * steps[day][0] + 0.5 * sum(steps[day][1:lead + 1])

    forecasts = tuple(
        tuple(round(2.0 * (temps[d] + error(d, d - t))) / 2.0
              for d in range(t, min(t + p.forecast_days, n_days)))
        for t in range(n_days)
    )

    ec_noise = {}
    for bench_id in BENCH_IDS:
        s = rng.stream(f"sensor/ec/{bench_id}")
        ec_noise[bench_id] = tuple(round(s.normal(0.0, p.ec_sensor_sigma_ds_m), 4) for _ in range(n_days + 1))

    incident_day = int(g["incident_day"])
    if not 0 <= incident_day < n_days:
        raise ValueError("generator.incident_day must be a day of the episode")
    backup = round(rng.stream("incident").uniform(*_pair(g["backup_salt_g_l"])), 3)
    return Instance(int(seed), p, tuple(benches), float(g["reserve_l"]), temps, forecasts, ec_noise,
                    incident_day, backup)
