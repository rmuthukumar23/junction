"""CHP, boiler, buffer, grid and CO2 supply shared by greenhouse compartments."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping

from envkit.rng import Rng
from greenhouse.config.facility import ClimateProfile, EnergyCentreSpec, EnergyPriceSpec, FacilitySpec
from greenhouse.contracts import ClimateSample, EquipmentEffect, Metered
from greenhouse.world.climate import CompartmentClimate
from greenhouse.world.controller import Actuators, ClimateController, ClimateSetpoints
from greenhouse.world.weather import PriceSeries, WeatherSeries


@dataclass(frozen=True)
class EnergySettings:
    chp_load: float = 0.0
    boiler: str = 'auto'
    buffer: str = 'auto'
    external_co2_kg_h: float = 0.0
    priority: Mapping[str, int] = field(default_factory=dict)
    heat_caps_kw: Mapping[str, float] = field(default_factory=dict)
    co2_caps_kg_h: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Dispatch:
    heat_kw: dict[str, float]
    co2_kg_h: dict[str, float]
    lamp_kw: dict[str, float]


def allocate(demand: Mapping[str, float], supply: float,
             priority: Mapping[str, int] | None = None,
             caps: Mapping[str, float] | None = None) -> dict[str, float]:
    """Higher integer priority first, proportional sharing within a level."""
    priority, caps = priority or {}, caps or {}
    if supply < 0 or any(v < 0 for v in demand.values()):
        raise ValueError('supply and demand must be non-negative')
    need = {key: min(value, caps.get(key, value)) for key, value in demand.items()}
    if any(v < 0 for v in need.values()):
        raise ValueError('capacity caps must be non-negative')
    result = {key: 0.0 for key in demand}
    remaining = supply
    for level in sorted({priority.get(k, 1) for k in demand}, reverse=True):
        keys = sorted(k for k in demand if priority.get(k, 1) == level)
        total = sum(need[k] for k in keys)
        if total <= 0:
            continue
        factor = min(1.0, remaining / total)
        for key in keys:
            result[key] = need[key] * factor
        remaining = max(0.0, remaining - total * factor)
    return result


class EnergyCentre:
    def __init__(self, spec: EnergyCentreSpec):
        self.spec = spec
        self.buffer_kwh = float(spec.buffer.capacity_kwh) * spec.buffer.start_fraction
        self.co2_store_kg = spec.co2_store.start_kg
        self._meter = self._empty_meter(0)
        self.last_co2_wasted_kg = 0.0
        self.last_co2_balance: dict[str, float] = {}
        self.last_electricity_balance: dict[str, float] = {}
        self.last_electricity_curtailed_kwh = 0.0

    @staticmethod
    def _empty_meter(hour: int) -> dict:
        return dict(hour=hour, gas_m3=0.0, electricity_import_kwh=0.0,
                    electricity_export_kwh=0.0, external_co2_kg=0.0,
                    co2_from_store_kg=0.0, heat_produced_kwh=0.0,
                    heat_delivered_kwh={}, heat_lost_kwh=0.0, buffer_change_kwh=0.0)

    @staticmethod
    def _factor(effects: Mapping[str, EquipmentEffect], target: str) -> float:
        return max(0.0, min(1.0, effects.get(target, EquipmentEffect(target)).capacity_factor))

    def dispatch(self, hour: int, dt_h: float,
                 heat_kw: Mapping[str, float], co2_kg_h: Mapping[str, float],
                 lamp_kw: Mapping[str, float], settings: EnergySettings,
                 effects: Mapping[str, EquipmentEffect] | None = None) -> Dispatch:
        if not 0 < dt_h <= 1:
            raise ValueError('duration must be in (0, 1] hours')
        if settings.boiler not in ('auto', 'off') or settings.buffer not in ('auto', 'charge', 'hold', 'discharge'):
            raise ValueError('invalid boiler or buffer mode')
        if not math.isfinite(settings.chp_load) or settings.chp_load < 0 or settings.chp_load > 1 or (
                0 < settings.chp_load < self.spec.chp.min_load):
            raise ValueError('CHP load outside allowed range')
        if not math.isfinite(settings.external_co2_kg_h) or settings.external_co2_kg_h < 0:
            raise ValueError('external CO2 request must be non-negative')
        if any(v < 0 or not math.isfinite(v) for caps in (settings.heat_caps_kw, settings.co2_caps_kg_h)
               for v in caps.values()):
            raise ValueError('capacity caps must be finite and non-negative')
        for requests in (heat_kw, co2_kg_h, lamp_kw):
            if any(v < 0 or not math.isfinite(v) for v in requests.values()):
                raise ValueError('physical requests must be finite and non-negative')
        effects = effects or {}
        m = self._meter
        if m['hour'] != hour:
            raise ValueError('call end_hour before advancing to another hour')
        start_buffer = self.buffer_kwh
        effective_buffer_capacity = float(self.spec.buffer.capacity_kwh) * self._factor(effects, 'buffer')
        spilled_buffer = max(0.0, self.buffer_kwh - effective_buffer_capacity)
        self.buffer_kwh -= spilled_buffer
        standing_loss = spilled_buffer + min(self.buffer_kwh, self.buffer_kwh * self.spec.buffer.loss_per_h * dt_h)
        self.buffer_kwh -= standing_loss - spilled_buffer
        chp_electric = (float(self.spec.chp.electric_kw) * self._factor(effects, 'chp')
                        * settings.chp_load * dt_h)
        chp_heat = chp_electric * self.spec.chp.heat_per_electric
        chp_gas = chp_electric * self.spec.chp.gas_m3_per_kwh_e
        heat_demand = sum(min(v, settings.heat_caps_kw.get(k, v)) for k, v in heat_kw.items()) * dt_h
        discharge = 0.0
        if settings.buffer in ('auto', 'discharge'):
            discharge = min(self.buffer_kwh, max(0.0, heat_demand - chp_heat))
            self.buffer_kwh -= discharge
        boiler_heat = 0.0
        if settings.boiler == 'auto':
            boiler_heat = min(float(self.spec.boiler.heat_kw) * self._factor(effects, 'boiler') * dt_h,
                              max(0.0, heat_demand - chp_heat - discharge))
        boiler_gas = boiler_heat * self.spec.boiler.gas_m3_per_kwh_heat
        heat_supply = chp_heat + discharge + boiler_heat
        delivered = allocate(heat_kw, heat_supply / dt_h, settings.priority, settings.heat_caps_kw)
        delivered_kwh = sum(delivered.values()) * dt_h
        surplus = max(0.0, chp_heat + boiler_heat + discharge - delivered_kwh)
        # A deliberate discharge with no demand cannot create saleable heat.
        charge = 0.0
        if settings.buffer in ('auto', 'charge'):
            charge = min(surplus, max(0.0, effective_buffer_capacity - self.buffer_kwh))
            self.buffer_kwh += charge
        wasted_heat = max(0.0, surplus - charge)
        # CHP and usable boiler flue gas are captured before the store is drawn.
        produced_co2 = chp_gas * self.spec.chp.co2_kg_per_m3_gas
        if self.spec.boiler.co2_usable:
            produced_co2 += boiler_gas * self.spec.chp.co2_kg_per_m3_gas
        co2_demand = sum(min(v, settings.co2_caps_kg_h.get(k, v)) for k, v in co2_kg_h.items()) * dt_h
        start_co2_store = self.co2_store_kg
        effective_co2_capacity = self.spec.co2_store.capacity_kg * self._factor(effects, 'co2_store')
        spilled_co2 = max(0.0, self.co2_store_kg - effective_co2_capacity)
        self.co2_store_kg -= spilled_co2
        from_flue = min(co2_demand, produced_co2)
        remaining_co2 = co2_demand - from_flue
        from_store = min(remaining_co2, self.co2_store_kg)
        self.co2_store_kg -= from_store
        remaining_co2 -= from_store
        external = min(remaining_co2, settings.external_co2_kg_h * dt_h,
                       float(self.spec.external_co2.max_kg_per_h) *
                       self._factor(effects, 'external_co2') * dt_h)
        excess_flue = produced_co2 - from_flue
        stored_flue = min(excess_flue, max(0.0, effective_co2_capacity - self.co2_store_kg))
        self.co2_store_kg += stored_flue
        self.last_co2_wasted_kg = spilled_co2 + excess_flue - stored_flue
        co2_delivered = allocate(co2_kg_h, (from_flue + from_store + external) / dt_h,
                                 settings.priority, settings.co2_caps_kg_h)
        # Electricity generated by CHP serves lamps first; then the grid imports.
        lamp_need = sum(lamp_kw.values()) * dt_h
        grid_import_cap = float(self.spec.grid.import_kw) * self._factor(effects, 'grid') * dt_h
        imported = min(max(0.0, lamp_need - chp_electric), grid_import_cap)
        lamp_supply = min(lamp_need, chp_electric + imported)
        lamps = allocate(lamp_kw, lamp_supply / dt_h, settings.priority)
        export_cap = float(self.spec.grid.export_kw) * self._factor(effects, 'grid') * dt_h
        exported = min(max(0.0, chp_electric - lamp_supply), export_cap)
        self.last_electricity_curtailed_kwh = max(0.0, chp_electric - lamp_supply - exported)
        self.last_co2_balance = dict(produced_kg=produced_co2, external_kg=external,
                                     delivered_kg=sum(co2_delivered.values()) * dt_h,
                                     stored_change_kg=self.co2_store_kg - start_co2_store,
                                     wasted_kg=self.last_co2_wasted_kg)
        self.last_electricity_balance = dict(generated_kwh=chp_electric, imported_kwh=imported,
                                             lamps_kwh=sum(lamps.values()) * dt_h,
                                             exported_kwh=exported,
                                             curtailed_kwh=self.last_electricity_curtailed_kwh)
        # All metered quantities are amounts over this sub-step, accumulated per hour.
        m['gas_m3'] += chp_gas + boiler_gas
        m['electricity_import_kwh'] += imported
        m['electricity_export_kwh'] += exported
        m['external_co2_kg'] += external
        m['co2_from_store_kg'] += from_store
        m['heat_produced_kwh'] += chp_heat + boiler_heat
        m['heat_lost_kwh'] += standing_loss + wasted_heat
        m['buffer_change_kwh'] += self.buffer_kwh - start_buffer
        for key, value in delivered.items():
            m['heat_delivered_kwh'][key] = m['heat_delivered_kwh'].get(key, 0.0) + value * dt_h
        return Dispatch(delivered, co2_delivered, lamps)

    def end_hour(self, hour: int) -> Metered:
        if self._meter['hour'] != hour:
            raise ValueError('hour does not match accumulated meter')
        result = Metered(**{**self._meter, 'heat_delivered_kwh': dict(self._meter['heat_delivered_kwh'])})
        self._meter = self._empty_meter(hour + 1)
        return result


class Facility:
    """Integration surface for `world.sim`; pass a resolved spec, call substep 12 times, then end_hour."""

    def __init__(self, spec: FacilitySpec, climate: ClimateProfile,
                 prices: EnergyPriceSpec, rng: Rng, hours: int):
        self.spec = spec
        self.weather = WeatherSeries(climate, rng, hours)
        self.prices = PriceSeries(prices, rng, hours)
        self.climates = {c.id: CompartmentClimate(c) for c in spec.compartments}
        self.controller = ClimateController(spec.controller)
        self.energy = EnergyCentre(spec.energy_centre)
        self.energy_settings = EnergySettings()
        self.effects: dict[str, EquipmentEffect] = {}
        self.rng = rng
        self.setpoints = {c.id: ClimateSetpoints.fallback(spec.fallback) for c in spec.compartments}
        self._open_hour: int | None = None
        self._elapsed_h = 0.0

    @classmethod
    def from_specs(cls, spec: FacilitySpec, climate: ClimateProfile,
                   prices: EnergyPriceSpec, rng: Rng, hours: int) -> 'Facility':
        return cls(spec, climate, prices, rng, hours)

    def apply_effect(self, effect: EquipmentEffect) -> None:
        if (not math.isfinite(effect.capacity_factor) or not 0 <= effect.capacity_factor <= 1
                or not math.isfinite(effect.leakage_factor) or effect.leakage_factor < 0):
            raise ValueError('equipment effect factors out of bounds')
        self.effects[effect.target] = effect

    def substep(self, hour: int, dt_h: float,
                setpoints: Mapping[str, ClimateSetpoints],
                batches_load: Mapping[str, tuple[float, float]]) -> dict[str, ClimateSample]:
        """`batches_load[id] = (transpiration_kg_h, co2_uptake_kg_h)`.

        The crop model computes the loads from its previous sample, avoiding an
        algebraic loop between current climate and current crop uptake.
        """
        if not math.isfinite(dt_h) or dt_h <= 0 or dt_h > 1:
            raise ValueError('substep duration must be in (0, 1]')
        if self._open_hour is not None and self._open_hour != hour:
            raise ValueError('end_hour required before the next hour')
        if self._elapsed_h + dt_h > 1 + 1e-9:
            raise ValueError('substeps exceed one hour')
        known = set(self.climates)
        if set(setpoints) - known or set(batches_load) - known:
            raise ValueError('unknown compartment')
        if any(len(load) != 2 or any(not math.isfinite(v) or v < 0 for v in load)
               for load in batches_load.values()):
            raise ValueError('crop loads must be finite, non-negative pairs')
        weather = self.weather.at(hour)
        effects = {key: value for key, value in self.effects.items()
                   if value.until_hour is None or hour < value.until_hour}
        acts: dict[str, Actuators] = {}
        for c in self.spec.compartments:
            room = self.climates[c.id]
            choice = setpoints.get(c.id, self.setpoints[c.id])
            acts[c.id] = self.controller.actuate(c, room.temp_c, room.rh_pct,
                                                 room.co2_ppm, weather.is_day,
                                                 hour, choice, effects)
        dispatch = self.energy.dispatch(
            hour, dt_h,
            {key: act.heat_request_kw for key, act in acts.items()},
            {key: act.co2_request_kg_h for key, act in acts.items()},
            {key: act.lamp_kw for key, act in acts.items()},
            self.energy_settings, effects,
        )
        result = {}
        for c in self.spec.compartments:
            key = c.id
            transpiration, uptake = batches_load.get(key, (0.0, 0.0))
            act = acts[key]
            realised = Actuators(act.vent_pct, act.screen_closed, dispatch.lamp_kw[key],
                                 dispatch.heat_kw[key], dispatch.co2_kg_h[key])
            leak = effects.get(f'{key}.cover', EquipmentEffect('')).leakage_factor
            result[key] = self.climates[key].step(
                hour, dt_h, weather, realised, dispatch.heat_kw[key],
                dispatch.co2_kg_h[key], transpiration, uptake, leak,
            )
        self.setpoints.update(setpoints)
        self._open_hour = hour
        self._elapsed_h += dt_h
        return result

    def end_hour(self, hour: int) -> Metered:
        if hour != self._open_hour or abs(self._elapsed_h - 1.0) > 1e-8:
            raise ValueError('end_hour requires a complete hour of substeps')
        metered = self.energy.end_hour(hour)
        self._open_hour = None
        self._elapsed_h = 0.0
        return metered

    def sensor_readings(self, hour: int) -> dict[str, dict[str, float]]:
        """Named streams make repeated reads identical and do not alter future weather."""
        sensor = self.spec.sensor
        readings = {}
        for key, room in self.climates.items():
            def noise(name: str, sigma: float) -> float:
                return self.rng.stream(f'sensor/{key}/{name}/{hour}').normal(0, sigma)
            readings[key] = {
                'temp_c': room.temp_c + noise('temp', sensor.temp_sigma_c),
                'rh_pct': min(100.0, max(0.0, room.rh_pct + noise('rh', sensor.rh_sigma_pct))),
                'co2_ppm': max(0.0, room.co2_ppm + noise('co2', sensor.co2_sigma_ppm)),
                'par_umol_m2_s': max(0.0, room.last_par_umol_m2_s + noise('par', sensor.par_sigma_umol_m2_s)),
                'dli_mol_m2': room.dli_mol_m2,
            }
        return readings

    def get_forecast(self, issue_hour: int, hours: int) -> tuple[tuple, tuple]:
        return (self.weather.forecast(issue_hour, hours),
                self.prices.forecast(issue_hour, hours, self.weather.profile.forecast))
