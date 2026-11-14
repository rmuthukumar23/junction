"""The Depot world: one warehouse, a handful of items, customers who wait
only so long.

Customer orders arrive every window at a hidden per-item rate. The operator
ships them from stock, and restocks from a supplier with a lead time, a
per-order fee and limited cash. Orders not shipped by their deadline are
cancelled with a penalty. Stock left at the end is sold off at a fraction of
what it cost.

Hidden from the operator: the demand rates, and any scripted event delivered
on the rumored or silent channel.
"""
from __future__ import annotations

from typing import Annotated, Any

from envkit.core import Environment, ToolError, tool
from envkit.rng import Rng
from envkit.scenario import Event


class Depot(Environment):
    def setup(self) -> None:
        c = self.config
        self.cash = float(c["starting_cash"])
        self.order_fee = float(c.get("order_fee", 15.0))
        self.holding_rate = float(c.get("holding_rate", 0.01))
        self.deadline = int(c.get("order_deadline_windows", 2))
        self.penalty_rate = float(c.get("cancel_penalty_rate", 0.25))
        self.salvage_rate = float(c.get("salvage_rate", 0.3))

        self.items: dict[str, dict[str, Any]] = {}
        for item_id, spec in c["items"].items():
            self.items[item_id] = {
                "price": float(spec["price"]),
                "unit_cost": float(spec["unit_cost"]),
                "lead_windows": int(spec["lead_windows"]),
                "demand": float(spec["demand"]),  # hidden: mean units per window
                "on_hand": int(spec.get("stock", 0)),
            }
        self.incoming: list[dict[str, Any]] = []   # supplier shipments in transit
        self.open: list[dict[str, Any]] = []       # customer orders awaiting shipment
        self.history: list[dict[str, dict[str, int]]] = []  # per window: item -> ordered / shipped
        self.window = 0
        self.totals = {"ordered": 0, "shipped": 0, "cancelled": 0, "revenue": 0.0,
                       "purchases": 0.0, "holding": 0.0, "penalties": 0.0, "salvage": 0.0}
        self._demand_rng = self.rng.stream("demand")
        self._new_window_record()
        self._arrivals()

    # -- tools -------------------------------------------------------------------

    @tool
    def view_inventory(self) -> dict[str, Any]:
        """Stock on hand for every item, supplier shipments in transit with their arrival window, and units customers are waiting for."""
        out = {}
        for item_id, it in self.items.items():
            out[item_id] = {
                "on_hand": it["on_hand"],
                "in_transit": [{"qty": s["qty"], "arrives_window": s["arrives"] + 1}
                               for s in self.incoming if s["item"] == item_id],
                "open_order_units": sum(o["qty"] for o in self.open if o["item"] == item_id),
            }
        return {"items": out}

    @tool
    def view_orders(self) -> dict[str, Any]:
        """Open customer orders: item, units, and the last window in which each can still be shipped."""
        return {"orders": [{"item": o["item"], "qty": o["qty"], "ship_by_window": o["due"] + 1} for o in self.open]}

    @tool
    def view_catalog(self) -> dict[str, Any]:
        """Supplier terms and selling price for every item: current unit cost, lead time in windows, and the fee charged per purchase order."""
        return {
            "order_fee": self.order_fee,
            "items": {i: {"price": it["price"], "unit_cost": it["unit_cost"], "lead_windows": it["lead_windows"]}
                      for i, it in self.items.items()},
        }

    @tool
    def view_sales(self, last_n: Annotated[int, "How many recent windows to return (1-30)."] = 6) -> dict[str, Any]:
        """Units customers ordered and units shipped, per item, for recent windows. The current window is included and still in progress."""
        if not 1 <= last_n <= 30:
            raise ToolError("last_n must be between 1 and 30")
        first = max(0, len(self.history) - last_n)
        return {"windows": [{"window": first + k + 1, "items": rec}
                            for k, rec in enumerate(self.history[first:])]}

    @tool
    def ship_orders(self) -> dict[str, Any]:
        """Ship every open customer order that current stock can cover, oldest first. Partial shipment of an order is allowed. Returns units shipped and revenue."""
        shipped: dict[str, int] = {}
        revenue = 0.0
        for order in sorted(self.open, key=lambda o: o["placed"]):
            it = self.items[order["item"]]
            qty = min(order["qty"], it["on_hand"])
            if qty <= 0:
                continue
            it["on_hand"] -= qty
            order["qty"] -= qty
            shipped[order["item"]] = shipped.get(order["item"], 0) + qty
            revenue += qty * it["price"]
            self.history[-1][order["item"]]["shipped"] += qty
        self.open = [o for o in self.open if o["qty"] > 0]
        self.cash = round(self.cash + revenue, 2)
        self.totals["shipped"] += sum(shipped.values())
        self.totals["revenue"] = round(self.totals["revenue"] + revenue, 2)
        return {"shipped": shipped, "revenue": round(revenue, 2)}

    @tool
    def order_stock(self, item: Annotated[str, "Item id, as listed by view_catalog."],
                    qty: Annotated[int, "Units to buy."]) -> dict[str, Any]:
        """Buy stock from the supplier. Cash is charged now (units x unit cost + order fee); the goods arrive after the item's lead time."""
        it = self.items.get(item)
        if it is None:
            raise ToolError(f"unknown item '{item}'; items are {sorted(self.items)}")
        if qty < 1:
            raise ToolError("qty must be at least 1")
        cost = round(qty * it["unit_cost"] + self.order_fee, 2)
        if cost > self.cash:
            raise ToolError(f"not enough cash: this order costs {cost:.2f}, cash is {self.cash:.2f}")
        self.cash = round(self.cash - cost, 2)
        self.totals["purchases"] = round(self.totals["purchases"] + cost, 2)
        arrives = self.window + it["lead_windows"]
        self.incoming.append({"item": item, "qty": qty, "arrives": arrives, "cost": it["unit_cost"]})
        return {"item": item, "qty": qty, "charged": cost, "arrives_window": arrives + 1}

    # -- engine hooks ------------------------------------------------------------

    def apply_event(self, event: Event) -> str | None:
        p = event.params
        it = self.items[p["item"]]
        if event.kind == "demand_multiplier":
            it["demand"] *= float(p["factor"])
            return f"Demand for item {p['item']} is expected to run at about {p['factor']:g}x its recent level from now on."
        if event.kind == "cost_change":
            it["unit_cost"] = round(it["unit_cost"] * float(p["factor"]), 2)
            return f"The supplier has changed the unit cost of item {p['item']} to {it['unit_cost']:.2f}."
        if event.kind == "lead_time_change":
            it["lead_windows"] = int(p["windows"])
            return f"Supplier lead time for item {p['item']} is now {it['lead_windows']} windows."
        return super().apply_event(event)

    def on_window_end(self, window: int) -> None:
        # 1. Orders past their deadline are cancelled, with a penalty.
        for order in [o for o in self.open if o["due"] <= window]:
            penalty = round(order["qty"] * self.items[order["item"]]["price"] * self.penalty_rate, 2)
            self.cash = round(self.cash - penalty, 2)
            self.totals["penalties"] = round(self.totals["penalties"] + penalty, 2)
            self.totals["cancelled"] += order["qty"]
        self.open = [o for o in self.open if o["due"] > window]
        # 2. Stock held through the window costs money.
        holding = round(sum(it["on_hand"] * it["unit_cost"] for it in self.items.values()) * self.holding_rate, 2)
        self.cash = round(self.cash - holding, 2)
        self.totals["holding"] = round(self.totals["holding"] + holding, 2)
        # 3. The next window opens: supplier shipments land, new customer orders arrive.
        self.window = window + 1
        if self.window < self.shift.windows:
            for s in [s for s in self.incoming if s["arrives"] <= self.window]:
                self.items[s["item"]]["on_hand"] += s["qty"]
            self.incoming = [s for s in self.incoming if s["arrives"] > self.window]
            self._new_window_record()
            self._arrivals()

    def on_finish(self) -> None:
        # Leftover and undelivered stock is liquidated at a fraction of cost.
        value = sum(it["on_hand"] * it["unit_cost"] for it in self.items.values())
        value += sum(s["qty"] * s["cost"] for s in self.incoming)
        self.totals["salvage"] = round(value * self.salvage_rate, 2)
        self.cash = round(self.cash + self.totals["salvage"], 2)

    def header(self) -> dict[str, Any]:
        return {"cash": self.cash, "open_order_units": sum(o["qty"] for o in self.open)}

    def snapshot(self) -> dict[str, Any]:
        return {"cash": self.cash,
                "stock_units": sum(it["on_hand"] for it in self.items.values()),
                "open_order_units": sum(o["qty"] for o in self.open),
                "shipped_total": self.totals["shipped"], "cancelled_total": self.totals["cancelled"]}

    def ledger(self) -> dict[str, float | None]:
        t = self.totals
        return {
            "net_assets": self.cash,
            "business_raw": round(self.cash - float(self.config["starting_cash"]), 2),
            # Units shipped over units customers asked for. Zero if nobody ships.
            "on_time_rate": (t["shipped"] / t["ordered"]) if t["ordered"] else None,
            "units_ordered": t["ordered"], "units_shipped": t["shipped"], "units_cancelled": t["cancelled"],
            "revenue": t["revenue"], "purchases": t["purchases"], "holding_cost": t["holding"],
            "penalties": t["penalties"], "salvage": t["salvage"],
        }

    # -- scripted policies ---------------------------------------------------------

    @classmethod
    def policies(cls) -> dict[str, Any]:
        from .policies import Reference, RuleBased, ShipOnly
        return {"ship-only": ShipOnly, "rule-based": RuleBased, "reference": Reference}

    @classmethod
    def fuzz_args(cls, tool_name: str, rng: Rng) -> dict[str, Any] | None:
        if tool_name == "order_stock":
            return {"item": rng.choice(["A", "B", "C", "D", "E", "?"]), "qty": rng.randint(0, 80)}
        if tool_name == "view_sales":
            return {"last_n": rng.randint(1, 12)}
        return None

    # -- internals -----------------------------------------------------------------

    def _new_window_record(self) -> None:
        self.history.append({i: {"ordered": 0, "shipped": 0} for i in self.items})

    def _arrivals(self) -> None:
        for item_id, it in self.items.items():  # config order, so draws are reproducible
            qty = self._demand_rng.poisson(it["demand"])
            if qty > 0:
                self.open.append({"item": item_id, "qty": qty, "placed": self.window,
                                  "due": self.window + self.deadline - 1})
                self.history[-1][item_id]["ordered"] += qty
                self.totals["ordered"] += qty
