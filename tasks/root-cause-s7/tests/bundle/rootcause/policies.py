"""Observation-only comparator policies.

Each plays through a `Client`: it can list tools and call them, exactly like
an agent, and has no handle on the simulator.

  do-nothing   (envkit) never acts: every day runs the default plan
  stop-early   (envkit) plays the reference for the first days, then stops
  absentee     advances every day without submitting a plan
  ec-rules     a grower's EC rules: feed less when EC is high, flush when it
               is very high, never test, never touch the reserve
  blind        planner.Blind: a good planner that ignores the notice
  reference    planner.Reference: diagnoses, then plans
"""
from __future__ import annotations

from typing import Any

from envkit.policies import Client, Policy

from .model import Params, demand_l


class Attend(Policy):
    """Shows up every day and advances without deciding anything."""

    def run(self, client: Client) -> None:
        for _ in range(100):
            if client.call("advance_day")["header"]["done"]:
                return


class ECRules(Policy):
    """What a grower might pin to the wall, using only the morning EC.

    Top-up:     bring each bench back to a fixed level with mains water.
    Fertilizer: by EC band. Below target feed more; above target feed less;
                well above it stop feeding.
    Flush:      300 L when EC is far above the stress threshold.

    It reads EC as a nutrient gauge. Before the incident that is right. After
    it, the rise in EC is salt from the new water, so this rule cuts feeding
    exactly when the crop needs it, and flushes with the salty water itself.
    """

    level_l = 900.0

    def run(self, client: Client) -> None:
        rules = client.call("get_rules")["result"]
        p = Params.from_mapping(rules["parameters"])
        status = client.call("get_status")["result"]
        while not client.done:
            client.call("submit_day_plan", bench_plans=self.plan(p, status))
            response = client.call("advance_day")
            if client.done or not response["ok"]:
                return
            status = response["result"]["status"]

    def plan(self, p: Params, status: dict[str, Any]) -> dict[str, dict[str, float]]:
        temp = status["forecast_c"][0]["temp_c"]
        plan = {}
        for b in status["benches"]:
            ec = b["ec_ds_m"]
            demand = demand_l(p, b["transpiration_base_l_per_day"], temp, b["condition"])
            top_up = min(p.top_up_max_l, max(0.0, self.level_l + demand - b["volume_l"]))
            if ec < 1.4:
                fertilizer = 180.0
            elif ec < 1.7:
                fertilizer = 120.0
            elif ec < 2.1:
                fertilizer = 60.0
            else:
                fertilizer = 0.0
            flush = min(300.0, b["pumpable_l"]) if ec > p.ec_threshold_ds_m + 0.6 else 0.0
            plan[b["bench_id"]] = {"mains_l": round(top_up, 1), "reserve_l": 0.0, "fertilizer_g": fertilizer,
                                   "flush_l": round(flush, 1)}
        return plan
