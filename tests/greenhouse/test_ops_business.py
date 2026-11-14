"""The business adapter (world/business.py): refusals change nothing; CO2 is the facility's."""
import dataclasses
import tomllib
import unittest
from pathlib import Path

from envkit.rng import Rng
from greenhouse.config.base import resolve
from greenhouse.config.market import parse_event, parse_market
from greenhouse.contracts import Metered, Recorded, RuleError, WeatherNow
from greenhouse.world.business import build_business

ROOT = Path(__file__).resolve().parents[2]
CROPS = ("lettuce_butterhead", "broccoli_micro")
EQUIPMENT = ("boiler",)
HORIZON = 240


def business(pin_boiler_at=None):
    rng = Rng(1).stream("params")
    read = lambda rel: (tomllib.loads((ROOT / rel).read_text()), rel)   # noqa: E731
    market = resolve(parse_market(*read("data/markets/nl_winter.toml")), rng.stream("market"))
    events = [dataclasses.replace(resolve(parse_event(*read(f"data/events/{e}.toml")), rng.stream(e)), rate_per_day=0.0)
              for e in ("boiler_trip", "late_delivery")]
    if pin_boiler_at is not None:
        events[0] = dataclasses.replace(events[0], pinned_hours=(pin_boiler_at,))
    recorded = Recorded(tuple(WeatherNow(h, 2.0, 3.0, 0.0, 80.0) for h in range(HORIZON)), (0.4,) * HORIZON)
    return build_business(market, events, [], CROPS, EQUIPMENT, HORIZON, Rng(1).stream("business"), recorded)


class BusinessTests(unittest.TestCase):
    def test_a_refused_booking_changes_nothing(self):
        b = business()
        before = (b.cash_eur(), len(b.contractors.bookings), len(b.ops.tasks))
        for call in (lambda: b.book_contractor(0, "glazier", "boiler"),          # wrong trade for the target
                     lambda: b.book_contractor(0, "heating_installer", "boiler"),  # nothing broken
                     lambda: b.book_contractor(0, "plumber", "boiler")):           # unknown trade
            with self.assertRaises(RuleError):
                call()
        self.assertEqual((b.cash_eur(), len(b.contractors.bookings), len(b.ops.tasks)), before)

    def test_a_booking_is_free_until_the_visit(self):
        b = business(pin_boiler_at=5)
        b.start_hour(5)
        cash = b.cash_eur()
        booking = b.book_contractor(5, "heating_installer", "boiler")
        self.assertEqual((booking["status"], booking["parts_needed"]), ("waiting_for_parts", {"part:boiler_kit": 1}))
        self.assertEqual(b.cash_eur(), cash)
        self.assertEqual(b.events.outages[0].booked_hour, 5)
        outage = b.view(5, Rng(1))["outages"][0]
        self.assertEqual(outage["repair"]["booking_id"], booking["booking_id"])

    def test_a_co2_delivery_is_handed_on_and_never_held(self):
        b = business()
        order = b.place_order(0, "co2_kg", 2000)
        deliveries = []
        for h in range(order["expected_arrival_hour"] + 1):
            deliveries += b.end_hour(h, Metered(hour=h)).deliveries
        self.assertEqual([(d.item, d.quantity) for d in deliveries], [("co2_kg", 2000.0)])
        self.assertNotIn("co2_kg", b.view(0, Rng(1))["stock"])


if __name__ == "__main__":
    unittest.main()
