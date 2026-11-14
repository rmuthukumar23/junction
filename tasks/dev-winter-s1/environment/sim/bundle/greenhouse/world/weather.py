"""Recorded winter weather and prices with seeded, read-stable forecasts."""
from __future__ import annotations

import math
from dataclasses import dataclass

from envkit.rng import Rng
from greenhouse.config.facility import ClimateProfile, EnergyPriceSpec, ForecastSpec


@dataclass(frozen=True)
class WeatherHour:
    hour: int
    temp_c: float
    solar_w_m2: float
    wind_m_s: float
    rh_pct: float
    is_day: bool
    outside_co2_ppm: float


@dataclass(frozen=True)
class PriceHour:
    hour: int
    import_eur_kwh: float
    export_eur_kwh: float
    gas_eur_m3: float


def _clamp(value: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, value))


class WeatherSeries:
    """Select a committed recording; observations never consume forecast RNG."""

    def __init__(self, profile: ClimateProfile, rng: Rng, hours: int):
        self.profile, self.rng = profile, rng
        group = 'evaluation' if rng.seed in profile.evaluation_seeds else 'development'
        candidates = tuple(window for window in profile.windows if window.group == group)
        window = rng.stream('recorded-window').choice(candidates)
        if hours > len(window.rows):
            raise ValueError('recorded weather window is shorter than requested horizon')
        self.window_id = window.id
        self.start_utc = window.start_utc
        self.hours = tuple(WeatherHour(hour, *row[:4], row[4], profile.weather.outside_co2_ppm)
                           for hour, row in enumerate(window.rows[:hours]))
        daylight_solar = [row[1] for row in window.rows if row[4]]
        self._solar_scale_w_m2 = sum(daylight_solar) / len(daylight_solar) if daylight_solar else 0.0

    def at(self, hour: int) -> WeatherHour:
        return self.hours[hour]

    def forecast(self, issue_hour: int, hours: int) -> tuple[WeatherHour, ...]:
        if hours < 1 or issue_hour < 0 or issue_hour + hours >= len(self.hours):
            raise ValueError('forecast outside generated weather horizon')
        f = self.profile.forecast
        predicted = []
        for lead in range(1, hours + 1):
            actual = self.hours[issue_hour + lead]
            stream = self.rng.stream(f'weather-forecast/{issue_hour}/{lead}')
            scale = math.sqrt(lead / 24)
            temp = actual.temp_c + stream.normal(0, f.temp_sigma_at_24h_c * scale)
            solar = (max(0.0, actual.solar_w_m2 + stream.normal(
                0, self._solar_scale_w_m2 * f.solar_fraction_sigma_at_24h * scale))
                if actual.is_day else 0.0)
            wind = max(0.0, actual.wind_m_s + stream.normal(0, f.wind_sigma_at_24h_m_s * scale))
            rh = _clamp(actual.rh_pct + stream.normal(0, f.rh_sigma_at_24h_pct * scale), 0.0, 100.0)
            predicted.append(WeatherHour(actual.hour, temp, solar,
                                         wind, rh, actual.is_day, actual.outside_co2_ppm))
        return tuple(predicted)


class PriceSeries:
    """Recorded Dutch wholesale quotes transformed by published scenario tariffs."""

    def __init__(self, spec: EnergyPriceSpec, rng: Rng, hours: int, window_id: str | None = None):
        self.spec, self.rng = spec, rng
        group = 'evaluation' if rng.seed in spec.evaluation_seeds else 'development'
        candidates = tuple(window for window in spec.windows if window.group == group)
        if window_id is None:
            window = rng.stream('recorded-window').choice(candidates)
        else:
            window = next((item for item in candidates if item.id == window_id), None)
            if window is None:
                raise ValueError(f'price recording has no matching {group} window {window_id!r}')
        if hours > len(window.rows):
            raise ValueError('recorded price window is shorter than requested horizon')
        self.window_id = window.id
        self.start_utc = window.start_utc
        self.hours = tuple(PriceHour(hour, wholesale / 1000 + spec.tariff.import_markup_eur_kwh,
                                     wholesale / 1000 * spec.tariff.export_fraction, gas)
                           for hour, (wholesale, gas) in enumerate(window.rows[:hours]))
        self._wholesale_scale_eur_kwh = sum(abs(row[0]) for row in window.rows) / len(window.rows) / 1000

    def at(self, hour: int) -> PriceHour:
        return self.hours[hour]

    def forecast(self, issue_hour: int, hours: int, forecast_spec: ForecastSpec) -> tuple[PriceHour, ...]:
        if hours < 1 or issue_hour < 0 or issue_hour + hours >= len(self.hours):
            raise ValueError('forecast outside generated price horizon')
        predicted = []
        for lead in range(1, hours + 1):
            actual = self.hours[issue_hour + lead]
            stream = self.rng.stream(f'price-forecast/{issue_hour}/{lead}')
            wholesale = (actual.import_eur_kwh - self.spec.tariff.import_markup_eur_kwh +
                         stream.normal(0, self._wholesale_scale_eur_kwh *
                                       forecast_spec.price_fraction_sigma_at_24h * math.sqrt(lead / 24)))
            gas_stream = self.rng.stream(f'gas-forecast/{issue_hour}/{lead}')
            gas_factor = max(0.0, 1 + gas_stream.normal(0, forecast_spec.price_fraction_sigma_at_24h * math.sqrt(lead / 24)))
            predicted.append(PriceHour(actual.hour, wholesale + self.spec.tariff.import_markup_eur_kwh,
                                       wholesale * self.spec.tariff.export_fraction,
                                       actual.gas_eur_m3 * gas_factor))
        return tuple(predicted)
