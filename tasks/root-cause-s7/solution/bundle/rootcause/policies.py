"""Observation-only comparator policies.

Each plays through a `Client`: it can list tools and call them, exactly like
an agent, and has no handle on the simulator. None reads hidden composition,
realized future weather or evaluator data.

  do-nothing   (envkit) never acts: every day runs the default plan
  stop-early   (envkit) plays the reference for the first days, then stops:
               the remaining days run the default plan
  absentee     advances every day without submitting a plan
  rule-based   the rules below: a level rule for water, an EC rule for
               fertilizer and flushing, no tests and no model
  reference    planner.Reference
"""
from __future__ import annotations

from typing import Any

from envkit.policies import Client, Policy

from .model import Params, transpiration_factor


class Attend(Policy):
    """Shows up every day and advances without deciding anything."""

    def run(self, client: Client) -> None:
        for _ in range(1000):
            if client.call("advance_day")["header"]["done"]:
                return


def submit_within_supply(client: Client, plan: dict[str, dict[str, float]], attempts: int = 6) -> bool:
    """Submit a plan. If it is rejected, shrink water use and try again, so a
    scripted policy never stalls on a rounding difference. Returns whether a
    plan was accepted; if not, the default plan will apply."""
    for _ in range(attempts):
        if client.call("submit_day_plan", zone_plans=plan)["ok"]:
            return True
        plan = {z: {"irrigation_l": round(zp["irrigation_l"] * 0.9, 1), "fertilizer_g": zp["fertilizer_g"],
                    "flush_l": round(zp["flush_l"] * 0.5, 1)} for z, zp in plan.items()}
    return False


class RuleBased(Policy):
    """What a grower might pin to the wall, using only the daily readings.

    Water:      top each zone back up to a fixed level, replacing what today's
                forecast says it will transpire; spread a shortage evenly.
    Fertilizer: by EC band. Low EC means feed more, high EC means feed less.
    Flush:      when EC is far above the stress threshold and the allocation
                still covers the rest of the season.

    It never tests, so it reads EC as if it were a nutrient gauge. That is
    right for a zone that is simply lean or simply rich, and wrong for a zone
    whose EC is mostly salt.
    """

    level = 0.75          # target volume as a share of capacity
    flush_l = 300.0

    def run(self, client: Client) -> None:
        rules = client.call("get_rules")["result"]
        p = Params.from_mapping(rules["parameters"])
        status = client.call("get_status")["result"]
        while not client.done:
            plan = self.plan(p, status)
            submit_within_supply(client, plan)
            response = client.call("advance_day")
            if client.done or not response["ok"]:
                return
            status = response["result"]["status"]

    def plan(self, p: Params, status: dict[str, Any]) -> dict[str, dict[str, float]]:
        temp = status["forecast_today_temp_c"]
        days_left = status["days_left"]
        water = status["fresh_water"]
        zones = status["zones"]
        demand = {z["zone_id"]: z["transpiration_base_l_per_day"] * transpiration_factor(p, temp) for z in zones}

        plan: dict[str, dict[str, float]] = {}
        for z in zones:
            zid, ec = z["zone_id"], z["ec_ds_m"]
            irrigation = min(p.irrigation_max_l, max(0.0, self.level * p.capacity_l + demand[zid] - z["volume_l"]))
            if ec < 2.4:
                fertilizer = 300.0
            elif ec < 2.9:
                fertilizer = 200.0
            elif ec < p.ec_threshold_ds_m:
                fertilizer = p.default_fertilizer_g
            else:
                fertilizer = 0.0
            plan[zid] = {"irrigation_l": irrigation, "fertilizer_g": fertilizer, "flush_l": 0.0}

        # Keep enough of the allocation to replace transpiration for the rest of the season.
        reserve = sum(demand.values()) * max(0, days_left - 1)
        spare = water["left_l"] - reserve - sum(zp["irrigation_l"] for zp in plan.values())
        room_today = water["available_today_l"] - sum(zp["irrigation_l"] for zp in plan.values())
        for z in sorted(zones, key=lambda z: -z["ec_ds_m"]):   # saltiest-looking zone first
            amount = min(self.flush_l, z["pumpable_l"])
            if z["ec_ds_m"] > p.ec_threshold_ds_m + 0.7 and amount <= min(spare, room_today) and days_left > 2:
                plan[z["zone_id"]]["flush_l"] = amount
                spare -= amount
                room_today -= amount

        need = sum(zp["irrigation_l"] + zp["flush_l"] for zp in plan.values())
        if need > water["available_today_l"] and need > 0:   # a shortage is shared in proportion
            scale = water["available_today_l"] / need
            for zp in plan.values():
                zp["irrigation_l"] *= scale
                zp["flush_l"] *= scale
        return {z: {k: int(v * 10) / 10.0 for k, v in zp.items()} for z, zp in plan.items()}
