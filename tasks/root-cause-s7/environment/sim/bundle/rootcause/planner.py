"""The reference policy: a receding-horizon planner on a state estimate.

It plays through the same tools as any player and uses only what they return:
the published rules, the morning readings, the forecast, and the results of
the tests it pays for. It is a strong comparator, not a proof of what is
optimal: it searches a small grid of candidate plans and plans against a
forecast, so a better player can beat it.

Estimate. The split of each zone's EC into nutrients and salts is not
observable, so on day 0 it orders one composition test per zone and acts on a
cautious guess until the results arrive. From then on it keeps its own copy of
each zone's nutrient and salt mass and rolls it forward every morning with the
published daily update (`model.step_zone`), its own plan, and the temperature
that the history reports for the day just played.

Plan. Every morning, for each zone, it scores a grid of candidates:

    flush today       x  nutrient level to hold  x  volume level to hold

by simulating its estimate of that zone to the end of the season under the
forecast (the seasonal normal beyond it) and adding up sales minus costs.
Zones share fresh water, so it then picks one candidate per zone to maximize
the total, subject to today's deliverable water and the allocation left. It
does that by raising an internal price on water, first for the season and
then for today, until the picks fit. Only today's part of the plan is
submitted; tomorrow it plans again from new readings.
"""
from __future__ import annotations

from typing import Any, NamedTuple

from envkit.policies import Client, Policy

from .model import Params, step_zone, transpiration_factor
from .policies import submit_within_supply

FLUSHES_L = (0.0, 150.0, 300.0, 450.0, 600.0)
NUTRIENT_LEVELS_G_L = (0.8, 1.0, 1.2, 1.4)                         # held at mid-day
VOLUME_LEVELS_L = (500.0, 650.0, 800.0, 950.0, 1100.0, 1250.0, 1400.0)   # held at the end of the day
WATER_PRICES = (0.0, 0.01, 0.02, 0.04, 0.07, 0.1, 0.15, 0.2, 0.3, 0.5, 0.8, 1.2, 2.0, 4.0)
PRIOR_SALT_G_L = 0.9   # the guess used before any test result exists


class Candidate(NamedTuple):
    value: float          # sales minus costs over the rest of the season, EUR
    water_today: float
    water_total: float
    irrigation_l: float   # today's part of the plan
    fertilizer_g: float
    flush_l: float


class Zone:
    """What the planner knows or believes about one zone this morning."""

    def __init__(self, zone_id: str, growth_max: float, transp_base: float):
        self.id, self.growth_max, self.transp_base = zone_id, growth_max, transp_base
        self.volume = self.condition = 0.0
        self.nutrient = self.salt = 0.0     # estimated masses, g
        self.tested = False


def day_plan(p: Params, transp_base: float, v: float, n: float, condition: float, temp: float,
             flush: float, nutrient_level: float, volume_level: float, last_day: bool) -> tuple[float, float]:
    """Irrigation and fertilizer that hold the two levels for one day."""
    demand = transp_base * transpiration_factor(p, temp) * (p.canopy_floor + (1.0 - p.canopy_floor) * condition)
    if last_day:   # water left in the loop after the last day is worth nothing
        volume_level = min(volume_level, p.comfort_volume_l - 0.3 * demand)
    irrigation = min(p.irrigation_max_l, p.capacity_l - v, max(0.0, volume_level + demand - v))
    irrigation = max(0.0, irrigation)
    n_after_flush = n * (1.0 - min(1.0, flush / v)) if v > 0 else n
    wanted = nutrient_level * (v + irrigation - 0.5 * demand)
    fertilizer = min(p.fertilizer_max_g, max(0.0, (wanted - n_after_flush) / (1.0 - p.fertilizer_ballast)))
    return irrigation, fertilizer


def rollout(p: Params, zone: Zone, temps: list[float], flush_today: float,
            nutrient_level: float, volume_level: float, day0: int = 0) -> Candidate:
    """Simulate the estimate of one zone to the end of the season."""
    v, n, s, h = zone.volume, zone.nutrient, zone.salt, zone.condition
    value = water_total = 0.0
    today = (0.0, 0.0, 0.0)
    last = len(temps) - 1
    for k, temp in enumerate(temps):
        flush = flush_today if k == 0 else 0.0
        irrigation, fertilizer = day_plan(p, zone.transp_base, v, n, h, temp, flush,
                                          nutrient_level, volume_level, k == last)
        r = step_zone(p, zone.growth_max, zone.transp_base, v, n, s, h, irrigation, fertilizer, flush, temp, day0 + k)
        water = irrigation + flush
        value += (p.price_per_kg * r.growth_kg - water * p.water_price_per_l
                  - fertilizer * p.fertilizer_price_per_g - (flush + r.overflow_l) * p.discharge_price_per_l)
        water_total += water
        if k == 0:
            today = (irrigation, fertilizer, flush)
        v, n, s, h = r.volume_l, r.nutrient_g, r.salt_g, r.condition
    return Candidate(value, today[0] + today[2], water_total, *today)


def candidates(p: Params, zone: Zone, temps: list[float], allow_flush: bool, day0: int = 0) -> list[Candidate]:
    pumpable = max(0.0, zone.volume - p.dead_volume_l)
    flushes = [f for f in FLUSHES_L if f <= pumpable] if allow_flush else [0.0]
    return [rollout(p, zone, temps, flush, level, volume, day0)
            for flush in flushes for level in NUTRIENT_LEVELS_G_L for volume in VOLUME_LEVELS_L]


def choose(options: dict[str, list[Candidate]], water_left: float, available_today: float) -> dict[str, Candidate]:
    """One candidate per zone, maximizing total value within both water limits."""
    picks: dict[str, Candidate] = {}
    for season_price in WATER_PRICES:
        for today_price in WATER_PRICES:
            picks = {z: max(cs, key=lambda c: c.value - season_price * c.water_total - today_price * c.water_today)
                     for z, cs in options.items()}
            if (sum(c.water_total for c in picks.values()) <= water_left + 1e-6
                    and sum(c.water_today for c in picks.values()) <= available_today + 1e-6):
                return picks
    return picks   # nothing fits: the caller scales the thriftiest picks down


class Reference(Policy):
    def run(self, client: Client) -> None:
        rules = client.call("get_rules")["result"]
        p = Params.from_mapping(rules["parameters"])
        zones = {z["zone_id"]: Zone(z["zone_id"], z["growth_max_kg_per_day"], z["transpiration_base_l_per_day"])
                 for z in rules["zones"]}
        status = client.call("get_status")["result"]
        for z in status["zones"]:
            zone = zones[z["zone_id"]]
            zone.volume, zone.condition = z["volume_l"], z["condition"]
            dissolved = z["ec_ds_m"] * z["volume_l"] / p.ec_per_g_l
            zone.salt = min(0.8 * dissolved, PRIOR_SALT_G_L * z["volume_l"])
            zone.nutrient = dissolved - zone.salt
            client.call("order_test", zone_id=zone.id, test_type="composition")

        journal: list[dict[str, Any]] = []   # per played day: what each zone looked like and what was applied
        while not client.done:
            forecast = client.call("get_forecast")["result"]
            if client.done:
                return
            days_left = status["days_left"]
            temps = [d["temp_c"] for d in forecast["days"]][:days_left]
            temps += [forecast["normal_temp_c"]] * (days_left - len(temps))
            options = {z.id: candidates(p, z, temps, z.tested, status["day"]) for z in zones.values()}
            water = status["fresh_water"]
            picks = choose(options, water["left_l"], water["available_today_l"])
            plan = {z: {"irrigation_l": c.irrigation_l, "fertilizer_g": c.fertilizer_g, "flush_l": c.flush_l}
                    for z, c in picks.items()}
            need = sum(zp["irrigation_l"] + zp["flush_l"] for zp in plan.values())
            if need > water["available_today_l"] and need > 0:
                scale = water["available_today_l"] / need
                for zp in plan.values():
                    zp["irrigation_l"] *= scale
                    zp["flush_l"] *= scale
            plan = {z: {k: int(v * 10) / 10.0 for k, v in zp.items()} for z, zp in plan.items()}   # round down
            submit_within_supply(client, plan)

            before = {z.id: (z.volume, z.condition) for z in zones.values()}
            response = client.call("advance_day")
            if not response["ok"]:
                return
            report = response["result"]
            journal.append({"temp": report["temp_c"], "before": before,
                            "plan": {r["zone_id"]: r["plan"] for r in report["zones"]}})
            self.update(p, zones, journal, report)
            status = report["status"]

    @staticmethod
    def update(p: Params, zones: dict[str, Zone], journal: list[dict[str, Any]], report: dict[str, Any]) -> None:
        """Bring every zone's estimate to this morning."""
        today = report["day"]
        results = {t["zone_id"]: t for t in report["tests_delivered"] if t["test_type"] == "composition"}
        readings = {z["zone_id"]: z for z in report["status"]["zones"]}
        for zone in zones.values():
            test = results.get(zone.id)
            if test is not None:
                # A result describes the sample day's morning. Start there and
                # replay every day since with the plans that were applied.
                r = test["result"]
                zone.nutrient, zone.salt = r["nutrient_g_l"] * r["volume_l"], r["salt_g_l"] * r["volume_l"]
                zone.tested = True
                first = test["sampled_day"]
            else:
                first = today - 1
            for day in range(first, today):
                entry = journal[day]
                volume, condition = entry["before"][zone.id]
                zp = entry["plan"][zone.id]
                step = step_zone(p, zone.growth_max, zone.transp_base, volume, zone.nutrient, zone.salt, condition,
                                 zp["irrigation_l"], zp["fertilizer_g"], zp["flush_l"], entry["temp"], day)
                zone.nutrient, zone.salt = step.nutrient_g, step.salt_g
            reading = readings[zone.id]
            zone.volume, zone.condition = reading["volume_l"], reading["condition"]
            if not zone.tested:
                # Without a test only the total is known: keep the nutrient
                # estimate and let the salt estimate absorb what EC reports.
                dissolved = reading["ec_ds_m"] * reading["volume_l"] / p.ec_per_g_l
                zone.salt = max(0.0, dissolved - zone.nutrient)
