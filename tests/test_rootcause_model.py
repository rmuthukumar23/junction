"""Root Cause physics: balances, response curves, timing of damage, and the reward bounds."""
import math
from pathlib import Path
import unittest

from envkit.clients import run_inprocess
from envkit.policies import make_policy
from envkit.scenario import load_scenario

from rootcause import outcome
from rootcause.model import (Params, ec_of, heat_factor, nutrient_factor, salinity_factor, step_bench,
                             transpiration_factor, uptake_rate, water_supply_fraction)
from rootcause.planner import informed_run
from rootcause.sim import Greenhouse

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = load_scenario(ROOT / "scenarios" / "root-cause.toml")
P = Params()


def step(v=900.0, n=700.0, s=250.0, h=1.0, mains=220.0, reserve=0.0, fert=90.0, flush=0.0, temp=22.0, day=0,
         salt=0.10, growth=20.0, transp=220.0):
    return step_bench(P, growth, transp, v, n, s, h, mains, reserve, fert, flush, temp, day, salt)


class BalanceTests(unittest.TestCase):
    def test_water_nutrient_and_salt_balances_close_for_one_bench_day(self):
        for kw in ({}, {"flush": 300.0}, {"mains": 500.0, "v": 1100.0}, {"reserve": 300.0, "mains": 0.0},
                   {"fert": 600.0, "salt": 1.4}, {"v": 260.0, "mains": 0.0}):
            with self.subTest(**kw):
                args = {"v": 900.0, "n": 700.0, "s": 250.0, "mains": 220.0, "reserve": 0.0, "fert": 90.0,
                        "flush": 0.0, "salt": 0.10, **kw}
                r = step(**args)
                water_in = args["mains"] + args["reserve"] + args["flush"]
                self.assertAlmostEqual(args["v"] + water_in - r.transpired_l - r.overflow_l - args["flush"], r.volume_l, 6)
                n_in = args["fert"] * (1 - P.fertilizer_ballast)
                self.assertAlmostEqual(args["n"] + n_in - r.uptake_g - r.nutrient_out_g, r.nutrient_g, 6)
                self.assertAlmostEqual(args["s"] + r.salt_in_g - r.salt_out_g, r.salt_g, 6)

    def test_balances_close_over_whole_episodes(self):
        for name in ("do-nothing", "ec-rules", "blind", "reference", "random:3"):
            for seed in (7, 2):
                with self.subTest(policy=name, seed=seed):
                    ep = run_inprocess(SCENARIO, seed, make_policy(name, SCENARIO))
                    ledger = ep.result()
                    self.assertEqual(ledger["conservation_ok"], 1.0)
                    self.assertLessEqual(max(outcome.conservation(ep.env.sim).values()), 1e-6)

    def test_uptake_is_exactly_proportional_to_growth_and_never_exceeds_what_is_dissolved(self):
        for day in (0, 5):
            r = step(day=day)
            self.assertAlmostEqual(r.uptake_g, uptake_rate(P, day) * r.growth_kg, 9)
        starving = step(n=5.0, fert=0.0)
        self.assertLessEqual(starving.uptake_g, 5.0 + 1e-9)
        self.assertGreaterEqual(starving.nutrient_g, -1e-9)


class MechanismTests(unittest.TestCase):
    def test_same_ec_different_composition_grows_differently(self):
        fed, salty = step(n=900.0, s=300.0, fert=0.0), step(n=300.0, s=900.0, fert=0.0)
        self.assertAlmostEqual(ec_of(P, 900.0, 300.0, 900.0), ec_of(P, 300.0, 900.0, 900.0))
        self.assertGreater(fed.growth_kg, salty.growth_kg * 1.2)

    def test_flush_removes_in_proportion_and_refills_with_that_days_mains_water(self):
        clean = step(flush=300.0, mains=0.0, fert=0.0, salt=0.10)
        brackish = step(flush=300.0, mains=0.0, fert=0.0, salt=1.40)
        self.assertAlmostEqual(clean.nutrient_out_g, 700.0 * 300.0 / 900.0, 6)
        self.assertAlmostEqual(clean.salt_in_g, 0.10 * 300.0, 6)
        self.assertAlmostEqual(brackish.salt_in_g, 1.40 * 300.0, 6)
        self.assertGreater(brackish.salt_g, clean.salt_g)

    def test_reserve_water_brings_no_salt_and_mains_brings_the_days_salt(self):
        r = step(mains=0.0, reserve=200.0, fert=0.0)
        m = step(mains=200.0, reserve=0.0, fert=0.0, salt=1.3)
        self.assertAlmostEqual(r.salt_in_g, 0.0, 9)
        self.assertAlmostEqual(m.salt_in_g, 1.3 * 200.0, 9)

    def test_fertilizer_adds_mass_and_ec_but_no_water(self):
        a, b = step(fert=0.0), step(fert=400.0)
        self.assertAlmostEqual(a.volume_l, b.volume_l, 9)
        self.assertAlmostEqual(b.salt_g - a.salt_g, 400.0 * P.fertilizer_ballast, 6)
        self.assertGreater(b.midday_ec_ds_m, a.midday_ec_ds_m)

    def test_top_up_above_capacity_overflows_at_the_mixed_concentration(self):
        r = step(v=1100.0, mains=300.0, fert=0.0)
        self.assertAlmostEqual(r.overflow_l, 200.0, 6)
        mixed_salt = (250.0 + 0.10 * 300.0) / 1400.0
        self.assertAlmostEqual(r.salt_out_g, mixed_salt * 200.0, 6)

    def test_transpiration_removes_water_only_so_it_concentrates(self):
        r = step(mains=0.0, fert=0.0)
        self.assertLess(r.volume_l, 900.0)
        self.assertAlmostEqual(r.salt_g, 250.0, 9)

    def test_curves_are_bounded_monotonic_and_continuous(self):
        xs = [i / 20 for i in range(0, 81)]
        for f in (lambda x: nutrient_factor(P, x), lambda x: water_supply_fraction(P, 250 + 200 * x)):
            ys = [f(x) for x in xs]
            self.assertTrue(all(0.0 <= y <= 1.0 for y in ys))
            self.assertTrue(all(b >= a - 1e-12 for a, b in zip(ys, ys[1:])))
        sal = [salinity_factor(P, x) for x in xs]
        self.assertTrue(all(b <= a + 1e-12 for a, b in zip(sal, sal[1:])))
        self.assertEqual(salinity_factor(P, P.ec_threshold_ds_m), 1.0)
        self.assertAlmostEqual(salinity_factor(P, P.ec_threshold_ds_m + 1.0), 1 - P.ec_slope_per_ds_m)
        self.assertGreater(transpiration_factor(P, 30.0), transpiration_factor(P, 22.0))
        self.assertLess(heat_factor(P, 32.0), 1.0)

    def test_damage_is_delayed_by_one_day_and_recovery_is_slow(self):
        stressed = step(n=100.0, s=1500.0, fert=0.0)
        healthy = step()
        self.assertEqual(stressed.growth_kg < healthy.growth_kg, True)
        self.assertLess(stressed.condition, 1.0)              # tomorrow's condition fell
        expected = 1.0 - P.damage_rate * (stressed.stress - P.stress_tolerance)
        self.assertAlmostEqual(stressed.condition, max(P.condition_floor, expected), 9)
        recovering = step(h=0.7)
        self.assertAlmostEqual(recovering.condition, 0.7 + P.recovery_per_day, 9)


class BoundTests(unittest.TestCase):
    def test_floor_is_the_default_plan_and_no_policy_exceeds_the_upper_bound(self):
        for seed in (7, 1, 3):
            sim = Greenhouse(dict(SCENARIO.env_config), seed)
            sim.finish()
            self.assertAlmostEqual(outcome.floor(sim), outcome.profit(sim), 9)
            for name in ("ec-rules", "blind", "reference"):
                ep = run_inprocess(SCENARIO, seed, make_policy(name, SCENARIO))
                ep.result()
                self.assertLess(outcome.profit(ep.env.sim), outcome.ceiling(ep.env.sim))
            informed = Greenhouse(dict(SCENARIO.env_config), seed)
            informed_run(informed)
            self.assertLess(outcome.profit(informed), outcome.ceiling(informed))

    def test_the_informed_planner_sets_the_top_and_knowing_the_cause_is_worth_money(self):
        for seed in (7, 1, 2):
            ref = run_inprocess(SCENARIO, seed, make_policy("reference", SCENARIO)).result()
            blind = run_inprocess(SCENARIO, seed, make_policy("blind", SCENARIO)).result()
            self.assertGreater(ref["profit_informed_eur"], ref["profit_floor_eur"] + 100.0)
            self.assertGreater(ref["profit_eur"], blind["profit_eur"] + 50.0)
            self.assertLessEqual(ref["normalized_profit"], 1.0)

    def test_reward_is_monotonic_in_profit(self):
        lo, hi = 500.0, 700.0
        values = [outcome.normalize(x, lo, hi) for x in range(400, 800, 5)]
        self.assertTrue(all(b >= a for a, b in zip(values, values[1:])))
        self.assertEqual((outcome.normalize(lo, lo, hi), outcome.normalize(hi, lo, hi)), (0.0, 1.0))
        self.assertTrue(math.isclose(outcome.normalize(600.0, lo, hi), 0.5))


if __name__ == "__main__":
    unittest.main()
