"""Shared helpers for scripted policies: reading tool results defensively.

Only tool results are used. Field names follow views.py and the business view
(world/business.py); a missing field means "not offered here", never an error,
so the same policy runs on the fakes and on the real modules.
"""
from __future__ import annotations

from typing import Any

from envkit.policies import Client, Policy


def result(response: dict[str, Any]) -> dict[str, Any]:
    return response.get("result", {}) if response.get("ok") else {}


def midpoint(pair: Any, fallback: float) -> float:
    if isinstance(pair, (list, tuple)) and len(pair) == 2 and all(isinstance(x, (int, float)) for x in pair):
        return (float(pair[0]) + float(pair[1])) / 2.0
    return fallback


class ToolPolicy(Policy):
    """Base: a daily loop of read -> decide -> advance, through tools only."""

    advance_h = 24          # policy choice: decide once a simulated day (advance stops earlier on alarms)

    def run(self, client: Client) -> None:
        self.client = client
        self.rules = result(client.call("get_rules"))
        self.setup(result(client.call("get_status")))
        guard = 0
        while not client.done and guard < 5000:
            guard += 1
            status = result(client.call("get_status"))
            if not status:
                return
            self.decide(status)
            if client.done:
                return
            r = client.call("advance", hours=self.advance_h)
            if not r.get("ok"):
                return

    # -- hooks -------------------------------------------------------------------------

    def setup(self, status: dict[str, Any]) -> None:
        """Once, at hour 0."""

    def decide(self, status: dict[str, Any]) -> None:
        """Every decision point."""

    # -- reading -----------------------------------------------------------------------

    def call(self, tool: str, **args: Any) -> dict[str, Any]:
        return self.client.call(tool, **args)

    def crop_of(self, status: dict[str, Any]) -> dict[str, str]:
        """Compartment -> crop id, from the batches it holds."""
        out: dict[str, str] = {}
        for b in status.get("batches", []):
            out.setdefault(b["compartment"], b["crop"])
        return out

    def targets(self, crop_id: str) -> dict[str, Any]:
        crop = self.rules.get("crops", {}).get(crop_id, {})
        return crop.get("climate_targets", {}) if isinstance(crop, dict) else {}

    def item_rule(self, item: str) -> dict[str, Any]:
        return self.rules.get("business", {}).get("items", {}).get(item, {})

    def min_order(self, item: str, fallback: float) -> float:
        q = self.item_rule(item).get("min_quantity")
        return float(q) if isinstance(q, (int, float)) and q > 0 else fallback

    def lead_time_h(self, item: str, fallback: float) -> float:
        lt = self.item_rule(item).get("lead_time_h")
        if isinstance(lt, list):              # a published range: plan for the slow end
            lt = max(lt)
        return float(lt) if isinstance(lt, (int, float)) else fallback

    @staticmethod
    def co2_store(status: dict[str, Any]) -> float | None:
        v = status.get("readings", {}).get("energy_centre", {}).get("co2_store_kg")
        return float(v) if isinstance(v, (int, float)) else None

    @staticmethod
    def business(status: dict[str, Any]) -> dict[str, Any]:
        return status.get("business", {})

    def open_orders(self, status: dict[str, Any], item: str) -> list[dict[str, Any]]:
        return [o for o in self.business(status).get("open_orders", []) if o.get("item") == item]

    def seedlings(self, status: dict[str, Any], crop_id: str) -> float:
        b = self.business(status)
        stock = b.get("stock", {}).get(f"seedlings:{crop_id}")
        if stock is None:                       # the fake business reports seedlings by crop
            stock = b.get("seedlings", {}).get(crop_id, 0)
        return float(stock)

    def harvest_ready(self, status: dict[str, Any]) -> None:
        for b in status.get("batches", []):
            if b.get("status") == "ready" and not b.get("harvest_queued"):
                self.call("harvest", batch_id=b["id"])
