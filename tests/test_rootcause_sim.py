"""Root Cause simulator: determinism, atomic plans, shared budgets, tests, reads, bounds of the episode."""
import copy
import json
import unittest

from rootcause import outcome, views
from rootcause.generator import generate
from rootcause.sim import Greenhouse, RuleError

ZONES = "ABCD"


def plan(irrigation=230.0, fertilizer=120.0, flush=0.0, **overrides):
    out = {z: {"irrigation_l": irrigation, "fertilizer_g": fertilizer, "flush_l": flush} for z in ZONES}
    for zone, values in overrides.items():
        out[zone].update(values)
    return out


def fingerprint(sim):
    """Everything that defines the state of a run, as comparable JSON."""
    return json.dumps({
        "day": sim.day, "fresh": sim.fresh_water_l, "plan": sim.plan, "costs": sim.costs, "used": sim.used,
        "tests": sim.tests, "events": sim.events, "days": sim.days, "mornings": sim.mornings,
        "zones": {z: [zone.volume, zone.nutrient, zone.salt, zone.condition, zone.harvest]
                  for z, zone in sim.zones.items()},
        "plans_submitted": sim.plans_submitted,
    }, sort_keys=True)


def play(seed, script):
    """script: one entry per day, each a list of ('plan', {...}) / ('test', zone) requests."""
    sim = Greenhouse({}, seed)
    for requests in script:
        for kind, arg in requests:
            if kind == "plan":
                sim.submit_plan(arg)
            else:
                sim.order_test(arg, "composition")
        sim.advance()
    sim.finish()
    return sim


class DeterminismTests(unittest.TestCase):
    SCRIPT = [[("test", "A"), ("test", "C"), ("plan", plan(B={"fertilizer_g": 0.0}))],
              [("plan", plan(300, 200, C={"flush_l": 400.0}))],
              [], [("plan", plan(150, 0))], [("test", "B")]]

    def test_same_seed_and_actions_give_the_same_outcome(self):
        a, b = play(7, self.SCRIPT), play(7, self.SCRIPT)
        self.assertEqual(fingerprint(a), fingerprint(b))
        self.assertEqual(outcome.ledger(a), outcome.ledger(b))
        self.assertEqual(outcome.report(a), outcome.report(b))

    def test_different_seeds_differ(self):
        self.assertNotEqual(outcome.ledger(play(7, self.SCRIPT))["profit_eur"],
                            outcome.ledger(play(8, self.SCRIPT))["profit_eur"])

    def test_weather_forecasts_and_sensor_noise_do_not_depend_on_what_the_player_does(self):
        idle, busy = Greenhouse({}, 7), Greenhouse({}, 7)
        for _ in range(25):                       # extra reads and tests must not shift any random stream
            views.status(busy), views.forecast(busy), views.history(busy, "A", 0, None)
        busy.order_test("A", "composition")
        busy.submit_plan(plan(300, 900, flush=100))
        self.assertEqual(idle.instance, busy.instance)
        for _ in range(14):
            self.assertEqual(views.forecast(idle), views.forecast(busy))
            idle.advance(), busy.advance()
        self.assertEqual([d["temp_c"] for d in idle.days], [d["temp_c"] for d in busy.days])
        self.assertEqual(generate({}, 7), generate({}, 7))

    def test_forecasts_never_contain_the_realized_future(self):
        sim = Greenhouse({}, 7)
        issued = [d["temp_c"] for d in views.forecast(sim)["days"]]
        self.assertEqual(len(issued), sim.p.forecast_days)
        self.assertNotEqual(issued, list(sim.instance.temps[:len(issued)]))
        self.assertNotIn("temp_c", views.history(sim, "A", 0, None)["days"][0])   # day 0 has not happened yet
        sim.advance()
        self.assertEqual(views.history(sim, "A", 0, None)["days"][0]["temp_c"], sim.instance.temps[0])


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.sim = Greenhouse({}, 7)

    def rejected(self, zone_plans):
        before = fingerprint(self.sim)
        with self.assertRaises(RuleError) as caught:
            self.sim.submit_plan(zone_plans)
        self.assertEqual(fingerprint(self.sim), before, "a rejected plan must change nothing")
        return str(caught.exception)

    def test_malformed_plans_are_rejected_without_any_change(self):
        cases = {
            "not an object": [1, 2, 3],
            "missing zone": {z: plan()[z] for z in "ABC"},
            "unknown zone": {**plan(), "E": plan()["A"]},
            "missing field": plan(A={}) | {"A": {"irrigation_l": 1.0}},
            "unknown field": plan(A={"water": 5.0}),
            "negative": plan(A={"irrigation_l": -1.0}),
            "nan": plan(A={"fertilizer_g": float("nan")}),
            "infinity": plan(A={"flush_l": float("inf")}),
            "string": plan(A={"irrigation_l": "lots"}),
            "boolean": plan(A={"irrigation_l": True}),
            "zone not an object": {**plan(), "A": 220},
            "too much irrigation": plan(A={"irrigation_l": self.sim.p.irrigation_max_l + 1}),
            "too much fertilizer": plan(A={"fertilizer_g": self.sim.p.fertilizer_max_g + 1}),
            "flush beyond pumpable": plan(A={"flush_l": self.sim.pumpable_l("A") + 1}),
        }
        for name, bad in cases.items():
            with self.subTest(name):
                self.assertIn("nothing was changed", self.rejected(bad))

    def test_error_names_every_problem_so_it_can_be_fixed_in_one_go(self):
        message = self.rejected({"A": {"irrigation_l": -5.0, "fertilizer_g": 10.0, "flush_l": 0.0}, "Z": {}})
        for expected in ("unknown zone(s) ['Z']", "missing zone(s) ['B', 'C', 'D']", "zone A: irrigation_l must not be negative"):
            self.assertIn(expected, message)

    def test_plan_over_the_daily_cap_is_rejected_whole(self):
        cap = self.sim.p.daily_fresh_water_cap_l
        message = self.rejected(plan(irrigation=cap / 4 + 1))
        self.assertIn(f"only {cap:.1f} L can be delivered", message)
        self.assertIn("Reduce irrigation or flush by at least 4.0 L", message)
        self.sim.submit_plan(plan(irrigation=cap / 4))            # exactly at the cap is fine
        self.assertEqual(self.sim.plan["A"]["irrigation_l"], cap / 4)

    def test_flush_counts_against_the_same_shared_water(self):
        cap = self.sim.p.daily_fresh_water_cap_l
        self.rejected(plan(irrigation=cap / 4, A={"flush_l": 0.5}))
        self.assertTrue(self.sim.submit_plan(plan(irrigation=cap / 4 - 100, A={"flush_l": 400.0}))["accepted"])

    def test_plan_cannot_draw_more_than_the_allocation_left(self):
        self.sim.fresh_water_l = 500.0
        message = self.rejected(plan(irrigation=200))
        self.assertIn("500.0 L left in the allocation", message)
        self.sim.submit_plan(plan(irrigation=125))
        self.sim.advance()
        self.assertAlmostEqual(self.sim.fresh_water_l, 0.0)
        self.rejected(plan(irrigation=0.1))                        # nothing left: water is never created
        self.sim.submit_plan(plan(irrigation=0, fertilizer=50))

    def test_no_zone_is_favored_when_the_default_plan_cannot_be_supplied(self):
        self.sim.fresh_water_l = 460.0                             # half of what four default irrigations need
        applied, source = self.sim.effective_plan()
        self.assertEqual(source, "default_scaled")
        self.assertEqual({round(zp["irrigation_l"], 6) for zp in applied.values()}, {115.0})
        self.sim.advance()
        self.assertAlmostEqual(self.sim.fresh_water_l, 0.0)
        self.assertEqual(self.sim.days[0]["plan_source"], "default_scaled")

    def test_resubmitting_replaces_the_plan_and_nothing_is_charged_until_the_day_runs(self):
        self.sim.submit_plan(plan(100, 50))
        summary = self.sim.submit_plan(plan(200, 200, A={"flush_l": 100.0}))["plan"]
        self.assertEqual(self.sim.plans_submitted, 1)
        self.assertEqual((sum(self.sim.costs.values()), self.sim.fresh_water_l), (0.0, self.sim.instance.fresh_water_l))
        self.assertEqual(summary["fresh_water_l"], 900.0)
        self.assertEqual(summary["immediate_cost"], {"water_eur": 18.0, "fertilizer_eur": 16.0, "discharge_eur": 1.0,
                                                     "total_eur": 35.0})
        self.sim.advance()
        self.assertAlmostEqual(self.sim.costs["water"], 18.0)
        self.assertAlmostEqual(self.sim.costs["fertilizer"], 16.0)
        self.assertAlmostEqual(self.sim.costs["discharge"], 1.0)
        self.assertEqual(self.sim.days[0]["zones"]["A"]["plan"], {"irrigation_l": 200.0, "fertilizer_g": 200.0, "flush_l": 100.0})

    def test_a_plan_lasts_one_day(self):
        self.sim.submit_plan(plan(300, 0))
        self.sim.advance()
        self.sim.advance()
        self.assertEqual([d["plan_source"] for d in self.sim.days], ["submitted", "default"])
        self.assertEqual(self.sim.days[1]["zones"]["A"]["plan"], self.sim.default_plan()["A"])

    def test_plan_summary_reveals_no_outcome(self):
        text = json.dumps(self.sim.submit_plan(plan())["plan"])
        for hidden in ("growth", "harvest", "nutrient_g_l", "salt", "stress", "profit", "temp"):
            self.assertNotIn(hidden, text)


class LabTests(unittest.TestCase):
    def setUp(self):
        self.sim = Greenhouse({}, 7)

    def test_cost_is_charged_once_at_order_time(self):
        price = self.sim.p.test_price
        self.sim.order_test("B", "composition")
        self.assertEqual(self.sim.costs["tests"], price)
        for _ in range(3):
            self.sim.advance()
        self.assertEqual(self.sim.costs["tests"], price)
        self.assertEqual(outcome.ledger(play(7, [[("test", "B")]]))["cost_tests_eur"], price)

    def test_duplicate_request_the_same_day_is_refused_and_free(self):
        self.sim.order_test("B", "composition")
        before = fingerprint(self.sim)
        with self.assertRaises(RuleError) as caught:
            self.sim.order_test("B", "composition")
        self.assertIn("Nothing was charged", str(caught.exception))
        self.assertEqual(fingerprint(self.sim), before)
        self.sim.order_test("C", "composition")                    # another zone is a different sample
        self.sim.advance()
        self.sim.order_test("B", "composition")                    # so is the same zone on another day
        self.assertEqual(self.sim.costs["tests"], 3 * self.sim.p.test_price)

    def test_invalid_requests_change_and_charge_nothing(self):
        before = fingerprint(self.sim)
        for zone, kind in (("E", "composition"), ("A", "dna"), (None, "composition"), ("A", None), (7, 7)):
            with self.assertRaises(RuleError):
                self.sim.order_test(zone, kind)
        self.assertEqual(fingerprint(self.sim), before)

    def test_result_arrives_after_one_day_and_describes_the_sample_time(self):
        truth = self.sim.truth[0]["C"]
        ordered = self.sim.order_test("C", "composition")
        self.assertEqual((ordered["sampled_day"], ordered["delivery_day"], ordered["status"]), (0, 1, "pending"))
        self.assertNotIn("result", ordered)
        self.assertNotIn("result", views.tests(self.sim)["pending"][0])
        self.assertNotIn("nutrient_g_l", json.dumps(views.status(self.sim)))

        self.sim.submit_plan(plan(C={"flush_l": 500.0, "fertilizer_g": 900.0}))   # change the zone after sampling
        report = self.sim.advance()
        (delivered,) = report["tests_delivered"]
        self.assertEqual((delivered["sampled_day"], delivered["delivery_day"], delivered["status"]), (0, 1, "delivered"))
        self.assertIn("before that day's plan", delivered["sample_time"])
        result = delivered["result"]
        self.assertAlmostEqual(result["nutrient_g_l"], truth["nutrient_g_l"], places=3)
        self.assertAlmostEqual(result["salt_g_l"], truth["salt_g_l"], places=3)
        self.assertEqual(result["volume_l"], self.sim.mornings[0]["C"]["volume_l"])
        now = self.sim.truth[1]["C"]
        self.assertGreater(abs(now["salt_g_l"] - result["salt_g_l"]), 0.3, "the zone has moved on since the sample")
        self.assertEqual(views.status(self.sim)["zones"][2]["latest_test"]["sampled_day"], 0)

    def test_a_result_can_be_rolled_forward_with_the_public_rules(self):
        """The sample plus the published daily update reproduce today's hidden state."""
        from rootcause.model import step_zone
        sim = self.sim
        sim.order_test("C", "composition")
        sim.submit_plan(plan(C={"flush_l": 400.0, "fertilizer_g": 700.0, "irrigation_l": 150.0}))
        report = sim.advance()
        result = report["tests_delivered"][0]["result"]
        spec = next(z for z in sim.instance.zones if z.id == "C")
        rolled = step_zone(sim.p, spec.growth_max_kg, spec.transp_base_l, result["volume_l"],
                           result["nutrient_g_l"] * result["volume_l"], result["salt_g_l"] * result["volume_l"],
                           sim.mornings[0]["C"]["condition"], 150.0, 700.0, 400.0, report["temp_c"])
        self.assertAlmostEqual(rolled.nutrient_g, sim.zones["C"].nutrient, delta=1.5)
        self.assertAlmostEqual(rolled.salt_g, sim.zones["C"].salt, delta=1.5)

    def test_late_tests_stay_charged_and_are_delivered_at_the_end(self):
        sim = self.sim
        for _ in range(13):
            sim.advance()
        sim.order_test("A", "composition")
        sim.finish()
        self.assertTrue(sim.tests[0]["delivered"])
        self.assertEqual(outcome.ledger(sim)["cost_tests_eur"], sim.p.test_price)


class ReadTests(unittest.TestCase):
    def test_reads_are_repeatable_and_change_nothing(self):
        sim = Greenhouse({}, 7)
        sim.order_test("A", "composition")
        sim.submit_plan(plan())
        sim.advance()
        before = fingerprint(sim)
        reads = [lambda: views.status(sim), lambda: views.rules(sim), lambda: views.forecast(sim),
                 lambda: views.tests(sim), lambda: views.events(sim, 0), lambda: views.history(sim, "A", 0, None),
                 lambda: sim.plan_summary(*sim.effective_plan()), lambda: outcome.ledger(sim)]
        for read in reads:
            first = copy.deepcopy(read())
            for _ in range(5):
                self.assertEqual(read(), first)
        self.assertEqual(fingerprint(sim), before)

    def test_a_returned_view_cannot_be_used_to_edit_the_simulator(self):
        sim = Greenhouse({}, 7)
        status = views.status(sim)
        status["fresh_water"]["left_l"] = 10 ** 9
        status["zones"][0]["volume_l"] = 0
        views.rules(sim)["parameters"]["price_per_kg"] = 10 ** 6
        sim.default_plan()["A"]["irrigation_l"] = 0
        self.assertEqual(views.status(sim)["fresh_water"]["left_l"], sim.instance.fresh_water_l)
        self.assertEqual(sim.p.price_per_kg, 2.0)
        self.assertEqual(sim.default_plan()["A"]["irrigation_l"], sim.p.default_irrigation_l)

    def test_live_views_never_expose_hidden_state(self):
        sim = Greenhouse({}, 7)
        sim.advance()
        future = [t for t in sim.instance.temps[sim.day:]]
        text = json.dumps([views.status(sim), views.rules(sim), views.forecast(sim), views.tests(sim),
                           views.events(sim, 0), views.history(sim, "C", 0, None)])
        for hidden in ("salty_hungry", "starting_composition", "hidden_morning", "\"factors\"", "realized_temps",
                       "midday_ec", "\"nutrient_g_l\"", "\"salt_g_l\""):
            self.assertNotIn(hidden, text)
        self.assertNotIn(json.dumps(future)[1:-1], text)
        with self.assertRaises(RuleError):
            outcome.report(sim)                                     # the analysis view opens only at the end
        sim.finish()
        self.assertIn("starting_composition_type", json.dumps(outcome.report(sim)))


class EpisodeBoundTests(unittest.TestCase):
    def test_exactly_fourteen_days_then_everything_is_refused(self):
        sim = Greenhouse({}, 7)
        for expected in range(14):
            self.assertEqual(sim.day, expected)
            sim.advance()
        self.assertTrue(sim.done)
        before = fingerprint(sim)
        for request in (sim.advance, lambda: sim.submit_plan(plan()), lambda: sim.order_test("A", "composition")):
            with self.assertRaises(RuleError):
                request()
        sim.finish()                                                # harmless once over
        self.assertEqual(fingerprint(sim).replace('"finished"', ""), before.replace('"finished"', ""))
        self.assertEqual(len(sim.days), 14)

    def test_doing_nothing_runs_the_default_plan_to_the_last_day(self):
        sim = Greenhouse({}, 7)
        sim.finish()
        self.assertEqual((sim.day, len(sim.days)), (14, 14))
        self.assertTrue(all(d["plan_source"].startswith("default") for d in sim.days))
        ledger = outcome.ledger(sim)
        self.assertEqual((ledger["profit_eur"], ledger["normalized_profit"]), (ledger["profit_floor_eur"], 0.0))

    def test_stopping_early_is_scored_at_the_same_final_day_as_playing_on(self):
        script = [[("plan", plan(250, 300, C={"flush_l": 500.0}))], [("plan", plan(250, 200))]]
        stopped = Greenhouse({}, 7)
        for requests in script:
            stopped.submit_plan(requests[0][1])
            stopped.advance()
        frozen = outcome.profit(stopped)                            # what stopping would freeze, if it could
        stopped.finish()

        walked = Greenhouse({}, 7)
        for requests in script:
            walked.submit_plan(requests[0][1])
            walked.advance()
        while not walked.done:
            walked.advance()                                        # same thing, one explicit day at a time
        self.assertEqual(outcome.ledger(stopped), outcome.ledger(walked))
        self.assertEqual(stopped.day, 14)
        self.assertNotEqual(round(frozen, 2), outcome.ledger(stopped)["profit_eur"])
        self.assertEqual([d["plan_source"] for d in stopped.days], ["submitted"] * 2 + ["default"] * 12)

    def test_a_plan_submitted_before_stopping_still_runs_for_its_day(self):
        sim = Greenhouse({}, 7)
        sim.submit_plan(plan(400, 0))
        sim.finish()
        self.assertEqual([d["plan_source"] for d in sim.days][:2], ["submitted", "default"])

    def test_unused_inventory_is_worth_nothing(self):
        thrifty, lavish = Greenhouse({}, 7), Greenhouse({}, 7)
        thrifty.finish()
        self.assertGreater(thrifty.fresh_water_l, 0)
        ledger = outcome.ledger(thrifty)
        # Each figure is rounded to the cent on its own, so the identity holds to within a cent.
        self.assertAlmostEqual(ledger["profit_eur"], ledger["revenue_eur"] - ledger["cost_total_eur"], delta=0.011)
        self.assertAlmostEqual(ledger["revenue_eur"], 2.0 * ledger["harvest_kg"], places=1)
        del lavish

    def test_two_runs_do_not_share_state(self):
        a, b = Greenhouse({}, 7), Greenhouse({}, 7)
        a.order_test("A", "composition")
        a.submit_plan(plan(400, 1000))
        a.advance()
        self.assertEqual(fingerprint(b), fingerprint(Greenhouse({}, 7)))
        b.finish()
        self.assertEqual(outcome.ledger(b)["normalized_profit"], 0.0)


if __name__ == "__main__":
    unittest.main()
