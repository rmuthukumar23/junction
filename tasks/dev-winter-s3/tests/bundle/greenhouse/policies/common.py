"""Shared helpers for scripted policies: reading tool results defensively.

Only tool results are used. Field names follow views.py and the business view
(world/business.py); a missing field means "not offered here", never an error,
so the same policy runs on the fakes and on the real modules.
"""
from __future__ import annotations

import math
from typing import Any

from envkit.policies import Client, Policy


def result(response: dict[str, Any]) -> dict[str, Any]:
    return response.get("result", {}) if response.get("ok") else {}


def midpoint(pair: Any, fallback: float) -> float:
    if isinstance(pair, (list, tuple)) and len(pair) == 2 and all(isinstance(x, (int, float)) for x in pair):
        return (float(pair[0]) + float(pair[1])) / 2.0
    return fallback


def import_prices(forecast: dict[str, Any], now_hour: int = 0) -> list[tuple[int, float]]:
    """(episode hour, electricity import price) per forecast hour, in forecast order.

    The real facility returns `energy_prices` as hourly rows with `hour` and
    `import_eur_kwh`. A plain list of numbers under a key with "price" in its name is
    read as the hours from `now_hour` on. Anything else gives an empty list ("no price
    forecast offered").
    """
    for key, rows in forecast.items():
        if "price" not in key or not isinstance(rows, list) or not rows:
            continue
        if all(isinstance(r, (int, float)) and not isinstance(r, bool) for r in rows):
            return [(now_hour + i, float(r)) for i, r in enumerate(rows)]
        if all(isinstance(r, dict) and isinstance(r.get("import_eur_kwh"), (int, float))
               and isinstance(r.get("hour"), int) for r in rows):
            return [(r["hour"], float(r["import_eur_kwh"])) for r in rows]
    return []


class Absentee(Policy):
    """Shows up every morning, reads the briefing, and changes nothing (spec 9). It must
    score about 0: the facility runs on its baseline exactly as if nobody were there."""

    name = "absentee"

    def run(self, client: Client) -> None:
        guard = 0
        while not client.done and guard < 5000:
            guard += 1
            if not client.call("submit_day", actions=[]).get("ok"):
                return


# The tools that count as actions under the daily turn, and the order a day plan sends
# them in when it cannot send them all (the most urgent first).
ACTIONS = ("book_contractor", "harvest", "plant", "place_order", "place_orders", "hire", "release",
           "cancel_order", "set_energy", "set_climate", "set_night_schedule")
SETTINGS = ("set_energy", "set_climate")


class DayPlan:
    """A day's actions, queued during the planning round and sent merged: all harvests in
    one call, all plantings in one, all orders in one, climate changes grouped by
    compartments that get the same change. Policies keep their one-call-per-thing code."""

    def __init__(self) -> None:
        self.harvest: list[str] = []
        self.plant: dict[str, float] = {}
        self.orders: dict[str, float] = {}
        self.climate: dict[str, dict[str, Any]] = {}
        self.energy: dict[str, Any] = {}
        self.other: list[tuple[str, dict[str, Any]]] = []
        self.night: dict[str, Any] | None = None

    def add(self, tool: str, args: dict[str, Any]) -> None:
        if tool == "harvest":
            ids = args.get("batch_ids") or [args.get("batch_id")]
            self.harvest += [b for b in ids if b and b not in self.harvest]
        elif tool == "plant":
            if "areas_m2" in args:
                for c, a in args["areas_m2"].items():
                    self.plant[c] = self.plant.get(c, 0.0) + float(a)
            else:
                c = args["compartment"]
                self.plant[c] = self.plant.get(c, 0.0) + float(args["area_m2"])
        elif tool in ("place_order", "place_orders"):
            pairs = args["orders"].items() if "orders" in args else [(args["item"], args["quantity"])]
            for item, q in pairs:
                self.orders[item] = self.orders.get(item, 0.0) + float(q)
        elif tool == "set_climate":
            changes = {k: v for k, v in args.items() if k not in ("compartment", "compartments")}
            targets = args.get("compartments") or ([args["compartment"]] if args.get("compartment") else ["*"])
            for c in targets:
                self.climate.setdefault(c, {}).update(changes)
        elif tool == "set_energy":
            for k, v in args.items():
                self.energy[k] = {**self.energy.get(k, {}), **v} if isinstance(v, dict) else v
        elif tool == "set_night_schedule":
            self.night = dict(args)
        else:
            self.other.append((tool, dict(args)))

    def calls(self) -> list[tuple[str, dict[str, Any]]]:
        """Merged calls, most urgent first; settings last, the night entry after them."""
        out: list[tuple[str, dict[str, Any]]] = [c for c in self.other if c[0] == "book_contractor"]
        if self.harvest:
            out.append(("harvest", {"batch_ids": list(self.harvest)}))
        if self.plant:
            out.append(("plant", {"areas_m2": {c: round(a, 1) for c, a in self.plant.items()}}))
        if self.orders:
            out.append(("place_orders", {"orders": dict(self.orders)}))
        out += [c for c in self.other if c[0] != "book_contractor"]
        if self.energy:
            out.append(("set_energy", dict(self.energy)))
        groups: dict[str, list[str]] = {}
        changes: dict[str, dict[str, Any]] = {}
        for c, ch in self.climate.items():
            key = repr(sorted(ch.items()))
            groups.setdefault(key, []).append(c)
            changes[key] = ch
        for key, comps in groups.items():
            args = dict(changes[key])
            if "*" not in comps:
                args["compartments"] = comps
            out.append(("set_climate", args))
        return out


class ToolPolicy(Policy):
    """Base: one planning round each morning under the daily turn (round 3): read the
    briefing, decide, send the day's actions merged within the day's limit (a night
    entry copying the day settings last, when they changed), end the day. Tools only."""

    night_policy = "daily"      # "daily": copy changed day settings to the night; "once": first day only; "never"

    def run(self, client: Client) -> None:
        # No read tools (round 3): the rules and the first briefing are what the player is
        # shown before its first call; every later briefing comes back when a day ends.
        self.client = client
        self.calls = 0
        opening = client.opening() or {}
        self.rules = opening.get("rules", {})
        self.briefing = opening.get("briefing", {})
        self.limit = int(self.rules.get("turn", {}).get("actions_per_day", 5))
        status = self.briefing.get("status")
        if not self.rules or not status:
            return
        self.plan = DayPlan()
        self.days = 0
        self.setup(status)
        guard = 0
        while not client.done and guard < 5000:
            guard += 1
            self.decide(status)
            if client.done:
                return
            briefing = self.send_day()
            if client.done or not briefing:
                return
            self.briefing = briefing
            status = briefing.get("status")
            if not status:
                return

    def send_day(self) -> dict[str, Any] | None:
        """Send the day's merged actions (at most the limit), then end the day if they
        did not. Returns the next morning's briefing."""
        plan, self.plan = self.plan, DayPlan()
        self.days += 1
        carry = DayPlan()
        wanted = plan.calls()
        night = plan.night
        copy = (self.night_policy == "daily" or (self.night_policy == "once" and self.days == 1))
        chosen: list[tuple[str, dict[str, Any]]] = []
        for tool, args in wanted:
            settings = tool in SETTINGS
            need = 1 + (1 if settings and copy and night is None
                        and not any(t in SETTINGS for t, _ in chosen) else 0)
            if len(chosen) + need + (1 if night is not None else 0) <= self.limit:
                chosen.append((tool, args))
            elif settings:                    # a setting that did not fit is tried again tomorrow
                carry.add(tool, args)
        if night is None and copy and any(t in SETTINGS for t, _ in chosen):
            night = {"from_hour": 18, "copy_day": True}
        if night is not None and len(chosen) < self.limit:
            chosen.append(("set_night_schedule", night))
        self.plan = carry
        r = self.real_call("submit_day", actions=[{"tool": tool, **args} for tool, args in chosen])
        return result(r).get("briefing") if r.get("ok") else None

    # -- hooks -------------------------------------------------------------------------

    def setup(self, status: dict[str, Any]) -> None:
        """Once, on the first morning."""

    def decide(self, status: dict[str, Any]) -> None:
        """Every decision point."""

    # -- calls -------------------------------------------------------------------------

    def call(self, tool: str, **args: Any) -> dict[str, Any]:
        """An action is queued for the day plan (and reported as accepted); a read is
        answered from the briefing."""
        if tool in ACTIONS:
            self.plan.add(tool, args)
            return {"ok": True, "result": {"queued": True}}
        return self.read(tool, **args)

    def read(self, tool: str, **args: Any) -> dict[str, Any]:
        """The old read tools, answered from what the player was shown."""
        b = getattr(self, "briefing", {}) or {}
        from ..views import rows                      # the briefing sends the forecast as columns
        hours = int(args.get("hours", 72))
        forecast = {k: v[:hours] if isinstance(v, list) else v for k, v in rows(b.get("forecast") or {}).items()}
        found = {"get_rules": self.rules, "get_status": b.get("status"),
                 "get_forecast": {"forecast": forecast}}.get(tool)
        return {"ok": found is not None, "result": found or {}}

    def real_call(self, tool: str, **args: Any) -> dict[str, Any]:
        self.calls += 1
        return self.client.call(tool, **args)

    # -- reading -----------------------------------------------------------------------

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


def contractor_for(rules: dict[str, Any], target: str) -> tuple[str, str | None] | None:
    """(trade, part item) of a contractor whose published `fixes` covers `target`, or None.
    An equipment id matches a kind when it equals it or ends with ".<kind>"."""
    table = rules.get("business", {}).get("contractors", {})
    rows = table.items() if isinstance(table, dict) else ((r.get("trade", ""), r) for r in table)
    for trade, row in rows:
        if not isinstance(row, dict):
            continue
        kinds = row.get("fixes", [])
        if any(target == k or target.endswith(f".{k}") for k in kinds):
            return str(trade), row.get("part")
    return None


def repair_damage(policy: Any, status: dict[str, Any]) -> None:
    """Book the trade for every outage without a booking and order the parts it needs
    that are neither in stock nor on order. Used by the rule-based and reference growers."""
    business = status.get("business", {})
    stock = business.get("stock", {})
    on_order: dict[str, float] = {}
    for o in business.get("open_orders", []):
        on_order[o.get("item")] = on_order.get(o.get("item"), 0.0) + float(o.get("quantity", 0.0))
    booked = {b.get("target") for b in business.get("contractor_bookings", []) if b.get("status") != "done"}
    need: dict[str, float] = {}
    for outage in business.get("outages", []):
        target = outage.get("equipment")
        found = contractor_for(policy.rules, target) if target else None
        if found is None:
            continue
        trade, _ = found
        if target not in booked and not outage.get("repair"):
            if policy.call("book_contractor", trade=trade, target=target).get("ok"):
                booked.add(target)
        for item, n in (outage.get("parts_needed") or {}).items():
            need[item] = need.get(item, 0.0) + float(n)
    for item, n in need.items():
        short = math.ceil(n - float(stock.get(item, 0.0)) - on_order.get(item, 0.0))
        if short > 0:
            rule = policy.rules.get("business", {}).get("items", {}).get(item, {})
            minimum = rule.get("min_quantity", 1) if isinstance(rule, dict) else 1
            policy.call("place_order", item=item, quantity=max(short, math.ceil(float(minimum or 1))))
