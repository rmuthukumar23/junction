"""Growth behaviour of the leafy_vanhenten model against published lettuce behaviour.

Climates here are hand-made test inputs, not crop values: the model reads every
crop value from the data file.
"""
import tomllib
import unittest
from pathlib import Path

from greenhouse.config.crop import GROWTH_PARAMS, CropSpec, parse_crop
from greenhouse.contracts import ClimateSample
from greenhouse.world.crop import MODELS, model_for, target_climate

ROOT = Path(__file__).resolve().parents[2]


def load(path: Path) -> CropSpec:
    return parse_crop(tomllib.loads(path.read_text()), path.name)


LETTUCE = ROOT / "data" / "crops" / "lettuce_butterhead.toml"


def climate(hour, dt_h=1.0, day_c=20.0, night_c=16.0, co2=900.0, dli=15.0, photoperiod=16, rh=75.0):
    is_day = hour % 24 < photoperiod
    par = dli * 1e6 / (photoperiod * 3600) if is_day else 0.0
    return ClimateSample(hour=hour, dt_h=dt_h, temp_c=day_c if is_day else night_c, rh_pct=rh,
                         co2_ppm=co2, par_umol_m2_s=par, is_day=is_day)


def grow(model, batch, hours, substeps=1, start=0, **kw):
    for h in range(start, start + hours):
        for _ in range(substeps):
            model.step(batch, climate(h, 1.0 / substeps, **kw))
    return batch


def days_to_ready(model, batch, sample, limit_days=200):
    for h in range(limit_days * 24):
        for c in sample(h):
            model.step(batch, c)
        if batch.status == "ready":
            return (batch.ready_hour - batch.planted_hour + 1) / 24
    return None


class RegistryTests(unittest.TestCase):
    def test_every_schema_has_a_model(self):
        self.assertEqual(set(MODELS), set(GROWTH_PARAMS))


class LettuceGrowthTests(unittest.TestCase):
    def setUp(self):
        self.spec = load(LETTUCE)
        self.model = model_for(self.spec)

    def new(self, **kw):
        return self.model.new_batch("b1", "A", 100.0, 0, **kw)

    def dry(self, batch):
        return batch.model_state["dry_weight_kg_m2"]

    def test_ready_in_nominal_days_at_20c_900ppm_dli15(self):
        days = days_to_ready(self.model, self.new(), lambda h: [climate(h, 1 / 12)] * 12)
        self.assertIsNotNone(days)
        self.assertAlmostEqual(days, self.spec.cycle.nominal_days, delta=0.15 * self.spec.cycle.nominal_days)

    def test_ready_in_nominal_days_under_the_published_targets(self):
        days = days_to_ready(self.model, self.new(), lambda h: [target_climate(self.spec, h, 1.0)])
        self.assertAlmostEqual(days, self.spec.cycle.nominal_days, delta=0.15 * self.spec.cycle.nominal_days)

    def test_ready_weight_is_reached_when_ready(self):
        b = self.new()
        days_to_ready(self.model, b, lambda h: [climate(h)])
        self.assertGreaterEqual(self.model.fresh_weight_g(b), self.spec.cycle.ready_fresh_weight_g)

    def test_barely_grows_at_5c_and_low_light(self):
        start = self.dry(self.new())
        cold = self.dry(grow(self.model, self.new(), 14 * 24, day_c=5, night_c=5, dli=3))
        warm = self.dry(grow(self.model, self.new(), 14 * 24))
        self.assertLess(cold - start, 0.1 * (warm - start))

    def test_no_extra_co2_grows_slower(self):
        ambient = self.dry(grow(self.model, self.new(), 20 * 24, co2=400))
        enriched = self.dry(grow(self.model, self.new(), 20 * 24, co2=900))
        self.assertLess(ambient, 0.9 * enriched)

    def test_co2_benefit_saturates(self):
        b = grow(self.model, self.new(), 10 * 24)
        rate = {c: self.model.co2_uptake_kg_h(b, climate(10, co2=c)) for c in (400, 700, 1000, 5000)}
        self.assertLess((rate[1000] - rate[700]) / 300, (rate[700] - rate[400]) / 300)
        saturation = self.spec.growth.co2_saturation_ppm
        self.assertEqual(rate[5000], self.model.co2_uptake_kg_h(b, climate(10, co2=saturation)))
        self.assertEqual(self.dry(grow(self.model, self.new(), 20 * 24, co2=5000)),
                         self.dry(grow(self.model, self.new(), 20 * 24, co2=saturation)))

    def test_temperature_has_an_optimum(self):
        w = {t: self.dry(grow(self.model, self.new(), 20 * 24, day_c=t, night_c=t - 4)) for t in (12, 20, 38)}
        self.assertGreater(w[20], w[12])
        self.assertGreater(w[20], w[38])

    def test_more_light_grows_faster(self):
        dim = self.dry(grow(self.model, self.new(), 20 * 24, dli=8))
        bright = self.dry(grow(self.model, self.new(), 20 * 24, dli=15))
        self.assertGreater(bright, dim)

    def test_twelve_substeps_match_one_hour(self):
        fine = self.dry(grow(self.model, self.new(), 25 * 24, substeps=12))
        coarse = self.dry(grow(self.model, self.new(), 25 * 24, substeps=1))
        self.assertAlmostEqual(fine / coarse, 1.0, delta=0.01)

    def test_same_inputs_same_output_bit_for_bit(self):
        a = grow(self.model, self.new(), 10 * 24, substeps=12)
        b = grow(model_for(load(LETTUCE)), self.new(), 10 * 24, substeps=12)
        self.assertEqual(a, b)
        self.assertEqual(repr(a.model_state), repr(b.model_state))

    def test_old_batch_matches_one_grown_from_planting(self):
        old = self.model.new_batch("b2", "A", 100.0, -16 * 24, age_days=16)
        young = self.model.new_batch("b2", "A", 100.0, -16 * 24)
        for h in range(-16 * 24, 0):
            self.model.step(young, target_climate(self.spec, h, 1.0))
        self.assertEqual(old.model_state, young.model_state)
        self.assertEqual(old.status, young.status)

    def test_co2_uptake_by_day_release_by_night(self):
        b = grow(self.model, self.new(), 10 * 24)
        self.assertGreater(self.model.co2_uptake_kg_h(b, climate(10)), 0)
        self.assertLess(self.model.co2_uptake_kg_h(b, climate(20)), 0)

    def test_transpiration_follows_the_vapour_deficit(self):
        b = grow(self.model, self.new(), 10 * 24)
        dry_air = self.model.transpiration_kg_h(b, climate(10, rh=60))
        humid = self.model.transpiration_kg_h(b, climate(10, rh=90))
        self.assertGreater(dry_air, humid)
        self.assertGreater(humid, 0)
        self.assertEqual(self.model.transpiration_kg_h(b, climate(10, rh=100)), 0)

    def test_fluxes_scale_with_area(self):
        small = grow(self.model, self.model.new_batch("s", "A", 10.0, 0), 10 * 24)
        large = grow(self.model, self.model.new_batch("l", "A", 20.0, 0), 10 * 24)
        c = climate(10)
        self.assertAlmostEqual(self.model.co2_uptake_kg_h(large, c), 2 * self.model.co2_uptake_kg_h(small, c))
        self.assertAlmostEqual(self.model.transpiration_kg_h(large, c), 2 * self.model.transpiration_kg_h(small, c))


if __name__ == "__main__":
    unittest.main()
