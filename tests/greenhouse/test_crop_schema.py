"""Crop data-file schema (spec 3.1): every key read through Table, strict errors."""
import copy
import dataclasses
import json
import tomllib
import unittest
from pathlib import Path

from greenhouse.config.base import ConfigError
from greenhouse.config.crop import CropSpec, parse_crop

ROOT = Path(__file__).resolve().parents[2]
CROPS = ROOT / "data" / "crops"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def raw(name: str) -> dict:
    path = FIXTURES / name if name.startswith("spinach") else CROPS / name
    return tomllib.loads(path.read_text())


def load(name: str) -> CropSpec:
    return parse_crop(raw(name), name)


class LettuceSchemaTests(unittest.TestCase):
    def setUp(self):
        self.raw = raw("lettuce_butterhead.toml")

    def bad(self, mutate, pattern):
        doc = copy.deepcopy(self.raw)
        mutate(doc)
        with self.assertRaisesRegex(ConfigError, pattern):
            parse_crop(doc, "lettuce_butterhead.toml")

    def test_lettuce_loads(self):
        spec = load("lettuce_butterhead.toml")
        self.assertEqual(spec.id, "lettuce_butterhead")
        self.assertEqual(spec.growth_model, "leafy_vanhenten")
        self.assertEqual(spec.cycle.harvest_mode, "single")
        self.assertIsNone(spec.cycle.max_cuts)
        self.assertEqual(spec.market.unit, "head")
        self.assertEqual([c.name for c in spec.stress.counters], ["tipburn", "bolting", "cold"])
        self.assertEqual([c.signal for c in spec.stress.counters], ["dli_excess", "temp_day_mean", "temp_min"])

    def test_missing_key_is_named(self):
        self.bad(lambda d: d["planting"].pop("density_per_m2"), r"missing key 'planting.density_per_m2'")
        self.bad(lambda d: d["growth"].pop("yield_factor"), r"missing key 'growth.yield_factor'")

    def test_stray_key_is_named(self):
        self.bad(lambda d: d["planting"].update(densty_per_m2=20), r"unknown key\(s\) \['planting.densty_per_m2'\]")
        self.bad(lambda d: d["stress"]["cold"].update(rte=1), r"unknown key\(s\) \['stress.cold.rte'\]")

    def test_negative_density_is_named(self):
        self.bad(lambda d: d["planting"].update(density_per_m2=-20), r"'planting.density_per_m2'")
        self.bad(lambda d: d["planting"].update(density_per_m2=0), r"'planting.density_per_m2'")

    def test_unknown_growth_model_is_named(self):
        self.bad(lambda d: d.update(growth_model="tomato_tomgro"), r"'growth_model' must be one of")

    def test_unknown_stress_signal_is_named(self):
        self.bad(lambda d: d["stress"]["cold"].update(signal="temp_mean"), r"'stress.cold.signal' must be one of")

    def test_single_crop_rejects_repeated_keys(self):
        self.bad(lambda d: d["cycle"].update(max_cuts=3), r"unknown key\(s\) \['cycle.max_cuts'\]")

    def test_grades_must_descend_to_zero(self):
        self.bad(lambda d: d["market"]["grades"].reverse(), r"'market.grades'")
        self.bad(lambda d: d["market"]["grades"].pop(), r"'market.grades'")

    def test_target_ranges_are_ordered_pairs(self):
        self.bad(lambda d: d["climate_targets"].update(co2_ppm=[1000, 800]), r"'climate_targets.co2_ppm'")
        self.bad(lambda d: d["climate_targets"].update(co2_ppm=[800]), r"'climate_targets.co2_ppm'")

    def test_spec_is_plain_json_for_get_rules(self):
        text = json.dumps(dataclasses.asdict(load("lettuce_butterhead.toml")))
        self.assertIn("leafy_vanhenten", text)

    def test_grade_lookup(self):
        market = load("lettuce_butterhead.toml").market
        self.assertEqual(market.grade(1.0).name, "A")
        self.assertEqual(market.grade(0.7).name, "B")
        self.assertEqual(market.grade(0.0).name, "waste")


if __name__ == "__main__":
    unittest.main()
