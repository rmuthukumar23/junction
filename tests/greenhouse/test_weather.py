"""Seeded weather, prices, and stable forecasts."""
import tomllib
import unittest
from pathlib import Path

from envkit.rng import Rng
from greenhouse.config.facility import parse_climate, parse_energy_prices
from greenhouse.world.weather import WeatherSeries, PriceSeries

DATA = Path(__file__).resolve().parents[2] / 'data'


class WeatherTests(unittest.TestCase):
    def setUp(self):
        self.climate = parse_climate(tomllib.loads((DATA / 'climates/nl_january.toml').read_text()), 'climate')
        self.prices = parse_energy_prices(tomllib.loads((DATA / 'energy_prices/nl_winter.toml').read_text()), 'prices')

    def test_weather_and_prices_are_deterministic(self):
        a = WeatherSeries(self.climate, Rng(4), 1008)
        b = WeatherSeries(self.climate, Rng(4), 1008)
        self.assertEqual(a.hours, b.hours)
        self.assertNotEqual(a.hours, WeatherSeries(self.climate, Rng(5), 1008).hours)
        self.assertNotEqual(a.hours, WeatherSeries(self.climate, Rng(101), 1008).hours)
        self.assertEqual({WeatherSeries(self.climate, Rng(seed), 24).window_id
                          for seed in range(1, 7)}, {'2024-jan01', '2024-jan08'})
        self.assertEqual({WeatherSeries(self.climate, Rng(seed), 24).window_id
                          for seed in range(101, 109)}, {'2025-jan01', '2025-jan08'})
        self.assertEqual(PriceSeries(self.prices, Rng(4), 1008).hours,
                         PriceSeries(self.prices, Rng(4), 1008).hours)
        self.assertAlmostEqual(sum(x.temp_c for x in a.hours) / 1008, 3.6, delta=2.5)
        self.assertLess(sum(x.is_day for x in a.hours) / 1008, 0.4)

    def test_forecast_does_not_change_with_extra_reads(self):
        series = WeatherSeries(self.climate, Rng(4), 100)
        first = series.forecast(10, 24)
        self.assertEqual(first, series.forecast(10, 24))
        self.assertEqual(first, WeatherSeries(self.climate, Rng(4), 120).forecast(10, 24))
        self.assertEqual(series.hours, WeatherSeries(self.climate, Rng(4), 100).hours)
        self.assertNotEqual(first[-1].temp_c, series.hours[34].temp_c)
        prices = PriceSeries(self.prices, Rng(4), 100)
        prediction = prices.forecast(10, 24, self.climate.forecast)
        self.assertEqual(prediction, prices.forecast(10, 24, self.climate.forecast))
        self.assertEqual(prediction, PriceSeries(self.prices, Rng(4), 120).forecast(10, 24,
                                                                                  self.climate.forecast))
        self.assertNotEqual(prediction[-1].gas_eur_m3, prices.hours[34].gas_eur_m3)

class PricePrefixTests(unittest.TestCase):
    def test_longer_horizon_preserves_earlier_prices(self):
        spec = parse_energy_prices(tomllib.loads((DATA / 'energy_prices/nl_winter.toml').read_text()), 'prices')
        self.assertEqual(PriceSeries(spec, Rng(9), 24).hours,
                         PriceSeries(spec, Rng(9), 48).hours[:24])
        self.assertNotEqual(PriceSeries(spec, Rng(9), 24).hours,
                            PriceSeries(spec, Rng(101), 24).hours)
