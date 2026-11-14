"""Shared-resource allocation and physical conservation."""
import dataclasses
import math
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
    def test_handover_baseline_is_the_anti_freeze_setting(self):
        # D5 revised (round 3): 5 C, no CO2, lamps off, as day settings and night schedule.
        spec = resolve(parse_facility(tomllib.loads((DATA / 'facilities/nl_two_compartment.toml').read_text()),
                                      'facility'), Rng(19))
        climate = parse_climate(tomllib.loads((DATA / 'climates/nl_january.toml').read_text()), 'climate')
        prices = parse_energy_prices(tomllib.loads((DATA / 'energy_prices/nl_winter.toml').read_text()), 'prices')
        facility = build_facility(spec, climate, prices, Rng(19))
        baseline = facility.fallback_climate()['A']
        self.assertEqual((baseline.heat_day_c, baseline.heat_night_c), (5.0, 5.0))
        self.assertGreater(baseline.heat_night_c, facility.spec.alarms.frost_risk_temp_c)
        self.assertEqual(baseline.co2_ppm, 0)
        self.assertEqual(baseline.lamp_hours, ())
        self.assertIn('boiler', facility.equipment_ids())
        self.assertIn('A.glass', facility.equipment_ids())
        loads = {key: CropLoad(0, 0, 0) for key in facility.compartment_ids}
        start_co2 = facility.energy.co2_store_kg
        for hour in range(48):
            for _ in range(12):
                facility.substep(hour, 1/12, facility.fallback_climate(), facility.fallback_energy(), loads)
            facility.end_hour(hour)
        self.assertEqual(facility.energy.co2_store_kg, start_co2)       # nothing is dosed
        self.assertGreater(facility.climates['A'].temp_c, facility.spec.alarms.frost_risk_temp_c)

    def test_thermostat_uses_sources_in_order_up_to_their_caps(self):
        # D10: CHP at its load, then buffer draw up to its cap, then boiler up to its level.
        doc = tomllib.loads((DATA / 'facilities/nl_two_compartment.toml').read_text())
        spec = resolve(parse_facility(doc, 'facility'), Rng(2)).energy_centre
        demand = {'A': 5000.0}
        none = {'A': 0.0}

        def heat(settings):
            energy = EnergyCentre(spec)
            energy.buffer_kwh = float(spec.buffer.capacity_kwh)
            out = energy.dispatch(0, 1.0, demand, none, none, settings)
            meter = energy.end_hour(0)
            return out.heat_kw['A'], meter

        full, _ = heat(EnergySettings(0, 'auto', 'auto', 0))
        capped_buffer, _ = heat(EnergySettings(0, 'off', 'auto', 0, buffer_draw_max_kw=100.0))
        self.assertAlmostEqual(capped_buffer, 100.0)
        no_boiler, _ = heat(EnergySettings(0, 'auto', 'hold', 0, boiler_max_fraction=0.0))
        self.assertEqual(no_boiler, 0.0)
        half_boiler, meter = heat(EnergySettings(0, 'auto', 'hold', 0, boiler_max_fraction=0.5))
        self.assertAlmostEqual(half_boiler, 0.5 * float(spec.boiler.heat_kw))
        self.assertGreater(full, half_boiler)
        with self.assertRaises(ValueError):
            heat(EnergySettings(0, 'auto', 'auto', 0, boiler_max_fraction=1.5))

    def test_a_planned_frost_night_loses_less_when_the_boiler_fails(self):
        # Spec 14.5 test 1 (context 0.5): a charged buffer, the CHP available and the screens
        # closed keep the crop clearly warmer than a naive night when the boiler fails.
        spec = resolve(parse_facility(tomllib.loads((DATA / 'facilities/nl_two_compartment.toml').read_text()),
                                      'facility'), Rng(6))
        climate = parse_climate(tomllib.loads((DATA / 'climates/nl_january.toml').read_text()), 'climate')
        prices = parse_energy_prices(tomllib.loads((DATA / 'energy_prices/nl_winter.toml').read_text()), 'prices')
        loads = {key: CropLoad(0, 0, 0) for key in ('A', 'B')}

        def night(planned: bool) -> float:
            facility = Facility(spec, climate, prices, Rng(6), hours=48)
            if planned:
                facility.energy.buffer_kwh = float(spec.energy_centre.buffer.capacity_kwh)
            facility.apply_effect(EquipmentEffect('boiler', capacity_factor=0.0, until_hour=None))
            base = facility.fallback_climate()['A']
            sp = dataclasses.replace(base, heat_day_c=17.0, heat_night_c=17.0,
                                     screen='closed' if planned else 'open')
            energy = EnergySettings(spec.energy_centre.chp.min_load if planned else 0.0, 'auto',
                                    'auto' if planned else 'hold', 0.0)
            lowest = math.inf
            for hour in range(0, 8):              # the recorded night before day 1's sunrise
                for _ in range(12):
                    facility.substep(hour, 1/12, {'A': sp, 'B': sp}, energy, loads)
                facility.end_hour(hour)
                lowest = min(lowest, facility.climates['A'].temp_c)
            return lowest

        self.assertGreater(night(True), night(False) + 2.0)

    def test_broken_glass_raises_heat_loss_until_cleared(self):
        spec = resolve(parse_facility(tomllib.loads((DATA / 'facilities/nl_two_compartment.toml').read_text()),
                                      'facility'), Rng(4))
        climate = parse_climate(tomllib.loads((DATA / 'climates/nl_january.toml').read_text()), 'climate')
        prices = parse_energy_prices(tomllib.loads((DATA / 'energy_prices/nl_winter.toml').read_text()), 'prices')
        loads = {key: CropLoad(0, 0, 0) for key in ('A', 'B')}
        warm = {c.id: dataclasses.replace(Facility(spec, climate, prices, Rng(4), hours=24).fallback_climate()['A'],
                                          heat_day_c=18.0, heat_night_c=18.0) for c in spec.compartments}

        def gas(broken: bool) -> float:
            facility = Facility(spec, climate, prices, Rng(4), hours=24)
            if broken:
                facility.apply_effect(EquipmentEffect('A.glass', leakage_factor=2.0, until_hour=None))
            total = 0.0
            for hour in range(12):
                for _ in range(12):
                    facility.substep(hour, 1/12, warm, facility.fallback_energy(), loads)
                total += facility.end_hour(hour)[0].heat_delivered_kwh.get('A', 0.0)
            return total

        self.assertGreater(gas(True), gas(False))

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
        business = build_business(market, events, [], tuple(growth), facility.equipment_ids(), 240,
                                  rng.stream('business'), facility.recorded())
        sim = Greenhouse(Modules(facility, business, growth, 240, 12), rng.stream('sim'))
        for hour in range(240):
            sim.run_hour()
            if hour == 7:
                self.assertIn('boiler', sim.effects)
                self.assertEqual(facility.effects['boiler'].capacity_factor, 0)
        self.assertEqual(sim.hour, 240)
        self.assertEqual(len(sim.history), 240)
        self.assertGreater(sim.history[0].metered['gas_eur_per_m3'], 0)
        self.assertLess(sim.business.totals()['wages'], 0)

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
        # On the anti-freeze baseline (D5) nothing is dosed, and wages and gas are paid.
        self.assertEqual(sim.facility.energy.co2_store_kg,
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
