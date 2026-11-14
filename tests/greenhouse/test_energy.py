"""Shared-resource allocation and physical conservation."""
import dataclasses
import tomllib
import unittest
from pathlib import Path

from envkit.rng import Rng
from greenhouse.config.base import resolve
from greenhouse.config.facility import parse_facility, parse_climate, parse_energy_prices
from greenhouse.world.energy import EnergyCentre, EnergySettings, Facility, build_facility
from greenhouse.world.weather import PriceSeries
from greenhouse.contracts import CropLoad, EquipmentEffect, RuleError

DATA = Path(__file__).resolve().parents[2] / 'data'


class EnergyTests(unittest.TestCase):
    def setUp(self):
        doc = tomllib.loads((DATA / 'facilities/nl_two_compartment.toml').read_text())
        self.spec = resolve(parse_facility(doc, 'facility'), Rng(2))

    def test_allocation_priority_and_conservation(self):
        energy = EnergyCentre(self.spec.energy_centre)
        settings = EnergySettings(0.5, 'off', 'hold', 0.0, priority={'A': 2, 'B': 1})
        result = energy.dispatch(0, 1.0, {'A': 300.0, 'B': 300.0},
                                 {'A': 0.0, 'B': 0.0}, {'A': 0.0, 'B': 0.0}, settings)
        self.assertGreater(result.heat_kw['A'], result.heat_kw['B'])
        self.assertEqual(result.heat_kw['B'], 0.0)
        meter = energy.end_hour(0)
        self.assertAlmostEqual(meter.heat_produced_kwh,
                               sum(meter.heat_delivered_kwh.values()) + meter.buffer_change_kwh + meter.heat_lost_kwh,
                               places=6)

    def test_boiler_trip_and_cover_leak(self):
        facility = Facility(
            self.spec,
            parse_climate(tomllib.loads((DATA / 'climates/nl_january.toml').read_text()), 'climate'),
            parse_energy_prices(tomllib.loads((DATA / 'energy_prices/nl_winter.toml').read_text()), 'prices'),
            Rng(3), hours=24,
        )
        facility.apply_effect(EquipmentEffect('boiler', capacity_factor=0.0))
        facility.apply_effect(EquipmentEffect('A.cover', leakage_factor=3.0))
        before = facility.climates['A'].temp_c
        loads = {key: CropLoad(0, 0, 0) for key in facility.compartment_ids}
        facility.substep(0, 1/12, facility.fallback_climate(), facility.fallback_energy(), loads)
        self.assertNotEqual(facility.climates['A'].temp_c, before)
        self.assertEqual(facility.sensor_readings(0), facility.sensor_readings(0))
        self.assertEqual(facility.forecast(0, 5), facility.forecast(0, 5))

class AdditionalEnergyTests(unittest.TestCase):
    def setUp(self):
        spec = parse_facility(tomllib.loads((DATA / 'facilities/nl_two_compartment.toml').read_text()), 'facility')
        self.spec = resolve(spec, Rng(2)).energy_centre

    def test_invalid_caps_do_not_change_state(self):
        energy = EnergyCentre(self.spec)
        start = (energy.buffer_kwh, energy.co2_store_kg)
        bad = EnergySettings(0, 'auto', 'auto', 0, heat_cap_kw={'A': -1})
        with self.assertRaises(ValueError):
            energy.dispatch(0, 1/12, {'A': 100}, {'A': 0}, {'A': 0}, bad)
        self.assertEqual((energy.buffer_kwh, energy.co2_store_kg), start)
        self.assertEqual(energy.end_hour(0).gas_m3, 0)

    def test_boiler_trip_removes_boiler_heat(self):
        energy = EnergyCentre(self.spec)
        settings = EnergySettings(0, 'auto', 'hold', 0)
        result = energy.dispatch(0, 1, {'A': 1000}, {}, {}, settings,
                                 {'boiler': EquipmentEffect('boiler', capacity_factor=0)})
        self.assertEqual(result.heat_kw['A'], 0)
        self.assertEqual(energy.end_hour(0).heat_produced_kwh, 0)

    def test_co2_and_electricity_conserve_and_chp_sale_loses_money(self):
        energy = EnergyCentre(self.spec)
        settings = EnergySettings(1, 'off', 'hold', 0)
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
        first_price = PriceSeries(prices, Rng(2), 1).at(0)
        self.assertLess(meter.electricity_export_kwh * first_price.export_eur_kwh -
                        meter.gas_m3 * first_price.gas_eur_m3, 0)

class FacilityEpisodeTests(unittest.TestCase):
    def test_handover_baseline_uses_crop_climate_and_depletes_unreplenished_co2(self):
        spec = resolve(parse_facility(tomllib.loads((DATA / 'facilities/nl_two_compartment.toml').read_text()),
                                      'facility'), Rng(19))
        climate = parse_climate(tomllib.loads((DATA / 'climates/nl_january.toml').read_text()), 'climate')
        prices = parse_energy_prices(tomllib.loads((DATA / 'energy_prices/nl_winter.toml').read_text()), 'prices')
        facility = build_facility(spec, climate, prices, Rng(19))
        baseline = facility.fallback_climate()['A']
        self.assertGreater(baseline.heat_day_c, baseline.heat_night_c)
        self.assertGreater(baseline.heat_night_c, facility.spec.alarms.frost_risk_temp_c)
        self.assertGreater(baseline.co2_ppm, 0)
        self.assertTrue(baseline.lamp_hours)
        self.assertIn('boiler', facility.equipment_ids())
        loads = {key: CropLoad(0, 0, 0) for key in facility.compartment_ids}
        low_alarms = []
        for hour in range(1008):
            for _ in range(12):
                facility.substep(hour, 1/12, facility.fallback_climate(), facility.fallback_energy(), loads)
            _, alarms = facility.end_hour(hour)
            low_alarms.extend(a for a in alarms if a.target == 'co2_store' and a.kind == 'stock_low')
        self.assertEqual(facility.energy.co2_store_kg, 0)
        self.assertEqual(len(low_alarms), 1)

    def test_contract_refusals_do_not_mutate_state_and_hour_meter_has_prices(self):
        spec = resolve(parse_facility(tomllib.loads((DATA / 'facilities/nl_two_compartment.toml').read_text()),
                                      'facility'), Rng(20))
        climate = parse_climate(tomllib.loads((DATA / 'climates/nl_january.toml').read_text()), 'climate')
        prices = parse_energy_prices(tomllib.loads((DATA / 'energy_prices/nl_winter.toml').read_text()), 'prices')
        facility = build_facility(spec, climate, prices, Rng(20))
        before = (facility.energy.buffer_kwh, facility.energy.co2_store_kg,
                  {k: v.temp_c for k, v in facility.climates.items()})
        with self.assertRaises(RuleError):
            facility.check_energy(EnergySettings(0, 'auto', 'auto', 0, heat_cap_kw={'missing': 1}))
        with self.assertRaises(RuleError):
            facility.check_climate('A', dataclasses.replace(facility.fallback_climate()['A'], heat_day_c=100))
        self.assertEqual(before, (facility.energy.buffer_kwh, facility.energy.co2_store_kg,
                                  {k: v.temp_c for k, v in facility.climates.items()}))
        loads = {key: CropLoad(0, 0, 0) for key in facility.compartment_ids}
        for _ in range(12):
            facility.substep(0, 1/12, facility.fallback_climate(), facility.fallback_energy(), loads)
        metered, alarms = facility.end_hour(0)
        self.assertGreater(metered.gas_eur_per_m3, 0)
        self.assertEqual(metered.import_eur_per_kwh, facility.prices.at(0).import_eur_kwh)
        self.assertEqual(metered.export_eur_per_kwh, facility.prices.at(0).export_eur_kwh)
        self.assertIsInstance(alarms, list)

    def test_real_facility_with_real_business_and_fake_crops_for_ten_days(self):
        from fakes import FakeCrop
        from greenhouse.config.market import parse_event, parse_market
        from greenhouse.world.business import build_business
        from greenhouse.world.modules import Modules
        from greenhouse.world.sim import Greenhouse

        def read(relative):
            return tomllib.loads((DATA / relative).read_text())

        rng = Rng(21)
        spec = resolve(parse_facility(read('facilities/nl_two_compartment.toml'), 'facility'), rng.stream('facility'))
        climate = parse_climate(read('climates/nl_january.toml'), 'climate')
        prices = parse_energy_prices(read('energy_prices/nl_winter.toml'), 'prices')
        facility = build_facility(spec, climate, prices, rng.stream('facility'))
        market = resolve(parse_market(read('markets/nl_winter.toml'), 'market'), rng.stream('market'))
        events = [resolve(parse_event(read(f'events/{name}.toml'), name), rng.stream(name))
                  for name in ('boiler_trip', 'late_delivery')]
        events = [dataclasses.replace(e, rate_per_day=0.0) for e in events]
        events[0] = dataclasses.replace(events[0], pinned_hours=(7,))
        growth = {c.crop: FakeCrop(c.crop) for c in spec.compartments}
        business = build_business(market, events, tuple(growth), facility.equipment_ids(), 240,
                                  rng.stream('business'))
        sim = Greenhouse(Modules(facility, business, growth, 240, 12), rng.stream('sim'))
        for hour in range(240):
            sim.run_hour()
            if hour == 7:
                self.assertIn('boiler', sim.effects)
                self.assertEqual(facility.effects['boiler'].capacity_factor, 0)
        self.assertEqual(sim.hour, 240)
        self.assertEqual(len(sim.history), 240)
        self.assertGreater(sim.history[0].metered['gas_eur_per_m3'], 0)
        self.assertLess(sim.business.totals()['gas'], 0)

    def test_real_modules_run_together_for_ten_days(self):
        from greenhouse.world.modules import build
        from greenhouse.world.sim import Greenhouse

        env = {
            'facility': 'data/facilities/nl_two_compartment.toml',
            'climate': 'data/climates/nl_january.toml',
            'energy_prices': 'data/energy_prices/nl_winter.toml',
            'market': 'data/markets/nl_winter.toml',
            'crops': ['data/crops/lettuce_butterhead.toml', 'data/crops/broccoli_micro.toml'],
            'events': ['data/events/boiler_trip.toml', 'data/events/late_delivery.toml'],
            'horizon_days': 10,
            'substeps_per_hour': 12,
        }
        sim = Greenhouse(build(env, Rng(1)), Rng(1))
        for _ in range(240):
            sim.run_hour()
        self.assertEqual(sim.hour, 240)
        self.assertEqual(len(sim.history), 240)
        self.assertLess(sim.facility.energy.co2_store_kg,
                        sim.facility.spec.energy_centre.co2_store.start_kg)
        self.assertLess(sim.business.profit_eur(), 0)

    def test_full_42_days_under_10s_and_conserved(self):
        import time
        from greenhouse.world.controller import ClimateSetpoints
        facility = parse_facility(tomllib.loads((DATA / 'facilities/nl_two_compartment.toml').read_text()), 'facility')
        climate = parse_climate(tomllib.loads((DATA / 'climates/nl_january.toml').read_text()), 'climate')
        prices = parse_energy_prices(tomllib.loads((DATA / 'energy_prices/nl_winter.toml').read_text()), 'prices')
        spec = resolve(facility, Rng(11))
        greenhouse = Facility(spec, climate, prices, Rng(11), hours=1008)
        energy_settings = EnergySettings(0.5, 'auto', 'auto', 0)
        loads = {c: CropLoad(0, 0, 0) for c in greenhouse.compartment_ids}
        setpoints = {c.id: ClimateSetpoints(19, 15, 0, 100, 800, 'auto',
                                            tuple(range(8, 16)), 60) for c in spec.compartments}
        started = time.perf_counter()
        total_heat = 0.0
        for hour in range(1008):
            for _ in range(12):
                greenhouse.substep(hour, 1/12, setpoints, energy_settings, loads)
            metered, _ = greenhouse.end_hour(hour)
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
        settings = EnergySettings(0, 'off', 'auto', 0)
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
            facility = Facility(resolved, climate, prices, Rng(13), hours=25)
            result = []
            loads = {c: CropLoad(0, 0, 0) for c in facility.compartment_ids}
            energy = EnergySettings(0, 'auto', 'auto', 0)
            for hour in range(24):
                for _ in range(12):
                    samples = facility.substep(hour, 1/12, settings, energy, loads)
                result.append((samples, facility.end_hour(hour), facility.sensor_readings(hour)))
            return result
        self.assertEqual(run(), run())

    def test_invalid_setpoints_do_not_mutate_facility(self):
        from greenhouse.world.controller import ClimateSetpoints
        spec = parse_facility(tomllib.loads((DATA / 'facilities/nl_two_compartment.toml').read_text()), 'facility')
        climate = parse_climate(tomllib.loads((DATA / 'climates/nl_january.toml').read_text()), 'climate')
        prices = parse_energy_prices(tomllib.loads((DATA / 'energy_prices/nl_winter.toml').read_text()), 'prices')
        facility = Facility(resolve(spec, Rng(5)), climate, prices, Rng(5), hours=25)
        before = (facility.climates['A'].temp_c, facility.energy.buffer_kwh,
                  dict(facility._last_actuators))
        bad = ClimateSetpoints(20, 16, 80, 10, 800, 'auto', (), 0)
        with self.assertRaises(ValueError):
            facility.substep(0, 1/12, {**facility.fallback_climate(), 'A': bad},
                             facility.fallback_energy(),
                             {c: CropLoad(0, 0, 0) for c in facility.compartment_ids})
        self.assertEqual((facility.climates['A'].temp_c, facility.energy.buffer_kwh,
                          facility._last_actuators), before)

    def test_facility_runs_through_real_simulator_contract(self):
        from fakes import FakeBusiness, FakeCrop
        from greenhouse.world.modules import Modules
        from greenhouse.world.sim import Greenhouse
        spec = resolve(parse_facility(tomllib.loads((DATA / 'facilities/nl_two_compartment.toml').read_text()),
                                      'facility'), Rng(17))
        climate = parse_climate(tomllib.loads((DATA / 'climates/nl_january.toml').read_text()), 'climate')
        prices = parse_energy_prices(tomllib.loads((DATA / 'energy_prices/nl_winter.toml').read_text()), 'prices')
        facility = build_facility(spec, climate, prices, Rng(17))
        crops = {c.crop: FakeCrop(c.crop) for c in spec.compartments}
        business = FakeBusiness(Rng(17), tuple(crops))
        sim = Greenhouse(Modules(facility, business, crops, 24, 12), Rng(17))
        for _ in range(24):
            sim.run_hour()
        self.assertEqual(sim.hour, 24)
        self.assertEqual(len(sim.history), 24)
        self.assertGreater(sim.history[0].metered['gas_eur_per_m3'], 0)
        self.assertEqual(sim.facility.forecast(0, 3), sim.facility.forecast(0, 3))

    def test_rules_publish_fixed_model_without_resolved_hidden_capacities(self):
        spec = resolve(parse_facility(tomllib.loads((DATA / 'facilities/nl_two_compartment.toml').read_text()),
                                      'facility'), Rng(18))
        climate = parse_climate(tomllib.loads((DATA / 'climates/nl_january.toml').read_text()), 'climate')
        prices = parse_energy_prices(tomllib.loads((DATA / 'energy_prices/nl_winter.toml').read_text()), 'prices')
        facility = build_facility(spec, climate, prices, Rng(18))
        rules = facility.rules()
        self.assertEqual(rules['weather_profile']['outside_co2_ppm'], 420.0)
        self.assertIn('export_fraction', rules['energy_prices']['tariff'])
        self.assertNotIn('windows', str(rules))
        self.assertNotIn('2024-jan', str(rules))
        self.assertNotIn('electric_kw', rules['energy_centre']['chp'])
        self.assertNotIn('floor_m2', rules['compartments']['A'])
