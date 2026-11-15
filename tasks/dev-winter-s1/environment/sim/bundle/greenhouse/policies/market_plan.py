"""The reference's market planning: when to cut a ready crop and how much to sow, for crops
sold by weight against a published weekly demand (rules.business.demand).

Everything here is computed from the published rule: buyers take the week's demand at
full price in any rolling `window_h` hours, the price then falls linearly to 0 at
`glut_at` x demand, and the demand in force at a sale is demand_per_week x the factor of
the episode week the sale falls in. The planner keeps its own log of what it sold (hour,
kg), so it can price a sale on any future hour exactly as the market will.

Two decisions follow:

  * Cut timing. Each morning the ready batches are taken most urgent first (least time
    left in the top grade). For each, every hour it could still be sold at (today, or a
    later morning while it keeps a grade) is priced against the log plus the sales already
    planned for more urgent batches; it is cut today only if today is the best of them.
  * Sowing in bursts. Selling a week's demand at once and then nothing until the window
    has cleared earns the full price for the whole demand; a steady stream into a week
    that follows a big one sells into the window's glut. So each target week gets one
    sowing, sized to that week's demand, timed to be ready as the week starts (or as soon
    after as the seed lead time allows).
"""
from __future__ import annotations

import math
from typing import Any


class MarketPlan:
    # -- policy choices (tuned on development seeds 4-6) --
    burst_over = 1.1              # sow for this multiple of a week's demand (selling a little into the glut pays)
    burst_yield = 1.2             # expected kg per m2 at the cut, as a share of ready weight x sowing density
    grow_frac = 0.65              # sow-to-ready time as a share of nominal days, until the crop's own is measured
    grade_safety_days = 0.3       # treat a batch as this much older when checking it keeps a grade
    ready_lead_days = 0.5         # aim to be ready this long before the target week starts
    max_hold_days = 6             # look this many mornings ahead when timing a cut
    end_sale_margin_days = 0.5    # the last burst sells at least this long before the end
    late_in_week = 0.01           # a burst's value falls this share per day it sells into its week (slack for late ripening)
    sale_hour = 12                # hour of day a burst cut at the 06:00 round is sold by

    # -- the published market rule --------------------------------------------------------------

    def demand_rules(self) -> dict[str, Any]:
        return self.rules.get("business", {}).get("demand", {}) or {}

    def week_demand(self, crop_id: str, week: int) -> float | None:
        d = self.demand_rules()
        base = (d.get("demand_per_week") or {}).get(crop_id)
        if not base:
            return None
        base = sum(base) / 2 if isinstance(base, list) else float(base)
        factors = (d.get("week_factors") or {}).get(crop_id) or [1.0]
        return base * float(factors[min(max(week, 0), len(factors) - 1)])

    def window_h(self) -> int:
        return int(self.demand_rules().get("window_h", 168))

    def price_share(self, crop_id: str, hour: float, kg: float, log: list[tuple[float, float]]) -> float:
        """Average share of the list price `kg` sold at `hour` would fetch, given sales `log`."""
        demand = self.week_demand(crop_id, int(hour // self.window_h()))
        if not demand or kg <= 0:
            return 1.0
        before = sum(q for h, q in log if hour - self.window_h() < h <= hour)
        span = (float((self.demand_rules().get("glut_at") or {}).get(crop_id, 2.0)) - 1.0) * demand

        def area(x: float) -> float:
            x = max(0.0, x)
            if x <= demand:
                return x
            y = min(x, demand + span) - demand
            return demand + y - y * y / (2 * span)
        return (area(before + kg) - area(before)) / kg

    def sells_by_demand(self, crop_id: str) -> bool:
        crop = self.crops.get(crop_id, {})
        return (crop.get("market", {}).get("unit") == "kg" and crop.get("cycle", {}).get("harvest_mode") == "single"
                and self.week_demand(crop_id, 0) is not None)

    # -- cut timing ---------------------------------------------------------------------------------

    @property
    def sold(self) -> dict[str, list[tuple[float, float]]]:
        if not hasattr(self, "_sold"):
            self._sold = {}
        return self._sold

    def grade_factor(self, crop: dict[str, Any], quality: float) -> float:
        for g in crop["market"]["grades"]:
            if quality >= float(g["min_quality"]):
                return float(g.get("price_factor", 0.0))
        return 0.0

    def market_cuts(self, status: dict[str, Any], hour: int, standing: list[dict[str, Any]],
                    backlog: float) -> float:
        """Cut the ready by-weight batches whose best sale hour is today; returns the new backlog."""
        staff = status["business"].get("staff", {})
        crew = max(1, self.crew_at(staff, hour))
        ready = [b for b in standing if b["status"] == "ready" and self.sells_by_demand(b["crop"])]

        def quality(b: dict[str, Any]) -> float:
            # The estimate is noisy; since the ready alarm the quality falls at the published rate.
            q = float(b.get("estimate", {}).get("quality") or 1.0)
            if b["id"] in self.ready_hour:
                q = min(q, 1.0 - loss(b) * (hour - self.ready_hour[b["id"]]) / 24.0)
            return q

        def loss(b: dict[str, Any]) -> float:
            return float(self.crops[b["crop"]]["stress"].get("ready_loss_per_day", 0.0))
        # Most urgent first: least time left in the top grade.
        top = {b["id"]: float(self.crops[b["crop"]]["market"]["grades"][0]["min_quality"]) for b in ready}
        ready.sort(key=lambda b: (quality(b) - top[b["id"]]) / max(1e-9, loss(b)))
        log = {c: list(v) for c, v in self.sold.items()}
        for b in ready:
            crop = self.crops[b["crop"]]
            kg = float(b.get("estimate", {}).get("units", 0.0))
            work = self.harvest_hours(b)
            best_d, best_v, best_t = -1, 0.0, 0.0
            for d in range(self.max_hold_days + 1):
                if d == 0:
                    t = self.finish_hour(staff, hour, backlog + work)
                else:
                    t = hour + 24 * d + math.ceil(work / crew)
                if t >= self.horizon:
                    break
                q = quality(b) - loss(b) * ((t - hour) / 24.0 + self.grade_safety_days)
                v = kg * self.grade_factor(crop, q) * self.price_share(
                    b["crop"], t, kg, log.get(b["crop"], []))
                if v > best_v * 1.005 or best_d < 0:
                    best_d, best_v, best_t = d, v, t
            if best_d < 0:
                best_d, best_t = 0, float(hour)
            log.setdefault(b["crop"], []).append((best_t, kg))
            if best_d == 0 and self.call("harvest", batch_id=b["id"]).get("ok"):
                backlog += work
                b["harvest_queued"] = True
                self.sold.setdefault(b["crop"], []).append((best_t, kg))
        return backlog

    # -- sowing in bursts ------------------------------------------------------------------------

    @property
    def grow_seen(self) -> dict[str, list[float]]:
        if not hasattr(self, "_grow_seen"):
            self._grow_seen = {}
        return self._grow_seen

    def grow_days(self, crop_id: str) -> float:
        seen = sorted(self.grow_seen.get(crop_id, []))
        if seen:
            return seen[len(seen) // 2]
        return float(self.crops[crop_id]["cycle"]["nominal_days"]) * self.grow_frac

    def watch_growth(self, status: dict[str, Any], hour: int) -> None:
        """Sow-to-ready days of its own sowings: a batch first seen after a planting call in
        its compartment was sown by that call; its ready alarm ends the count."""
        if not hasattr(self, "_born"):
            self._born = {b["id"]: None for b in status["batches"]}
            self._planted_at: dict[str, int] = {}
        for b in status["batches"]:
            if b["id"] not in self._born:
                self._born[b["id"]] = self._planted_at.get(b["compartment"])
            sown = self._born[b["id"]]
            if sown is not None and b["status"] == "ready" and b["id"] in self.ready_hour:
                self.grow_seen.setdefault(b["crop"], []).append((self.ready_hour[b["id"]] - sown) / 24.0)
                self._born[b["id"]] = None

    def note_planting(self, compartment: str, hour: int) -> None:
        if hasattr(self, "_planted_at"):
            self._planted_at[compartment] = hour

    def kg_per_m2(self, crop_id: str) -> float:
        crop = self.crops[crop_id]
        return float(crop["cycle"]["ready_fresh_weight_g"]) * float(crop["planting"]["density_per_m2"]) / 1000.0 * self.burst_yield

    @property
    def burst_fixed(self) -> dict[tuple[str, int], float]:
        if not hasattr(self, "_burst_fixed"):
            self._burst_fixed = {}
        return self._burst_fixed

    def load(self, crop_id: str, hour: float, events: list[tuple[float, float]]) -> float:
        return sum(q for t, q in events if hour - self.window_h() < t <= hour)

    def burst_plan(self, crop_id: str, hour: float) -> list[tuple[float, float]]:
        """The bursts still to sow, as (sale hour, kg): the set of mornings at least one window
        apart, none before a sowing today could be ready, that sells the most at full price
        given what was sold and what is already sown (a small dynamic programme over days;
        each burst sells the demand in force on its day less the window's load). A burst is
        worth a little less for each day into its week: one that ripens late still sells in it."""
        w_h = self.window_h()
        days = w_h // 24
        events = list(self.sold.get(crop_id, [])) + [
            (at, (self.week_demand(crop_id, int(at // w_h)) or 0.0) * self.burst_over)
            for (c, _), at in self.burst_fixed.items() if c == crop_id and at > hour]
        first = hour + 24.0 * (self.grow_days(crop_id) - self.ready_lead_days)
        last_fixed = max((at for (c, _), at in self.burst_fixed.items() if c == crop_id), default=-1e9)
        first = max(first, last_fixed + w_h - 1)
        last = min(self.horizon - 24.0 * self.end_sale_margin_days,     # sold in time, and sown while allowed
                   self.plant_deadline(self.crops[crop_id]) + 24.0 * (self.grow_days(crop_id) + self.ready_lead_days))
        grid = [24.0 * d + self.sale_hour for d in range(int(self.horizon // 24))
                if first <= 24.0 * d + self.sale_hour <= last]
        if not grid:
            return []
        value = [max(0.0, (self.week_demand(crop_id, int(t // w_h)) or 0.0) - self.load(crop_id, t, events))
                 * (1.0 - self.late_in_week * ((t // 24) % days)) for t in grid]
        best = [0.0] * (len(grid) + days + 1)
        take = [False] * len(grid)
        for i in range(len(grid) - 1, -1, -1):
            with_it = value[i] + best[i + days]
            take[i] = with_it > best[i + 1] + 1e-6
            best[i] = with_it if take[i] else best[i + 1]
        out, i = [], 0
        while i < len(grid):
            if take[i]:
                out.append((grid[i], value[i]))
                i += days
            else:
                i += 1
        return out

    def sow_today(self, crop_id: str, hour: float) -> tuple[float, float] | None:
        """(sale hour, kg) of the burst to sow this morning: the first planned burst, if a
        sowing tomorrow would no longer be ready for it."""
        plan = self.burst_plan(crop_id, hour)
        if not plan:
            return None
        at, kg = plan[0]
        too_late_tomorrow = hour + 24.0 > self.plant_deadline(self.crops[crop_id])
        if at < hour + 24.0 * (1 + self.grow_days(crop_id) - self.ready_lead_days) or too_late_tomorrow:
            return max(at, hour + 24.0 * self.grow_days(crop_id)), kg
        return None

    def burst_area(self, crop_id: str, hour: float) -> float:
        """Bench area still to sow this morning (one burst may take several compartments)."""
        today = getattr(self, "_today", {}).get(crop_id)
        if today is None or today[0] != hour:
            t = self.sow_today(crop_id, hour)
            if t is None:
                return 0.0
            today = (hour, t[0], t[1] * self.burst_over / self.kg_per_m2(crop_id), 0.0)
            self._today = {**getattr(self, "_today", {}), crop_id: today}
        return max(0.0, today[2] - today[3])

    def record_sowing(self, crop_id: str, hour: float, area: float) -> None:
        today = getattr(self, "_today", {}).get(crop_id)
        if today is not None and today[0] == hour:
            self._today[crop_id] = (hour, today[1], today[2], today[3] + area)
            self.burst_fixed[(crop_id, int(today[1]))] = today[1]

    def seed_plan(self, crop_id: str, hour: float, days: int) -> float:
        """Area the burst plan will sow over the next `days` mornings (from today)."""
        until = hour + 24.0 * (days + self.grow_days(crop_id))
        return sum(kg * self.burst_over / self.kg_per_m2(crop_id)
                   for at, kg in self.burst_plan(crop_id, hour) if at <= until)
