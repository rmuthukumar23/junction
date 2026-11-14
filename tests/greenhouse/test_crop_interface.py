"""The rest of GrowthModel that sim.py and get_rules call: labour, seedlings, the
planting cut-off, describe(), and the grade and price factor of a harvest
(lucas.md round 2, tasks 2, 3 and 5)."""
import json
import math
import unittest

from test_crop_files import CROP_FILES
from test_crop_growth import ROOT, load

from greenhouse.config.crop import GROWTH_PARAMS
from greenhouse.contracts import GrowthModel
from greenhouse.world import crop as crop_module
from greenhouse.world.crop import MODELS, model_for, target_climate

LETTUCE = ROOT / "data" / "crops" / "lettuce_butterhead.toml"
BROCCOLI = ROOT / "data" / "crops" / "broccoli_micro.toml"
PROTOCOL = [n for n in vars(GrowthModel) if not n.startswith("_")]


def grow_ready(model, spec, batch, start=0):
    h = start
    while batch.status != "ready":
        model.step(batch, target_climate(spec, h, 1.0))
        h += 1
    return h


class PlanningTests(unittest.TestCase):
    def test_every_model_has_the_whole_protocol(self):
        for path in CROP_FILES:
            model = model_for(load(path))
            for name in PROTOCOL:
                with self.subTest(path.name, method=name):
                    self.assertTrue(hasattr(model, name))

    def test_labour_is_the_file_rate_per_1000_plants(self):
        spec = load(LETTUCE)
        model = model_for(spec)
        plants = spec.planting.density_per_m2 * 500.0
        self.assertAlmostEqual(model.labour_hours("plant", 500.0),
                               plants / 1000 * spec.planting.plant_worker_hours_per_1000)
        self.assertAlmostEqual(model.labour_hours("harvest", 500.0),
                               plants / 1000 * spec.planting.harvest_worker_hours_per_1000)
        self.assertEqual(model.labour_hours("plant", 0.0), 0.0)
        with self.assertRaisesRegex(ValueError, "plant' or 'harvest"):
            model.labour_hours("weed", 10.0)

    def test_seedlings_round_up_to_whole_plants(self):
        spec = load(LETTUCE)
        model = model_for(spec)
        d = spec.planting.density_per_m2
        self.assertEqual(model.seedlings_needed(12.5), round(12.5 * d))       # exact: no extra plant
        self.assertEqual(model.seedlings_needed(0.1 + 0.2), math.ceil(round(0.3 * d, 6)))
        self.assertEqual(model.seedlings_needed(1.01), math.ceil(1.01 * d))
        self.assertIsInstance(model.seedlings_needed(3.0), int)

    def test_planting_cut_off_is_the_files(self):
        for path in CROP_FILES:
            spec = load(path)
            with self.subTest(path.name):
                self.assertEqual(model_for(spec).min_days_before_end(), float(spec.cycle.min_days_before_end))


class DescribeTests(unittest.TestCase):
    def test_registries_agree(self):
        self.assertEqual(set(MODELS), set(GROWTH_PARAMS))
        self.assertEqual(set(MODELS), set(crop_module._MECHANICS))

    def test_describe_is_json_and_publishes_the_file(self):
        for path in CROP_FILES:
            spec = load(path)
            with self.subTest(path.name):
                d = model_for(spec).describe()
                self.assertEqual(json.loads(json.dumps(d)), d)
                self.assertEqual(d["id"], spec.id)
                self.assertEqual(d["cycle"]["nominal_days"], spec.cycle.nominal_days)
                self.assertEqual(d["planting"]["density_per_m2"], spec.planting.density_per_m2)
                self.assertEqual(d["market"]["min_sellable_fresh_weight_g"], spec.market.min_sellable_fresh_weight_g)
                self.assertEqual([g["name"] for g in d["market"]["grades"]], [g.name for g in spec.market.grades])
                self.assertEqual(d["growth"]["temperature"]["curve"], "cardinal")
                self.assertEqual([c["name"] for c in d["stress"]["counters"]],
                                 [c.name for c in spec.stress.counters])
                self.assertTrue(all("curve" in c and "signal" in c for c in d["stress"]["counters"]))
                self.assertIn("growth", d["mechanics"])

    def test_describe_does_not_publish_prices(self):
        """Seedling and produce prices belong to the market file."""
        for path in CROP_FILES:
            with self.subTest(path.name):
                self.assertNotIn("eur", json.dumps(model_for(load(path)).describe()))


class GradeTests(unittest.TestCase):
    def setUp(self):
        self.spec = load(LETTUCE)
        self.model = model_for(self.spec)
        self.batch = self.model.new_batch("A1", "A", 10.0, 0)

    def test_fresh_ready_head_is_top_grade(self):
        h = grow_ready(self.model, self.spec, self.batch)
        r = self.model.harvest(self.batch, h)
        top = self.spec.market.grades[0]
        self.assertEqual((r.grade, r.price_factor), (top.name, top.price_factor))

    def test_unsellable_harvest_has_factor_zero(self):
        for _ in range(48):
            self.model.step(self.batch, target_climate(self.spec, _, 1.0))
        r = self.model.harvest(self.batch, 48)
        self.assertFalse(r.sellable)
        self.assertEqual((r.grade, r.price_factor), (self.spec.market.grades[-1].name, 0.0))

    def test_grade_follows_quality(self):
        for q in (1.0, 0.86, 0.85, 0.7, 0.3, 0.0):
            batch = self.model.new_batch("A2", "A", 10.0, 0)
            h = grow_ready(self.model, self.spec, batch)
            batch.model_state[crop_module.READY_LOSS] = 1.0 - q
            r = self.model.harvest(batch, h)
            g = self.spec.market.grade(r.quality)
            with self.subTest(quality=q):
                self.assertEqual((r.grade, r.price_factor), (g.name, g.price_factor))


class WaitingTests(unittest.TestCase):
    """D5: a ready batch that is not harvested loses grade, then all its value."""

    def test_waiting_ready_drops_grades_then_sells_for_nothing(self):
        for path in (LETTUCE, BROCCOLI):
            spec = load(path)
            model = model_for(spec)
            with self.subTest(path.name):
                rate = spec.stress.ready_loss_per_day
                top_q = spec.market.grades[0].min_quality
                days_top = (1 - top_q) / rate
                days_worthless = (1 - min(g.min_quality for g in spec.market.grades if g.price_factor > 0)) / rate

                def after(days):
                    b = model.new_batch("x", "A", 1.0, 0)
                    h = grow_ready(model, spec, b)
                    for i in range(round(days * 24)):
                        model.step(b, target_climate(spec, h + i, 1.0))
                    return model.harvest(b, h + round(days * 24))

                self.assertEqual(after(days_top - 1).grade, spec.market.grades[0].name)
                self.assertNotEqual(after(days_top + 1).grade, spec.market.grades[0].name)
                late = after(days_worthless + 1)
                self.assertLess(late.quality, top_q)
                self.assertEqual(late.price_factor, 0.0)


if __name__ == "__main__":
    unittest.main()
