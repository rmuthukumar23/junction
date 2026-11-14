"""Events: a fixed per-seed schedule, persistent outages and storms on the recorded wind."""
import tomllib
import unittest
from dataclasses import replace
from pathlib import Path

from envkit.rng import Rng
from greenhouse.config.base import Range
from greenhouse.config.market import parse_event, parse_market
from greenhouse.contracts import Alarm, EquipmentEffect, Recorded, WeatherNow
from greenhouse.world.events import DeliveryDelay, Events, storm_hours
from greenhouse.world.ledger import Ledger
from greenhouse.world.operations import Operations

ROOT = Path(__file__).resolve().parents[2]


def event(name):
    return parse_event(tomllib.loads((ROOT / f"data/events/{name}.toml").read_text()), name)


BOILER, LATE, STORM = event("boiler_trip"), event("late_delivery"), event("storm")
MARKET = parse_market(tomllib.loads((ROOT / "data/markets/nl_winter.toml").read_text()), "nl_winter")
HORIZON = 42 * 24
EQUIPMENT = ("boiler", "A.glass", "B.glass")


def recorded(hours, wind=None, default=3.0):
    """A hand-made recorded series: `wind` maps hour -> m/s, everything else is calm."""
    wind = wind or {}
    weather = tuple(WeatherNow(h, 2.0, wind.get(h, default), 0.0, 80.0) for h in range(hours))
    return Recorded(weather, tuple(0.4 for _ in range(hours)))


class ScheduleTests(unittest.TestCase):
    def test_the_schedule_is_a_pure_function_of_the_seed(self):
        a = Events([BOILER, LATE], HORIZON, Rng(3)).schedule
        b = Events([BOILER, LATE], HORIZON, Rng(3)).schedule
        c = Events([BOILER, LATE], HORIZON, Rng(4)).schedule
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_adding_an_event_type_does_not_move_the_others(self):
        alone = [o for o in Events([BOILER], HORIZON, Rng(3)).schedule]
        both = [o for o in Events([BOILER, LATE], HORIZON, Rng(3)).schedule if o.event_id == "boiler_trip"]
        self.assertEqual(alone, both)

    def test_rates_are_roughly_honoured_and_delays_stay_in_their_range(self):
        counts, boilers, delays = 0, 0, []
        for seed in range(1, 61):
            ev = Events([BOILER, LATE], HORIZON, Rng(seed))
            boilers += sum(1 for o in ev.schedule if o.event_id == "boiler_trip")
            delays += [o.value_h for o in ev.schedule if o.event_id == "late_delivery"]
        expected = 60 * 42 * BOILER.rate_per_day
        self.assertLess(abs(boilers - expected), 0.5 * expected)
        self.assertTrue(delays and all(LATE.delay_h.min <= d <= LATE.delay_h.max for d in delays))

    def test_pinned_hours_add_an_occurrence(self):
        pinned = replace(BOILER, rate_per_day=0.0, pinned_hours=(100,))
        ev = Events([pinned], HORIZON, Rng(1))
        self.assertEqual([o.start_hour for o in ev.schedule], [100])


class PersistentOutageTests(unittest.TestCase):
    def setUp(self):
        self.ev = Events([replace(BOILER, rate_per_day=0.0, pinned_hours=(100,))], HORIZON, Rng(1))

    def test_a_persistent_fault_has_no_end_until_it_is_repaired(self):
        out = self.ev.due(100)
        effects = [x for x in out if isinstance(x, EquipmentEffect)]
        alarms = [x for x in out if isinstance(x, Alarm)]
        self.assertEqual((effects[0].target, effects[0].capacity_factor, effects[0].until_hour), ("boiler", 0.0, None))
        self.assertEqual(alarms[0].kind, "equipment")
        for hour in (101, 400, HORIZON - 1):
            self.assertEqual(len(self.ev.effects_in_force(hour)), 1)
        outage = self.ev.outages[0]
        alarms, remaining = self.ev.complete_repair(110, outage)
        self.assertIsNone(remaining)
        self.assertEqual(alarms[0].kind, "contractor")
        self.assertEqual(self.ev.effects_in_force(111), [])

    def test_a_second_fault_on_broken_equipment_changes_nothing(self):
        ev = Events([replace(BOILER, rate_per_day=0.0, pinned_hours=(10, 20))], HORIZON, Rng(1))
        self.assertTrue(ev.due(10))
        self.assertEqual(ev.due(20), [])
        self.assertEqual(len(ev.outages), 1)

    def test_a_timed_fault_clears_by_itself(self):
        timed = replace(BOILER, persistent=False, repair=None, duration_h=Range("duration_h", 6, 30),
                        rate_per_day=0.0, pinned_hours=(100,))
        ev = Events([timed], HORIZON, Rng(1))
        duration = ev.schedule[0].value_h
        self.assertTrue(6 <= duration <= 30)
        ev.due(100)
        self.assertEqual(len(ev.effects_in_force(100 + duration - 1)), 1)
        self.assertEqual(ev.effects_in_force(100 + duration), [])
        self.assertTrue(any(isinstance(x, Alarm) for x in ev.due(100 + duration)))
        self.assertFalse(ev.outages[0].persistent)

    def test_the_view_shows_outages_and_parts_but_never_the_schedule(self):
        self.assertEqual(self.ev.view(99), {"outages": []})
        self.ev.due(100)
        row = self.ev.view(100)["outages"][0]
        self.assertEqual((row["equipment"], row["persistent"]), ("boiler", True))
        self.assertEqual(row["parts_needed"], {"part:boiler_kit": 1})
        rules = self.ev.rules()[0]
        self.assertEqual(rules["repair"], {"trade": "heating_installer", "parts": {"part:boiler_kit": 1.0}})


class StormTests(unittest.TestCase):
    def test_storm_hours_follow_the_recorded_wind_once_per_spell(self):
        wind = {h: 11.0 for h in (50, 51, 52)} | {h: 12.0 for h in (60, 61)} | {200: 10.0, 201: 9.9}
        spec = replace(STORM, wind_threshold_m_s=10.0, min_gap_h=48)
        # 50 starts the first spell; 60 is inside the 48 h gap; 200 reaches the threshold exactly.
        self.assertEqual(storm_hours(spec, recorded(300, wind).weather, 300), [50, 200])

    def test_a_pinned_storm_is_added_and_a_calm_series_has_none(self):
        spec = replace(STORM, pinned_hours=(30,))
        self.assertEqual(storm_hours(spec, recorded(100).weather, 100), [30])
        self.assertEqual(storm_hours(STORM, recorded(100).weather, 100), [])

    def test_damage_is_drawn_per_compartment_on_its_own_stream_and_persists(self):
        rec = recorded(300, {50: 15.0})
        ev = Events([replace(STORM, panes_min=1.0, panes_max=12.0)], 300, Rng(7), EQUIPMENT, rec)
        again = Events([replace(STORM, panes_min=1.0, panes_max=12.0)], 300, Rng(7), EQUIPMENT, rec)
        self.assertEqual(ev.schedule, again.schedule)
        self.assertEqual(len(ev.schedule), 1)
        damage = dict(ev.schedule[0].damage)
        self.assertEqual(set(damage), {"A.glass", "B.glass"})
        self.assertTrue(all(1 <= p <= 12 for p in damage.values()))
        out = ev.due(50)
        effects = {x.target: x for x in out if isinstance(x, EquipmentEffect)}
        for target, panes in damage.items():
            self.assertIsNone(effects[target].until_hour)
            self.assertAlmostEqual(effects[target].leakage_factor, 1.0 + panes * STORM.leakage_per_pane)
            self.assertEqual(effects[target].capacity_factor, 1.0)
        self.assertEqual([a.kind for a in out if isinstance(a, Alarm)], ["storm"])
        self.assertEqual(len(ev.effects_in_force(299)), 2)
        self.assertEqual({r["equipment"]: r["panes_broken"] for r in ev.view(60)["outages"]}, damage)

    def test_a_second_storm_on_broken_glass_adds_panes(self):
        spec = replace(STORM, panes_min=3.0, panes_max=3.0, pinned_hours=(10, 100))
        ev = Events([spec], 300, Rng(1), EQUIPMENT, recorded(300))
        ev.due(10)
        ev.due(100)
        self.assertEqual(len(ev.outages), 2)                          # one outage per compartment
        self.assertEqual({o.target: o.panes for o in ev.outages}, {"A.glass": 6, "B.glass": 6})
        self.assertAlmostEqual(ev.outage_effect("A.glass", 101).leakage_factor, 1.0 + 6 * STORM.leakage_per_pane)

    def test_a_storm_with_no_panes_broken_has_no_effect_but_still_raises_an_alarm_and_a_surge(self):
        spec = replace(STORM, panes_min=0.0, panes_max=0.0, pinned_hours=(20,))
        ev = Events([spec], 300, Rng(1), EQUIPMENT, recorded(300))
        self.assertIsNone(ev.surge_until(19))
        out = ev.due(20)
        self.assertEqual([x for x in out if isinstance(x, EquipmentEffect)], [])
        self.assertIn("No damage", [x for x in out if isinstance(x, Alarm)][0].text)
        self.assertEqual(ev.outages, [])
        self.assertEqual(ev.surge_until(20), 20 + round(24 * STORM.surge_days))

    def test_the_surge_starts_with_the_storm_and_is_not_known_before_it(self):
        spec = replace(STORM, pinned_hours=(20, 400))
        ev = Events([spec], 600, Rng(1), EQUIPMENT, recorded(600))
        self.assertEqual([ev.surge_until(h) for h in (19, 20)], [None, 20 + 240])
        self.assertEqual(ev.surge_until(399), 260)
        self.assertEqual(ev.surge_until(400), 640)


class LateDeliveryTests(unittest.TestCase):
    def test_a_late_delivery_occurrence_reaches_operations(self):
        ev = Events([replace(LATE, rate_per_day=0.0, pinned_hours=(20,))], HORIZON, Rng(1))
        delay = [x for x in ev.due(20) if isinstance(x, DeliveryDelay)][0]
        ops = Operations(MARKET, Ledger(0.0), Rng(1))
        order = ops.place_order(0, "co2_kg", 2000)
        alarms = ops.delay(20, delay.delay_h, delay.items)
        self.assertEqual(order.eta_hour, 72 + delay.delay_h)
        self.assertTrue(LATE.delay_h.min <= delay.delay_h <= LATE.delay_h.max)
        self.assertEqual(alarms[0].kind, "delivery")


if __name__ == "__main__":
    unittest.main()
