"""Persistent damage, parts, contractors and the storm surge (context 0.7 tests 1-4, spec 14.5 item 2).

These build the Business directly from the committed data files with a hand-made recorded series, fixed
prices and response times, and play a few hundred hours: no simulator, no 42-day episode."""
import tomllib
import unittest
from dataclasses import replace
from pathlib import Path

from envkit.rng import Rng
from greenhouse.config.market import parse_event, parse_market
from greenhouse.contracts import Metered, Recorded, RuleError, WeatherNow
from greenhouse.world.business import build_business

ROOT = Path(__file__).resolve().parents[2]
CROPS = ("lettuce_butterhead", "broccoli_micro")
EQUIPMENT = ("boiler", "A.glass", "B.glass")
HORIZON = 800
STORM_HOUR = 30                 # 06:00 on day 1
SURGE_H = 240                   # data/events/storm.toml: surge_days = 10


def event(name):
    return parse_event(tomllib.loads((ROOT / f"data/events/{name}.toml").read_text()), name)


def fixed_market():
    """The committed market with the hidden ranges pinned, so timings are exact."""
    market = parse_market(tomllib.loads((ROOT / "data/markets/nl_winter.toml").read_text()), "nl_winter")
    items = dict(market.items)
    items["part:glass_pane"] = replace(items["part:glass_pane"], lead_time_h=96.0, surge_lead_time_h=480.0,
                                       price_eur_per_unit=45.0, express_price_eur_per_unit=90.0)
    items["part:boiler_kit"] = replace(items["part:boiler_kit"], lead_time_h=36.0, surge_lead_time_h=72.0,
                                       price_eur_per_unit=350.0, express_price_eur_per_unit=560.0)
    glazier = replace(market.contractors["glazier"], callout_eur=90.0, rate_eur_per_h=60.0, response_h=24.0,
                      surge_response_h=120.0)
    installer = replace(market.contractors["heating_installer"], callout_eur=94.0, rate_eur_per_h=90.0,
                        response_h=24.0, surge_response_h=48.0)
    return replace(market, items=items, contractors={"glazier": glazier, "heating_installer": installer})


def world(panes=4, wind=None, boiler_pin=(), storm_pin=(), boiler=None):
    """A Business whose recorded wind spikes at STORM_HOUR (override with `wind`), plus a driver."""
    wind = {STORM_HOUR: 14.0} if wind is None else wind
    weather = tuple(WeatherNow(h, 2.0, wind.get(h, 3.0), 0.0, 80.0) for h in range(HORIZON))
    recorded = Recorded(weather, (0.4,) * HORIZON)
    storm = replace(event("storm"), panes_min=float(panes), panes_max=float(panes), pinned_hours=tuple(storm_pin))
    boiler = boiler or replace(event("boiler_trip"), rate_per_day=0.0, pinned_hours=tuple(boiler_pin))
    late = replace(event("late_delivery"), rate_per_day=0.0)
    b = build_business(fixed_market(), [storm, boiler, late], [], CROPS, EQUIPMENT, HORIZON, Rng(1).stream("business"),
                       recorded)
    return Driver(b)


class Driver:
    """Plays hours like sim.py: start_hour, then end_hour. The agent acts between `play` calls."""

    def __init__(self, business):
        self.b = business
        self.hour = 0
        self.alarms, self.effects = [], []
        self.repaired = {}            # target -> hour of the end_hour that reported it repaired
        self.left_over = []           # effects re-applied after a repair

    def play(self, until):
        while self.hour < until:
            h = self.hour
            eff, alarms = self.b.start_hour(h, None)
            self.effects += eff
            self.alarms += alarms
            end = self.b.end_hour(h, Metered(h))
            self.alarms += end.alarms
            self.left_over += end.effects
            for target in end.repaired:
                self.repaired.setdefault(target, h)
            self.hour += 1

    def damage_hours(self):
        return sum((o.repaired_hour + 1 if o.repaired_hour is not None else HORIZON) - o.start_hour
                   for o in self.b.events.outages)

    def totals(self):
        return self.b.totals()


class StormDamageTests(unittest.TestCase):
    def test_a_storm_on_the_recorded_wind_breaks_glass_and_the_damage_persists_until_repaired(self):
        w = world(panes=4)
        w.play(STORM_HOUR)
        self.assertEqual(w.effects, [])                                  # calm until the wind passes the threshold
        w.play(STORM_HOUR + 1)
        broken = {e.target: e for e in w.effects}
        self.assertEqual(set(broken), {"A.glass", "B.glass"})
        self.assertTrue(all(e.until_hour is None and e.leakage_factor > 1.0 for e in broken.values()))
        self.assertEqual([a.kind for a in w.alarms if a.kind == "storm"], ["storm"])
        view = w.b.view(STORM_HOUR + 1, Rng(1))
        self.assertEqual({o["equipment"]: o["panes_broken"] for o in view["outages"]}, {"A.glass": 4, "B.glass": 4})
        self.assertEqual(view["outages"][0]["parts_needed"], {"part:glass_pane": 4})
        self.assertEqual(view["surge_until_hour"], STORM_HOUR + SURGE_H)
        w.play(600)                                                      # nothing is booked: it stays broken
        self.assertEqual(w.repaired, {})
        self.assertEqual(len(w.b.events.effects_in_force(599)), 2)

    def test_the_repair_happens_only_when_a_glazier_with_the_panes_has_done_the_job(self):
        w = world(panes=4)
        w.b.place_order(0, "part:glass_pane", 8)                         # arrives at hour 96
        w.play(54)                                                       # the next morning, 06:00
        booking = w.b.book_contractor(54, "glazier", "A.glass")
        self.assertEqual(booking["parts_needed"], {"part:glass_pane": 4})
        self.assertEqual(booking["earliest_visit_hour"], 54 + 120)       # the glazier is in surge
        w.b.book_contractor(54, "glazier", "B.glass")
        w.play(173)
        self.assertEqual(w.repaired, {})
        self.assertEqual(w.totals()["contractors"], 0.0)                 # nothing charged before the visit
        self.assertEqual(w.b.ops.stock["part:glass_pane"], 8)
        w.play(180)
        # call-out 90 + (1 + 0.5 x 4) = 3 job hours at 60, per compartment
        self.assertEqual(w.repaired, {"A.glass": 176, "B.glass": 176})
        self.assertAlmostEqual(w.totals()["contractors"], -2 * (90.0 + 3 * 60.0))
        self.assertEqual(w.b.ops.stock["part:glass_pane"], 0)
        self.assertEqual(w.b.events.effects_in_force(177), [])
        self.assertEqual(w.b.view(177, Rng(1))["outages"], [])
        self.assertTrue(any(a.kind == "contractor" for a in w.alarms))

    def test_pre_ordered_glass_and_a_booking_next_morning_beat_ordering_after_the_storm(self):
        ready = world(panes=4)
        ready.b.place_order(0, "part:glass_pane", 8)
        ready.play(54)
        ready.b.book_contractor(54, "glazier", "A.glass")
        ready.b.book_contractor(54, "glazier", "B.glass")
        ready.play(700)
        late = world(panes=4)
        late.play(54)
        late.b.place_order(54, "part:glass_pane", 8)                     # ordered into the surge
        late.b.book_contractor(54, "glazier", "A.glass")
        late.b.book_contractor(54, "glazier", "B.glass")
        late.play(700)
        self.assertEqual(set(ready.repaired), {"A.glass", "B.glass"})
        self.assertEqual(set(late.repaired), {"A.glass", "B.glass"})
        self.assertLess(ready.repaired["A.glass"] + 300, late.repaired["A.glass"])
        self.assertLess(ready.damage_hours() + 600, late.damage_hours())  # two compartments, 300+ h each

    def test_a_storm_without_damage_only_costs_what_was_ordered(self):
        w = world(panes=0)
        w.b.place_order(0, "part:glass_pane", 8)
        w.play(200)
        self.assertEqual(w.effects, [])
        self.assertEqual(w.b.events.outages, [])
        storm_alarm = [a for a in w.alarms if a.kind == "storm"][0]
        self.assertIn("No damage", storm_alarm.text)
        totals = w.totals()
        self.assertAlmostEqual(totals["parts"], -8 * 45.0)
        self.assertEqual((totals["contractors"], totals["express"]), (0.0, 0.0))
        with self.assertRaisesRegex(RuleError, "nothing is broken"):
            w.b.book_contractor(200, "glazier", "A.glass")
        self.assertEqual(w.b.ops.stock["part:glass_pane"], 8)            # unused parts stay in stock, worth nothing
        self.assertEqual(w.b.view(200, Rng(1))["surge_until_hour"], STORM_HOUR + SURGE_H)   # the surge still happens

    def test_a_second_storm_adds_panes_and_the_extra_ones_need_a_new_booking(self):
        w = world(panes=4, storm_pin=(60,))
        w.b.place_order(0, "part:glass_pane", 8)
        w.play(54)
        w.b.book_contractor(54, "glazier", "A.glass")                   # covers the 4 panes broken so far
        w.play(61)                                                       # the second storm at hour 60
        self.assertEqual({o["equipment"]: o["panes_broken"] for o in w.b.view(61, Rng(1))["outages"]},
                         {"A.glass": 8, "B.glass": 8})
        w.play(190)
        self.assertEqual(w.repaired, {})                                 # A.glass is repaired, but 4 panes remain
        leftover = [e for e in w.left_over if e.target == "A.glass"][0]
        self.assertAlmostEqual(leftover.leakage_factor, 1.0 + 4 * event("storm").leakage_per_pane)
        self.assertIsNone(leftover.until_hour)
        self.assertEqual(w.b.ops.stock["part:glass_pane"], 4)
        w.b.book_contractor(190, "glazier", "A.glass")                   # a new booking is allowed now


class ThreeConditionsTests(unittest.TestCase):
    def test_without_a_booking_nothing_is_repaired_however_long_we_wait(self):
        w = world(panes=4)
        w.b.place_order(0, "part:glass_pane", 8)
        w.play(500)
        self.assertEqual(w.repaired, {})
        self.assertEqual(w.totals()["contractors"], 0.0)

    def test_a_booked_visit_waits_for_the_parts_and_charges_nothing_meanwhile(self):
        w = world(panes=4)
        w.play(STORM_HOUR + 1)
        booking = w.b.book_contractor(STORM_HOUR + 1, "glazier", "A.glass")
        self.assertEqual(booking["status"], "waiting_for_parts")
        w.play(400)                                                      # the visit was due at hour 150
        self.assertEqual(w.repaired, {})
        self.assertEqual(w.totals()["contractors"], 0.0)
        status = w.b.view(400, Rng(1))["contractor_bookings"][0]["status"]
        self.assertEqual(status, "waiting_for_parts")
        order = w.b.place_order(400, "part:glass_pane", 4)               # the surge is over by now
        self.assertEqual(order["expected_arrival_hour"], 400 + 96)

    def test_a_visit_that_falls_due_at_night_waits_for_six_in_the_morning(self):
        w = world(boiler_pin=(20,), wind={})                             # the boiler trips at 20:00
        w.b.place_order(0, "part:boiler_kit", 1)                         # arrives at hour 36
        w.play(21)
        booking = w.b.book_contractor(21, "heating_installer", "boiler")
        self.assertEqual(booking["earliest_visit_hour"], 45)             # 21:00 the next day: off the site hours
        w.play(54)
        self.assertEqual(w.totals()["contractors"], 0.0)
        self.assertEqual(w.b.view(54, Rng(1))["contractor_bookings"][0]["status"], "waiting")
        w.play(55)                                                       # 06:00 (hour 54): the visit starts
        self.assertAlmostEqual(w.totals()["contractors"], -(94.0 + 90.0))
        w.play(60)
        self.assertEqual(w.repaired, {"boiler": 56})                     # 3 job hours: 54, 55, 56
        self.assertAlmostEqual(w.totals()["contractors"], -(94.0 + 3 * 90.0))
        self.assertEqual(w.b.ops.stock["part:boiler_kit"], 0)

    def test_work_stops_at_the_end_of_the_day_slot_and_resumes_next_morning(self):
        w = world(boiler_pin=(5,), wind={})
        w.play(4)
        w.b.place_order(4, "part:boiler_kit", 1)                         # arrives at hour 40 (16:00)
        w.play(6)
        w.b.book_contractor(6, "heating_installer", "boiler")            # earliest visit 30
        w.play(43)
        self.assertEqual(w.b.contractors.bookings[0].visit_hour, 40)     # parts, not the contractor, were late
        self.assertAlmostEqual(w.totals()["contractors"], -(94.0 + 2 * 90.0))   # 16:00 and 17:00 only
        self.assertEqual(w.repaired, {})
        w.play(60)
        self.assertEqual(w.repaired, {"boiler": 54})                     # the last job hour is at 06:00 the next day
        self.assertAlmostEqual(w.totals()["contractors"], -(94.0 + 3 * 90.0))      # one call-out only

    def test_booking_refusals_change_nothing(self):
        w = world(panes=4, boiler_pin=(5,))
        w.play(STORM_HOUR + 1)
        cash = w.b.cash_eur()
        for trade, target in (("plumber", "boiler"), ("glazier", "boiler"), ("heating_installer", "A.glass"),
                              ("glazier", "nowhere"), ("glazier", None)):
            with self.subTest(trade=trade, target=target):
                with self.assertRaises(RuleError):
                    w.b.book_contractor(STORM_HOUR + 1, trade, target)
        w.b.book_contractor(STORM_HOUR + 1, "glazier", "A.glass")
        with self.assertRaisesRegex(RuleError, "already booked"):
            w.b.book_contractor(STORM_HOUR + 1, "glazier", "A.glass")
        self.assertEqual((len(w.b.contractors.bookings), w.b.cash_eur()), (1, cash))

    def test_a_fault_that_clears_by_itself_needs_no_contractor(self):
        timed = replace(event("boiler_trip"), persistent=False, repair=None, duration_h=10.0, rate_per_day=0.0,
                        pinned_hours=(5,))
        w = world(wind={}, boiler=timed)
        w.play(6)
        with self.assertRaisesRegex(RuleError, "clears by itself"):
            w.b.book_contractor(6, "heating_installer", "boiler")


class SurgeTests(unittest.TestCase):
    def test_after_a_storm_glass_lead_time_and_glazier_response_rise(self):
        w = world(panes=4)
        before = w.b.place_order(10, "part:glass_pane", 1)
        self.assertEqual(before["expected_arrival_hour"] - 10, 96)
        self.assertIsNone(w.b.view(10, Rng(1))["surge_until_hour"])      # nobody knew about it yet
        w.play(54)
        after = w.b.place_order(54, "part:glass_pane", 1)
        self.assertEqual(after["expected_arrival_hour"] - 54, 480)       # the surge lead time
        booking = w.b.book_contractor(54, "glazier", "A.glass")
        self.assertEqual(booking["earliest_visit_hour"] - 54, 120)       # against 24 h normally
        self.assertEqual(before["expected_arrival_hour"], 106)           # an order placed earlier keeps its lead time

    def test_the_surge_ends_after_its_days(self):
        w = world(panes=4)
        w.play(STORM_HOUR + SURGE_H)
        order = w.b.place_order(STORM_HOUR + SURGE_H, "part:glass_pane", 1)
        self.assertEqual(order["expected_arrival_hour"] - (STORM_HOUR + SURGE_H), 96)

    def test_express_shortens_whichever_lead_time_applies_and_charges_a_surcharge(self):
        w = world(panes=4)
        normal = w.b.place_order(0, "part:glass_pane", 2, express=True)
        self.assertEqual(normal["expected_arrival_hour"], 48)            # half of 96
        w.play(49)
        totals = w.totals()
        self.assertAlmostEqual(totals["parts"], -2 * 45.0)               # the category is charged the normal price
        self.assertAlmostEqual(totals["express"], -2 * (90.0 - 45.0))    # and the surcharge is its own category
        w.play(54)
        surged = w.b.place_order(54, "part:glass_pane", 1, express=True)
        self.assertEqual(surged["expected_arrival_hour"] - 54, 240)      # half of the surge time, not back to normal

    def test_express_on_an_item_without_it_is_refused_and_orders_nothing(self):
        w = world()
        with self.assertRaisesRegex(RuleError, "no express option"):
            w.b.place_order(0, "co2_kg", 2000.0, express=True)
        self.assertEqual(w.b.ops.orders, [])
        self.assertEqual(w.b.cash_eur(), w.b.market.start_cash_eur)


if __name__ == "__main__":
    unittest.main()
