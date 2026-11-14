"""What get_batches shows: noisy, seeded, repeatable estimates (lucas.md task 8)."""
import copy
import dataclasses
import statistics
import unittest

from test_crop_files import at_targets
from test_crop_growth import LETTUCE, climate, grow, load

from envkit.rng import Rng
from greenhouse.world.crop import model_for, target_climate


def stream(batch, hour, seed=7):
    """The stream the simulator passes, per contracts.py."""
    return Rng(seed).stream(f"estimate/{batch.id}/{hour}")


class EstimateTests(unittest.TestCase):
    def setUp(self):
        self.spec = load(LETTUCE)
        self.model = model_for(self.spec)
        self.batch = grow(self.model, self.model.new_batch("b", "A", 10.0, 0), 10 * 24)

    def exact(self, spec):
        return model_for(dataclasses.replace(spec, estimate=dataclasses.replace(
            spec.estimate, weight_rel_sigma=0.0, quality_sigma=0.0)))

    def test_same_hour_same_answer(self):
        a = self.model.estimate(self.batch, 240, stream(self.batch, 240))
        b = self.model.estimate(self.batch, 240, stream(self.batch, 240))
        self.assertEqual(a, b)

    def test_reusing_one_stream_object_gives_the_same_answer(self):
        rng = stream(self.batch, 240)
        self.assertEqual(self.model.estimate(self.batch, 240, rng), self.model.estimate(self.batch, 240, rng))

    def test_reading_does_not_change_the_batch(self):
        before = copy.deepcopy(self.batch)
        self.model.estimate(self.batch, 240, stream(self.batch, 240))
        self.assertEqual(self.batch, before)

    def test_noise_differs_between_hours_and_seeds(self):
        a = self.model.estimate(self.batch, 240, stream(self.batch, 240))
        self.assertNotEqual(a, self.model.estimate(self.batch, 240, stream(self.batch, 241)))
        self.assertNotEqual(a, self.model.estimate(self.batch, 240, stream(self.batch, 240, seed=8)))

    def test_weight_noise_has_the_files_sigma(self):
        true = self.model.fresh_weight_g(self.batch)
        ratios = [self.model.estimate(self.batch, h, stream(self.batch, h)).fresh_weight_g_per_unit / true
                  for h in range(2000)]
        sigma = self.spec.estimate.weight_rel_sigma
        self.assertAlmostEqual(statistics.fmean(ratios), 1.0, delta=0.01)
        self.assertAlmostEqual(statistics.stdev(ratios), sigma, delta=0.1 * sigma)

    def test_quality_estimate_stays_in_0_1(self):
        qualities = [self.model.estimate(self.batch, h, stream(self.batch, h)).quality for h in range(500)]
        self.assertTrue(all(0.0 <= q <= 1.0 for q in qualities))
        self.assertLess(min(qualities), 1.0)

    def test_exact_estimate_without_noise(self):
        model = self.exact(self.spec)
        e = model.estimate(self.batch, 240, stream(self.batch, 240))
        self.assertEqual(e.fresh_weight_g_per_unit, model.fresh_weight_g(self.batch))
        self.assertEqual(e.units, self.spec.planting.density_per_m2 * 10.0)
        self.assertEqual(e.quality, 1.0)

    def test_days_to_ready_is_close_under_the_target_climate(self):
        model = self.exact(self.spec)
        for age in (6, 12, 18):
            batch = model.new_batch("b", "A", 10.0, 0, age_days=age)
            estimated = model.estimate(batch, age * 24, stream(batch, age * 24)).days_to_ready
            _, actual = at_targets(model, self.spec, batch, age * 24)
            self.assertAlmostEqual(estimated, actual, delta=max(2.0, 0.25 * actual), msg=f"age {age}")

    def test_days_to_ready_on_the_planting_day(self):
        model = self.exact(self.spec)
        batch = model.new_batch("b", "A", 10.0, 0)
        days = model.estimate(batch, 0, stream(batch, 0)).days_to_ready
        _, actual = at_targets(model, self.spec, batch, 0)
        self.assertAlmostEqual(days, actual, delta=1 / 24)

    def test_days_to_ready_is_none_once_ready_harvested_or_lost(self):
        h = 10 * 24
        while self.batch.status != "ready":
            self.model.step(self.batch, climate(h))
            h += 1
        self.assertIsNone(self.model.estimate(self.batch, h, stream(self.batch, h)).days_to_ready)
        self.model.harvest(self.batch, h)
        self.assertIsNone(self.model.estimate(self.batch, h, stream(self.batch, h)).days_to_ready)




if __name__ == "__main__":
    unittest.main()
