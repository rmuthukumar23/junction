"""Order item ids survive the serializers that mangle ':' (seen with Gemini via OpenCode)."""
import unittest
from pathlib import Path

from envkit.core import Episode
from envkit.scenario import load_scenario
from envkit.trace import Trace

ROOT = Path(__file__).resolve().parents[2]


class OrderIdTests(unittest.TestCase):
    def test_escaped_or_slashed_colon_orders_the_same_item(self):
        for key in ("seedlings:radish_micro", "seedlings\\u003aradish_micro", "seedlings/radish_micro"):
            ep = Episode(load_scenario(ROOT / "scenarios" / "normal-winter.toml"), 1, Trace(None), "")
            r = ep.call("submit_day", {"actions": [{"tool": "place_orders", "orders": {key: 1_000_000}}]})
            self.assertTrue(r["ok"], r)
            self.assertTrue(r["result"]["results"][0]["ok"], (key, r["result"]["results"][0]))

    def test_order_list_orders_by_value(self):
        ep = Episode(load_scenario(ROOT / "scenarios" / "normal-winter.toml"), 1, Trace(None), "")
        r = ep.call("submit_day", {"actions": [{"tool": "place_orders",
                                                "order_list": [{"item": "seedlings:radish_micro", "quantity": 1_000_000}]}]})
        self.assertTrue(r["result"]["results"][0]["ok"], r["result"]["results"][0])

    def test_unknown_item_is_still_refused(self):
        ep = Episode(load_scenario(ROOT / "scenarios" / "normal-winter.toml"), 1, Trace(None), "")
        r = ep.call("submit_day", {"actions": [{"tool": "place_orders", "orders": {"seedlings": 1_000_000}}]})
        self.assertFalse(r["result"]["results"][0]["ok"])


if __name__ == "__main__":
    unittest.main()
