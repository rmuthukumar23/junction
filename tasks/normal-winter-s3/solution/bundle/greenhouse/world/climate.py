"""Conserved heat, CO2 and water-vapour balances for one compartment."""
from __future__ import annotations

import math

from greenhouse.config.facility import CompartmentSpec
from greenhouse.contracts import ClimateSample
from greenhouse.world.controller import Actuators
from greenhouse.world.weather import WeatherHour

# Dry-air density and heat capacity at greenhouse conditions, SI approximations.
_AIR_KG_M3 = 1.2
_AIR_CP_KWH_KG_K = 1005.0 / 3_600_000.0
# Ideal-gas ratio converting CO2 volume fraction to mass fraction.
_CO2_TO_AIR_MOLAR_RATIO = 44.01 / 28.97


def _saturated_water_kg_m3(temp_c: float) -> float:
    """Magnus saturation pressure and ideal-gas water-vapour density."""
    pressure_pa = 610.94 * math.exp(17.625 * temp_c / (temp_c + 243.04))
    return pressure_pa * 0.01801528 / (8.314462618 * (temp_c + 273.15))


class CompartmentClimate:
    def __init__(self, spec: CompartmentSpec, *, initial_temp_c: float | None = None,
                 initial_rh_pct: float | None = None, initial_co2_ppm: float | None = None):
        self.spec = spec
        initial_temp_c = spec.initial_temp_c if initial_temp_c is None else initial_temp_c
        initial_rh_pct = spec.initial_rh_pct if initial_rh_pct is None else initial_rh_pct
        initial_co2_ppm = spec.initial_co2_ppm if initial_co2_ppm is None else initial_co2_ppm
        self.temp_c = initial_temp_c
        self.co2_ppm = initial_co2_ppm
        self.vapour_kg = (_saturated_water_kg_m3(initial_temp_c) * initial_rh_pct / 100
                          * self.volume_m3)
        self.dli_mol_m2 = 0.0
        self.condensed_kg = 0.0
        self.last_par_umol_m2_s = 0.0
        self._dli_day = -1

    @property
    def volume_m3(self) -> float:
        return float(self.spec.floor_m2) * float(self.spec.height_m)

    @property
    def rh_pct(self) -> float:
        return max(0.0, min(100.0, 100 * self.vapour_kg /
                            (self.volume_m3 * _saturated_water_kg_m3(self.temp_c))))

    def step(self, hour: int, dt_h: float, weather: WeatherHour,
             actuator: Actuators, heat_kw: float, co2_kg_h: float,
             transpiration_kg_h: float, co2_uptake_kg_h: float,
             leakage_factor: float = 1.0) -> ClimateSample:
        if dt_h <= 0 or dt_h > 1:
            raise ValueError('substep duration must be in (0, 1] hours')
        if (any(not math.isfinite(v) for v in
                (heat_kw, co2_kg_h, transpiration_kg_h, co2_uptake_kg_h)) or
                min(heat_kw, co2_kg_h, transpiration_kg_h) < 0):
            raise ValueError('physical flows must be finite; heat, dosing and transpiration must be non-negative')
        if hour // 24 != self._dli_day:
            self.dli_mol_m2 = 0.0
            self._dli_day = hour // 24
        area = float(self.spec.floor_m2)
        screen_factor = 1 - float(self.spec.screen.insulation) if actuator.screen_closed else 1.0
        exchange_ach = (float(self.spec.leakage_ach) * leakage_factor
                        * (1 + self.spec.wind_leakage_per_m_s * weather.wind_m_s)
                        + self.spec.max_vent_ach * actuator.vent_pct / 100)
        cover_kw = (float(self.spec.cover_u_w_m2_k) * area * screen_factor
                    * (self.temp_c - weather.temp_c) / 1000)
        exchange_kw = (exchange_ach * self.volume_m3 * _AIR_KG_M3 * _AIR_CP_KWH_KG_K
                       * (self.temp_c - weather.temp_c))
        solar_kw = weather.solar_w_m2 * area * float(self.spec.cover_transmission) / 1000
        lamp_heat_kw = actuator.lamp_kw * self.spec.lamps.heat_fraction
        net_kw = heat_kw + solar_kw + lamp_heat_kw - cover_kw - exchange_kw
        # Exponential approach prevents Euler overshoot when a pane breaks.
        thermal_mass = float(self.spec.thermal_mass_kwh_m2_k) * area
        cooling_kw_per_c = (float(self.spec.cover_u_w_m2_k) * area * screen_factor / 1000
                            + exchange_ach * self.volume_m3 * _AIR_KG_M3 * _AIR_CP_KWH_KG_K)
        if cooling_kw_per_c > 0:
            equilibrium = self.temp_c + net_kw / cooling_kw_per_c
            self.temp_c = equilibrium + (self.temp_c - equilibrium) * math.exp(-cooling_kw_per_c * dt_h / thermal_mass)
        else:
            self.temp_c += net_kw * dt_h / thermal_mass
        # Air exchange acts on concentrations. Negative crop uptake releases CO2.
        # Exponential relaxation preserves bounds.
        decay = math.exp(-exchange_ach * dt_h)
        air_mass = self.volume_m3 * _AIR_KG_M3
        ppm_per_kg = 1e6 / (air_mass * _CO2_TO_AIR_MOLAR_RATIO)
        self.co2_ppm = max(0.0, (weather.outside_co2_ppm + (self.co2_ppm - weather.outside_co2_ppm) * decay
                          + (co2_kg_h - co2_uptake_kg_h) * ppm_per_kg *
                          ((1 - decay) / exchange_ach if exchange_ach else dt_h)))
        # The outside CO2 level is a climate-profile value supplied by weather.
        outside_vapour = _saturated_water_kg_m3(weather.temp_c) * weather.rh_pct / 100
        exchange_fraction = 1 - decay
        source_hours = exchange_fraction / exchange_ach if exchange_ach else dt_h
        self.vapour_kg += ((outside_vapour * self.volume_m3 - self.vapour_kg) * exchange_fraction
                           + transpiration_kg_h * source_hours)
        self.vapour_kg = max(0.0, self.vapour_kg)
        # Condensate is explicitly recorded rather than silently clipping RH.
        cover_temp = weather.temp_c + self.spec.cover_surface_temp_fraction * (self.temp_c - weather.temp_c)
        saturation = _saturated_water_kg_m3(cover_temp) * self.volume_m3
        if self.vapour_kg > saturation:
            self.condensed_kg += self.vapour_kg - saturation
            self.vapour_kg = saturation
        par = (weather.solar_w_m2 * float(self.spec.cover_transmission) * self.spec.solar_umol_per_j
               + actuator.lamp_kw * 1000 / area * self.spec.lamps.umol_per_j)
        self.last_par_umol_m2_s = par
        self.dli_mol_m2 += par * dt_h * 3600 / 1e6
        return ClimateSample(hour, dt_h, self.temp_c, self.rh_pct, self.co2_ppm, par, weather.is_day)
