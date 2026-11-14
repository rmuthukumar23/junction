"""Operations: orders with lead times, stock, staff, wages and the worker-hour task queue."""
import tomllib
import unittest
from dataclasses import replace
from pathlib import Path

from envkit.rng import Rng
from greenhouse.config.market import parse_market
from greenhouse.world.ledger import Ledger
from greenhouse.world.operations import Operations, OpsError

ROOT = Path(__file__).resolve().parents[2]
MARKET = parse_market(tomllib.loads((ROOT / "data/markets/nl_winter.toml").read_text()), "nl_winter")
STAFF = MARKET.staff


def ops():
    book = Ledger(MARKET.start_cash_eur)
    return Operations(MARKET, book, Rng(1)), book


def run(o, first, last):
    """End every hour in [first, last]; return all alarms and completed tasks."""
    alarms, done = [], []
    for h in range(first, last + 1):
        r = o.end_hour(h)
        alarms += r.alarms
        done += r.completed
    return alarms, done


class OrderTests(unittest.TestCase):
    def test_a_co2_order_arrives_after_its_lead_time_and_not_before(self):
        o, book = ops()
        order = o.place_order(10, "co2_kg", 2000)
        self.assertEqual(order.eta_hour, 82)
        delivered = []
        for h in range(10, 82):
            delivered += o.end_hour(h).delivered
        self.assertEqual(delivered, [])
        self.assertEqual(book.totals()["co2"], 0.0)               # charged on arrival, not before
        r = o.end_hour(82)
        self.assertEqual([d.id for d in r.delivered], [order.id])
        self.assertAlmostEqual(book.totals()["co2"], -2000 * MARKET.items["co2_kg"].price_eur_per_unit)
        self.assertTrue(any(a.kind == "delivery" for a in r.alarms))

    def test_co2_goes_to_the_facility_and_never_into_business_stock(self):
        o, _ = ops()
        self.assertNotIn("co2_kg", o.stock)
        o.place_order(0, "co2_kg", 2000)
        run(o, 0, 80)
        self.assertNotIn("co2_kg", o.stock)
        self.assertNotIn("co2_kg", o.view()["stock"])

    def test_minimum_quantities_and_unknown_items_are_refused_without_change(self):
        o, book = ops()
        for item, qty in (("co2_kg", 10), ("co2_kg", -5), ("gold", 1), ("co2_kg", float("nan")), ("co2_kg", True)):
            with self.subTest(item=item, qty=qty):
                with self.assertRaises(OpsError):
                    o.place_order(0, item, qty)
        self.assertEqual((o.orders, book.entries), ([], []))

    def test_cancelling_costs_a_fee_and_is_only_possible_before_dispatch(self):
        o, book = ops()
        a = o.place_order(0, "co2_kg", 2000)
        b = o.place_order(0, "co2_kg", 2000)
        o.cancel_order(5, a.id)
        self.assertEqual(a.status, "cancelled")
        self.assertAlmostEqual(book.totals()["orders"], -MARKET.items["co2_kg"].cancel_fee_eur)
        with self.assertRaises(OpsError):
            o.cancel_order(b.dispatch_hour, b.id)
        with self.assertRaises(OpsError):
            o.cancel_order(6, a.id)                               # already cancelled
        delivered = []
        for h in range(0, 81):
            delivered += o.end_hour(h).delivered
        self.assertEqual([d.id for d in delivered], [b.id])         # only the order not cancelled

    def test_a_late_delivery_pushes_back_the_order_due_soonest(self):
        o, _ = ops()
        first = o.place_order(0, "co2_kg", 2000)
        second = o.place_order(5, "co2_kg", 2000)
        alarms = o.delay(10, 30, ("co2_kg",))
        self.assertEqual((first.eta_hour, second.eta_hour), (102, 77))
        self.assertEqual(alarms[0].kind, "delivery")
        self.assertEqual(o.delay(10, 30, ("seedlings:broccoli_micro",)), [])   # nothing open of that item


class StockTests(unittest.TestCase):
    def test_a_stock_low_alarm_fires_once_when_crossing_the_warning_level(self):
        item = "seedlings:lettuce_butterhead"
        market = replace(MARKET, items={**MARKET.items, item: replace(MARKET.items[item], warn_below=1000.0)},
                         start_stock={**MARKET.start_stock, item: 1500.0})
        o = Operations(market, Ledger(0.0), Rng(1))
        o.take_seedlings("lettuce_butterhead", 600)
        a1, _ = run(o, 0, 0)
        a2, _ = run(o, 1, 1)
        self.assertEqual([a.target for a in a1 if a.kind == "stock_low"], [item])
        self.assertEqual([a.kind for a in a2].count("stock_low"), 0)

    def test_planting_needs_seedlings_in_stock(self):
        o, _ = ops()
        with self.assertRaises(OpsError):
            o.take_seedlings("lettuce_butterhead", 100)
        o.place_order(0, "seedlings:lettuce_butterhead", 5000)
        run(o, 0, o.lead_time_h["seedlings:lettuce_butterhead"])
        o.take_seedlings("lettuce_butterhead", 4000)
        self.assertEqual(o.stock["seedlings:lettuce_butterhead"], 1000)


class StaffTests(unittest.TestCase):
    def test_wages_are_charged_every_hour_from_hour_zero(self):
        o, book = ops()
        run(o, 0, 23)
        day = STAFF.start_crew * STAFF.wage_eur_per_worker_hour * STAFF.shift_hours
        self.assertAlmostEqual(book.totals()["wages"], -day)
        self.assertEqual(len([e for e in book.entries if e.category == "wages"]), 24)

    def test_hiring_costs_a_fee_and_the_worker_starts_after_the_notice(self):
        o, book = ops()
        start = o.hire(0, 2)
        self.assertEqual(start, 24 * STAFF.hire_notice_days)
        self.assertAlmostEqual(book.totals()["hiring"], -2 * STAFF.hiring_fee_eur)
        run(o, 0, start - 1)
        self.assertEqual(o.crew, STAFF.start_crew)
        run(o, start, start)
        self.assertEqual(o.crew, STAFF.start_crew + 2)
        with self.assertRaises(OpsError):
            o.hire(start, STAFF.max_crew)

    def test_a_released_worker_stops_working_but_is_paid_through_the_notice(self):
        o, book = ops()
        end = o.release(0, 1)
        self.assertEqual(o.crew, STAFF.start_crew - 1)
        run(o, 0, end - 1)
        per_hour = STAFF.wage_eur_per_worker_hour * STAFF.shift_hours / 24
        self.assertAlmostEqual(book.totals()["wages"], -STAFF.start_crew * per_hour * end)
        before = book.totals()["wages"]
        run(o, end, end)
        self.assertAlmostEqual(book.totals()["wages"] - before, -(STAFF.start_crew - 1) * per_hour)


class TaskTests(unittest.TestCase):
    def test_tasks_use_worker_hours_in_queue_order_during_the_shift(self):
        o, _ = ops()
        crew_hours = STAFF.start_crew
        first = o.queue(0, "plant", "A", crew_hours * 2)
        second = o.queue(0, "harvest", "L1", crew_hours)
        _, done = run(o, 0, STAFF.shift_start_h + 1)                 # the first two shift hours
        self.assertEqual([t.id for t in done], [first.id])
        _, done = run(o, STAFF.shift_start_h + 2, STAFF.shift_start_h + 2)
        self.assertEqual([t.id for t in done], [second.id])

    def test_a_harvest_queued_with_no_hours_left_completes_the_next_day(self):
        o, _ = ops()
        day_pool = STAFF.start_crew * STAFF.shift_hours
        o.queue(0, "plant", "A", day_pool)                           # uses all of today's worker-hours
        harvest = o.queue(0, "harvest", "L1", 1.0)
        _, done = run(o, 0, 23)
        self.assertNotIn(harvest, done)
        _, done = run(o, 24, 47)
        self.assertIn(harvest, done)
        self.assertEqual(harvest.done_hour, 24 + STAFF.shift_start_h)
        self.assertEqual(o.task_wait_h["harvest"], harvest.done_hour)

    def test_nothing_is_worked_outside_the_shift_or_with_no_crew(self):
        o, _ = ops()
        o.release(0, STAFF.start_crew)
        task = o.queue(0, "harvest", "L1", 1.0)
        run(o, 0, 47)
        self.assertIsNone(task.done_hour)


if __name__ == "__main__":
    unittest.main()
