"""Compartment balance sanity checks."""
import tomllib
import dataclasses
import unittest
from pathlib import Path

from envkit.rng import Rng
from greenhouse.config.base import resolve
from greenhouse.config.facility import parse_facility, parse_climate
from greenhouse.world.climate import CompartmentClimate
from greenhouse.world.controller import Actuators
from greenhouse.world.weather import WeatherHour

DATA = Path(__file__).resolve().parents[2] / 'data'


class ClimateTests(unittest.TestCase):
    def setUp(self):
        facility = parse_facility(tomllib.loads((DATA / 'facilities/nl_two_compartment.toml').read_text()), 'facility')
        self.comp = resolve(facility, Rng(1)).compartments[0]
        self.weather = WeatherHour(0, -2.0, 0.0, 2.0, 85.0, False, 420.0)
        self.off = Actuators(0.0, False, 0.0, 0.0, 0.0)

    def test_unheated_room_cools_towards_outside(self):
        room = CompartmentClimate(self.comp, initial_temp_c=20)
        for _ in range(12 * 24):
            room.step(0, 1/12, self.weather, self.off, 0.0, 0.0, 0.0, 0.0)
        self.assertLess(room.temp_c, 5)
        self.assertGreater(room.temp_c, -3)

    def test_closed_screen_reduces_night_heat_loss(self):
        open_room = CompartmentClimate(self.comp, initial_temp_c=20)
        closed_room = CompartmentClimate(self.comp, initial_temp_c=20)
        closed = Actuators(0.0, True, 0.0, 0.0, 0.0)
        open_room.step(0, 1/12, self.weather, self.off, 0, 0, 0, 0)
        closed_room.step(0, 1/12, self.weather, closed, 0, 0, 0, 0)
        self.assertGreater(closed_room.temp_c, open_room.temp_c)

    def test_open_vents_reduce_co2_and_twelve_steps_match_hour(self):
        vents = Actuators(100.0, False, 0.0, 0.0, 0.0)
        room = CompartmentClimate(self.comp, initial_temp_c=20, initial_co2_ppm=1200)
        for _ in range(12):
            room.step(0, 1/12, self.weather, vents, 0, 0, 0, 0)
        self.assertLess(room.co2_ppm, 1200)
        self.assertGreaterEqual(room.co2_ppm, 420)
        a = CompartmentClimate(self.comp, initial_temp_c=20)
        b = CompartmentClimate(self.comp, initial_temp_c=20)
        for _ in range(12):
            a.step(0, 1/12, self.weather, self.off, 50, 0, 0, 0)
        b.step(0, 1.0, self.weather, self.off, 50, 0, 0, 0)
        self.assertAlmostEqual(a.temp_c, b.temp_c, places=6)

class AdditionalClimateTests(unittest.TestCase):
    def setUp(self):
        facility = parse_facility(tomllib.loads((DATA / 'facilities/nl_two_compartment.toml').read_text()), 'facility')
        self.comp = resolve(facility, Rng(1)).compartments[0]
        self.weather = WeatherHour(0, -2.0, 0.0, 2.0, 85.0, False, 420.0)

    def test_area_scales_heat_request(self):
        from greenhouse.world.controller import ClimateController, ClimateSetpoints
        facility = parse_facility(tomllib.loads((DATA / 'facilities/nl_two_compartment.toml').read_text()), 'facility')
        controller = ClimateController(facility.controller)
        settings = ClimateSetpoints(20, 20, 0, 100, 0, 'open', (), 0)
        one = controller.actuate(self.comp, 10, 70, 420, False, 0, settings)
        twice = controller.actuate(dataclasses.replace(self.comp, floor_m2=self.comp.floor_m2 * 2),
                                   10, 70, 420, False, 0, settings)
        self.assertAlmostEqual(twice.heat_request_kw, 2 * one.heat_request_kw)

    def test_co2_dosing_needs_daylight_or_scheduled_lamps(self):
        from greenhouse.world.controller import ClimateController, ClimateSetpoints
        facility = parse_facility(tomllib.loads((DATA / 'facilities/nl_two_compartment.toml').read_text()), 'facility')
        controller = ClimateController(facility.controller)
        setting = ClimateSetpoints(18, 15, 0, 20, 800, 'auto', (), 0)
        night = controller.actuate(self.comp, 15, 70, 420, False, 2, setting)
        day = controller.actuate(self.comp, 18, 70, 420, True, 12, setting)
        lit = controller.actuate(self.comp, 15, 70, 420, False, 2,
                                dataclasses.replace(setting, lamp_hours=(2,), lamp_intensity_pct=50))
        self.assertEqual(night.co2_request_kg_h, 0)
        self.assertGreater(day.co2_request_kg_h, 0)
        self.assertGreater(lit.co2_request_kg_h, 0)

    def test_broken_cover_increases_cooling_and_dli_resets_each_day(self):
        act = Actuators(0, False, 0, 0, 0)
        intact = CompartmentClimate(self.comp, initial_temp_c=20)
        broken = CompartmentClimate(self.comp, initial_temp_c=20)
        intact.step(0, 1/12, self.weather, act, 0, 0, 0, 0)
        broken.step(0, 1/12, self.weather, act, 0, 0, 0, 0, leakage_factor=4)
        self.assertLess(broken.temp_c, intact.temp_c)
        sunny = WeatherHour(12, 8, 200, 2, 70, True, 420)
        intact.step(12, 1/12, sunny, act, 0, 0, 0, 0)
        self.assertGreater(intact.dli_mol_m2, 0)
        intact.step(24, 1/12, self.weather, act, 0, 0, 0, 0)
        self.assertEqual(intact.dli_mol_m2, 0)

    def test_night_respiration_releases_co2_into_the_air(self):
        act = Actuators(0, False, 0, 0, 0)
        control = CompartmentClimate(self.comp, initial_co2_ppm=420)
        respiring = CompartmentClimate(self.comp, initial_co2_ppm=420)
        control.step(0, 1/12, self.weather, act, 0, 0, 0, 0)
        respiring.step(0, 1/12, self.weather, act, 0, 0, 0, -1)
        self.assertGreater(respiring.co2_ppm, control.co2_ppm)
