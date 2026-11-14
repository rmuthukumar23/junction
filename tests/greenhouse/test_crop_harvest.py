"""Harvest: minimum sellable weight, single and repeated cuts (lucas.md task 5)."""
import dataclasses
import unittest

from test_crop_growth import LETTUCE, climate, grow, load

from greenhouse.world.crop import DRY, model_for


def until_ready(model, batch, start=0, limit_h=200 * 24):
    h = start
    while batch.status != "ready":
        model.step(batch, climate(h))
        h += 1
        if h - start > limit_h:
            raise AssertionError("never ready")
    return h


class SingleHarvestTests(unittest.TestCase):
    def setUp(self):
        self.spec = load(LETTUCE)
        self.model = model_for(self.spec)
        self.batch = self.model.new_batch("b", "A", 10.0, 0)

    def test_ready_harvest_is_sellable_and_counts_heads(self):
        h = until_ready(self.model, self.batch)
        weight, quality = self.model.fresh_weight_g(self.batch), self.model.quality(self.batch)
        r = self.model.harvest(self.batch, h)
        self.assertEqual((r.batch_id, r.crop_id, r.unit), ("b", "lettuce_butterhead", "head"))
        self.assertEqual(r.units, self.spec.planting.density_per_m2 * 10.0)
        self.assertEqual(r.fresh_weight_g_per_unit, weight)
        self.assertGreaterEqual(r.fresh_weight_g_per_unit, self.spec.cycle.ready_fresh_weight_g)
        self.assertEqual(r.quality, quality)
        self.assertTrue(r.sellable)
        self.assertEqual(self.batch.status, "harvested")

    def test_harvesting_early_is_not_sellable(self):
        """The exploit judges try: harvest everything at once, early."""
        for days in (0, 1, 10):
            batch = grow(self.model, self.model.new_batch("e", "A", 10.0, 0), days * 24)
            r = self.model.harvest(batch, days * 24)
            self.assertLess(r.fresh_weight_g_per_unit, self.spec.market.min_sellable_fresh_weight_g)
            self.assertFalse(r.sellable, days)
            self.assertEqual(batch.status, "harvested")

    def test_sellable_from_the_minimum_weight_before_ready(self):
        h = 0
        while self.model.fresh_weight_g(self.batch) < self.spec.market.min_sellable_fresh_weight_g:
            self.model.step(self.batch, climate(h))
            h += 1
        self.assertEqual(self.batch.status, "growing")
        self.assertTrue(self.model.harvest(self.batch, h).sellable)

    def test_cannot_harvest_twice_or_a_lost_batch(self):
        self.model.harvest(self.batch, 0)
        with self.assertRaisesRegex(ValueError, "harvested"):
            self.model.harvest(self.batch, 1)
        lost = self.model.new_batch("l", "A", 10.0, 0)
        self.model.step(lost, climate(20, night_c=self.spec.stress.frost_kill_c - 1))
        with self.assertRaisesRegex(ValueError, "lost"):
            self.model.harvest(lost, 21)

    def test_harvested_batch_stops(self):
        self.model.harvest(self.batch, 0)
        before = dict(self.batch.model_state)
        self.model.step(self.batch, climate(1))
        self.assertEqual(self.batch.model_state, before)
        self.assertEqual(self.model.co2_uptake_kg_h(self.batch, climate(1)), 0.0)


class RepeatedHarvestTests(unittest.TestCase):
    """A repeated, kg-sold variant of the lettuce spec, so this runs without the basil file."""

    def setUp(self):
        base = load(LETTUCE)
        self.spec = dataclasses.replace(
            base,
            cycle=dataclasses.replace(base.cycle, harvest_mode="repeated", regrow_fraction=0.4,
                                      regrow_days=14.0, max_cuts=2),
            market=dataclasses.replace(base.market, unit="kg"))
        self.model = model_for(self.spec)
        self.batch = self.model.new_batch("r", "B", 10.0, 0)

    def test_cut_keeps_the_regrow_fraction_and_sells_the_rest_in_kg(self):
        h = until_ready(self.model, self.batch)
        self.batch.stress["cold"] = 0.1
        dry, weight = self.batch.model_state[DRY], self.model.fresh_weight_g(self.batch)
        r = self.model.harvest(self.batch, h)
        plants = self.spec.planting.density_per_m2 * 10.0
        self.assertEqual(r.unit, "kg")
        self.assertAlmostEqual(r.units, 0.6 * weight * plants / 1000)
        self.assertEqual(r.fresh_weight_g_per_unit, 1000.0)
        self.assertAlmostEqual(r.quality, 0.9)
        self.assertTrue(r.sellable)
        self.assertAlmostEqual(self.batch.model_state[DRY], 0.4 * dry)
        self.assertEqual((self.batch.status, self.batch.cuts, self.batch.ready_hour), ("growing", 1, None))
        self.assertEqual(self.model.quality(self.batch), 1.0)   # regrowth is new leaves

    def test_regrows_and_stops_after_max_cuts(self):
        h = until_ready(self.model, self.batch)
        self.model.harvest(self.batch, h)
        h = until_ready(self.model, self.batch, start=h)
        self.model.harvest(self.batch, h)
        self.assertEqual((self.batch.status, self.batch.cuts), ("harvested", 2))
        with self.assertRaisesRegex(ValueError, "harvested"):
            self.model.harvest(self.batch, h)

    def test_early_cut_is_not_sellable(self):
        r = self.model.harvest(self.batch, 0)
        self.assertFalse(r.sellable)
        self.assertEqual(self.batch.cuts, 1)


if __name__ == "__main__":
    unittest.main()
