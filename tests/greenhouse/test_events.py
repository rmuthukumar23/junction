"""Events: a fixed per-seed schedule, outages and their effects, repairs and their cost."""
import tomllib
import unittest
from dataclasses import replace
from pathlib import Path

from envkit.rng import Rng
from greenhouse.config.market import parse_event, parse_market
from greenhouse.contracts import Alarm, EquipmentEffect
from greenhouse.world.events import DeliveryDelay, Events
from greenhouse.world.ledger import Ledger
from greenhouse.world.operations import Operations

ROOT = Path(__file__).resolve().parents[2]
BOILER = parse_event(tomllib.loads((ROOT / "data/events/boiler_trip.toml").read_text()), "boiler_trip")
LATE = parse_event(tomllib.loads((ROOT / "data/events/late_delivery.toml").read_text()), "late_delivery")
MARKET = parse_market(tomllib.loads((ROOT / "data/markets/nl_winter.toml").read_text()), "nl_winter")
HORIZON = 42 * 24


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

    def test_rates_are_roughly_honoured_and_durations_stay_in_their_range(self):
        counts, durations = 0, []
        for seed in range(1, 61):
            occ = [o for o in Events([BOILER], HORIZON, Rng(seed)).schedule]
            counts += len(occ)
            durations += [o.value_h for o in occ]
        expected = 60 * 42 * BOILER.rate_per_day
        self.assertLess(abs(counts - expected), 0.5 * expected)
        self.assertTrue(all(BOILER.duration_h.min <= d <= BOILER.duration_h.max for d in durations))

    def test_pinned_hours_add_an_occurrence(self):
        pinned = replace(BOILER, rate_per_day=0.0, pinned_hours=(100,))
        ev = Events([pinned], HORIZON, Rng(1))
        self.assertEqual([o.start_hour for o in ev.schedule], [100])


class OutageTests(unittest.TestCase):
    def setUp(self):
        self.ev = Events([replace(BOILER, rate_per_day=0.0, pinned_hours=(100,))], HORIZON, Rng(1))
        self.duration = self.ev.schedule[0].value_h

    def test_an_outage_raises_an_alarm_takes_effect_and_ends_by_itself(self):
        out = self.ev.due(100)
        effects = [x for x in out if isinstance(x, EquipmentEffect)]
        alarms = [x for x in out if isinstance(x, Alarm)]
        self.assertEqual((effects[0].target, effects[0].capacity_factor), ("boiler", 0.0))
        self.assertEqual(alarms[0].kind, "equipment")
        self.assertEqual(len(self.ev.effects_in_force(100 + self.duration - 1)), 1)
        self.assertEqual(self.ev.effects_in_force(100 + self.duration), [])
        self.assertTrue(any(isinstance(x, Alarm) for x in self.ev.due(100 + self.duration)))

    def test_a_repair_shortens_the_outage(self):
        self.ev.due(100)
        req = self.ev.request_repair(101, "boiler")
        self.assertTrue(req.broken)
        self.assertEqual((req.cost_eur, req.worker_hours), (BOILER.repair.cost_eur, BOILER.repair.worker_hours))
        self.ev.complete_repair(102, "boiler")
        until = self.ev.outages[0].until_hour
        self.assertEqual(until, min(100 + self.duration, 103 + round(BOILER.repair.shortens_to_h)))
        self.assertEqual(self.ev.effects_in_force(until), [])

    def test_the_view_shows_outages_but_never_the_schedule_or_durations(self):
        self.assertEqual(self.ev.view(99), {"outages": []})
        self.ev.due(100)
        view = self.ev.view(100)
        self.assertEqual(view["outages"][0]["equipment"], "boiler")
        self.assertNotIn("until", str(view))
        rules = self.ev.rules()[0]
        self.assertEqual(rules["duration_h"], [BOILER.duration_h.min, BOILER.duration_h.max])


class QuoteTests(unittest.TestCase):
    def test_a_repair_quote_changes_nothing_and_unknown_equipment_is_refused(self):
        from greenhouse.world.operations import OpsError
        ev = Events([replace(BOILER, rate_per_day=0.0, pinned_hours=(10,))], HORIZON, Rng(1))
        ev.due(10)
        quote = ev.repair_quote(11, "boiler")
        self.assertTrue(quote.broken)
        self.assertEqual((ev.repairs_requested, ev.outages[0].repair_requested_hour), (0, None))
        self.assertIsNotNone(ev.outage_effect("boiler", 11))
        self.assertIsNone(ev.outage_effect("boiler", 9))
        with self.assertRaises(OpsError):
            ev.repair_quote(11, "chp")


class SpamTests(unittest.TestCase):
    def test_fifty_repairs_in_a_row_are_clearly_worse_than_none(self):
        """Repairs of working equipment cost money and worker-hours and do nothing."""
        def play(repairs):
            book = Ledger(MARKET.start_cash_eur)
            ops = Operations(MARKET, book, Rng(1))
            ev = Events([replace(BOILER, rate_per_day=0.0)], HORIZON, Rng(1))
            for _ in range(repairs):
                req = ev.request_repair(0, "boiler")
                book.charge(0, "repairs", req.cost_eur, "repair boiler")
                ops.queue(0, "repair", "boiler", req.worker_hours)
            harvest = ops.queue(0, "harvest", "L1", 1.0)
            for h in range(48):
                ops.end_hour(h)
            return book.profit_eur, harvest.done_hour, ev.repairs_wasted
        none_profit, none_harvest, _ = play(0)
        spam_profit, spam_harvest, wasted = play(50)
        self.assertLess(spam_profit, none_profit - 50 * BOILER.repair.cost_eur + 1)
        self.assertIsNone(spam_harvest)                           # the queue is blocked by useless repairs
        self.assertIsNotNone(none_harvest)
        self.assertEqual(wasted, 50)


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
