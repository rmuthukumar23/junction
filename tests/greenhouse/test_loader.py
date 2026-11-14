"""The loader: data files, overrides, parsers, per-seed hidden parameters."""
import dataclasses
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from envkit.rng import Rng
from greenhouse.config.base import ConfigError, Range, Table
from greenhouse.config import loader
from greenhouse.config.loader import data_files, load


@dataclasses.dataclass(frozen=True)
class Doc:
    id: str
    size: float | Range


def parse(raw, source):
    t = Table(raw, source)
    d = Doc(t.str("id"), t.param("size"))
    t.done()
    return d


PARSERS = {k: parse for k in ("facility", "climate", "energy_prices", "market", "crops", "events")}
FILES = {
    "f.toml": 'id = "fac"\nsize = {min = 1, max = 2}\n',
    "c.toml": 'id = "clim"\nsize = 3\n',
    "e.toml": 'id = "eprice"\nsize = 4\n',
    "m.toml": 'id = "mkt"\nsize = 5\n',
    "lettuce.toml": 'id = "lettuce"\nsize = {min = 10, max = 20}\n',
    "basil.toml": 'id = "basil"\nsize = {min = 10, max = 20}\n',
}
ENV = {"facility": "f.toml", "climate": "c.toml", "energy_prices": "e.toml", "market": "m.toml",
       "crops": ["lettuce.toml", "basil.toml"], "horizon_days": 2}


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name, text in FILES.items():
            (self.root / name).write_text(text)

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, env=None, seed=1):
        return load(env or ENV, Rng(seed), self.root, PARSERS)

    def test_loads_and_draws_hidden_parameters_per_seed(self):
        cfg = self.load()
        self.assertEqual(cfg.horizon_h, 48)
        self.assertEqual(sorted(cfg.crops), ["basil", "lettuce"])
        self.assertTrue(1 <= cfg.facility.size <= 2)
        self.assertEqual(self.load().facility.size, cfg.facility.size)
        self.assertNotEqual(self.load(seed=2).facility.size, cfg.facility.size)
        self.assertEqual(cfg.published_ranges["facility"], {"size": (1.0, 2.0)})

    def test_two_crops_with_the_same_key_draw_independently(self):
        cfg = self.load()
        self.assertNotEqual(cfg.crops["lettuce"].size, cfg.crops["basil"].size)

    def test_overrides_change_one_value(self):
        cfg = self.load({**ENV, "overrides": {"market.size": 9, "crops.basil.size": 15}})
        self.assertEqual(cfg.market.size, 9.0)
        self.assertEqual(cfg.crops["basil"].size, 15.0)
        with self.assertRaisesRegex(ConfigError, "no key 'nope'"):
            self.load({**ENV, "overrides": {"market.nope": 1}})
        with self.assertRaisesRegex(ConfigError, "no crops file with id 'kale'"):
            self.load({**ENV, "overrides": {"crops.kale.size": 1}})

    def test_overrides_reach_an_array_of_tables_by_item_id(self):
        raw = {"facility": ("f.toml", {"compartments": [{"id": "A", "crop": "lettuce", "batches": [1]},
                                                         {"id": "B", "crop": "basil"}]})}
        loader._apply_overrides(raw, {"facility.compartments.B.crop": "spinach",
                                      "facility.compartments.A.batches": [9]})
        self.assertEqual(raw["facility"][1]["compartments"], [{"id": "A", "crop": "lettuce", "batches": [9]},
                                                              {"id": "B", "crop": "spinach"}])
        with self.assertRaisesRegex(ConfigError, "no item with id 'C'"):
            loader._apply_overrides(raw, {"facility.compartments.C.crop": "kale"})
        with self.assertRaisesRegex(ConfigError, "name an item by its id"):
            loader._apply_overrides(raw, {"facility.compartments.crop": "kale"})

    def test_bad_scenarios_fail_clearly(self):
        with self.assertRaisesRegex(ConfigError, "missing 'market'"):
            self.load({k: v for k, v in ENV.items() if k != "market"})
        with self.assertRaisesRegex(ConfigError, "unknown key"):
            self.load({**ENV, "colour": "green"})
        with self.assertRaisesRegex(ConfigError, "duplicate crops id"):
            self.load({**ENV, "crops": ["lettuce.toml", "lettuce.toml"]})
        with self.assertRaisesRegex(ConfigError, "not found"):
            self.load({**ENV, "climate": "missing.toml"})
        with self.assertRaisesRegex(ConfigError, "inside the project"):
            self.load({**ENV, "climate": "../outside.toml"})

    def test_missing_owner_parser_names_the_owner(self):
        # Every real parser exists now, so point one at a module that does not.
        with mock.patch.dict(loader.PARSERS, {"crops": ("greenhouse.config.not_yet", "parse_crop", "Lucas")}):
            with self.assertRaisesRegex(ConfigError, r"not built \(Lucas\)"):
                load(ENV, Rng(1), self.root)

    def test_data_files_lists_every_file(self):
        self.assertEqual(data_files(ENV), ["f.toml", "c.toml", "e.toml", "m.toml", "lettuce.toml", "basil.toml"])


if __name__ == "__main__":
    unittest.main()
