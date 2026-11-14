"""Market and event schemas: the committed files load; bad files fail naming the file and key."""
import copy
import tomllib
import unittest
from pathlib import Path

from greenhouse.config.base import ConfigError, Range
from greenhouse.config.market import parse_event, parse_market

ROOT = Path(__file__).resolve().parents[2]
MARKET = ROOT / "data" / "markets" / "nl_winter.toml"
EVENTS = sorted((ROOT / "data" / "events").glob("*.toml"))


def load(path):
    return tomllib.loads(path.read_text())


class MarketSchemaTests(unittest.TestCase):
    def test_the_committed_market_loads(self):
        m = parse_market(load(MARKET), str(MARKET))
        self.assertEqual(m.id, "nl_winter")
        self.assertEqual(set(m.crops), {"lettuce_butterhead", "broccoli_micro", "radish_micro"})
        self.assertIn("co2_kg", m.items)
        self.assertEqual(m.items["co2_kg"].lead_time_h, 72.0)
        self.assertGreater(m.staff.wage_eur_per_worker_hour, 0)

    def test_bad_market_files_fail_with_file_and_key(self):
        raw = load(MARKET)
        cases = []
        missing = copy.deepcopy(raw); del missing["staff"]["wage_eur_per_worker_hour"]
        cases.append((missing, "staff.wage_eur_per_worker_hour"))
        stray = copy.deepcopy(raw); stray["staff"]["wage_per_hour_typo"] = 1.0
        cases.append((stray, "wage_per_hour_typo"))
        negative = copy.deepcopy(raw); negative["items"]["co2_kg"]["min_quantity"] = -5
        cases.append((negative, "min_quantity"))
        bad_item = copy.deepcopy(raw); bad_item["items"]["gas_m3"] = dict(raw["items"]["co2_kg"])
        cases.append((bad_item, "gas_m3"))
        orphan = copy.deepcopy(raw); orphan["items"]["seedlings:spinach"] = dict(raw["items"]["seedlings:broccoli_micro"])
        cases.append((orphan, "seedlings:spinach"))
        stock = copy.deepcopy(raw); stock["start_stock"]["nutrients_kg"] = 5.0
        cases.append((stock, "nutrients_kg"))
        crew = copy.deepcopy(raw); crew["staff"]["start_crew"] = 99
        cases.append((crew, "start_crew"))
        bad_cat = copy.deepcopy(raw); bad_cat["items"]["co2_kg"]["category"] = "wages"
        cases.append((bad_cat, "category"))
        co2_stock = copy.deepcopy(raw); co2_stock["start_stock"]["co2_kg"] = 500.0
        cases.append((co2_stock, "start_stock.co2_kg"))
        for doc, key in cases:
            with self.subTest(key=key):
                with self.assertRaises(ConfigError) as cm:
                    parse_market(doc, "markets/test.toml")
                self.assertIn("markets/test.toml", str(cm.exception))
                self.assertIn(key, str(cm.exception))

    def test_a_price_can_be_a_hidden_range(self):
        raw = load(MARKET)
        raw["items"]["co2_kg"]["lead_time_h"] = {"min": 48, "max": 96}
        m = parse_market(raw, "x")
        self.assertIsInstance(m.items["co2_kg"].lead_time_h, Range)


class EventSchemaTests(unittest.TestCase):
    def test_every_committed_event_file_loads(self):
        self.assertTrue(EVENTS)
        for path in EVENTS:
            with self.subTest(path=path.name):
                spec = parse_event(load(path), str(path))
                self.assertEqual(spec.id, path.stem)

    def test_bad_event_files_fail_with_file_and_key(self):
        raw = load(ROOT / "data" / "events" / "boiler_trip.toml")
        cases = []
        no_rate = copy.deepcopy(raw); del no_rate["rate_per_day"]
        cases.append((no_rate, "rate_per_day"))
        bad_kind = copy.deepcopy(raw); bad_kind["kind"] = "meteor"
        cases.append((bad_kind, "kind"))
        bad_range = copy.deepcopy(raw); bad_range["duration_h"] = {"min": 30, "max": 6}
        cases.append((bad_range, "duration_h"))
        stray = copy.deepcopy(raw); stray["effect"]["colour"] = "red"
        cases.append((stray, "effect.colour"))
        bad_factor = copy.deepcopy(raw); bad_factor["effect"]["capacity_factor"] = 2.0
        cases.append((bad_factor, "capacity_factor"))
        bad_pin = copy.deepcopy(raw); bad_pin["pinned_hours"] = [-3]
        cases.append((bad_pin, "pinned_hours"))
        for doc, key in cases:
            with self.subTest(key=key):
                with self.assertRaises(ConfigError) as cm:
                    parse_event(doc, "events/test.toml")
                self.assertIn("events/test.toml", str(cm.exception))
                self.assertIn(key, str(cm.exception))


if __name__ == "__main__":
    unittest.main()
