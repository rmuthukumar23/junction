"""Scripted policies for the Depot world, weakest to strongest.

Each one plays through the tools only. The gap between `rule-based` and
`reference` is the kind of gap an agent has to close: estimating demand from
its own sales, reacting to news, and not buying stock it cannot sell before
the horizon ends.
"""
from __future__ import annotations

from envkit.policies import Client, Policy


class ShipOnly(Policy):
    """Ships what the opening stock covers and never restocks."""

    def run(self, client: Client) -> None:
        while not client.done:
            client.call("ship_orders")
            client.call("end_window")


class RuleBased(Policy):
    """A fixed reorder point and a fixed order quantity for every item."""

    reorder_point = 25
    order_qty = 40

    def run(self, client: Client) -> None:
        while not client.done:
            client.call("ship_orders")
            items = client.call("view_inventory")["result"]["items"]
            for item_id, it in items.items():
                position = it["on_hand"] + sum(s["qty"] for s in it["in_transit"])
                if position < self.reorder_point and not client.done:
                    client.call("order_stock", item=item_id, qty=self.order_qty)
            if not client.done:
                client.call("end_window")


class Reference(Policy):
    """Base-stock ordering on estimated demand.

    Each window: read any news, ship, look at stock and recent sales, then
    order each profitable item up to (estimated demand per window) x (lead
    time + cover). It stops buying what would arrive too late to sell.
    """

    cover_windows = 3

    def run(self, client: Client) -> None:
        catalog = client.call("view_catalog")["result"]
        while not client.done:
            head = client.last_header
            if head["unread_alerts"]:
                client.call("read_alerts")
                catalog = client.call("view_catalog")["result"]  # news may mean new costs or lead times
            client.call("ship_orders")
            items = client.call("view_inventory")["result"]["items"]
            sales = client.call("view_sales", last_n=5)["result"]["windows"]
            head = client.last_header
            if head["done"]:
                return
            window, total, cash = head["window"], head["windows_total"], head["cash"]

            plans = []
            for item_id, it in items.items():
                terms = catalog["items"][item_id]
                margin = terms["price"] - terms["unit_cost"]
                if margin <= 0:
                    continue
                # Recent windows weigh more, so a shift in demand shows up within a few windows.
                closed = [w["items"][item_id]["ordered"] for w in sales if w["window"] < window]
                recent = closed[-4:] or [sales[-1]["items"][item_id]["ordered"]]
                weights = list(range(1, len(recent) + 1))
                rate = sum(q * w for q, w in zip(recent, weights)) / sum(weights)
                lead = terms["lead_windows"]
                sellable = total - (window + lead) + 1  # windows left once this order lands
                if sellable <= 0 or rate <= 0:
                    continue
                target = rate * (lead + min(self.cover_windows, sellable))
                position = it["on_hand"] + sum(s["qty"] for s in it["in_transit"]) - it["open_order_units"]
                qty = int(round(target - position))
                # Small top-ups are not worth the order fee.
                if qty * margin > 3 * catalog["order_fee"] and qty >= rate:
                    plans.append((margin / terms["unit_cost"], item_id, qty, terms["unit_cost"]))

            for _, item_id, qty, unit_cost in sorted(plans, reverse=True):  # best return on cash first
                affordable = int((cash - catalog["order_fee"]) // unit_cost)
                qty = min(qty, affordable)
                if qty < 1 or client.done:
                    continue
                r = client.call("order_stock", item=item_id, qty=qty)
                cash = r["header"]["cash"]
            if not client.done:
                client.call("end_window")
