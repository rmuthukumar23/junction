"""The BusinessModel adapter (world/business.py) over Rowan's real market and event
files, alone and inside the simulator with the fake facility and crops."""
import dataclasses
import tomllib
import unittest
from pathlib import Path

from envkit.rng import Rng
from greenhouse.config.base import ConfigError, resolve
from greenhouse.config.market import parse_event, parse_market
from greenhouse.contracts import HarvestResult, Metered, RuleError, StartBatch
from greenhouse.world.business import build_business
from greenhouse.world.modules import Modules
from greenhouse.world.sim import Greenhouse

from fakes import FakeCrop, FakeFacility

ROOT = Path(__file__).resolve().parents[2]
CROPS = ("lettuce_butterhead", "broccoli_micro")
EQUIPMENT = ("boiler", "A.vents", "B.vents")


def read(rel: str):
    path = ROOT / rel
    return tomllib.loads(path.read_text(encoding="utf-8")), rel


def specs(seed: int = 1, pin_boiler_at: int | None = None):
    rng = Rng(seed).stream("params")
    market = resolve(parse_market(*read("data/markets/nl_winter.toml")), rng.stream("market"))
    events = [resolve(parse_event(*read(f"data/events/{e}.toml")), rng.stream(e)) for e in ("boiler_trip", "late_delivery")]
    events = [dataclasses.replace(e, rate_per_day=0.0) for e in events]       # no random events in these tests
    if pin_boiler_at is not None:
        events[0] = dataclasses.replace(events[0], pinned_hours=(pin_boiler_at,))
    return market, events


def business(seed: int = 1, horizon_h: int = 240, pin_boiler_at: int | None = None):
    market, events = specs(seed, pin_boiler_at)
    return build_business(market, events, CROPS, EQUIPMENT, horizon_h, Rng(seed).stream("business"))


class _Facility(FakeFacility):
    """The fake facility growing the real crop ids."""

    def crop_id(self, c):
        return CROPS[0] if c == "A" else CROPS[1]

    def start_batches(self):
        return [StartBatch("A", CROPS[0], 24.0, 500.0), StartBatch("B", CROPS[1], 20.0, 500.0)]


def sim(seed: int = 1, pin_boiler_at: int | None = None) -> Greenhouse:
    rng = Rng(seed)
    growth = {CROPS[0]: FakeCrop(CROPS[0]), CROPS[1]: FakeCrop(CROPS[1], repeated=True)}
    modules = Modules(_Facility(rng.stream("facility")), business(seed, pin_boiler_at=pin_boiler_at), growth, 240, 4)
    return Greenhouse(modules, rng.stream("sim"))


class AdapterTests(unittest.TestCase):
    def test_factory_checks_crops_and_equipment(self):
        market, events = specs()
        with self.assertRaisesRegex(ConfigError, "no price"):
            build_business(market, events, ("spinach",), EQUIPMENT, 240, Rng(1))
        with self.assertRaisesRegex(ConfigError, "boiler"):
            build_business(market, events, CROPS, ("chp",), 240, Rng(1))

    def test_refusals_are_rule_errors_and_change_nothing(self):
        b = business()
        cash = b.cash_eur()
        for call in (lambda: b.place_order(0, "co2_kg", 1.0), lambda: b.place_order(0, "gold", 5000.0),
                     lambda: b.cancel_order(0, "O999"), lambda: b.hire(0, 0), lambda: b.release(0, 99),
                     lambda: b.take_seedlings(0, CROPS[0], 1)):
            with self.assertRaises(RuleError):
                call()
        self.assertEqual(b.cash_eur(), cash)
        self.assertEqual(b.ops.orders, [])

    def test_co2_delivery_goes_to_the_facility_not_business_stock(self):
        b = business()
        order = b.place_order(0, "co2_kg", 2000.0)
        arrival = order["expected_arrival_hour"]
        for h in range(arrival + 1):
            end = b.end_hour(h, Metered(h))
            if h < arrival:
                self.assertEqual(end.deliveries, ())
        self.assertEqual([(d.item, d.quantity) for d in end.deliveries], [("co2_kg", 2000.0)])
        self.assertNotIn("co2_kg", b.view(arrival, Rng(1))["stock"])
        self.assertLess(b.totals()["co2"], 0)
        self.assertFalse(any(a.target == "co2_kg" and a.kind == "stock_low" for a in end.alarms))

    def test_energy_is_priced_from_the_metered_hour(self):
        b = business()
        b.end_hour(0, Metered(0, gas_m3=100.0, electricity_export_kwh=50.0, gas_eur_per_m3=0.5,
                              export_eur_per_kwh=0.1))
        t = b.totals()
        self.assertAlmostEqual(t["gas"], -50.0)
        self.assertAlmostEqual(t["electricity_sold"], 5.0)

    def test_sale_uses_the_crop_models_price_factor(self):
        b = business()
        price = b.crop_price[CROPS[0]]
        good = b.sell(5, HarvestResult("A1", CROPS[0], 1000.0, "head", 200.0, 0.9, True, "A", 0.8))
        self.assertAlmostEqual(good.eur, 1000.0 * price * 0.8)
        bad = b.sell(5, HarvestResult("A2", CROPS[0], 1000.0, "head", 50.0, 0.9, False, "waste", 0.0))
        self.assertEqual(bad.eur, 0.0)
        self.assertAlmostEqual(b.profit_eur(), good.eur)
        self.assertEqual(b.ledger.unsellable_harvests, 1)

    def test_rules_publish_prices_and_events_not_the_schedule(self):
        r = business(pin_boiler_at=50).rules()
        self.assertIn(CROPS[0], r["crop_prices_eur_per_unit"])
        self.assertEqual({e["id"] for e in r["events"]}, {"boiler_trip", "late_delivery"})
        self.assertNotIn("50", str(r["events"]))


class InSimTests(unittest.TestCase):
    def run_to(self, s: Greenhouse, hour: int):
        while s.hour < hour:
            s.run_hour()

    def test_co2_order_reaches_the_facility_store(self):
        s = sim()
        before = s.facility.co2_store_kg
        order = s.business.place_order(s.hour, "co2_kg", 2000.0)
        self.run_to(s, order["expected_arrival_hour"] + 1)
        self.assertGreater(s.facility.co2_store_kg, before)

    def test_repair_shortens_the_outage_then_clears_it(self):
        s = sim(pin_boiler_at=7)              # inside the 07:00 shift on day 0
        self.run_to(s, 8)
        self.assertIn("boiler", s.effects)
        self.assertEqual(s.facility.boiler_factor, 0.0)
        cash = s.business.cash_eur()
        task = s.repair("boiler")
        self.assertLess(s.business.cash_eur(), cash)          # call-out charged at once
        while task.id not in s.completed_task_ids:
            s.run_hour()
        done = s.hour - 1
        eff = s.effects.get("boiler")
        self.assertIsNotNone(eff)                              # back a few hours later, not at once
        self.assertGreater(eff.until_hour, done + 1)
        self.run_to(s, eff.until_hour + 1)
        self.assertNotIn("boiler", s.effects)
        self.assertEqual(s.facility.boiler_factor, 1.0)

    def test_planting_uses_stocked_seedlings_and_crew(self):
        s = sim()
        with self.assertRaisesRegex(RuleError, "seedlings"):
            s.business.take_seedlings(0, CROPS[0], 10)
        order = s.business.place_order(0, f"seedlings:{CROPS[0]}", 20000.0)
        self.run_to(s, order["expected_arrival_hour"] + 1)
        self.assertEqual(s.business.ops.stock[f"seedlings:{CROPS[0]}"], 20000.0)

    def test_same_seed_same_money(self):
        def money(seed):
            s = sim(seed, pin_boiler_at=30)
            s.business.place_order(0, "co2_kg", 2000.0)
            self.run_to(s, 120)
            return s.business.totals()
        self.assertEqual(money(3), money(3))


if __name__ == "__main__":
    unittest.main()
