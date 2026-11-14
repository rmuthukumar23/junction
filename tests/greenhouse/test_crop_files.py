"""Every crop file (data/crops plus test fixtures) behaves sensibly with no code changes."""
import tomllib
import unittest
from pathlib import Path

from test_crop_growth import ROOT, climate, grow, load

from greenhouse.world.crop import model_for, target_climate

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _is_crop(path: Path) -> bool:
    """The fixtures folder also holds task fixtures; keep the crop files."""
    return tomllib.loads(path.read_text(encoding="utf-8")).get("schema", "").startswith("crop/")


CROP_FILES = sorted((ROOT / "data" / "crops").glob("*.toml")) + sorted(filter(_is_crop, FIXTURES.glob("*.toml")))


def at_targets(model, spec, batch, start):
    """Step under the target climate until ready; return (hour reached, days taken)."""
    h = start
    while batch.status != "ready":
        model.step(batch, target_climate(spec, h, 1.0))
        h += 1
        if h - start > 10 * spec.cycle.nominal_days * 24:
            raise AssertionError(f"{spec.id} never ready")
    return h, (h - start) / 24


class EveryCropFileTests(unittest.TestCase):
    def test_the_crop_files_are_found(self):
        names = {p.name for p in CROP_FILES}
        self.assertTrue({"lettuce_butterhead.toml", "broccoli_micro.toml", "radish_micro.toml"} <= names, names)

    def test_ready_in_nominal_days_under_the_targets(self):
        for path in CROP_FILES:
            with self.subTest(path.name):
                spec = load(path)
                model = model_for(spec)
                h, days = at_targets(model, spec, model.new_batch("b", "A", 1.0, 0), 0)
                self.assertAlmostEqual(days, spec.cycle.nominal_days, delta=0.15 * spec.cycle.nominal_days)

    def test_regrows_in_regrow_days_under_the_targets(self):
        for path in CROP_FILES:
            spec = load(path)
            if spec.cycle.harvest_mode != "repeated":
                continue
            with self.subTest(path.name):
                model = model_for(spec)
                batch = model.new_batch("b", "A", 1.0, 0)
                h, _ = at_targets(model, spec, batch, 0)
                for _ in range(spec.cycle.max_cuts - 1):
                    self.assertTrue(model.harvest(batch, h).sellable)
                    h, days = at_targets(model, spec, batch, h)
                    self.assertAlmostEqual(days, spec.cycle.regrow_days, delta=0.15 * spec.cycle.regrow_days)
                self.assertTrue(model.harvest(batch, h).sellable)
                self.assertEqual(batch.status, "harvested")

    def test_no_stress_under_the_targets(self):
        for path in CROP_FILES:
            with self.subTest(path.name):
                spec = load(path)
                model = model_for(spec)
                batch = model.new_batch("b", "A", 1.0, 0)
                for h in range(int(spec.cycle.nominal_days * 24 * 0.8)):
                    model.step(batch, target_climate(spec, h, 1.0))
                self.assertEqual(model.quality(batch), 1.0)

    def test_twelve_substeps_match_one_hour(self):
        for path in CROP_FILES:
            with self.subTest(path.name):
                model = model_for(load(path))
                fine = grow(model, model.new_batch("b", "A", 1.0, 0), 20 * 24, substeps=12)
                coarse = grow(model, model.new_batch("b", "A", 1.0, 0), 20 * 24)
                self.assertAlmostEqual(model.fresh_weight_g(fine) / model.fresh_weight_g(coarse), 1.0, delta=0.01)


class SpinachFixtureTests(unittest.TestCase):
    """A crop the code has never seen: single cut but sold by kg, a piecewise stress curve."""

    def setUp(self):
        self.spec = load(FIXTURES / "spinach.toml")
        self.model = model_for(self.spec)

    def test_single_cut_sold_by_kg(self):
        batch = self.model.new_batch("s", "A", 2.0, 0)
        h, _ = at_targets(self.model, self.spec, batch, 0)
        weight = self.model.fresh_weight_g(batch)
        r = self.model.harvest(batch, h)
        self.assertEqual((r.unit, batch.status, r.sellable), ("kg", "harvested", True))
        self.assertAlmostEqual(r.units, weight * self.spec.planting.density_per_m2 * 2.0 / 1000)

    def test_piecewise_bolting_curve(self):
        batch = grow(self.model, self.model.new_batch("s", "A", 1.0, 0), 2 * 24 + 1, day_c=26, night_c=10)
        self.assertAlmostEqual(batch.stress["bolting"], 2 * 0.1)

    def test_survives_a_frost_lettuce_would_not(self):
        batch = grow(self.model, self.model.new_batch("s", "A", 1.0, 0), 2 * 24, night_c=-3)
        self.assertEqual(batch.status, "growing")


if __name__ == "__main__":
    unittest.main()
