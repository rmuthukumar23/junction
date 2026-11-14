"""The news feed (spec 14.3): drawn once from the seed and the recorded series, never from the agent."""
import re
import tomllib
import unittest
from dataclasses import replace
from pathlib import Path

from envkit.rng import Rng
from greenhouse.config.market import parse_event, parse_market, parse_news
from greenhouse.contracts import Metered, Recorded, WeatherNow
from greenhouse.world.business import build_business
from greenhouse.world.news import Feed, build_feed, real_events

ROOT = Path(__file__).resolve().parents[2]
HORIZON = 1008


def news(name):
    return parse_news(tomllib.loads((ROOT / f"data/news/{name}.toml").read_text()), name)


STORM, FROST, GAS = news("storm"), news("frost"), news("gas_price")
STORM_EVENT = parse_event(tomllib.loads((ROOT / "data/events/storm.toml").read_text()), "storm")


def series(hours=HORIZON, wind=None, temp=None, gas=None):
    """A hand-made recorded series. Mapping arguments give values at some hours, the rest is mild and calm."""
    wind, temp, gas = wind or {}, temp or {}, gas or {}
    weather = tuple(WeatherNow(h, temp.get(h, 4.0), wind.get(h, 3.0), 0.0, 80.0) for h in range(hours))
    return Recorded(weather, tuple(gas.get(h, 0.40) for h in range(hours)))


STORM_HOURS = list(range(100, 1000, 100))                  # nine well-separated storms
WINDY = series(wind={h: 15.0 for h in STORM_HOURS})
STORMY_NIGHTS = list(range(30, 1000, 24))                  # a frosty hour in the early morning of most days
FROSTY = series(temp={h: -6.0 for h in STORMY_NIGHTS[::2]})


class FeedTests(unittest.TestCase):
    def test_the_same_seed_gives_the_identical_feed_and_another_seed_a_different_one(self):
        specs = [STORM, FROST, GAS]
        a = build_feed(specs, STORM_HOURS, WINDY, HORIZON, Rng(3).stream("news"))
        b = build_feed(specs, STORM_HOURS, WINDY, HORIZON, Rng(3).stream("news"))
        c = build_feed(specs, STORM_HOURS, WINDY, HORIZON, Rng(4).stream("news"))
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_adding_a_news_file_does_not_move_the_others(self):
        alone = build_feed([STORM], STORM_HOURS, WINDY, HORIZON, Rng(3).stream("news"))
        both = build_feed([STORM, FROST], STORM_HOURS, WINDY, HORIZON, Rng(3).stream("news"))
        self.assertEqual(alone, [x for x in both if x.news_id == "storm"])

    def test_a_read_never_returns_a_future_headline_and_respects_the_window(self):
        feed = Feed([STORM, FROST, GAS], STORM_HOURS, WINDY, HORIZON, Rng(5).stream("news"))
        self.assertTrue(feed.items)
        for hour in (0, 1, 50, 333, 700, HORIZON - 1):
            for days in (0.5, 1, 3, 100):
                rows = feed.since(hour, days)
                self.assertTrue(all(hour - 24 * days < r["hour"] <= hour for r in rows))
                self.assertEqual([r["hour"] for r in rows], sorted(r["hour"] for r in rows))   # oldest first
                self.assertTrue(all(set(r) == {"hour", "day", "headline"} and r["day"] == r["hour"] // 24
                                    for r in rows))
        everything = feed.since(HORIZON - 1, HORIZON / 24)
        self.assertEqual(len(everything), len(feed.items))
        # reading later never changes what was already published
        early = feed.since(200, 100)
        self.assertEqual(early, [r for r in feed.since(900, 100) if r["hour"] <= 200])

    def test_false_alarms_appear_when_nothing_is_coming(self):
        noisy = replace(STORM, false_alarms_per_day=0.5)
        feed = build_feed([noisy], [], series(), HORIZON, Rng(1).stream("news"))
        self.assertGreater(len(feed), 5)                              # about 21 expected
        self.assertTrue(all(not x.real and x.text in noisy.headlines for x in feed))
        quiet = build_feed([replace(STORM, false_alarms_per_day=0.0)], [], series(), HORIZON, Rng(1).stream("news"))
        self.assertEqual(quiet, [])

    def test_a_storm_signal_precedes_most_storms_within_its_lead_range(self):
        always = replace(STORM, hit_rate=1.0, false_alarms_per_day=0.0)
        feed = build_feed([always], STORM_HOURS, WINDY, HORIZON, Rng(1).stream("news"))
        self.assertEqual(len(feed), len(STORM_HOURS))
        for storm, signal in zip(STORM_HOURS, feed):
            self.assertTrue(storm - always.lead_max_h <= signal.hour <= storm - always.lead_min_h, (storm, signal))
            self.assertTrue(signal.real)
        quiet = replace(STORM, false_alarms_per_day=0.0)
        hits = sum(len(build_feed([quiet], STORM_HOURS, WINDY, HORIZON, Rng(seed).stream("news")))
                   for seed in range(1, 31))                          # the published hit rate holds over seeds
        self.assertLess(abs(hits / (30 * len(STORM_HOURS)) - STORM.hit_rate), 0.1)

    def test_signals_before_hour_zero_are_clamped_to_hour_zero(self):
        always = replace(STORM, hit_rate=1.0, false_alarms_per_day=0.0)
        feed = build_feed([always], [5], series(), HORIZON, Rng(1).stream("news"))
        self.assertEqual([x.hour for x in feed], [0])

    def test_headlines_name_no_equipment_compartment_hour_or_weekday(self):
        banned = re.compile(r"\d|boiler|chp|vent|glass|screen|compartment|lamp|monday|tuesday|wednesday|thursday|"
                            r"friday|saturday|sunday|tonight|hour", re.I)
        for spec in (STORM, FROST, GAS):
            for text in spec.headlines:
                with self.subTest(text=text):
                    self.assertIsNone(banned.search(text))

    def test_frost_and_gas_follow_the_recorded_series(self):
        frost_hours = real_events(FROST, [], FROSTY, HORIZON)
        self.assertTrue(frost_hours)
        self.assertTrue(all(FROSTY.weather[h].temp_c < FROST.frost_below_c for h in frost_hours))
        self.assertTrue(all(b - a >= FROST.window_h for a, b in zip(frost_hours, frost_hours[1:])))
        spike = series(gas={h: 0.40 * (1 + GAS.rise_fraction) for h in range(500, 520)})
        self.assertEqual(real_events(GAS, [], spike, HORIZON), [500])
        self.assertEqual(real_events(GAS, [], series(), HORIZON), [])
        self.assertEqual(real_events(FROST, [], series(), HORIZON), [])

    def test_rules_publish_rates_but_not_the_feed(self):
        feed = Feed([STORM, FROST, GAS], STORM_HOURS, WINDY, HORIZON, Rng(1).stream("news"))
        rules = {r["id"]: r for r in feed.rules()}
        self.assertEqual(set(rules), {"storm", "frost", "gas_price"})
        self.assertEqual(rules["storm"]["hit_rate"], STORM.hit_rate)
        self.assertEqual(rules["storm"]["lead_h"], [STORM.lead_min_h, STORM.lead_max_h])
        self.assertNotIn("headline", str(rules))


class BusinessNewsTests(unittest.TestCase):
    def business(self, seed=1):
        market = parse_market(tomllib.loads((ROOT / "data/markets/nl_winter.toml").read_text()), "nl_winter")
        storm = replace(STORM_EVENT, pinned_hours=(), panes_min=2.0, panes_max=2.0)
        recorded = series(wind={h: 15.0 for h in STORM_HOURS}, temp={h: -6.0 for h in STORMY_NIGHTS[::2]})
        return build_business(market, [storm], [STORM, FROST, GAS], ("lettuce_butterhead",), ("boiler", "A.glass"),
                              HORIZON, Rng(seed).stream("business"), recorded)

    def test_the_feed_is_the_same_whatever_the_agent_does(self):
        quiet, busy = self.business(), self.business()
        busy.place_order(0, "co2_kg", 2000.0)
        busy.place_order(0, "part:glass_pane", 3, express=True)
        for h in range(400):
            busy.start_hour(h, None)
            busy.end_hour(h, Metered(h))
        self.assertEqual(quiet.news(HORIZON - 1, 100), busy.news(HORIZON - 1, 100))
        self.assertEqual(quiet.news(300, 5), busy.news(300, 5))

    def test_storm_news_matches_the_storms_the_events_will_fire(self):
        b = self.business()
        self.assertEqual(b.events.storm_starts(), STORM_HOURS)
        always = [x for x in b.feed.items if x.news_id == "storm" and x.real]
        self.assertLessEqual(len(always), len(STORM_HOURS))
        self.assertTrue(all(any(0 <= s - x.hour <= STORM.lead_max_h for s in STORM_HOURS) for x in always))


if __name__ == "__main__":
    unittest.main()
