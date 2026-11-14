"""Simple proportional greenhouse climate computer; setpoints persist outside it."""
from __future__ import annotations

from dataclasses import dataclass
import math

from greenhouse.config.facility import CompartmentSpec, ControllerSpec
from greenhouse.contracts import ClimateSetpoints, EquipmentEffect


@dataclass(frozen=True)
class Actuators:
    vent_pct: float
    screen_closed: bool
    lamp_kw: float
    heat_request_kw: float
    co2_request_kg_h: float


class ClimateController:
    def __init__(self, spec: ControllerSpec):
        self.spec = spec

    def actuate(self, compartment: CompartmentSpec, temp_c: float, rh_pct: float,
                co2_ppm: float, is_day: bool, hour: int,
                setpoints: ClimateSetpoints,
                effects: dict[str, EquipmentEffect] | None = None) -> Actuators:
        if setpoints.screen not in ('auto', 'open', 'closed'):
            raise ValueError('invalid screen mode')
        numbers = (setpoints.heat_day_c, setpoints.heat_night_c, setpoints.vent_min_pct,
                   setpoints.vent_max_pct, setpoints.co2_ppm, setpoints.lamp_intensity_pct)
        if any(not math.isfinite(v) for v in numbers):
            raise ValueError('climate setpoints must be finite')
        if not (0 <= setpoints.vent_min_pct <= setpoints.vent_max_pct <= 100):
            raise ValueError('vent bounds must be ordered percentages')
        if setpoints.co2_ppm < 0 or not 0 <= setpoints.lamp_intensity_pct <= 100:
            raise ValueError('CO2 and lamp setpoints out of bounds')
        if any(type(h) is not int or not 0 <= h <= 23 for h in setpoints.lamp_hours):
            raise ValueError('lamp hours must be hours of the day')
        effects = effects or {}
        target = setpoints.heat_day_c if is_day else setpoints.heat_night_c
        vent_pct = max(setpoints.vent_min_pct,
                       self.spec.vent_pct_per_c * max(0.0, temp_c - target),
                       self.spec.vent_pct_per_rh * max(0.0, rh_pct - self.spec.vent_target_rh_pct))
        vent_pct = min(100.0, setpoints.vent_max_pct, vent_pct)
        vent_pct *= effects.get(f'{compartment.id}.vents', EquipmentEffect('')).capacity_factor
        screen_closed = (setpoints.screen == 'closed' or
                         (setpoints.screen == 'auto' and not is_day and temp_c < target))
        if effects.get(f'{compartment.id}.screen', EquipmentEffect('')).capacity_factor <= 0:
            screen_closed = False
        lamp_kw = (float(compartment.lamps.w_per_m2) * float(compartment.floor_m2) / 1000
                   * setpoints.lamp_intensity_pct / 100)
        if hour % 24 not in setpoints.lamp_hours:
            lamp_kw = 0.0
        lamp_kw *= effects.get(f'{compartment.id}.lamps', EquipmentEffect('')).capacity_factor
        heat_kw = (max(0.0, target - temp_c - self.spec.heat_deadband_c)
                   * self.spec.heat_kw_per_c_m2 * float(compartment.floor_m2))
        co2_kg_h = (max(0.0, setpoints.co2_ppm - co2_ppm)
                    * self.spec.co2_kg_h_per_ppm_m2 * float(compartment.floor_m2))
        if vent_pct >= self.spec.vent_co2_pause_pct:
            co2_kg_h = 0.0
        return Actuators(vent_pct, screen_closed, lamp_kw, heat_kw, co2_kg_h)
