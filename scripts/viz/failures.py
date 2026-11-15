"""Failure modes on a short stretch of play (the phone challenge: one day, or a few).

The season-long flags in scripts/analyze_runs.py need 42 days. These read the same three
patterns off two mornings: the briefing each morning, the actions sent, what the simulator
did with them, and the market loss the business ledger counted in between. They run on the
player's two days and on the model's two recorded days from the same state, so both are
judged by the same tests. Every flag carries its evidence; none feeds a score.
"""
from __future__ import annotations

from typing import Any

PATTERNS = {
    "constraints": "Missing interacting constraints",
    "revising": "Not revising after new information",
    "tracking": "Losing track of unfinished work",
    "mechanics": "Action mechanics",
}


def _units(v: Any) -> float:
    if isinstance(v, dict):
        return float(v.get("units", 0.0) or 0.0)
    return float(v or 0.0)


def _ready(b: dict) -> bool:
    e = b.get("estimate") or {}
    return b.get("status") == "ready" or (b.get("status") == "growing" and (e.get("days_to_ready") if e.get("days_to_ready") is not None else 9) <= 0.05)


def _demand_now(rules: dict, crop: str, hour: int) -> float:
    d = rules["business"]["demand"]
    f = d["week_factors"].get(crop) or [1.0]
    return float(d["demand_per_week"].get(crop, 0.0)) * f[min(hour // 168, len(f) - 1)]


def _refusals(results: list | None) -> list[str]:
    out = []
    for r in results or []:
        if not r.get("ok"):
            out.append(f"{r.get('tool')}: {str(r.get('error', ''))[:120]}")
        for k, v in ((r.get("result") or {}).get("refused") or {}).items():
            out.append(f"{r.get('tool')} {k}: {str(v if isinstance(v, str) else v)[:120]}")
    return out


def detect(rules: dict, days: list[dict[str, Any]], end_briefing: dict | None) -> list[dict[str, Any]]:
    """days: [{"briefing", "actions", "results", "market_loss_eur"}] for each morning played."""
    flags: list[dict[str, Any]] = []

    def flag(key: str, pattern: str, text: str, day: int) -> None:
        flags.append({"key": key, "pattern": pattern, "pattern_name": PATTERNS[pattern], "text": text, "day": day})

    crops_of = {}
    for d in days:
        for b in d["briefing"]["status"].get("batches", []):
            crops_of[b["compartment"]] = b["crop"]

    for i, d in enumerate(days):
        b, acts, res = d["briefing"], d["actions"] or [], d["results"] or []
        st, day = b["status"], b["clock"]["day"]
        tools = [a.get("tool") for a in acts]
        harvested = {x for a in acts if a.get("tool") == "harvest" for x in a.get("batch_ids", [])}
        # 1. selling above the rolling week's demand (the business ledger's own count)
        if d.get("market_loss_eur", 0.0) > 500:
            flag("full_window", "constraints",
                 f"Sold above this week's demand: €{d['market_loss_eur']:,.0f} of produce went at a crashed price.", day)
        # 2. planting with no seed in stock
        for r in _refusals(res):
            if r.startswith("plant") and "seed" in r:
                flag("no_seed", "tracking", f"Tried to plant with no seed in stock ({r}). Seed takes 10 days.", day)
            elif not r.startswith("plant"):
                flag("refused", "mechanics", f"Refused: {r}", day)
        # 3. a morning sat out while work was waiting
        ready = [x for x in st.get("batches", []) if _ready(x) and not x.get("harvest_queued")]
        free = {c: a for c, a in (st.get("free_area_m2") or {}).items() if a > 1}
        if not acts and (ready or free):
            flag("idle", "revising", f"Did nothing on day {day} with {len(ready)} crop(s) ready and "
                 f"{len(free)} empty bench(es).", day)
        # 4. a ready crop left standing while its week still had room at full price
        if i == len(days) - 1:
            first = {x["id"] for x in days[0]["briefing"]["status"].get("batches", []) if _ready(x)}
            all_cut = {x for dd in days for a in (dd["actions"] or []) if a.get("tool") == "harvest" for x in a.get("batch_ids", [])}
            word = "both mornings" if len(days) > 1 else "this morning"
            sold = st["business"].get("sold_last_7_days") or {}
            for x in st.get("batches", []):
                if x["id"] in first and _ready(x) and not x.get("harvest_queued") and x["id"] not in all_cut:
                    room = _demand_now(rules, x["crop"], b["clock"]["hour"]) - _units(sold.get(x["crop"]))
                    if room > 0.5 * (x.get("estimate") or {}).get("units", 0):
                        flag("left_standing", "revising",
                             f"{x['id']} was ready {word} and this week still had room for it at full price; "
                             "its grade drops about 2 days after it is ready.", day)
        _ = tools, harvested
    # 5. seed pipeline: benches free up within the 10-day lead time, and no seed is in stock or coming
    if end_briefing:
        b0 = days[0]["briefing"]["status"]
        biz = end_briefing["status"]["business"]
        lead = 10.0
        ordered = {k for d in days for a in (d["actions"] or []) if a.get("tool") == "place_orders"
                   for k in list((a.get("orders") or {}).keys()) + [o.get("item") for o in a.get("order_list") or []]}
        coming = {o["item"] for o in biz.get("open_orders", [])} | ordered
        for crop in sorted(set(crops_of.values())):
            item = "seedlings:" + crop
            soon = [x for x in b0.get("batches", []) if x["crop"] == crop and x["status"] != "harvested"
                    and ((x.get("estimate") or {}).get("days_to_ready") or 0) <= lead]
            if soon and biz["stock"].get(item, 0) <= 0 and item not in coming:
                flag("no_pipeline", "tracking",
                     f"{len(soon)} {crop.split('_')[0]} bench(es) come free within 10 days, and no {crop.split('_')[0]} seed is "
                     "in stock or on order: seed takes 10 days, so they will stand empty.", end_briefing["clock"]["day"])
    # 6. empty benches with no seed coming (checked on the morning after the last day played)
    if end_briefing:
        st = end_briefing["status"]
        biz = st["business"]
        coming = {o["item"] for o in biz.get("open_orders", [])}
        for c, area in (st.get("free_area_m2") or {}).items():
            crop = crops_of.get(c)
            if not crop or area < 50:
                continue
            item = "seedlings:" + crop
            if biz["stock"].get(item, 0) <= 0 and item not in coming:
                flag("empty_bench", "tracking",
                     f"House {c} has {area:,.0f} m² empty and no {crop.split('_')[0]} seed in stock or on order: "
                     "it stays empty for at least 10 days.", end_briefing["clock"]["day"])
        # 7. houses left far below the crop's climate (day 0 starts at 5 °C)
        cl = st.get("settings", {}).get("climate", {})
        cold = [c for c, s in cl.items() if s.get("heat_day_c", 99) < 12]
        if cold:
            flag("cold", "constraints", f"Houses {', '.join(cold)} still heated to {cl[cold[0]]['heat_day_c']:.0f} °C by day: "
                 "the crop's target is about 20 °C, so it barely grows.", end_briefing["clock"]["day"])
    if any(f["key"] == "left_standing" for f in flags):     # the specific flag says more than "idle"
        flags = [f for f in flags if f["key"] != "idle"]
    seen, out = set(), []
    for f in flags:                                    # one flag per key and day
        k = (f["key"], f["day"], f["text"][:40])
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out
