"""The submitted scenario on the real facility, business and crops.

These are the checks a judge makes: the ladder is ordered, nobody scores by avoiding
the task, the reference is reproducible, and nothing hidden is published. They play
whole 42-day episodes (about 2 s each), on development seed 1.
"""
import json
import os
import unittest
from pathlib import Path

from envkit.calibrate import calibrate
from envkit.clients import run_inprocess
from envkit.core import Episode, replay
from envkit.policies import make_policy
from envkit.scenario import load_scenario
from envkit.scoring import score
from greenhouse.config.base import Range
from greenhouse.env import GreenhouseBench

if os.environ.get("ENVKIT_TEST_SCENARIO") != "normal-winter":
    # Benchmark checks: they play whole 42-day episodes. Never part of the quick suite.
    raise unittest.SkipTest("full 42-day benchmark checks; run with ENVKIT_TEST_SCENARIO=normal-winter")

ROOT = Path(__file__).resolve().parents[2]
SCENARIO = load_scenario(ROOT / "scenarios" / "normal-winter.toml")
SEED = 1
EXPLOITS = sorted(n for n in GreenhouseBench.policies() if n.startswith("exploit:"))

_cache: dict[str, Episode] = {}
_calibration: dict = {}


def play(name: str) -> Episode:
    if name not in _cache:
        _cache[name] = run_inprocess(SCENARIO, SEED, make_policy(name, SCENARIO))
    return _cache[name]


def profit(name: str) -> float:
    return play(name).result()["profit_eur"]


def reward(name: str) -> float:
    if not _calibration:
        _calibration.update(calibrate(SCENARIO, SEED))
    return score(SCENARIO, play(name).result(), _calibration)["reward"]


def numbers(value) -> list[float]:
    if isinstance(value, dict):
        return [n for v in value.values() for n in numbers(v)]
    if isinstance(value, (list, tuple)):
        return [n for v in value for n in numbers(v)]
    return [float(value)] if isinstance(value, (int, float)) and not isinstance(value, bool) else []


class ScenarioTests(unittest.TestCase):
    def test_the_scenario_names_real_data_and_the_whole_ladder(self):
        self.assertEqual(SCENARIO.shift.windows, 42 * 24)
        self.assertEqual(SCENARIO.shift.max_calls, 400)
        files = GreenhouseBench.data_files(SCENARIO.env_config)
        self.assertEqual(len(files), 9)   # facility, climate, prices, market, 3 crops, 2 events
        for rel in files:
            self.assertTrue((ROOT / rel).is_file(), rel)
        registered = GreenhouseBench.policies()
        for name in SCENARIO.anchor_names():
            if name not in ("do-nothing", "stop-early"):
                self.assertIn(name, registered)

    def test_every_policy_plays_the_whole_episode_without_faults_inside_the_call_budget(self):
        for name in ["absentee", "naive", "rule-based", "reference", *EXPLOITS]:
            with self.subTest(policy=name):
                ep = play(name)
                self.assertEqual(ep.faults, 0, ep.fault_log)
                self.assertEqual(ep.env.sim.hour, SCENARIO.shift.windows)
                self.assertLessEqual(ep.calls, SCENARIO.shift.max_calls)
                self.assertLess(abs(ep.result()["money_conservation_error_eur"]), 1e-6)   # float sums, not money


class LadderTests(unittest.TestCase):
    def test_nobody_acting_loses_money_and_watching_changes_nothing(self):
        self.assertLess(profit("do-nothing"), 0)
        self.assertEqual(profit("absentee"), profit("do-nothing"))
        self.assertEqual(reward("do-nothing"), 0.0)
        self.assertEqual(reward("absentee"), 0.0)

    def test_the_reference_is_far_above_the_simple_growers(self):
        nothing, reference = profit("do-nothing"), profit("reference")
        self.assertGreater(profit("naive"), nothing)
        self.assertGreater(profit("rule-based"), nothing)
        best_simple = max(profit("naive"), profit("rule-based"))
        # The room an agent has to improve: the simple growers reach less than half of
        # what the reference adds over doing nothing.
        self.assertLess(best_simple - nothing, 0.5 * (reference - nothing))
        self.assertAlmostEqual(reward("reference"), 0.8, places=3)

    def test_stopping_at_once_is_the_same_as_doing_nothing(self):
        ep = Episode(SCENARIO, SEED)
        self.assertTrue(ep.call("finish_episode")["ok"])
        self.assertEqual(ep.result()["profit_eur"], profit("do-nothing"))

    def test_stopping_early_never_beats_playing_on(self):
        full = reward("reference")
        early = reward("stop-early")
        self.assertLess(early, full)
        rewards = [reward(f"stop-after:reference@{n}") for n in (20, 80, 160)]
        for a, b in zip(rewards, rewards[1:]):
            self.assertLessEqual(a, b + 0.02)
        self.assertLess(max(rewards), full)


class ExploitTests(unittest.TestCase):
    def test_no_exploit_comes_near_the_reference(self):
        """Several exploit policies are the rule-based grower plus one twist, so they keep
        its score. None may add more than a little to it (running the CHP flat out adds
        about 0.03 because CHP power is simply good play here, and the reference uses it),
        and all stay under half of the reference."""
        honest = reward("rule-based")
        for name in EXPLOITS:
            with self.subTest(exploit=name):
                self.assertLess(reward(name), honest + 0.05)
                self.assertLess(reward(name), 0.5 * reward("reference"))

    def test_the_rule_based_grower_beats_the_naive_one(self):
        self.assertGreater(profit("rule-based"), profit("naive"))

    def test_exploits_that_avoid_the_work_score_next_to_nothing(self):
        for name in ("exploit:never-harvest", "exploit:spam-orders", "exploit:extreme-climate",
                     "exploit:harvest-early", "exploit:spam-repairs"):
            with self.subTest(exploit=name):
                self.assertLess(reward(name), 0.1)

    def test_harvesting_everything_early_sells_nothing_extra(self):
        ledger = play("exploit:harvest-early").result()
        self.assertGreater(ledger["unsellable_harvests"], 0)
        self.assertLess(profit("exploit:harvest-early"), profit("naive"))

    def test_never_harvesting_earns_nothing(self):
        self.assertEqual(play("exploit:never-harvest").result()["eur_harvest_revenue"], 0.0)
        self.assertEqual(reward("exploit:never-harvest"), 0.0)


class IntegrityTests(unittest.TestCase):
    def test_the_reference_run_replays_exactly(self):
        ep = play("reference")
        again = run_inprocess(SCENARIO, SEED, make_policy("reference", SCENARIO))
        self.assertEqual([r["digest"] for r in ep.trace.calls], [r["digest"] for r in again.trace.calls])
        replayed, mismatches = replay(SCENARIO, SEED, ep.trace.records)
        self.assertEqual(mismatches, [])
        self.assertEqual(replayed.result()["profit_eur"], ep.result()["profit_eur"])

    def test_get_rules_publishes_ranges_never_the_drawn_values(self):
        ep = Episode(SCENARIO, SEED)
        rules = ep.call("get_rules")["result"]
        published = set(numbers({k: v for k, v in rules.items() if k != "hidden_parameter_ranges"}))
        sim = ep.env.sim
        centre = sim.facility.spec.energy_centre
        drawn = {"chp.electric_kw": centre.chp.electric_kw, "boiler.heat_kw": centre.boiler.heat_kw,
                 "buffer.capacity_kwh": centre.buffer.capacity_kwh, "grid.import_kw": centre.grid.import_kw}
        for c in sim.facility.spec.compartments:
            drawn.update({f"{c.id}.floor_m2": c.floor_m2, f"{c.id}.cover_u": c.cover_u_w_m2_k,
                          f"{c.id}.transmission": c.cover_transmission, f"{c.id}.lamps": c.lamps.w_per_m2})
        for spec in sim.business.events.specs.values():
            drawn[f"event.{spec.id}"] = spec.duration_h if spec.kind == "equipment" else spec.delay_h
        for name, value in drawn.items():
            with self.subTest(parameter=name):
                self.assertNotIsInstance(value, Range)           # the loader resolved it for this seed
                self.assertNotIn(float(value), published)
        ranges = rules["hidden_parameter_ranges"]
        self.assertIn("duration_h", ranges["events.boiler_trip"])
        self.assertIn("delay_h", ranges["events.late_delivery"])
        self.assertNotIn("duration_h", json.dumps(rules["business"]["events"]))

    def test_the_ledger_carries_failure_mode_evidence_that_is_not_scored(self):
        ledger = play("naive").result()
        for key in ("fm_harvests", "fm_unsellable_harvests", "fm_import_kwh", "fm_orders_placed",
                    "money_harvest_revenue_eur", "money_wages_eur"):
            self.assertIn(key, ledger)
        self.assertEqual([m for c in SCENARIO.components for m in c.metrics], ["profit_eur"])


if __name__ == "__main__":
    unittest.main()
