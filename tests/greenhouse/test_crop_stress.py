"""Stress counters, quality, frost loss and waiting losses (lucas.md task 4)."""
import unittest

from test_crop_growth import LETTUCE, climate, grow, load

from greenhouse.world.crop import model_for


class LettuceStressTests(unittest.TestCase):
    def setUp(self):
        self.spec = load(LETTUCE)
        self.model = model_for(self.spec)
        self.counters = {c.name: c for c in self.spec.stress.counters}

    def run_days(self, days, **kw):
        """Grow `days` whole days, then one hour so the last day is closed."""
        return grow(self.model, self.model.new_batch("b", "A", 10.0, 0), days * 24 + 1, **kw)

    def test_target_climate_causes_no_stress(self):
        b = self.run_days(20)
        self.assertEqual(b.stress, {"tipburn": 0.0, "bolting": 0.0, "cold": 0.0})
        self.assertEqual(self.model.quality(b), 1.0)

    def test_high_light_raises_tipburn(self):
        b = self.run_days(5, dli=22)
        expected = 5 * self.counters["tipburn"].curve(22.0)
        self.assertGreater(expected, 0)
        self.assertAlmostEqual(b.stress["tipburn"], expected)
        self.assertEqual(b.stress["bolting"], 0.0)
        self.assertEqual(b.stress["cold"], 0.0)
        self.assertAlmostEqual(self.model.quality(b), 1 - expected)

    def test_more_light_more_tipburn(self):
        self.assertGreater(self.run_days(5, dli=25).stress["tipburn"], self.run_days(5, dli=20).stress["tipburn"])

    def test_hot_days_raise_bolting(self):
        b = self.run_days(4, day_c=28)
        self.assertAlmostEqual(b.stress["bolting"], 4 * self.counters["bolting"].curve(28.0))
        self.assertGreater(b.stress["bolting"], 0)

    def test_cold_nights_raise_cold_stress(self):
        b = self.run_days(3, night_c=1)
        self.assertAlmostEqual(b.stress["cold"], 3 * self.counters["cold"].curve(1.0))
        self.assertGreater(b.stress["cold"], 0)
        self.assertEqual(b.status, "growing")

    def test_quality_is_clipped_at_zero(self):
        b = self.run_days(40, night_c=0, dli=30, day_c=30)
        self.assertGreater(sum(b.stress.values()), 1)
        self.assertEqual(self.model.quality(b), 0.0)

    def test_frost_kills_the_batch(self):
        b = self.run_days(2)
        frost = self.spec.stress.frost_kill_c
        self.model.step(b, climate(2 * 24 + 18, night_c=frost - 0.5))   # a night hour
        self.assertEqual(b.status, "lost")
        before = dict(b.model_state)
        self.model.step(b, climate(50))
        self.assertEqual(b.model_state, before)
        self.assertEqual(self.model.co2_uptake_kg_h(b, climate(50)), 0.0)
        self.assertEqual(self.model.transpiration_kg_h(b, climate(50)), 0.0)

    def test_just_above_frost_is_not_lost(self):
        b = self.run_days(1, night_c=self.spec.stress.frost_kill_c + 0.5)
        self.assertEqual(b.status, "growing")

    def test_waiting_ready_batch_loses_quality(self):
        b = self.model.new_batch("b", "A", 10.0, 0)
        h = 0
        while b.status != "ready":
            self.model.step(b, climate(h))
            h += 1
        q0 = self.model.quality(b)
        grow(self.model, b, 3 * 24, start=h)
        self.assertAlmostEqual(q0 - self.model.quality(b), 3 * self.spec.stress.ready_loss_per_day, places=6)


if __name__ == "__main__":
    unittest.main()
