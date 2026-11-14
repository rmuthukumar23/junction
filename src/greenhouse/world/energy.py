"""CHP, boiler, buffer, grid and CO2 supply shared by greenhouse compartments."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from typing import Mapping

from envkit.rng import Rng
from greenhouse.config.facility import ClimateProfile, EnergyCentreSpec, EnergyPriceSpec, FacilitySpec
from greenhouse.contracts import (Alarm, ClimateSample, ClimateSetpoints, CropLoad,
                                  EnergySettings, EquipmentEffect, Metered, RuleError,
                                  StartBatch as WorldStartBatch)
from greenhouse.world.climate import CompartmentClimate
from greenhouse.world.controller import Actuators, ClimateController
from greenhouse.world.weather import PriceSeries, WeatherSeries


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
        if any(v < 0 or not math.isfinite(v) for caps in (settings.heat_cap_kw, settings.co2_cap_kg_h)
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
        heat_demand = sum(min(v, settings.heat_cap_kw.get(k, v)) for k, v in heat_kw.items()) * dt_h
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
        delivered = allocate(heat_kw, heat_supply / dt_h, settings.priority, settings.heat_cap_kw)
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
        co2_demand = sum(min(v, settings.co2_cap_kg_h.get(k, v)) for k, v in co2_kg_h.items()) * dt_h
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
                                 settings.priority, settings.co2_cap_kg_h)
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
    """Resolved facility and climate model consumed by `world.sim.Greenhouse`."""

    def __init__(self, spec: FacilitySpec, climate: ClimateProfile,
                 prices: EnergyPriceSpec, rng: Rng, hours: int):
        self.spec = spec
        self.climate_profile = climate
        self.price_spec = prices
        if climate.evaluation_seeds != prices.evaluation_seeds:
            raise ValueError('weather and price files must reserve the same evaluation seeds')
        self.weather = WeatherSeries(climate, rng, hours)
        self.prices = PriceSeries(prices, rng, hours, self.weather.window_id)
        if self.weather.start_utc != self.prices.start_utc:
            raise ValueError('recorded weather and price windows start at different hours')
        self.compartment_ids = tuple(c.id for c in spec.compartments)
        for key, setting in self.fallback_climate().items():
            self.check_climate(key, setting)
        self.check_energy(self.fallback_energy())
        self.climates = {c.id: CompartmentClimate(c) for c in spec.compartments}
        self.controller = ClimateController(spec.controller)
        self.energy = EnergyCentre(spec.energy_centre)
        self.effects: dict[str, EquipmentEffect] = {}
        self.rng = rng
        self._last_actuators: dict[str, Actuators] = {}
        self._open_hour: int | None = None
        self._elapsed_h = 0.0
        self._frost_active = {c: False for c in self.compartment_ids}
        self._co2_low_active = False

    def floor_area_m2(self, compartment_id: str) -> float:
        return float(self._compartment(compartment_id).floor_m2)

    def crop_id(self, compartment_id: str) -> str:
        return self._compartment(compartment_id).crop

    def start_batches(self) -> list[WorldStartBatch]:
        return [WorldStartBatch(c.id, c.crop, batch.age_days,
                                float(c.floor_m2) * batch.area_fraction)
                for c in self.spec.compartments for batch in c.start_batches]

    def equipment_ids(self) -> tuple[str, ...]:
        return (('chp', 'boiler', 'buffer', 'co2_store', 'external_co2', 'grid') +
                tuple(f'{c.id}.{part}' for c in self.spec.compartments
                      for part in ('vents', 'lamps', 'screen', 'cover')))

    def fallback_climate(self) -> dict[str, ClimateSetpoints]:
        fallback = self.spec.fallback
        setting = ClimateSetpoints(fallback.heat_day_c, fallback.heat_night_c,
                                   fallback.vent_min_pct, fallback.vent_max_pct,
                                   fallback.co2_ppm, fallback.screen,
                                   fallback.lamp_hours, fallback.lamp_intensity_pct)
        return {c: setting for c in self.compartment_ids}

    def fallback_energy(self) -> EnergySettings:
        fallback = self.spec.fallback
        return EnergySettings(fallback.chp_load, fallback.boiler, fallback.buffer,
                              fallback.external_co2_kg_h)

    def check_climate(self, compartment_id: str, setpoints: ClimateSetpoints) -> None:
        self._compartment(compartment_id)
        limits = self.spec.limits
        values = (setpoints.heat_day_c, setpoints.heat_night_c,
                  setpoints.vent_min_pct, setpoints.vent_max_pct,
                  setpoints.co2_ppm, setpoints.lamp_intensity_pct)
        if any(not math.isfinite(v) for v in values):
            raise RuleError('climate setpoints must be finite')
        if not all(limits.min_heat_c <= t <= limits.max_heat_c
                   for t in (setpoints.heat_day_c, setpoints.heat_night_c)):
            raise RuleError(f'heating setpoints must be {limits.min_heat_c:g} to {limits.max_heat_c:g} C')
        if not 0 <= setpoints.vent_min_pct <= setpoints.vent_max_pct <= 100:
            raise RuleError('need 0 <= vent_min_pct <= vent_max_pct <= 100')
        if not 0 <= setpoints.co2_ppm <= limits.max_co2_ppm:
            raise RuleError(f'co2_ppm must be 0 to {limits.max_co2_ppm:g}')
        if setpoints.screen not in ('auto', 'open', 'closed'):
            raise RuleError('invalid screen mode')
        if not 0 <= setpoints.lamp_intensity_pct <= 100:
            raise RuleError('lamp_intensity_pct must be 0 to 100')
        if any(type(h) is not int or not 0 <= h <= 23 for h in setpoints.lamp_hours):
            raise RuleError('lamp_hours must contain hours 0 to 23')
        if len(set(setpoints.lamp_hours)) != len(setpoints.lamp_hours):
            raise RuleError('lamp_hours must be distinct')

    def check_energy(self, settings: EnergySettings) -> None:
        values = (settings.chp_load, settings.external_co2_kg_h,
                  *settings.heat_cap_kw.values(), *settings.co2_cap_kg_h.values())
        if any(not math.isfinite(v) for v in values):
            raise RuleError('energy settings must be finite')
        if (settings.chp_load != 0 and
                not self.spec.energy_centre.chp.min_load <= settings.chp_load <= 1):
            raise RuleError(f'chp_load must be 0 or {self.spec.energy_centre.chp.min_load:g} to 1')
        if settings.boiler not in ('auto', 'off') or settings.buffer not in ('auto', 'charge', 'hold', 'discharge'):
            raise RuleError('invalid boiler or buffer mode')
        if not 0 <= settings.external_co2_kg_h <= float(self.spec.energy_centre.external_co2.max_kg_per_h):
            raise RuleError('external_co2_kg_h exceeds the contract limit')
        for name, mapping in (('priority', settings.priority), ('heat_cap_kw', settings.heat_cap_kw),
                              ('co2_cap_kg_h', settings.co2_cap_kg_h)):
            if set(mapping) - set(self.compartment_ids):
                raise RuleError(f'{name} contains an unknown compartment')
        if any(type(level) is not int or level < 0 for level in settings.priority.values()):
            raise RuleError('priority must contain non-negative integers')
        if any(v < 0 for mapping in (settings.heat_cap_kw, settings.co2_cap_kg_h)
               for v in mapping.values()):
            raise RuleError('capacity caps must be non-negative')

    def apply_effect(self, effect: EquipmentEffect) -> None:
        if effect.target not in self.equipment_ids():
            raise RuleError(f'unknown equipment {effect.target!r}')
        if (not math.isfinite(effect.capacity_factor) or not 0 <= effect.capacity_factor <= 1
                or not math.isfinite(effect.leakage_factor) or effect.leakage_factor < 0):
            raise RuleError('equipment effect factors out of bounds')
        self.effects[effect.target] = effect

    def clear_effect(self, target: str) -> None:
        self.effects.pop(target, None)

    def receive_co2(self, kg: float) -> None:
        if not math.isfinite(kg) or kg < 0:
            raise RuleError('CO2 delivery must be finite and non-negative')
        self.energy.co2_store_kg = min(self.spec.energy_centre.co2_store.capacity_kg,
                                       self.energy.co2_store_kg + kg)

    def substep(self, hour: int, dt_h: float,
                climate: dict[str, ClimateSetpoints], energy: EnergySettings,
                loads: dict[str, CropLoad]) -> dict[str, ClimateSample]:
        """Crop loads use the preceding sample; negative CO2 uptake is night respiration."""
        if not math.isfinite(dt_h) or dt_h <= 0 or dt_h > 1:
            raise ValueError('substep duration must be in (0, 1]')
        if self._open_hour is not None and self._open_hour != hour:
            raise ValueError('end_hour required before the next hour')
        if self._elapsed_h + dt_h > 1 + 1e-9:
            raise ValueError('substeps exceed one hour')
        if set(climate) != set(self.compartment_ids) or set(loads) != set(self.compartment_ids):
            raise ValueError('one climate setting and crop load required per compartment')
        for key in self.compartment_ids:
            self.check_climate(key, climate[key])
            load = loads[key]
            if (any(not math.isfinite(v) for v in
                    (load.planted_m2, load.transpiration_kg_h, load.co2_uptake_kg_h)) or
                    load.planted_m2 < 0 or load.transpiration_kg_h < 0):
                raise ValueError('crop loads must be finite; area and transpiration must be non-negative')
        self.check_energy(energy)
        weather = self.weather.at(hour)
        effects = {key: value for key, value in self.effects.items()
                   if value.until_hour is None or hour < value.until_hour}
        acts: dict[str, Actuators] = {}
        for c in self.spec.compartments:
            room = self.climates[c.id]
            acts[c.id] = self.controller.actuate(c, room.temp_c, room.rh_pct,
                                                 room.co2_ppm, weather.is_day,
                                                 hour, climate[c.id], effects)
        dispatch = self.energy.dispatch(
            hour, dt_h,
            {key: act.heat_request_kw for key, act in acts.items()},
            {key: act.co2_request_kg_h for key, act in acts.items()},
            {key: act.lamp_kw for key, act in acts.items()},
            energy, effects,
        )
        result: dict[str, ClimateSample] = {}
        for c in self.spec.compartments:
            key = c.id
            load, act = loads[key], acts[key]
            realised = Actuators(act.vent_pct, act.screen_closed, dispatch.lamp_kw[key],
                                 dispatch.heat_kw[key], dispatch.co2_kg_h[key])
            leak = effects.get(f'{key}.cover', EquipmentEffect('')).leakage_factor
            result[key] = self.climates[key].step(
                hour, dt_h, weather, realised, dispatch.heat_kw[key],
                dispatch.co2_kg_h[key], load.transpiration_kg_h,
                load.co2_uptake_kg_h, leak,
            )
            self._last_actuators[key] = realised
        self._open_hour = hour
        self._elapsed_h += dt_h
        return result

    def end_hour(self, hour: int) -> tuple[Metered, list[Alarm]]:
        if hour != self._open_hour or abs(self._elapsed_h - 1.0) > 1e-8:
            raise ValueError('end_hour requires a complete hour of substeps')
        metered = self.energy.end_hour(hour)
        price = self.prices.at(hour)
        metered = replace(metered, gas_eur_per_m3=price.gas_eur_m3,
                          import_eur_per_kwh=price.import_eur_kwh,
                          export_eur_per_kwh=price.export_eur_kwh)
        alarms = []
        for key in self.compartment_ids:
            cold = self.climates[key].temp_c < self.spec.alarms.frost_risk_temp_c
            if cold and not self._frost_active[key]:
                alarms.append(Alarm(hour, 'frost_risk', key,
                                    f'{key} temperature is {self.climates[key].temp_c:.1f} C'))
            self._frost_active[key] = cold
        low = self.energy.co2_store_kg < self.spec.alarms.co2_low_kg
        if low and not self._co2_low_active:
            alarms.append(Alarm(hour, 'stock_low', 'co2_store', 'CO2 store is low'))
        self._co2_low_active = low
        self._open_hour = None
        self._elapsed_h = 0.0
        return metered, alarms

    def view(self, hour: int, rng: Rng) -> dict:
        weather = self.weather.at(min(hour, len(self.weather.hours) - 1))
        readings = self.sensor_readings(hour, rng)
        return {
            'compartments': {key: {**values, 'actuators': asdict(self._last_actuators[key])
                                         if key in self._last_actuators else {}}
                             for key, values in readings.items()},
            'energy_centre': {'buffer_kwh': self.energy.buffer_kwh,
                              'co2_store_kg': self.energy.co2_store_kg},
            'outside': {'temp_c': weather.temp_c, 'rh_pct': weather.rh_pct,
                        'solar_w_m2': weather.solar_w_m2, 'wind_m_s': weather.wind_m_s},
        }

    def sensor_readings(self, hour: int, rng: Rng | None = None) -> dict[str, dict[str, float]]:
        """Named streams make repeated reads identical and do not alter future weather."""
        rng = rng or self.rng.stream(f'readings/{hour}')
        sensor = self.spec.sensor
        readings = {}
        for key, room in self.climates.items():
            def noise(name: str, sigma: float) -> float:
                return rng.stream(f'sensor/{key}/{name}/{hour}').normal(0, sigma)
            readings[key] = {
                'temp_c': room.temp_c + noise('temp', sensor.temp_sigma_c),
                'rh_pct': min(100.0, max(0.0, room.rh_pct + noise('rh', sensor.rh_sigma_pct))),
                'co2_ppm': max(0.0, room.co2_ppm + noise('co2', sensor.co2_sigma_ppm)),
                'par_umol_m2_s': max(0.0, room.last_par_umol_m2_s + noise('par', sensor.par_sigma_umol_m2_s)),
                'dli_mol_m2': room.dli_mol_m2,
            }
        return readings

    def forecast(self, hour: int, hours: int) -> dict:
        return {
            'weather': [asdict(x) for x in self.weather.forecast(hour, hours)],
            'energy_prices': [asdict(x) for x in self.prices.forecast(hour, hours,
                                   self.climate_profile.forecast)],
        }

    def rules(self) -> dict:
        """Publish the fixed model and tariffs; hidden draws remain in observations."""
        centre = self.spec.energy_centre
        return {
            'model': {
                'heat': 'Thermal mass times temperature change = delivered heat + solar + lamp heat - cover U*A*(inside-outside) - air-exchange loss',
                'co2': 'Flue gas, stored and external CO2 are allocated by priority; vents and leakage dilute it',
                'humidity': 'Crop transpiration adds vapour; ventilation and cover condensation remove it',
                'time': 'One hour comprises substeps; controls apply through the built-in proportional controller',
            },
            'allocation': 'Higher integer priority first; proportional within each priority level',
            'compartments': {c.id: {
                'crop': c.crop,
                'start_batches': [asdict(batch) for batch in c.start_batches],
                'max_vent_ach': c.max_vent_ach,
                'solar_umol_per_j': c.solar_umol_per_j,
                'wind_leakage_per_m_s': c.wind_leakage_per_m_s,
                'cover_surface_temp_fraction': c.cover_surface_temp_fraction,
                'lamp_umol_per_j': c.lamps.umol_per_j,
                'lamp_heat_fraction': c.lamps.heat_fraction,
            } for c in self.spec.compartments},
            'controller': asdict(self.spec.controller),
            'sensors': asdict(self.spec.sensor),
            'climate_limits': asdict(self.spec.limits),
            'weather_profile': {**asdict(self.climate_profile.weather),
                                'source': 'recorded hourly KNMI De Bilt observations'},
            'forecast_error': asdict(self.climate_profile.forecast),
            'fallback': {'climate': {c: asdict(sp) for c, sp in self.fallback_climate().items()},
                         'energy': asdict(self.fallback_energy())},
            'energy_centre': {
                'chp': {'heat_per_electric': centre.chp.heat_per_electric,
                        'co2_kg_per_m3_gas': centre.chp.co2_kg_per_m3_gas,
                        'gas_m3_per_kwh_e': centre.chp.gas_m3_per_kwh_e,
                        'min_load': centre.chp.min_load},
                'boiler': {'gas_m3_per_kwh_heat': centre.boiler.gas_m3_per_kwh_heat,
                           'co2_usable': centre.boiler.co2_usable},
                'buffer': {'loss_per_h': centre.buffer.loss_per_h,
                           'start_fraction': centre.buffer.start_fraction},
                'co2_store': asdict(centre.co2_store),
            },
            # Historical rows are future truth; only the tariff transformation is public.
            'energy_prices': {'tariff': asdict(self.price_spec.tariff), 'source': 'recorded Dutch day-ahead and gas-day data'},
            'equipment_ids': self.equipment_ids(),
        }

    def _compartment(self, key: str):
        for c in self.spec.compartments:
            if c.id == key:
                return c
        raise RuleError(f'unknown compartment {key!r}')


def build_facility(facility: FacilitySpec, climate: ClimateProfile,
                   energy_prices: EnergyPriceSpec, rng: Rng) -> Facility:
    """Factory used by `world.modules.build` after data-file resolution."""
    return Facility(facility, climate, energy_prices, rng, climate.series_hours)
