"""Shared-resource allocation and physical conservation."""
import dataclasses
import tomllib
import unittest
from pathlib import Path

from envkit.rng import Rng
from greenhouse.config.base import resolve
from greenhouse.config.facility import parse_facility, parse_climate, parse_energy_prices
from greenhouse.world.energy import EnergyCentre, EnergySettings, Facility
from greenhouse.contracts import EquipmentEffect

DATA = Path(__file__).resolve().parents[2] / 'data'


class EnergyTests(unittest.TestCase):
    def setUp(self):
        doc = tomllib.loads((DATA / 'facilities/nl_two_compartment.toml').read_text())
        self.spec = resolve(parse_facility(doc, 'facility'), Rng(2))

    def test_allocation_priority_and_conservation(self):
        energy = EnergyCentre(self.spec.energy_centre)
        settings = EnergySettings(chp_load=0.5, boiler='off', buffer='hold',
                                  external_co2_kg_h=0.0, priority={'A': 2, 'B': 1})
        result = energy.dispatch(0, 1.0, {'A': 300.0, 'B': 300.0},
                                 {'A': 0.0, 'B': 0.0}, {'A': 0.0, 'B': 0.0}, settings)
        self.assertGreater(result.heat_kw['A'], result.heat_kw['B'])
        self.assertEqual(result.heat_kw['B'], 0.0)
        meter = energy.end_hour(0)
        self.assertAlmostEqual(meter.heat_produced_kwh,
                               sum(meter.heat_delivered_kwh.values()) + meter.buffer_change_kwh + meter.heat_lost_kwh,
                               places=6)

    def test_boiler_trip_and_cover_leak(self):
        facility = Facility.from_specs(
            self.spec,
            parse_climate(tomllib.loads((DATA / 'climates/nl_january.toml').read_text()), 'climate'),
            parse_energy_prices(tomllib.loads((DATA / 'energy_prices/nl_winter.toml').read_text()), 'prices'),
            Rng(3), hours=24,
        )
        facility.apply_effect(EquipmentEffect('boiler', capacity_factor=0.0))
        facility.apply_effect(EquipmentEffect('A.cover', leakage_factor=3.0))
        before = facility.climates['A'].temp_c
        facility.substep(0, 1/12, {}, {})
        self.assertNotEqual(facility.climates['A'].temp_c, before)
        self.assertEqual(facility.sensor_readings(0), facility.sensor_readings(0))
        self.assertEqual(facility.get_forecast(0, 5), facility.get_forecast(0, 5))

class AdditionalEnergyTests(unittest.TestCase):
    def setUp(self):
        spec = parse_facility(tomllib.loads((DATA / 'facilities/nl_two_compartment.toml').read_text()), 'facility')
        self.spec = resolve(spec, Rng(2)).energy_centre

    def test_invalid_caps_do_not_change_state(self):
        energy = EnergyCentre(self.spec)
        start = (energy.buffer_kwh, energy.co2_store_kg)
        bad = EnergySettings(heat_caps_kw={'A': -1})
        with self.assertRaises(ValueError):
            energy.dispatch(0, 1/12, {'A': 100}, {'A': 0}, {'A': 0}, bad)
        self.assertEqual((energy.buffer_kwh, energy.co2_store_kg), start)
        self.assertEqual(energy.end_hour(0).gas_m3, 0)

    def test_boiler_trip_removes_boiler_heat(self):
        energy = EnergyCentre(self.spec)
        settings = EnergySettings(buffer='hold')
        result = energy.dispatch(0, 1, {'A': 1000}, {}, {}, settings,
                                 {'boiler': EquipmentEffect('boiler', capacity_factor=0)})
        self.assertEqual(result.heat_kw['A'], 0)
        self.assertEqual(energy.end_hour(0).heat_produced_kwh, 0)

    def test_co2_and_electricity_conserve_and_chp_sale_loses_money(self):
        energy = EnergyCentre(self.spec)
        settings = EnergySettings(chp_load=1.0, boiler='off', buffer='hold')
        energy.dispatch(0, 1, {}, {}, {}, settings)
        co2 = energy.last_co2_balance
        self.assertAlmostEqual(co2['produced_kg'] + co2['external_kg'],
                               co2['delivered_kg'] + co2['stored_change_kg'] + co2['wasted_kg'])
        power = energy.last_electricity_balance
        self.assertAlmostEqual(power['generated_kwh'] + power['imported_kwh'],
                               power['lamps_kwh'] + power['exported_kwh'] + power['curtailed_kwh'])
        meter = energy.end_hour(0)
        prices = parse_energy_prices(tomllib.loads((DATA / 'energy_prices/nl_winter.toml').read_text()), 'prices')
        # Mild day: no heat/CO2 demand, so power export alone cannot pay for gas.
        self.assertLess(meter.electricity_export_kwh * prices.electricity.base_eur_kwh *
                        prices.electricity.export_fraction - meter.gas_m3 * prices.gas_eur_m3, 0)

class FacilityEpisodeTests(unittest.TestCase):
    def test_full_42_days_under_10s_and_conserved(self):
        import time
        from greenhouse.world.controller import ClimateSetpoints
        facility = parse_facility(tomllib.loads((DATA / 'facilities/nl_two_compartment.toml').read_text()), 'facility')
        climate = parse_climate(tomllib.loads((DATA / 'climates/nl_january.toml').read_text()), 'climate')
        prices = parse_energy_prices(tomllib.loads((DATA / 'energy_prices/nl_winter.toml').read_text()), 'prices')
        spec = resolve(facility, Rng(11))
        greenhouse = Facility.from_specs(spec, climate, prices, Rng(11), hours=1008)
        greenhouse.energy_settings = EnergySettings(chp_load=0.5)
        setpoints = {c.id: ClimateSetpoints(19, 15, 0, 100, 800, 'auto',
                                            tuple(range(8, 16)), 60) for c in spec.compartments}
        started = time.perf_counter()
        total_heat = 0.0
        for hour in range(1008):
            for _ in range(12):
                greenhouse.substep(hour, 1/12, setpoints, {})
            metered = greenhouse.end_hour(hour)
            self.assertAlmostEqual(metered.heat_produced_kwh,
                                   sum(metered.heat_delivered_kwh.values()) +
                                   metered.buffer_change_kwh + metered.heat_lost_kwh, places=6)
            total_heat += metered.heat_produced_kwh
        self.assertLess(time.perf_counter() - started, 10)
        self.assertGreater(total_heat, 0)
        self.assertEqual(greenhouse.sensor_readings(1007), greenhouse.sensor_readings(1007))

    def test_failed_buffer_and_co2_store_lose_capacity_without_creating_resources(self):
        spec = parse_facility(tomllib.loads((DATA / 'facilities/nl_two_compartment.toml').read_text()), 'facility')
        energy = EnergyCentre(resolve(spec, Rng(2)).energy_centre)
        settings = EnergySettings(boiler='off', buffer='auto')
        energy.dispatch(0, 1, {'A': 500}, {'A': 5}, {}, settings,
                        {'buffer': EquipmentEffect('buffer', capacity_factor=0),
                         'co2_store': EquipmentEffect('co2_store', capacity_factor=0)})
        self.assertEqual(energy.buffer_kwh, 0)
        self.assertEqual(energy.co2_store_kg, 0)
        meter = energy.end_hour(0)
        self.assertAlmostEqual(meter.heat_produced_kwh,
                               sum(meter.heat_delivered_kwh.values()) +
                               meter.buffer_change_kwh + meter.heat_lost_kwh)
        co2 = energy.last_co2_balance
        self.assertAlmostEqual(co2['produced_kg'] + co2['external_kg'],
                               co2['delivered_kg'] + co2['stored_change_kg'] + co2['wasted_kg'])

    def test_same_seed_and_actions_replay_exactly(self):
        from greenhouse.world.controller import ClimateSetpoints
        spec = parse_facility(tomllib.loads((DATA / 'facilities/nl_two_compartment.toml').read_text()), 'facility')
        climate = parse_climate(tomllib.loads((DATA / 'climates/nl_january.toml').read_text()), 'climate')
        prices = parse_energy_prices(tomllib.loads((DATA / 'energy_prices/nl_winter.toml').read_text()), 'prices')
        resolved = resolve(spec, Rng(13))
        settings = {c.id: ClimateSetpoints(18, 14, 0, 100, 800, 'auto', (), 0)
                    for c in resolved.compartments}
        def run():
            facility = Facility.from_specs(resolved, climate, prices, Rng(13), hours=25)
            result = []
            for hour in range(24):
                for _ in range(12):
                    samples = facility.substep(hour, 1/12, settings, {})
                result.append((samples, facility.end_hour(hour), facility.sensor_readings(hour)))
            return result
        self.assertEqual(run(), run())

    def test_invalid_setpoints_do_not_mutate_facility(self):
        from greenhouse.world.controller import ClimateSetpoints
        spec = parse_facility(tomllib.loads((DATA / 'facilities/nl_two_compartment.toml').read_text()), 'facility')
        climate = parse_climate(tomllib.loads((DATA / 'climates/nl_january.toml').read_text()), 'climate')
        prices = parse_energy_prices(tomllib.loads((DATA / 'energy_prices/nl_winter.toml').read_text()), 'prices')
        facility = Facility.from_specs(resolve(spec, Rng(5)), climate, prices, Rng(5), hours=25)
        before = (facility.climates['A'].temp_c, facility.energy.buffer_kwh,
                  dict(facility.setpoints))
        bad = ClimateSetpoints(20, 16, 80, 10, 800, 'auto', (), 0)
        with self.assertRaises(ValueError):
            facility.substep(0, 1/12, {'A': bad}, {})
        self.assertEqual((facility.climates['A'].temp_c, facility.energy.buffer_kwh,
                          facility.setpoints), before)
