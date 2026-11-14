"""Strict, data-driven facility, climate and energy-price schemas.

All tunable values are read from TOML. `Range` values are resolved once per seed
by `config.base.resolve`; their published bounds are available through `ranges`.
"""
from __future__ import annotations

from dataclasses import dataclass
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
    heat_c: float
    vents: str
    co2_ppm: float
    lamps: str


@dataclass(frozen=True)
class StaffSpec:
    start_workers: int
    hours_per_worker_day: float


@dataclass(frozen=True)
class FacilitySpec:
    id: str
    energy_centre: EnergyCentreSpec
    compartments: tuple[CompartmentSpec, ...]
    controller: ControllerSpec
    sensor: SensorSpec
    fallback: FallbackSpec
    staff: StaffSpec


@dataclass(frozen=True)
class WeatherSpec:
    daily_mean_c: float
    diurnal_amplitude_c: float
    diurnal_peak_hour: int
    ar1_persistence: float
    innovation_sigma_c: float
    sunrise_hour: int
    sunset_hour: int
    solar_peak_w_m2: float
    cloud_persistence: float
    cloud_innovation_sigma: float
    clear_sky_fraction: float
    min_solar_fraction: float
    wind_mean_m_s: float
    wind_sigma_m_s: float
    rh_mean_pct: float
    rh_sigma_pct: float
    outside_co2_ppm: float


@dataclass(frozen=True)
class ForecastSpec:
    temp_sigma_at_24h_c: float
    solar_fraction_sigma_at_24h: float
    wind_sigma_at_24h_m_s: float
    rh_sigma_at_24h_pct: float
    price_fraction_sigma_at_24h: float


@dataclass(frozen=True)
class ClimateProfile:
    id: str
    weather: WeatherSpec
    forecast: ForecastSpec


@dataclass(frozen=True)
class ElectricityPriceSpec:
    base_eur_kwh: float
    daily_peak_multiplier: float
    daily_peak_hour: int
    noise_sigma_eur_kwh: float
    spike_probability_per_day: float
    spike_multiplier: float
    export_fraction: float


@dataclass(frozen=True)
class EnergyPriceSpec:
    id: str
    gas_eur_m3: float
    electricity: ElectricityPriceSpec


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
    fallback = FallbackSpec(t.num('fallback.heat_c'),
                            t.str('fallback.vents', choices=('closed',)),
                            t.num('fallback.co2_ppm', lo=0),
                            t.str('fallback.lamps', choices=('off',)))
    staff = StaffSpec(t.int('staff.start_workers', lo=0),
                      t.num('staff.hours_per_worker_day', lo=0, hi=24))
    spec = FacilitySpec(t.str('id'), energy, compartments, controller, sensor, fallback, staff)
    t.done()
    return spec


def parse_climate(raw: dict[str, Any], source: str) -> ClimateProfile:
    t = Table(raw, source)
    _schema(t, 'climate/1')
    weather = WeatherSpec(
        t.num('weather.daily_mean_c'), t.num('weather.diurnal_amplitude_c', lo=0),
        t.int('weather.diurnal_peak_hour', lo=0, hi=23),
        t.num('weather.ar1_persistence', lo=0, hi=0.999),
        t.num('weather.innovation_sigma_c', lo=0),
        t.int('weather.sunrise_hour', lo=0, hi=23),
        t.int('weather.sunset_hour', lo=1, hi=24),
        t.num('weather.solar_peak_w_m2', lo=0),
        t.num('weather.cloud_persistence', lo=0, hi=0.999),
        t.num('weather.cloud_innovation_sigma', lo=0),
        t.num('weather.clear_sky_fraction', lo=0, hi=1),
        t.num('weather.min_solar_fraction', lo=0, hi=1),
        t.num('weather.wind_mean_m_s', lo=0), t.num('weather.wind_sigma_m_s', lo=0),
        t.num('weather.rh_mean_pct', lo=0, hi=100),
        t.num('weather.rh_sigma_pct', lo=0),
        t.num('weather.outside_co2_ppm', lo=0),
    )
    if weather.sunset_hour <= weather.sunrise_hour:
        raise ConfigError(f'{source}: sunset_hour must exceed sunrise_hour')
    forecast = ForecastSpec(t.num('forecast.temp_sigma_at_24h_c', lo=0),
                            t.num('forecast.solar_fraction_sigma_at_24h', lo=0),
                            t.num('forecast.wind_sigma_at_24h_m_s', lo=0),
                            t.num('forecast.rh_sigma_at_24h_pct', lo=0),
                            t.num('forecast.price_fraction_sigma_at_24h', lo=0))
    spec = ClimateProfile(t.str('id'), weather, forecast)
    t.done()
    return spec


def parse_energy_prices(raw: dict[str, Any], source: str) -> EnergyPriceSpec:
    t = Table(raw, source)
    _schema(t, 'energy_prices/1')
    elec = ElectricityPriceSpec(
        t.num('electricity.base_eur_kwh', lo=0),
        t.num('electricity.daily_peak_multiplier', lo=0),
        t.int('electricity.daily_peak_hour', lo=0, hi=23),
        t.num('electricity.noise_sigma_eur_kwh', lo=0),
        t.num('electricity.spike_probability_per_day', lo=0, hi=1),
        t.num('electricity.spike_multiplier', lo=1),
        t.num('electricity.export_fraction', lo=0, hi=1),
    )
    spec = EnergyPriceSpec(t.str('id'), t.num('gas_eur_m3', lo=0), elec)
    t.done()
    return spec
