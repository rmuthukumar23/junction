"""Strict, data-driven facility, climate and energy-price schemas.

All tunable values are read from TOML. `Range` values are resolved once per seed
by `config.base.resolve`; their published bounds are available through `ranges`.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from greenhouse.config.base import ConfigError, Param, Table


@dataclass(frozen=True)
class CHPConfig:
    electric_kw: Param
    heat_per_electric: float
    co2_kg_per_m3_gas: float
    gas_m3_per_kwh_e: float
    min_load: float


@dataclass(frozen=True)
class BoilerConfig:
    heat_kw: Param
    gas_m3_per_kwh_heat: float
    co2_usable: bool


@dataclass(frozen=True)
class BufferConfig:
    capacity_kwh: Param
    loss_per_h: float
    start_fraction: float


@dataclass(frozen=True)
class CO2StoreConfig:
    capacity_kg: float
    start_kg: float


@dataclass(frozen=True)
class ExternalCO2Config:
    max_kg_per_h: Param


@dataclass(frozen=True)
class GridConfig:
    import_kw: Param
    export_kw: Param


@dataclass(frozen=True)
class EnergyCentreSpec:
    chp: CHPConfig
    boiler: BoilerConfig
    buffer: BufferConfig
    co2_store: CO2StoreConfig
    external_co2: ExternalCO2Config
    grid: GridConfig


@dataclass(frozen=True)
class ScreenSpec:
    insulation: Param


@dataclass(frozen=True)
class LampSpec:
    w_per_m2: Param
    umol_per_j: float
    heat_fraction: float


@dataclass(frozen=True)
class StartBatch:
    age_days: float
    area_fraction: float


@dataclass(frozen=True)
class CompartmentSpec:
    id: str
    crop: str
    floor_m2: Param
    height_m: Param
    cover_u_w_m2_k: Param
    cover_transmission: Param
    solar_umol_per_j: float
    leakage_ach: Param
    wind_leakage_per_m_s: float
    thermal_mass_kwh_m2_k: Param
    max_vent_ach: float
    cover_surface_temp_fraction: float
    initial_temp_c: float
    initial_rh_pct: float
    initial_co2_ppm: float
    screen: ScreenSpec
    lamps: LampSpec
    start_batches: tuple[StartBatch, ...]


@dataclass(frozen=True)
class ControllerSpec:
    heat_kw_per_c_m2: float
    vent_pct_per_c: float
    vent_pct_per_rh: float
    vent_target_rh_pct: float
    co2_kg_h_per_ppm_m2: float
    vent_co2_pause_pct: float
    heat_deadband_c: float


@dataclass(frozen=True)
class SensorSpec:
    temp_sigma_c: float
    rh_sigma_pct: float
    co2_sigma_ppm: float
    par_sigma_umol_m2_s: float


@dataclass(frozen=True)
class FallbackSpec:
    heat_day_c: float
    heat_night_c: float
    vent_min_pct: float
    vent_max_pct: float
    co2_ppm: float
    lamp_hours: tuple[int, ...]
    lamp_intensity_pct: float
    screen: str
    chp_load: float
    boiler: str
    buffer: str
    external_co2_kg_h: float


@dataclass(frozen=True)
class ClimateLimits:
    min_heat_c: float
    max_heat_c: float
    max_co2_ppm: float


@dataclass(frozen=True)
class AlarmLimits:
    frost_risk_temp_c: float
    co2_low_kg: float


@dataclass(frozen=True)
class FacilitySpec:
    id: str
    energy_centre: EnergyCentreSpec
    compartments: tuple[CompartmentSpec, ...]
    controller: ControllerSpec
    sensor: SensorSpec
    fallback: FallbackSpec
    limits: ClimateLimits
    alarms: AlarmLimits


@dataclass(frozen=True)
class WeatherSpec:
    outside_co2_ppm: float


@dataclass(frozen=True)
class ForecastSpec:
    temp_sigma_at_24h_c: float
    solar_fraction_sigma_at_24h: float
    wind_sigma_at_24h_m_s: float
    rh_sigma_at_24h_pct: float
    price_fraction_sigma_at_24h: float


@dataclass(frozen=True)
class RecordedWeatherWindow:
    id: str
    group: str
    start_utc: str
    rows: tuple[tuple[float, float, float, float, bool], ...]


@dataclass(frozen=True)
class ClimateProfile:
    id: str
    series_hours: int
    weather: WeatherSpec
    forecast: ForecastSpec
    evaluation_seeds: tuple[int, ...]
    windows: tuple[RecordedWeatherWindow, ...]


@dataclass(frozen=True)
class TariffSpec:
    import_markup_eur_kwh: float
    export_fraction: float


@dataclass(frozen=True)
class RecordedPriceWindow:
    id: str
    group: str
    start_utc: str
    rows: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class EnergyPriceSpec:
    id: str
    tariff: TariffSpec
    evaluation_seeds: tuple[int, ...]
    windows: tuple[RecordedPriceWindow, ...]


def _schema(t: Table, expected: str) -> None:
    schema = t.str('schema')
    if schema != expected:
        raise ConfigError(f"{t.source}: 'schema' must be {expected!r}, got {schema!r}")


def _compartment(raw: dict[str, Any], source: str, index: int) -> CompartmentSpec:
    t = Table(raw, source, f'compartments[{index}]')
    batches = []
    for j, entry in enumerate(t.list('start_batches')):
        b = Table(entry, source, f'compartments[{index}].start_batches[{j}]')
        batches.append(StartBatch(b.num('age_days', lo=0), b.num('area_fraction', lo=0, hi=1)))
        b.done()
    if sum(b.area_fraction for b in batches) > 1 + 1e-9:
        raise ConfigError(f'{source}: compartments[{index}].start_batches area fractions exceed 1')
    spec = CompartmentSpec(
        id=t.str('id'), crop=t.str('crop'),
        floor_m2=t.param('floor_m2', lo=1), height_m=t.param('height_m', lo=1),
        cover_u_w_m2_k=t.param('cover_u_w_m2_k', lo=0),
        cover_transmission=t.param('cover_transmission', lo=0, hi=1),
        solar_umol_per_j=t.num('solar_umol_per_j', lo=0),
        leakage_ach=t.param('leakage_ach', lo=0),
        wind_leakage_per_m_s=t.num('wind_leakage_per_m_s', lo=0),
        thermal_mass_kwh_m2_k=t.param('thermal_mass_kwh_m2_k', lo=0.001),
        max_vent_ach=t.num('max_vent_ach', lo=0),
        cover_surface_temp_fraction=t.num('cover_surface_temp_fraction', lo=0, hi=1),
        initial_temp_c=t.num('initial_temp_c'),
        initial_rh_pct=t.num('initial_rh_pct', lo=0, hi=100),
        initial_co2_ppm=t.num('initial_co2_ppm', lo=0),
        screen=ScreenSpec(t.param('screen.insulation', lo=0, hi=1)),
        lamps=LampSpec(t.param('lamps.w_per_m2', lo=0),
                       t.num('lamps.umol_per_j', lo=0),
                       t.num('lamps.heat_fraction', lo=0, hi=1)),
        start_batches=tuple(batches),
    )
    t.done()
    return spec


def parse_facility(raw: dict[str, Any], source: str) -> FacilitySpec:
    t = Table(raw, source)
    _schema(t, 'facility/1')
    rows = t.list('compartments')
    if not rows:
        raise ConfigError(f'{source}: compartments must not be empty')
    compartments = tuple(_compartment(row, source, i) for i, row in enumerate(rows))
    if len({c.id for c in compartments}) != len(compartments):
        raise ConfigError(f'{source}: compartment ids must be unique')
    energy = EnergyCentreSpec(
        chp=CHPConfig(t.param('energy_centre.chp.electric_kw', lo=0),
                      t.num('energy_centre.chp.heat_per_electric', lo=0),
                      t.num('energy_centre.chp.co2_kg_per_m3_gas', lo=0),
                      t.num('energy_centre.chp.gas_m3_per_kwh_e', lo=0),
                      t.num('energy_centre.chp.min_load', lo=0, hi=1)),
        boiler=BoilerConfig(t.param('energy_centre.boiler.heat_kw', lo=0),
                            t.num('energy_centre.boiler.gas_m3_per_kwh_heat', lo=0),
                            t.bool('energy_centre.boiler.co2_usable')),
        buffer=BufferConfig(t.param('energy_centre.buffer.capacity_kwh', lo=0),
                            t.num('energy_centre.buffer.loss_per_h', lo=0, hi=1),
                            t.num('energy_centre.buffer.start_fraction', lo=0, hi=1)),
        co2_store=CO2StoreConfig(t.num('energy_centre.co2_store.capacity_kg', lo=0),
                                 t.num('energy_centre.co2_store.start_kg', lo=0)),
        external_co2=ExternalCO2Config(t.param('energy_centre.external_co2.max_kg_per_h', lo=0)),
        grid=GridConfig(t.param('energy_centre.grid.import_kw', lo=0),
                        t.param('energy_centre.grid.export_kw', lo=0)),
    )
    if energy.co2_store.start_kg > energy.co2_store.capacity_kg:
        raise ConfigError(f'{source}: co2_store.start_kg exceeds capacity_kg')
    controller = ControllerSpec(
        t.num('controller.heat_kw_per_c_m2', lo=0),
        t.num('controller.vent_pct_per_c', lo=0),
        t.num('controller.vent_pct_per_rh', lo=0),
        t.num('controller.vent_target_rh_pct', lo=0, hi=100),
        t.num('controller.co2_kg_h_per_ppm_m2', lo=0),
        t.num('controller.vent_co2_pause_pct', lo=0, hi=100),
        t.num('controller.heat_deadband_c', lo=0),
    )
    sensor = SensorSpec(t.num('sensor.temp_sigma_c', lo=0),
                        t.num('sensor.rh_sigma_pct', lo=0),
                        t.num('sensor.co2_sigma_ppm', lo=0),
                        t.num('sensor.par_sigma_umol_m2_s', lo=0))
    lamp_hours = t.list('fallback.lamp_hours')
    if any(type(h) is not int or not 0 <= h <= 23 for h in lamp_hours) or len(set(lamp_hours)) != len(lamp_hours):
        raise ConfigError(f'{source}: fallback.lamp_hours must contain distinct hours 0 to 23')
    fallback = FallbackSpec(t.num('fallback.heat_day_c'), t.num('fallback.heat_night_c'),
                            t.num('fallback.vent_min_pct', lo=0, hi=100),
                            t.num('fallback.vent_max_pct', lo=0, hi=100),
                            t.num('fallback.co2_ppm', lo=0), tuple(lamp_hours),
                            t.num('fallback.lamp_intensity_pct', lo=0, hi=100),
                            t.str('fallback.screen', choices=('auto', 'open', 'closed')),
                            t.num('fallback.chp_load', lo=0, hi=1),
                            t.str('fallback.boiler', choices=('auto', 'off')),
                            t.str('fallback.buffer', choices=('auto', 'charge', 'hold', 'discharge')),
                            t.num('fallback.external_co2_kg_h', lo=0))
    limits = ClimateLimits(t.num('limits.min_heat_c'), t.num('limits.max_heat_c'),
                           t.num('limits.max_co2_ppm', lo=0))
    if limits.min_heat_c > limits.max_heat_c:
        raise ConfigError(f'{source}: limits.min_heat_c must not exceed max_heat_c')
    if (not all(math.isfinite(v) for v in (fallback.heat_day_c, fallback.heat_night_c,
                                          fallback.vent_min_pct, fallback.vent_max_pct,
                                          fallback.co2_ppm, fallback.lamp_intensity_pct,
                                          fallback.chp_load, fallback.external_co2_kg_h)) or
            not limits.min_heat_c <= fallback.heat_day_c <= limits.max_heat_c or
            not limits.min_heat_c <= fallback.heat_night_c <= limits.max_heat_c or
            fallback.vent_min_pct > fallback.vent_max_pct or
            fallback.co2_ppm > limits.max_co2_ppm or
            (fallback.chp_load != 0 and fallback.chp_load < energy.chp.min_load)):
        raise ConfigError(f'{source}: fallback settings exceed facility limits')
    alarms = AlarmLimits(t.num('alarms.frost_risk_temp_c'), t.num('alarms.co2_low_kg', lo=0))
    spec = FacilitySpec(t.str('id'), energy, compartments, controller, sensor, fallback, limits, alarms)
    t.done()
    return spec


def parse_climate(raw: dict[str, Any], source: str) -> ClimateProfile:
    t = Table(raw, source)
    _schema(t, 'climate/1')
    weather = WeatherSpec(t.num('weather.outside_co2_ppm', lo=0))
    forecast = ForecastSpec(t.num('forecast.temp_sigma_at_24h_c', lo=0),
                            t.num('forecast.solar_fraction_sigma_at_24h', lo=0),
                            t.num('forecast.wind_sigma_at_24h_m_s', lo=0),
                            t.num('forecast.rh_sigma_at_24h_pct', lo=0),
                            t.num('forecast.price_fraction_sigma_at_24h', lo=0))
    if not all(math.isfinite(v) for v in (weather.outside_co2_ppm, *vars(forecast).values())):
        raise ConfigError(f'{source}: weather and forecast values must be finite')
    series_hours = t.int('series_hours', lo=1)
    seeds = _evaluation_seeds(t, source)
    windows = []
    for i, raw_window in enumerate(t.list('windows')):
        window = Table(raw_window, source, f'windows[{i}]')
        ident = window.str('id')
        group = window.str('group', choices=('development', 'evaluation'))
        start = window.str('start_utc')
        rows = []
        for j, raw_row in enumerate(window.list('rows')):
            if (not isinstance(raw_row, list) or len(raw_row) != 5 or
                    any(type(v) not in (int, float) or not math.isfinite(v) for v in raw_row[:4]) or
                    type(raw_row[4]) is not bool or raw_row[1] < 0 or raw_row[2] < 0 or
                    not 0 <= raw_row[3] <= 100):
                raise ConfigError(f'{source}: windows[{i}].rows[{j}] needs [temp_c, solar_w_m2, wind_m_s, rh_pct, is_day]')
            rows.append((*map(float, raw_row[:4]), raw_row[4]))
        if len(rows) < series_hours:
            raise ConfigError(f'{source}: windows[{i}].rows has fewer than series_hours')
        windows.append(RecordedWeatherWindow(ident, group, start, tuple(rows)))
        window.done()
    _validate_windows(windows, source)
    spec = ClimateProfile(t.str('id'), series_hours, weather, forecast, seeds, tuple(windows))
    t.done()
    return spec


def parse_energy_prices(raw: dict[str, Any], source: str) -> EnergyPriceSpec:
    t = Table(raw, source)
    _schema(t, 'energy_prices/1')
    tariff = TariffSpec(t.num('tariff.import_markup_eur_kwh', lo=0),
                        t.num('tariff.export_fraction', lo=0, hi=1))
    if not all(math.isfinite(v) for v in vars(tariff).values()):
        raise ConfigError(f'{source}: tariff values must be finite')
    seeds = _evaluation_seeds(t, source)
    windows = []
    for i, raw_window in enumerate(t.list('windows')):
        window = Table(raw_window, source, f'windows[{i}]')
        ident = window.str('id')
        group = window.str('group', choices=('development', 'evaluation'))
        start = window.str('start_utc')
        rows = []
        for j, raw_row in enumerate(window.list('rows')):
            if (not isinstance(raw_row, list) or len(raw_row) != 2 or
                    any(type(v) not in (int, float) or not math.isfinite(v) for v in raw_row) or
                    raw_row[1] < 0):
                raise ConfigError(f'{source}: windows[{i}].rows[{j}] needs [wholesale_eur_mwh, gas_eur_m3]')
            rows.append((float(raw_row[0]), float(raw_row[1])))
        if not rows:
            raise ConfigError(f'{source}: windows[{i}].rows must not be empty')
        windows.append(RecordedPriceWindow(ident, group, start, tuple(rows)))
        window.done()
    _validate_windows(windows, source)
    spec = EnergyPriceSpec(t.str('id'), tariff, seeds, tuple(windows))
    t.done()
    return spec


def _evaluation_seeds(t: Table, source: str) -> tuple[int, ...]:
    seeds = t.list('evaluation_seeds')
    if not seeds or any(type(seed) is not int or seed < 0 for seed in seeds) or len(set(seeds)) != len(seeds):
        raise ConfigError(f'{source}: evaluation_seeds needs distinct non-negative integers')
    return tuple(seeds)


def _validate_windows(windows: list, source: str) -> None:
    if len({window.id for window in windows}) != len(windows):
        raise ConfigError(f'{source}: window ids must be unique')
    if {window.group for window in windows} != {'development', 'evaluation'}:
        raise ConfigError(f'{source}: windows need both development and evaluation groups')
