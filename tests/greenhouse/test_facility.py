"""Facility configuration contracts and strict validation."""
import copy
import tomllib
import unittest
from pathlib import Path

from envkit.rng import Rng
from greenhouse.config.base import ConfigError, ranges, resolve
from greenhouse.config.facility import parse_facility, parse_climate, parse_energy_prices

DATA = Path(__file__).resolve().parents[2] / 'data'


def raw(folder, name):
    return tomllib.loads((DATA / folder / name).read_text())


class FacilityConfigTests(unittest.TestCase):
    def test_data_files_load_and_resolve(self):
        facility = parse_facility(raw('facilities', 'nl_two_compartment.toml'), 'facility.toml')
        climate = parse_climate(raw('climates', 'nl_january.toml'), 'climate.toml')
        prices = parse_energy_prices(raw('energy_prices', 'nl_winter.toml'), 'prices.toml')
        self.assertEqual(len(facility.compartments), 2)
        self.assertEqual({c.id for c in facility.compartments}, {'A', 'B'})
        self.assertIn('compartments[0].floor_m2', ranges(facility))
        self.assertEqual(resolve(facility, Rng(7)), resolve(facility, Rng(7)))
        self.assertEqual({w.group for w in climate.windows}, {'development', 'evaluation'})
        self.assertEqual({w.id for w in climate.windows}, {w.id for w in prices.windows})
        self.assertEqual(climate.windows[0].rows[0][0], 7.8)  # KNMI De Bilt, 2024-01-01 00 UTC
        self.assertGreater(prices.windows[0].rows[0][1], 0)

    def test_unknown_and_bad_values_fail(self):
        doc = raw('facilities', 'nl_two_compartment.toml')
        extra = copy.deepcopy(doc)
        extra['compartments'][0]['floor_m22'] = 3000
        with self.assertRaisesRegex(ConfigError, 'floor_m22'):
            parse_facility(extra, 'facility.toml')
        bad = copy.deepcopy(doc)
        bad['compartments'][0]['floor_m2'] = {'min': -1, 'max': 2}
        with self.assertRaisesRegex(ConfigError, 'floor_m2'):
            parse_facility(bad, 'facility.toml')
        with self.assertRaisesRegex(ConfigError, 'schema'):
            parse_climate({'schema': 'wrong'}, 'climate.toml')
        bad_climate = raw('climates', 'nl_january.toml')
        bad_climate['windows'][0]['rows'][0][3] = 101
        with self.assertRaisesRegex(ConfigError, 'rows\\[0\\]'):
            parse_climate(bad_climate, 'climate.toml')
        bad_prices = raw('energy_prices', 'nl_winter.toml')
        bad_prices['windows'][0]['rows'][0][1] = -1
        with self.assertRaisesRegex(ConfigError, 'rows\\[0\\]'):
            parse_energy_prices(bad_prices, 'prices.toml')
