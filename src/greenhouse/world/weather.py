"""Seeded winter weather and energy prices with read-stable forecasts."""
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
    """Future truth is generated once; observations never consume its RNG."""

    def __init__(self, profile: ClimateProfile, rng: Rng, hours: int):
        self.profile, self.rng = profile, rng
        w = profile.weather
        stream = rng.stream('weather')
        temp_state = cloud_state = 0.0
        result = []
        for hour in range(hours):
            clock = hour % 24
            is_day = w.sunrise_hour <= clock < w.sunset_hour
            # The warmest point follows the midday solar peak by a few hours.
            diurnal = w.diurnal_amplitude_c * math.cos(2 * math.pi * (clock - w.diurnal_peak_hour) / 24)
            temp_state = w.ar1_persistence * temp_state + stream.normal(0, w.innovation_sigma_c)
            cloud_state = w.cloud_persistence * cloud_state + stream.normal(0, w.cloud_innovation_sigma)
            phase = (clock - w.sunrise_hour) / (w.sunset_hour - w.sunrise_hour)
            clear = math.sin(math.pi * phase) if is_day else 0.0
            solar = w.solar_peak_w_m2 * clear * _clamp(w.clear_sky_fraction + cloud_state, w.min_solar_fraction, 1.0)
            wind = max(0.0, stream.normal(w.wind_mean_m_s, w.wind_sigma_m_s))
            rh = _clamp(stream.normal(w.rh_mean_pct, w.rh_sigma_pct), 25.0, 100.0)
            result.append(WeatherHour(hour, w.daily_mean_c + diurnal + temp_state,
                                      solar, wind, rh, is_day, w.outside_co2_ppm))
        self.hours = tuple(result)

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
            solar = max(0.0, actual.solar_w_m2 * (1 + stream.normal(0, f.solar_fraction_sigma_at_24h * scale)))
            wind = max(0.0, actual.wind_m_s + stream.normal(0, f.wind_sigma_at_24h_m_s * scale))
            rh = _clamp(actual.rh_pct + stream.normal(0, f.rh_sigma_at_24h_pct * scale), 0.0, 100.0)
            predicted.append(WeatherHour(actual.hour, temp, solar,
                                         wind, rh, actual.is_day, actual.outside_co2_ppm))
        return tuple(predicted)


class PriceSeries:
    """Hourly synthetic tariff with a capped export fraction of import price."""

    def __init__(self, spec: EnergyPriceSpec, rng: Rng, hours: int):
        self.spec, self.rng = spec, rng
        e = spec.electricity
        stream = rng.stream('prices/noise')
        spikes = [rng.stream(f'prices/spike/{day}').bernoulli(e.spike_probability_per_day)
                  for day in range((hours + 23) // 24)]
        result = []
        for hour in range(hours):
            clock = hour % 24
            peak = max(0.0, math.cos(2 * math.pi * (clock - e.daily_peak_hour) / 24))
            price = e.base_eur_kwh * (1 + e.daily_peak_multiplier * peak)
            if spikes[hour // 24]:
                price *= e.spike_multiplier
            price = max(0.0, price + stream.normal(0, e.noise_sigma_eur_kwh))
            result.append(PriceHour(hour, price, price * e.export_fraction, spec.gas_eur_m3))
        self.hours = tuple(result)

    def at(self, hour: int) -> PriceHour:
        return self.hours[hour]

    def forecast(self, issue_hour: int, hours: int, forecast_spec: ForecastSpec) -> tuple[PriceHour, ...]:
        if hours < 1 or issue_hour < 0 or issue_hour + hours >= len(self.hours):
            raise ValueError('forecast outside generated price horizon')
        predicted = []
        for lead in range(1, hours + 1):
            actual = self.hours[issue_hour + lead]
            stream = self.rng.stream(f'price-forecast/{issue_hour}/{lead}')
            factor = max(0.0, 1 + stream.normal(0, forecast_spec.price_fraction_sigma_at_24h * math.sqrt(lead / 24)))
            value = actual.import_eur_kwh * factor
            predicted.append(PriceHour(actual.hour, value, value * self.spec.electricity.export_fraction,
                                       actual.gas_eur_m3))
        return tuple(predicted)
