"""The business adapter (world/business.py): refusals change nothing; CO2 is the facility's."""
import dataclasses
import tomllib
import unittest
from pathlib import Path

from envkit.rng import Rng
from greenhouse.config.base import resolve
from greenhouse.config.market import parse_event, parse_market
from greenhouse.contracts import Metered, RuleError
from greenhouse.world.business import build_business

ROOT = Path(__file__).resolve().parents[2]
CROPS = ("lettuce_butterhead", "broccoli_micro")
EQUIPMENT = ("boiler",)


def business(pin_boiler_at=None):
    rng = Rng(1).stream("params")
    read = lambda rel: (tomllib.loads((ROOT / rel).read_text()), rel)   # noqa: E731
    market = resolve(parse_market(*read("data/markets/nl_winter.toml")), rng.stream("market"))
    events = [dataclasses.replace(resolve(parse_event(*read(f"data/events/{e}.toml")), rng.stream(e)), rate_per_day=0.0)
              for e in ("boiler_trip", "late_delivery")]
    if pin_boiler_at is not None:
        events[0] = dataclasses.replace(events[0], pinned_hours=(pin_boiler_at,))
    return build_business(market, events, CROPS, EQUIPMENT, 240, Rng(1).stream("business"))


class BusinessTests(unittest.TestCase):
    def test_a_refused_repair_changes_nothing(self):
        b = business()
        before = (b.cash_eur(), b.events.repairs_requested, len(b.ops.tasks))
        with self.assertRaises(RuleError):
            b.queue_task(0, "repair", "chp", None, {})
        self.assertEqual((b.cash_eur(), b.events.repairs_requested, len(b.ops.tasks)), before)

    def test_a_repair_is_recorded_and_charged_once_queued(self):
        b = business(pin_boiler_at=5)
        b.start_hour(5)
        cash = b.cash_eur()
        b.queue_task(5, "repair", "boiler", None, {})
        self.assertEqual(b.events.repairs_requested, 1)
        self.assertEqual(b.events.outages[0].repair_requested_hour, 5)
        self.assertLess(b.cash_eur(), cash)

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
