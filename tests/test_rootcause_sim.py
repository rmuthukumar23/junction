"""Root Cause simulator: determinism, requests, tests, the incident, views and failure modes."""
import json
from pathlib import Path
import unittest

from envkit.clients import run_inprocess
from envkit.policies import make_policy
from envkit.scenario import load_scenario

from rootcause import outcome, views
from rootcause.model import step_bench
from rootcause.sim import Greenhouse, RuleError

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = load_scenario(ROOT / "scenarios" / "root-cause.toml")
CONFIG = dict(SCENARIO.env_config)
SEED = 7


def sim(seed=SEED):
    return Greenhouse(CONFIG, seed)


def plan(mains=230.0, fertilizer=90.0, flush=0.0, reserve=0.0, **overrides):
    out = {z: {"mains_l": mains, "reserve_l": reserve, "fertilizer_g": fertilizer, "flush_l": flush} for z in "ABC"}
    for bench, values in overrides.items():
        out[bench].update(values)
    return out


def fingerprint(g):
    return json.dumps({"day": g.day, "reserve": g.reserve_l, "costs": g.costs,
                       "benches": {z: [b.volume, b.nutrient, b.salt, b.condition, b.harvest]
                                   for z, b in g.benches.items()}}, sort_keys=True)


class DeterminismTests(unittest.TestCase):
    def test_same_seed_and_actions_give_the_same_outcome(self):
        a, b = sim(), sim()
        for g in (a, b):
            g.submit_plan(plan(reserve=50.0))
            g.advance()
            g.finish()
        self.assertEqual(fingerprint(a), fingerprint(b))

    def test_different_seeds_differ(self):
        self.assertNotEqual(sim(1).instance.backup_salt_g_l, sim(2).instance.backup_salt_g_l)

    def test_exogenous_draws_do_not_depend_on_what_the_player_does(self):
        quiet, busy = sim(), sim()
        for _ in range(3):
            busy.order_water_test() if busy.day not in {t["sampled_day"] for t in busy.tests} else None
            views.status(busy)
            busy.submit_plan(plan(100.0, 300.0, reserve=100.0))
            busy.advance()
            quiet.advance()
        self.assertEqual(quiet.instance, busy.instance)
        self.assertEqual([m["A"]["day"] for m in quiet.mornings], [m["A"]["day"] for m in busy.mornings])


class RequestTests(unittest.TestCase):
    def test_error_names_every_problem_so_it_can_be_fixed_in_one_go(self):
        g = sim()
        with self.assertRaises(RuleError) as cm:
            g.submit_plan({"A": {"mains_l": -1, "reserve_l": 0, "fertilizer_g": 9999, "flush_l": 0},
                           "B": {"mains_l": 400, "reserve_l": 200, "fertilizer_g": 0, "flush_l": 0, "x": 1}})
        message = str(cm.exception)
        for fragment in ("missing bench(es) ['C']", "must not be negative", "fertilizer_g 9999",
                         "unknown field(s) ['x']", "top-up limit"):
            self.assertIn(fragment, message)
        self.assertIsNone(g.plan)

    def test_the_reserve_is_shared_and_limited(self):
        g = sim()
        with self.assertRaises(RuleError):
            g.submit_plan(plan(0.0, reserve=g.reserve_l / 3 + 1.0))
        g.submit_plan(plan(0.0, reserve=400.0))
        g.advance()
        self.assertAlmostEqual(g.reserve_l, g.instance.reserve_l - 1200.0)
        self.assertAlmostEqual(g.costs["reserve_water"], 1200.0 * g.p.reserve_price_per_l)

    def test_resubmitting_replaces_the_plan_and_nothing_is_charged_until_the_day_runs(self):
        g = sim()
        g.submit_plan(plan(100.0))
        g.submit_plan(plan(200.0))
        self.assertEqual(sum(g.costs.values()), 0.0)
        g.advance()
        self.assertEqual(g.days[0]["benches"]["A"]["plan"]["mains_l"], 200.0)
        self.assertEqual(g.plans_submitted, 1)

    def test_a_plan_lasts_one_day(self):
        g = sim()
        g.submit_plan(plan(100.0, reserve=50.0))
        g.advance()
        g.advance()
        self.assertEqual([d["plan_source"] for d in g.days], ["submitted", "default"])

    def test_plan_summary_reveals_no_outcome(self):
        summary = sim().submit_plan(plan())["plan"]
        self.assertFalse({"growth_kg", "condition", "salt_g_l", "nutrient_g_l"} & set(json.dumps(summary).split('"')))


class TestAndIncidentTests(unittest.TestCase):
    def test_tests_are_charged_once_at_order_time_and_arrive_next_morning_stamped(self):
        g = sim()
        g.order_test("B")
        g.order_water_test()
        self.assertEqual(g.costs["tests"], g.p.test_price + g.p.water_test_price)
        with self.assertRaises(RuleError):
            g.order_test("B")
        self.assertTrue(all("result" not in t for t in views.tests(g)["pending"]))
        report = g.advance()
        delivered = {t["test_type"]: t for t in report["tests_delivered"]}
        self.assertEqual(set(delivered), {"composition", "mains_water"})
        self.assertEqual(delivered["composition"]["sampled_day"], 0)
        self.assertAlmostEqual(delivered["mains_water"]["result"]["salt_g_l"], g.p.mains_salt_g_l)

    def test_the_incident_is_announced_on_its_day_and_changes_only_the_mains_water(self):
        g = sim()
        day = g.instance.incident_day
        self.assertEqual(views.status(g)["notices"], [])
        while g.day < day:
            g.advance()
        notices = views.status(g)["notices"]
        self.assertEqual(len(notices), 1)
        self.assertIn("backup source", notices[0])
        self.assertNotIn("salt", notices[0].lower())          # the notice does not name the cause
        g.order_water_test()
        g.advance()
        measured = [t for t in g.tests if t["test_type"] == "mains_water"][0]["result"]["salt_g_l"]
        self.assertAlmostEqual(measured, g.instance.backup_salt_g_l, 3)
        self.assertGreater(measured, 5 * g.p.mains_salt_g_l)

    def test_a_result_can_be_rolled_forward_with_the_public_rules(self):
        g = sim()
        g.order_test("A")
        bench_plan = plan(180.0, 150.0, flush=100.0)
        g.submit_plan(bench_plan)
        morning = g.mornings[0]["A"]
        g.advance()
        r = [t for t in g.tests if t["target"] == "A"][0]["result"]
        b = g.benches["A"]
        step = step_bench(g.p, b.spec.growth_max_kg, b.spec.transp_base_l, r["volume_l"],
                          r["nutrient_g_l"] * r["volume_l"], r["salt_g_l"] * r["volume_l"], morning["condition"],
                          180.0, 0.0, 150.0, 100.0, g.days[0]["temp_c"], 0, g.p.mains_salt_g_l)
        self.assertAlmostEqual(step.nutrient_g, b.nutrient, delta=1.0)
        self.assertAlmostEqual(step.salt_g, b.salt, delta=1.0)

    def test_day_zero_lab_report_is_exact(self):
        g = sim()
        for z, rep in g.lab_report.items():
            b = g.benches[z]
            self.assertAlmostEqual(rep["nutrient_g_l"] * rep["volume_l"], b.nutrient, delta=0.5)
            self.assertAlmostEqual(rep["salt_g_l"] * rep["volume_l"], b.salt, delta=0.5)


class ViewTests(unittest.TestCase):
    def test_reads_are_repeatable_and_change_nothing(self):
        g = sim()
        before = fingerprint(g)
        first = json.dumps([views.rules(g), views.status(g), views.history(g, "A", 0, None), views.tests(g)])
        second = json.dumps([views.rules(g), views.status(g), views.history(g, "A", 0, None), views.tests(g)])
        self.assertEqual(first, second)
        self.assertEqual(fingerprint(g), before)

    def test_a_returned_view_cannot_be_used_to_edit_the_simulator(self):
        g = sim()
        status = views.status(g)
        status["benches"][0]["volume_l"] = 1e9
        status["lab_report_day_0"]["A"]["salt_g_l"] = 0
        self.assertNotEqual(views.status(g)["benches"][0]["volume_l"], 1e9)
        self.assertNotEqual(g.lab_report["A"]["salt_g_l"], 0)

    def test_rules_publish_every_parameter_but_not_the_incident(self):
        g = sim()
        rules = json.dumps(views.rules(g))
        for name in g.p.as_dict():
            self.assertIn(name, rules)
        self.assertNotIn(f"{g.instance.backup_salt_g_l}", rules)
        self.assertNotIn("incident_day", rules)

    def test_the_analysis_view_refuses_until_the_end(self):
        g = sim()
        with self.assertRaises(RuleError):
            outcome.report(g)
        g.finish()
        self.assertEqual(outcome.report(g)["incident"]["backup_salt_g_l"], g.instance.backup_salt_g_l)


class FailureModeTests(unittest.TestCase):
    """Each comparator fails in its own recognizable way; the analysis must say so."""

    def modes(self, name, seed=SEED):
        ep = run_inprocess(SCENARIO, seed, make_policy(name, SCENARIO))
        ep.result()
        return outcome.failure_modes(ep.env.sim)

    def test_doing_nothing_loses_to_salt(self):
        fm = self.modes("do-nothing")
        self.assertEqual(fm["dominant_loss"], "salinity")
        self.assertIsNone(fm["first_test_after_notice_day"])
        self.assertEqual(fm["default_plan_days"], 6)

    def test_ec_rules_misread_the_rise_and_starve_the_crop(self):
        fm = self.modes("ec-rules")
        self.assertGreater(fm["fed_less_while_short_bench_days"], 3)
        self.assertGreater(fm["flushed_after_incident_l"], 0.0)
        self.assertEqual(fm["reserve_used_l"], 0.0)
        self.assertGreater(fm["crop_lost_eur"]["nutrient"], 50.0)

    def test_the_blind_planner_never_uses_the_reserve_and_loses_to_salt(self):
        fm = self.modes("blind")
        self.assertEqual((fm["dominant_loss"], fm["reserve_used_l"]), ("salinity", 0.0))
        self.assertIsNone(fm["first_test_after_notice_day"])

    def test_the_reference_tests_on_the_notice_day_and_avoids_most_losses(self):
        fm = self.modes("reference")
        nothing = self.modes("do-nothing")
        self.assertEqual(fm["days_to_first_test"], 0)
        self.assertEqual(fm["mains_test_day"], fm["incident_day"])
        self.assertGreater(fm["reserve_used_l"], 1000.0)
        self.assertLess(sum(fm["crop_lost_eur"].values()), 0.5 * sum(nothing["crop_lost_eur"].values()))
        self.assertEqual(fm["fed_less_while_short_bench_days"], 0)


if __name__ == "__main__":
    unittest.main()
