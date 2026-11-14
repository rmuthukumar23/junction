"""Root Cause physics: balances, EC ambiguity, flushing, fertilizer, damage and recovery."""
import unittest

from rootcause import outcome
from rootcause.model import (Params, best_condition, concentration, ec_of, heat_factor, nutrient_factor,
                             salinity_factor, step_zone, transpiration_factor, water_supply_fraction)
from rootcause.sim import Greenhouse

P = Params()
GROWTH, TRANSP = 30.0, 210.0


def step(volume=1100.0, nutrient=1320.0, salt=880.0, condition=1.0, irrigation=0.0, fertilizer=0.0, flush=0.0,
         temp=24.0, p=P):
    return step_zone(p, GROWTH, TRANSP, volume, nutrient, salt, condition, irrigation, fertilizer, flush, temp)


class BalanceTests(unittest.TestCase):
    def test_water_nutrient_and_salt_balances_close_for_one_zone_day(self):
        for kwargs in (dict(), dict(irrigation=250, fertilizer=300), dict(flush=400, irrigation=100),
                       dict(volume=1450, irrigation=400), dict(volume=320, temp=36), dict(flush=800, fertilizer=900)):
            before = dict(volume=1100.0, nutrient=1320.0, salt=880.0)
            before.update({k: v for k, v in kwargs.items() if k in before})
            r = step(**kwargs)
            irrigation, fertilizer, flush = (kwargs.get(k, 0.0) for k in ("irrigation", "fertilizer", "flush"))
            # Water: flush water in equals flush water out, so only irrigation, transpiration and overflow change volume.
            self.assertAlmostEqual(r.volume_l, before["volume"] + irrigation - r.transpired_l - r.overflow_l, places=9)
            self.assertAlmostEqual(r.nutrient_g, before["nutrient"] + fertilizer * (1 - P.fertilizer_ballast)
                                   - r.uptake_g - r.nutrient_out_g, places=9)
            self.assertAlmostEqual(r.salt_g, before["salt"] + r.salt_in_g - r.salt_out_g, places=9)
            self.assertAlmostEqual(r.salt_in_g, P.source_salt_g_l * (irrigation + flush) + fertilizer * P.fertilizer_ballast,
                                   places=9)
            self.assertGreaterEqual(min(r.volume_l - P.dead_volume_l, r.nutrient_g, r.salt_g), -1e-9)

    def test_balances_close_over_whole_episodes(self):
        plans = [None,
                 {z: {"irrigation_l": 300, "fertilizer_g": 200, "flush_l": 100} for z in "ABCD"},
                 {z: {"irrigation_l": 0, "fertilizer_g": 0, "flush_l": 0} for z in "ABCD"}]
        for seed in (1, 7, 42):
            for plan in plans:
                sim = Greenhouse({}, seed)
                while not sim.done:
                    if plan is not None:
                        try:
                            sim.submit_plan(plan)
                        except Exception:
                            pass   # an unaffordable day falls back to the default plan
                    sim.advance()
                worst = outcome.conservation(sim)
                self.assertLess(max(worst.values()), 1e-6, (seed, plan, worst))
                self.assertGreaterEqual(sim.fresh_water_l, -1e-9)
                self.assertEqual(outcome.ledger(sim)["conservation_ok"], 1.0)

    def test_uptake_is_exactly_proportional_to_growth_and_never_exceeds_what_is_dissolved(self):
        r = step()
        self.assertAlmostEqual(r.uptake_g, P.uptake_g_per_kg * r.growth_kg)
        starved = step(nutrient=20.0, salt=1500.0)
        self.assertLessEqual(starved.uptake_g, 20.0 + 1e-9)
        self.assertGreaterEqual(starved.nutrient_g, -1e-9)
        self.assertAlmostEqual(starved.uptake_g, P.uptake_g_per_kg * starved.growth_kg)


class ChemistryTests(unittest.TestCase):
    def test_same_ec_different_composition_grows_differently(self):
        """EC cannot tell a nutrient-rich zone from a salty, starving one."""
        volume = 1100.0
        rich = dict(nutrient=2.0 * volume, salt=0.4 * volume)
        salty = dict(nutrient=0.5 * volume, salt=1.9 * volume)
        self.assertAlmostEqual(ec_of(P, rich["nutrient"], rich["salt"], volume),
                               ec_of(P, salty["nutrient"], salty["salt"], volume), places=9)
        a, b = step(volume=volume, irrigation=220, **rich), step(volume=volume, irrigation=220, **salty)
        self.assertAlmostEqual(a.salinity_factor, b.salinity_factor, places=2)   # same EC, same salinity stress
        self.assertGreater(a.nutrient_factor, 0.99)
        self.assertLess(b.nutrient_factor, 0.75)
        self.assertGreater(a.growth_kg, 1.3 * b.growth_kg)
        # The same treatment has opposite effects: fertilizer helps the salty zone and hurts the rich one.
        self.assertGreater(step(volume=volume, irrigation=220, fertilizer=600, **salty).growth_kg, b.growth_kg)
        self.assertLess(step(volume=volume, irrigation=220, fertilizer=600, **rich).growth_kg, a.growth_kg)

    def test_flush_removes_dissolved_material_in_proportion_and_uses_exactly_that_water(self):
        volume, nutrient, salt = 1000.0, 1200.0, 1800.0
        r = step(volume=volume, nutrient=nutrient, salt=salt, flush=400.0, condition=0.0, p=Params(canopy_floor=0.0))
        # With no transpiration or growth, only the flush acts.
        self.assertEqual((r.transpired_l, r.growth_kg, r.overflow_l), (0.0, 0.0, 0.0))
        self.assertAlmostEqual(r.volume_l, volume)                       # bled volume is replaced
        self.assertAlmostEqual(r.nutrient_out_g, nutrient * 0.4)
        self.assertAlmostEqual(r.salt_out_g, salt * 0.4)
        self.assertAlmostEqual(r.nutrient_g, nutrient * 0.6)
        self.assertAlmostEqual(r.salt_g, salt * 0.6 + P.source_salt_g_l * 400.0)   # fresh water is not pure
        self.assertAlmostEqual(r.salt_in_g, P.source_salt_g_l * 400.0)
        self.assertLess(ec_of(P, r.nutrient_g, r.salt_g, r.volume_l), ec_of(P, nutrient, salt, volume))

    def test_fresh_water_drawn_by_a_flush_is_charged_to_the_shared_allocation(self):
        sim = Greenhouse({}, 7)
        before = sim.fresh_water_l
        sim.submit_plan({z: {"irrigation_l": 0, "fertilizer_g": 0, "flush_l": 250 if z == "A" else 0} for z in "ABCD"})
        sim.advance()
        self.assertAlmostEqual(before - sim.fresh_water_l, 250.0)
        self.assertAlmostEqual(sim.costs["water"], 250.0 * P.water_price_per_l)
        self.assertAlmostEqual(sim.costs["discharge"], 250.0 * P.discharge_price_per_l)

    def test_fertilizer_adds_mass_and_ec_but_no_water(self):
        base, fed = step(condition=0.0, p=Params(canopy_floor=0.0)), step(fertilizer=500.0, condition=0.0,
                                                                         p=Params(canopy_floor=0.0))
        self.assertAlmostEqual(fed.volume_l, base.volume_l)
        self.assertAlmostEqual(fed.nutrient_g - base.nutrient_g, 500.0 * (1 - P.fertilizer_ballast))
        self.assertAlmostEqual(fed.salt_g - base.salt_g, 500.0 * P.fertilizer_ballast)
        self.assertAlmostEqual(ec_of(P, fed.nutrient_g, fed.salt_g, fed.volume_l)
                               - ec_of(P, base.nutrient_g, base.salt_g, base.volume_l),
                               P.ec_per_g_l * 500.0 / base.volume_l)

    def test_irrigation_above_capacity_overflows_at_the_mixed_concentration(self):
        r = step(volume=1400.0, nutrient=1400.0, salt=700.0, irrigation=300.0, condition=0.0, p=Params(canopy_floor=0.0))
        self.assertAlmostEqual(r.overflow_l, 200.0)
        self.assertAlmostEqual(r.volume_l, P.capacity_l)
        mixed_salt = 700.0 + P.source_salt_g_l * 300.0
        self.assertAlmostEqual(r.nutrient_out_g, 1400.0 * 200.0 / 1700.0)
        self.assertAlmostEqual(r.salt_out_g, mixed_salt * 200.0 / 1700.0)

    def test_transpiration_removes_water_only_so_it_concentrates(self):
        r = step(salt=2000.0, nutrient=0.0)   # no nutrient: no growth, no uptake
        self.assertGreater(r.transpired_l, 0)
        self.assertEqual(r.salt_g, 2000.0)
        self.assertGreater(concentration(r.salt_g, r.volume_l), concentration(2000.0, 1100.0))

    def test_empty_volume_has_a_defined_concentration(self):
        self.assertEqual(concentration(5.0, 0.0), 0.0)
        self.assertEqual(ec_of(P, 5.0, 5.0, 0.0), 0.0)
        r = step(volume=P.dead_volume_l, nutrient=300.0, salt=300.0)   # nothing available to transpire
        self.assertEqual(r.transpired_l, 0.0)
        self.assertEqual(r.growth_kg, 0.0)
        self.assertAlmostEqual(r.volume_l, P.dead_volume_l)


class ResponseTests(unittest.TestCase):
    def test_curves_are_bounded_monotonic_and_continuous(self):
        for fn, xs, increasing in ((lambda x: nutrient_factor(P, x), [i / 50 for i in range(0, 150)], True),
                                   (lambda x: salinity_factor(P, x), [i / 10 for i in range(0, 200)], False),
                                   (lambda x: heat_factor(P, x), [10 + i / 5 for i in range(0, 200)], False),
                                   (lambda x: water_supply_fraction(P, x), [float(i * 10) for i in range(0, 200)], True),
                                   (lambda x: transpiration_factor(P, x), [10 + i / 5 for i in range(0, 200)], True)):
            ys = [fn(x) for x in xs]
            self.assertTrue(all(y >= 0 for y in ys))
            pairs = list(zip(ys, ys[1:]))
            self.assertTrue(all(b >= a - 1e-12 for a, b in pairs) if increasing else all(b <= a + 1e-12 for a, b in pairs))
            self.assertLess(max(abs(b - a) for a, b in pairs), 0.08, "no cliff between neighbouring points")
        self.assertEqual(nutrient_factor(P, P.nutrient_full_g_l), 1.0)
        self.assertEqual(salinity_factor(P, P.ec_threshold_ds_m), 1.0)

    def test_heat_raises_water_demand(self):
        cool, hot = step(temp=24.0, irrigation=300), step(temp=35.0, irrigation=300)
        self.assertGreater(hot.transpired_l, 1.5 * cool.transpired_l)

    def test_low_volume_limits_water_uptake_and_growth(self):
        plenty, short = step(volume=1100.0), step(volume=500.0, nutrient=600.0, salt=400.0)   # same concentrations
        self.assertEqual(plenty.water_factor, 1.0)
        self.assertLess(short.water_factor, 0.5)
        self.assertLess(short.growth_kg, plenty.growth_kg)


class ConditionTests(unittest.TestCase):
    def stressed(self, condition=1.0):
        return step(condition=condition, nutrient=300.0, salt=3200.0, irrigation=220)   # salty and starving

    def test_damage_is_delayed_by_one_day(self):
        """Today's growth uses this morning's condition; today's stress shows in tomorrow's."""
        day1 = self.stressed(condition=1.0)
        self.assertGreater(day1.stress, P.stress_tolerance)
        self.assertLess(day1.condition, 1.0)
        calm_same_morning = step(condition=1.0, nutrient=1600.0, salt=600.0, irrigation=220)
        # Growth on the day of the stress is reduced only by that day's factors, not by any condition loss yet.
        self.assertAlmostEqual(day1.growth_kg, GROWTH * 1.0 * day1.heat_factor * day1.water_factor
                               * day1.nutrient_factor * day1.salinity_factor)
        day2 = step(condition=day1.condition, nutrient=1600.0, salt=600.0, irrigation=220)   # ideal the next day
        self.assertLess(day2.growth_kg, calm_same_morning.growth_kg)
        # The next day's growth carries the lost condition as a multiplier, even with no stress at all.
        self.assertEqual((day2.water_factor, day2.nutrient_factor, day2.salinity_factor), (1.0, 1.0, 1.0))
        self.assertAlmostEqual(day2.growth_kg, GROWTH * day1.condition * day2.heat_factor)
        self.assertAlmostEqual(day2.condition - day1.condition, P.recovery_per_day)   # and it heals only one step

    def test_damage_is_proportional_to_stress_above_tolerance(self):
        r = self.stressed()
        self.assertAlmostEqual(1.0 - r.condition, P.damage_rate * (r.stress - P.stress_tolerance))
        mild = step(condition=1.0, nutrient=1.05 * 1100, salt=800.0, irrigation=220)
        self.assertLessEqual(mild.stress, P.stress_tolerance)
        self.assertEqual(mild.condition, 1.0)

    def test_recovery_is_slow_and_never_instant(self):
        condition, days = 0.6, 0
        while condition < 1.0:
            nxt = step(condition=condition, irrigation=220).condition
            self.assertAlmostEqual(nxt - condition, min(P.recovery_per_day, 1.0 - condition), places=9)
            condition, days = nxt, days + 1
        self.assertEqual(days, 14)   # 0.4 lost takes 14 calm days to regain
        self.assertEqual(best_condition(P, 0.6, 5), 0.75)

    def test_no_recovery_while_stress_continues_and_condition_has_a_floor(self):
        condition = 1.0
        for _ in range(40):
            nxt = self.stressed(condition).condition
            self.assertLessEqual(nxt, condition)
            condition = nxt
        self.assertAlmostEqual(condition, P.condition_floor)

    def test_growth_is_counted_once(self):
        """Harvest only accumulates: a day's growth is added once and never re-harvested."""
        sim = Greenhouse({}, 7)
        totals = [0.0]
        while not sim.done:
            report = sim.advance()
            totals.append(sum(z.harvest for z in sim.zones.values()))
            self.assertAlmostEqual(totals[-1] - totals[-2], sum(z["growth_kg"] for z in report["zones"]), places=1)
        self.assertEqual(totals, sorted(totals))
        self.assertAlmostEqual(outcome.revenue(sim), P.price_per_kg * totals[-1])


class BoundTests(unittest.TestCase):
    def test_no_policy_exceeds_the_ceiling_and_the_default_plan_is_the_floor(self):
        from envkit.clients import run_inprocess
        from envkit.policies import make_policy
        from envkit.scenario import load_scenario
        from pathlib import Path
        scenario = load_scenario(Path(__file__).resolve().parents[1] / "scenarios" / "root-cause.toml")
        for seed in (1, 7, 101):
            nothing = run_inprocess(scenario, seed, make_policy("do-nothing", scenario)).result()
            self.assertEqual(nothing["profit_eur"], nothing["profit_floor_eur"])
            self.assertEqual(nothing["normalized_profit"], 0.0)
            for name in ("reference", "rule-based", "random:3"):
                ledger = run_inprocess(scenario, seed, make_policy(name, scenario)).result()
                self.assertLess(ledger["profit_eur"], ledger["profit_ceiling_eur"])
                self.assertEqual((ledger["profit_floor_eur"], ledger["profit_ceiling_eur"]),
                                 (nothing["profit_floor_eur"], nothing["profit_ceiling_eur"]))
                self.assertTrue(0.0 <= ledger["normalized_profit"] < 1.0)

    def test_reward_is_monotonic_in_profit(self):
        values = [outcome.normalize(v, 1000.0, 2000.0) for v in range(0, 3000, 50)]
        self.assertEqual(values, sorted(values))
        self.assertEqual((values[0], values[-1]), (0.0, 1.0))
        self.assertEqual(outcome.normalize(5.0, 10.0, 10.0), 0.0)


if __name__ == "__main__":
    unittest.main()
