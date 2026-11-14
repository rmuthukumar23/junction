"""The response-curve library data files choose from."""
import unittest

from greenhouse.config.base import ConfigError, Table
from greenhouse.config.curves import Cardinal, Piecewise, parse_curve


def curve(**raw):
    return parse_curve(Table(raw, "test.toml", "c"))


class CurveTests(unittest.TestCase):
    def test_cardinal_is_one_at_optimum_and_zero_outside(self):
        c = curve(curve="cardinal", t_min=2, t_opt=20, t_max=30)
        self.assertAlmostEqual(c(20), 1.0)
        self.assertEqual(c(2), 0.0)
        self.assertEqual(c(31), 0.0)
        self.assertTrue(0 < c(10) < 1 and 0 < c(25) < 1)

    def test_saturating_and_linear(self):
        self.assertAlmostEqual(curve(curve="saturating", half_sat=100)(100), 0.5)
        self.assertEqual(curve(curve="linear_above", threshold=17, rate=0.1)(19), 0.2)
        self.assertEqual(curve(curve="linear_above", threshold=17, rate=0.1)(10), 0.0)
        self.assertEqual(curve(curve="linear_below", threshold=4, rate=1)(1), 3.0)

    def test_piecewise_interpolates_and_clamps(self):
        c = curve(curve="piecewise", points=[[0, 0], [10, 1], [20, 1]])
        self.assertEqual(c(5), 0.5)
        self.assertEqual(c(-5), 0.0)
        self.assertEqual(c(50), 1.0)
        self.assertIsInstance(c, Piecewise)

    def test_invalid_curves_fail_with_the_key(self):
        with self.assertRaisesRegex(ConfigError, "'c.curve' must be one of"):
            curve(curve="sigmoid")
        with self.assertRaisesRegex(ConfigError, "t_min < t_opt < t_max"):
            curve(curve="cardinal", t_min=20, t_opt=10, t_max=30)
        with self.assertRaisesRegex(ConfigError, "unknown key"):
            curve(curve="saturating", half_sat=1, extra=2)
        with self.assertRaisesRegex(ConfigError, "increasing x"):
            curve(curve="piecewise", points=[[1, 0], [1, 1]])

    def test_curves_are_hashable_values(self):
        self.assertEqual(Cardinal(2, 20, 30), curve(curve="cardinal", t_min=2, t_opt=20, t_max=30))


if __name__ == "__main__":
    unittest.main()
