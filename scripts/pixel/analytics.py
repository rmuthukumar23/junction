"""Analytics for the Greenhouse Bench pixel site.

    compute_stats(runs, load_replay) -> JSON-serialisable dict

`runs` is the RunMeta list, `load_replay(run_id)` returns a Replay (both defined by the
site's contract). The result is deterministic (no wall clock), has no NaN/inf, and every
number comes from the recorded runs. Anything derived by a rule of thumb is listed in
`meta.estimates` so the page can label it.

Failure classes (AGENTS.md: infrastructure failures are never agent failures):
  infrastructure  the harness, sandbox, network or model API failed before or during the run
  agent           the agent's own play ended the run (bankruptcy, stopped, out of calls)
  unknown         failed with no usable reason; counted separately, never as an agent failure

Run as a script to build stats JSON from Harbor trial directories (demo and debugging):
    python analytics.py --bench artifacts/bench --out artifacts/pixel-cache/stats.json

compare_runs(replays, reference) puts runs of one scenario and seed side by side, day by day,
against the reference policy. From the command line it replays the traces and the policies first:
    python analytics.py compare --trace gemini=<trial>/artifacts/var/lib/envkit/trace.jsonl \
        --out-json artifacts/compare/s1.json --out-md artifacts/compare/s1.md
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from typing import Any, Callable

DEFAULT_MAX_REPLAYS = 12
MAX_CURVE_POINTS = 43
REACT_WINDOW_H = 72  # an event is "not reacted to" if no relevant action follows within this
GONE_STATES = {"lost", "dead", "died", "failed", "destroyed", "rotten", "spoiled"}
DONE_STATES = GONE_STATES | {"harvested", "sold", "cleared"}

_AGENT_FIRST = re.compile(
    r"bankrupt|insolven|early stop|stopped early|ran out of (calls|actions)|max.?calls|gave up", re.I)
_INFRA = re.compile(
    r"setup|timed out after|docker|modal|sandbox|container|\b429\b|\b50[0-4]\b|rate.?limit|quota|"
    r"not_found|not found|connection|network|api key|unavailable|out of memory|oom|harbor|verifier|"
    r"infrastructure|no space|dns|ssl|permission denied|resource_exhausted|nonzeroagentexit", re.I)
_AGENT = re.compile(
    r"stopped calling|call budget|budget exhausted|invalid|refused|agenttimeout|agent timed out|no action", re.I)


def classify_failure(status: str, failure: str | None) -> str:
    """'none' for a clean run; otherwise infrastructure / agent / unknown."""
    text = (failure or "").strip()
    if status == "complete" and not text:
        return "none"
    if not text:
        return "unknown" if status in ("failed", "partial") else "none"
    if _AGENT_FIRST.search(text):
        return "agent"
    if _INFRA.search(text):
        return "infrastructure"
    if _AGENT.search(text):
        return "agent"
    return "unknown"


# ---------------------------------------------------------------- small helpers

def _num(x: Any) -> float | None:
    if isinstance(x, bool) or x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _clean(obj: Any) -> Any:
    """Make JSON-safe: non-finite floats become None, floats are rounded."""
    if isinstance(obj, float):
        return round(obj, 4) if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj


def _group_name(run: dict) -> str:
    if run.get("kind") == "policy":
        return str(run.get("policy") or run.get("label") or run.get("id"))
    return str(run.get("model") or run.get("label") or run.get("id"))


def _norm_err(err: Any) -> str:
    s = re.sub(r"\d+(\.\d+)?", "#", str(err or "unknown error")).strip()
    return s[:140]


def _thin(points: list[dict], limit: int = MAX_CURVE_POINTS) -> list[dict]:
    if len(points) <= limit:
        return points
    step = (len(points) - 1) / (limit - 1)
    return [points[round(i * step)] for i in range(limit)]


# ---------------------------------------------------------------- per-replay analysis

def _profit_curve(replay: dict) -> list[dict]:
    pts: dict[int, dict] = {}
    for d in replay.get("daily") or []:
        day = d.get("day")
        if isinstance(day, int):
            pts[day] = {"day": day, "cash": _num(d.get("cash")), "profit": _num(d.get("profit"))}
    if not pts:  # fall back to the last frame of every day
        for f in replay.get("frames") or []:
            m = f.get("money") or {}
            day = f.get("day")
            if isinstance(day, int):
                pts[day] = {"day": day, "cash": _num(m.get("cash_eur", m.get("cash"))), "profit": _num(m.get("profit_so_far_eur", m.get("profit")))}
    return _thin([pts[k] for k in sorted(pts)])


def _tool_usage(replay: dict) -> dict:
    acts = replay.get("actions") or []
    by_tool: dict[str, dict] = defaultdict(lambda: {"calls": 0, "invalid": 0})
    for a in acts:
        t = by_tool[str(a.get("tool", "?"))]
        t["calls"] += 1
        if not a.get("ok", True):
            t["invalid"] += 1
    n = len(acts)
    bad = sum(t["invalid"] for t in by_tool.values())
    days = {a.get("day") for a in acts if isinstance(a.get("day"), int)}
    return {"calls": n, "invalid": bad, "invalid_rate": (bad / n) if n else None,
            "days_with_actions": len(days),
            "actions_per_day": (n / len(days)) if days else None,
            "by_tool": {k: dict(v) for k, v in sorted(by_tool.items())}}


def _relevant(action: dict, target: str | None) -> bool:
    if not target:
        return True
    return target.lower() in json.dumps(action.get("args", {}), default=str).lower()


def _reaction(replay: dict) -> dict:
    """Time from each alarm/event to the first relevant action (estimate: relevance is
    'the action mentions the target', or any action when the signal names none)."""
    acts = sorted((a for a in replay.get("actions") or [] if _num(a.get("h")) is not None),
                  key=lambda a: a["h"])
    signals = [(s, "event") for s in replay.get("events") or []] + [(s, "alarm") for s in replay.get("alarms") or []]
    rows = []
    for s, src in signals:
        h = _num(s.get("h"))
        if h is None:
            continue
        target = s.get("target") or None
        hit = next((a for a in acts if a["h"] >= h and _relevant(a, target)), None)
        lat = (hit["h"] - h) if hit else None
        reacted = lat is not None and lat <= REACT_WINDOW_H
        rows.append({"h": h, "day": s.get("day"), "source": src, "kind": s.get("kind"), "target": target,
                     "text": str(s.get("text", ""))[:120], "latency_h": lat if reacted else None, "reacted": reacted})
    lat = [r["latency_h"] for r in rows if r["reacted"]]
    return {"signals": len(rows), "reacted": len(lat), "unreacted": len(rows) - len(lat),
            "mean_latency_h": _mean(lat), "median_latency_h": _median(lat), "rows": rows}


def _frame_health(replay: dict) -> dict:
    frames = replay.get("frames") or []
    fault_h: Counter = Counter()
    fault_days = set()
    ready_h: Counter = Counter()
    lost: dict[str, str] = {}
    min_cash, bankrupt_day = None, None
    for f in frames:
        day = f.get("day")
        for fl in f.get("faults") or []:
            fault_h[str(fl)] += 1
            fault_days.add(day)
        for b in f.get("b") or []:
            bid, st = str(b.get("id")), str(b.get("st", "")).lower()
            if st in GONE_STATES:
                lost[bid] = str(b.get("crop", "?"))
            elif st not in DONE_STATES:
                rd = _num(b.get("ready"))
                if st == "ready" or (rd is not None and rd <= 0):
                    ready_h[bid] += 1
        _m = f.get("money") or {}
        cash = _num(_m.get("cash_eur", _m.get("cash")))
        if cash is not None:
            min_cash = cash if min_cash is None else min(min_cash, cash)
            if cash <= 0 and bankrupt_day is None:
                bankrupt_day = day
    by_crop: Counter = Counter(lost.values())
    return {"fault_hours": dict(sorted(fault_h.items())), "damage_days": len({d for d in fault_days if d is not None}),
            "missed_harvest_days": sum(ready_h.values()) / 24.0, "missed_harvest_batches": len(ready_h),
            "crops_lost": len(lost), "crops_lost_by_crop": dict(sorted(by_crop.items())),
            "min_cash": min_cash, "bankrupt_day": bankrupt_day}


def _energy(replay: dict) -> dict:
    gas = imp = exp = heat = lost = 0.0
    gas_cost = imp_cost = exp_rev = 0.0
    chp_h = boiler_h = frames_n = 0
    co2_kg = 0.0
    for f in replay.get("frames") or []:
        ec = f.get("ec") or {}
        if not ec:
            continue
        frames_n += 1
        g, i, e = _num(ec.get("gas")) or 0.0, _num(ec.get("imp")) or 0.0, _num(ec.get("exp")) or 0.0
        gas, imp, exp = gas + g, imp + i, exp + e
        heat += _num(ec.get("heat")) or 0.0
        lost += _num(ec.get("lost")) or 0.0
        gas_cost += g * (_num(ec.get("p_gas")) or 0.0)
        imp_cost += i * (_num(ec.get("p_imp")) or 0.0)
        exp_rev += e * (_num(ec.get("p_exp")) or 0.0)
        chp_h += 1 if (_num(ec.get("chp")) or 0) > 0 else 0
        boiler_h += 1 if (_num(ec.get("boiler")) or 0) > 0 else 0
        co2_kg += sum(_num(c.get("co2req")) or 0.0 for c in (f.get("c") or {}).values())
    return {"hours": frames_n, "gas_m3": gas, "gas_cost_eur": gas_cost, "import_kwh": imp, "import_cost_eur": imp_cost,
            "export_kwh": exp, "export_revenue_eur": exp_rev, "heat_produced_kwh": heat, "heat_lost_kwh": lost,
            "heat_lost_share": (lost / heat) if heat > 0 else None, "chp_hours": chp_h, "boiler_hours": boiler_h,
            "co2_requested_kg": co2_kg}


def _analyse(replay: dict) -> dict:
    return {"curve": _profit_curve(replay), "tools": _tool_usage(replay), "reaction": _reaction(replay),
            "health": _frame_health(replay), "energy": _energy(replay),
            "invalid": [(_norm_err(a.get("err")), str(a.get("tool", "?")))
                        for a in replay.get("actions") or [] if not a.get("ok", True)]}


# ---------------------------------------------------------------- top level

def _run_row(r: dict) -> dict:
    status = str(r.get("status") or "failed")
    profit, base = _num(r.get("profit_eur")), _num(r.get("baseline_profit_eur"))
    return {"id": r.get("id"), "label": r.get("label"), "kind": r.get("kind"), "group": _group_name(r),
            "model": r.get("model"), "policy": r.get("policy"), "scenario": r.get("scenario"), "seed": r.get("seed"),
            "score": _num(r.get("score")), "profit_eur": profit, "baseline_profit_eur": base,
            "profit_vs_baseline_eur": (profit - base) if profit is not None and base is not None else None,
            "days": r.get("days"), "status": status, "failure": r.get("failure"),
            "failure_class": classify_failure(status, r.get("failure")), "started": r.get("started"),
            "source": r.get("source")}


def _leaderboard(rows: list[dict]) -> list[dict]:
    ref_profit: dict[Any, float] = {}  # reference policy profit by (scenario, seed)
    for r in rows:
        if (r["kind"] == "policy" and r["policy"] == "reference" and r["status"] == "complete"
                and r["profit_eur"] is not None):
            ref_profit[(r["scenario"], r["seed"])] = r["profit_eur"]
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["kind"], r["group"])].append(r)
    out = []
    for (kind, name), rs in groups.items():
        done = [r for r in rs if r["status"] == "complete"]
        sc = [r["score"] for r in done if r["score"] is not None]
        pf = [r["profit_eur"] for r in done if r["profit_eur"] is not None]
        gaps = [r["profit_vs_baseline_eur"] for r in done if r["profit_vs_baseline_eur"] is not None]
        paired = [r["profit_eur"] - ref_profit[(r["scenario"], r["seed"])] for r in done
                  if r["profit_eur"] is not None and (r["scenario"], r["seed"]) in ref_profit]
        fails = Counter(r["failure_class"] for r in rs if r["status"] in ("failed", "partial"))
        bases = [r["baseline_profit_eur"] for r in done if r["baseline_profit_eur"] is not None]
        out.append({
            "name": name, "kind": kind, "n_runs": len(rs), "n_complete": len(done),
            "n_partial": sum(r["status"] == "partial" for r in rs), "n_failed": sum(r["status"] == "failed" for r in rs),
            "mean_score": _mean(sc), "best_score": max(sc) if sc else None, "worst_score": min(sc) if sc else None,
            "mean_profit_eur": _mean(pf), "best_profit_eur": max(pf) if pf else None,
            "worst_profit_eur": min(pf) if pf else None,
            "mean_baseline_profit_eur": _mean(bases),
            "mean_profit_vs_baseline_eur": _mean(gaps), "beats_baseline": sum(g > 0 for g in gaps),
            "n_with_baseline": len(gaps),
            "gap_to_reference_eur": _mean(paired), "n_paired_with_reference": len(paired),
            "failures": {"agent": fails.get("agent", 0), "infrastructure": fails.get("infrastructure", 0),
                         "unknown": fails.get("unknown", 0)},
        })
    out.sort(key=lambda g: (g["mean_score"] is None, -(g["mean_score"] or 0), g["name"]))
    for i, g in enumerate(out, 1):
        g["rank"] = i
    return out


def _aggregate(analysed: dict[str, dict], rows_by_id: dict[str, dict]) -> dict:
    tools: dict[str, dict] = defaultdict(lambda: {"calls": 0, "invalid": 0})
    inv: dict[str, dict] = {}
    react_rows, per_run_mistakes, per_run_energy = [], [], []
    total_calls = total_bad = 0
    apd = []
    for rid in sorted(analysed):
        a, row = analysed[rid], rows_by_id[rid]
        for t, v in a["tools"]["by_tool"].items():
            tools[t]["calls"] += v["calls"]
            tools[t]["invalid"] += v["invalid"]
        total_calls += a["tools"]["calls"]
        total_bad += a["tools"]["invalid"]
        if a["tools"]["actions_per_day"] is not None:
            apd.append(a["tools"]["actions_per_day"])
        for err, tool in a["invalid"]:
            e = inv.setdefault(err, {"err": err, "count": 0, "tools": Counter(), "runs": set()})
            e["count"] += 1
            e["tools"][tool] += 1
            e["runs"].add(rid)
        for s in a["reaction"]["rows"]:
            react_rows.append({**s, "run": rid})
        h, rc = a["health"], a["reaction"]
        per_run_mistakes.append({"run": rid, "label": row["label"], "invalid_actions": a["tools"]["invalid"],
                                 "signals": rc["signals"], "unreacted": rc["unreacted"],
                                 "median_latency_h": rc["median_latency_h"], "damage_days": h["damage_days"],
                                 "fault_hours": h["fault_hours"], "missed_harvest_days": h["missed_harvest_days"],
                                 "crops_lost": h["crops_lost"], "crops_lost_by_crop": h["crops_lost_by_crop"],
                                 "heat_lost_kwh": a["energy"]["heat_lost_kwh"],
                                 "gas_cost_eur": a["energy"]["gas_cost_eur"],
                                 "min_cash": h["min_cash"], "bankrupt_day": h["bankrupt_day"],
                                 "early_stop": row["status"] == "partial"})
        per_run_energy.append({"run": rid, "label": row["label"], **a["energy"]})
    lat = [r["latency_h"] for r in react_rows if r["reacted"]]
    slow = sorted(react_rows, key=lambda r: (-(r["latency_h"] if r["latency_h"] is not None else 1e9),
                                             r["run"], r["h"]))[:10]
    pm = per_run_mistakes
    return {
        "tool_usage": {"by_tool": {k: dict(v) for k, v in sorted(tools.items())}, "calls": total_calls,
                       "invalid": total_bad, "invalid_rate": (total_bad / total_calls) if total_calls else None,
                       "mean_actions_per_day": _mean(apd),
                       "per_run": [{"run": rid, "label": rows_by_id[rid]["label"], **analysed[rid]["tools"]}
                                   for rid in sorted(analysed)]},
        "mistakes": {
            "invalid_actions": [{"err": e["err"], "count": e["count"], "tools": dict(sorted(e["tools"].items())),
                                 "runs": len(e["runs"])}
                                for e in sorted(inv.values(), key=lambda e: (-e["count"], e["err"]))[:25]],
            "reaction": {"signals": len(react_rows), "unreacted": sum(not r["reacted"] for r in react_rows),
                         "mean_latency_h": _mean(lat), "median_latency_h": _median(lat), "slowest": slow,
                         "window_h": REACT_WINDOW_H},
            "totals": {"damage_days": sum(m["damage_days"] for m in pm),
                       "missed_harvest_days": sum(m["missed_harvest_days"] for m in pm),
                       "crops_lost": sum(m["crops_lost"] for m in pm),
                       "heat_lost_kwh": sum(m["heat_lost_kwh"] for m in pm),
                       "gas_cost_eur": sum(m["gas_cost_eur"] for m in pm),
                       "bankruptcies": sum(m["bankrupt_day"] is not None for m in pm),
                       "early_stops": sum(m["early_stop"] for m in pm)},
            "per_run": pm},
        "energy": {"per_run": per_run_energy,
                   "total": {k: sum((e.get(k) or 0) for e in per_run_energy) for k in
                             ("gas_m3", "gas_cost_eur", "import_kwh", "import_cost_eur", "export_kwh",
                              "export_revenue_eur", "heat_produced_kwh", "heat_lost_kwh", "chp_hours",
                              "boiler_hours", "co2_requested_kg")}},
    }


def compute_stats(runs: list[dict], load_replay: Callable[[str], dict], max_replays: int = DEFAULT_MAX_REPLAYS) -> dict:
    rows = [_run_row(r) for r in runs]
    rows.sort(key=lambda r: (str(r["started"] or ""), str(r["id"])), reverse=True)
    rows_by_id = {str(r["id"]): r for r in rows}

    candidates = [r for r in rows if r["status"] in ("complete", "partial")][:max(0, max_replays)]
    analysed: dict[str, dict] = {}
    replay_errors: list[dict] = []
    for r in candidates:
        try:
            analysed[str(r["id"])] = _analyse(load_replay(r["id"]) or {})
        except Exception as exc:  # a broken replay must not take the stats page down
            replay_errors.append({"run": r["id"], "error": f"{type(exc).__name__}: {str(exc)[:160]}"})

    agg = _aggregate(analysed, rows_by_id)
    for r in rows:
        r["has_replay_stats"] = str(r["id"]) in analysed
    curves = [{"run": rid, "label": rows_by_id[rid]["label"], "group": rows_by_id[rid]["group"],
               "kind": rows_by_id[rid]["kind"], "points": a["curve"]}
              for rid, a in sorted(analysed.items()) if a["curve"]]
    n_class = Counter(r["failure_class"] for r in rows if r["status"] != "complete")
    out = {
        "leaderboard": _leaderboard(rows),
        "runs": rows,
        "profit_curves": curves,
        "tool_usage": agg["tool_usage"],
        "mistakes": agg["mistakes"],
        "energy": agg["energy"],
        "meta": {
            "runs": len(rows), "complete": sum(r["status"] == "complete" for r in rows),
            "partial": sum(r["status"] == "partial" for r in rows), "failed": sum(r["status"] == "failed" for r in rows),
            "failures_by_class": {"agent": n_class.get("agent", 0), "infrastructure": n_class.get("infrastructure", 0),
                                  "unknown": n_class.get("unknown", 0)},
            "replays_analysed": len(analysed), "replays_failed": replay_errors, "replay_cap": max_replays,
            "scenarios": sorted({str(r["scenario"]) for r in rows if r["scenario"]}),
            "estimates": [
                "reaction latency: first action at or after the alarm/event hour whose arguments mention its target "
                "(any action if it names none); in a daily-turn game latency is bounded below by the turn schedule",
                "missed harvest days: batch-hours with estimated days-to-ready <= 0 and not yet harvested, divided by 24",
                "damage days: days with at least one active fault; failure class is inferred from the failure text",
                f"unreacted: no relevant action within {REACT_WINDOW_H} h",
            ],
        },
    }
    return _clean(out)


# ---------------------------------------------------------------- run vs reference, day by day

LEDGER_KEYS = ("harvest_revenue_eur", "electricity_sold_eur", "gas_eur", "electricity_bought_eur", "co2_eur",
               "wages_eur", "hiring_eur", "seedlings_eur", "contractors_eur", "parts_eur", "orders_eur",
               "repairs_eur", "fines_eur", "express_eur")
DIVERGE_EUR = 5000.0  # a profit gap this large counts as "diverged"
_PLANTED = re.compile(r"Planted ([\d.]+) m2")
_HARVEST_EUR = re.compile(r"for (-?[\d.]+) EUR")


def daily_profile(replay: dict) -> list[dict]:
    """One row per clock day from a replay: end-of-day money (cumulative and that day's change per ledger
    line), harvests, planting, orders, the agent's actions and their errors, damage and lamp use.
    Frame h holds the state after hour h-1 ran, so day d covers frames 24d+1 .. 24(d+1)."""
    frames = [f for f in replay.get("frames") or [] if isinstance(f.get("h"), int) and f["h"] >= 1]
    by_day: dict[int, list[dict]] = defaultdict(list)
    for f in frames:
        by_day[(f["h"] - 1) // 24].append(f)
    acts: dict[int, list[dict]] = defaultdict(list)
    for a in replay.get("actions") or []:
        if isinstance(a.get("day"), int):
            acts[a["day"]].append(a)
    evs: dict[int, list[dict]] = defaultdict(list)
    for e in replay.get("events") or []:
        if isinstance(e.get("day"), int):
            evs[e["day"]].append(e)
    rows, prev = [], {k: 0.0 for k in LEDGER_KEYS}
    for d in sorted(by_day):
        fs = by_day[d]
        end = fs[-1]
        mo = end.get("money") or {}
        cum = {k: _num(mo.get(k)) or 0.0 for k in LEDGER_KEYS}
        day_acts = [a for a in acts.get(d, []) if a.get("tool") != "submit_day"]
        harvests = [e for e in evs.get(d, []) if e.get("kind") == "harvest"]
        planted = sum(float(m.group(1)) for e in evs.get(d, []) if e.get("kind") == "plant"
                      for m in [_PLANTED.search(str(e.get("text", "")))] if m)
        noon = next((f for f in fs if f.get("hod") == 12), end)
        comps = (noon.get("c") or {}).values()
        rows.append({
            "day": d,
            "profit": _num(mo.get("profit_so_far_eur")), "cash": _num(mo.get("cash_eur")),
            "ledger": cum, "ledger_day": {k: cum[k] - prev[k] for k in LEDGER_KEYS},
            "harvests": len(harvests),
            "harvest_eur": sum(float(m.group(1)) for e in harvests
                               for m in [_HARVEST_EUR.search(str(e.get("text", "")))] if m),
            "planted_m2": planted,
            "growing_m2": sum(_num(b.get("area")) or 0.0 for b in end.get("b") or []
                              if str(b.get("st", "")).lower() not in DONE_STATES),
            "orders_placed": sum(1 for e in evs.get(d, []) if e.get("kind") == "order_placed"),
            "actions": len(day_acts), "actions_failed": sum(1 for a in day_acts if not a.get("ok", True)),
            "tools": dict(sorted(Counter(str(a.get("tool")) for a in day_acts).items())),
            "errors": [{"tool": a.get("tool"), "args": a.get("args"), "err": a.get("err")}
                       for a in day_acts if not a.get("ok", True)],
            "panes_broken": sum(int(v or 0) for v in (end.get("panes") or {}).values()),
            "faults": sorted(x for x in end.get("faults") or [] if not str(x).endswith(".glass")),
            "lamp_kwh": sum(sum(_num(c.get("lamp")) or 0.0 for c in (f.get("c") or {}).values()) for f in fs),
            "co2_setpoint_ppm": _mean([v for c in comps for v in [_num(c.get("sp_co2"))] if v is not None]),
            "crew": end.get("staff"),
        })
        prev = cum
    return rows


def _settled_day(gaps: list[tuple[int, float]], limit: float) -> int | None:
    """First day from which the gap stays at or above `limit` for the rest of the episode."""
    out = None
    for day, g in gaps:
        if g >= limit:
            out = day if out is None else out
        else:
            out = None
    return out


def compare_runs(replays: dict[str, dict], reference: str, diverge_eur: float = DIVERGE_EUR) -> dict:
    """Day-by-day comparison of several replays of the same scenario and seed against `reference`.

    For each run: its daily profile, where its cumulative profit first falls `diverge_eur` behind the
    reference and the day from which it never catches back up, and its final profit gap split by
    ledger line (run minus reference: negative means the run earned less or spent more)."""
    prof = {name: daily_profile(r) for name, r in replays.items()}
    ref = {row["day"]: row for row in prof.get(reference, [])}
    runs = {}
    for name, rows in prof.items():
        gaps = [(row["day"], (ref[row["day"]]["profit"] or 0.0) - (row["profit"] or 0.0))
                for row in rows if row["day"] in ref and row["profit"] is not None]
        last, ref_last = (rows[-1] if rows else {}), (prof[reference][-1] if prof.get(reference) else {})
        gap_by = {k: (last.get("ledger") or {}).get(k, 0.0) - (ref_last.get("ledger") or {}).get(k, 0.0)
                  for k in LEDGER_KEYS}
        tot = lambda key: sum(row[key] for row in rows)  # noqa: E731
        errs = Counter(_norm_err(e["err"]) for row in rows for e in row["errors"])
        runs[name] = {
            "final_profit_eur": last.get("profit"),
            "final_gap_eur": gaps[-1][1] if gaps else None,
            "first_diverged_day": next((d for d, g in gaps if g >= diverge_eur), None),
            "settled_diverged_day": _settled_day(gaps, diverge_eur),
            "gap_by_ledger_eur": dict(sorted(gap_by.items(), key=lambda kv: kv[1])),
            "totals": {"harvests": tot("harvests"), "harvest_eur": tot("harvest_eur"), "planted_m2": tot("planted_m2"),
                       "orders_placed": tot("orders_placed"), "actions": tot("actions"),
                       "actions_failed": tot("actions_failed"), "lamp_kwh": tot("lamp_kwh"),
                       "days_with_actions": sum(1 for row in rows if row["actions"]),
                       "last_action_day": max((row["day"] for row in rows if row["actions"]), default=None),
                       "pane_days": sum(1 for row in rows if row["panes_broken"]),
                       "fault_days": sum(1 for row in rows if row["faults"])},
            "errors": [{"err": e, "count": n} for e, n in errs.most_common()],
            "gap_curve": [{"day": d, "gap_eur": g} for d, g in gaps],
            "daily": rows,
        }
    return _clean({"reference": reference, "diverge_eur": diverge_eur, "runs": runs})


def _eur(x: Any) -> str:
    v = _num(x)
    return "–" if v is None else f"{v:,.0f}"


def render_comparison_md(cmp: dict, focus: str) -> str:
    """Markdown tables for a comparison: a summary of every run and the focus run's day-by-day log."""
    ref, runs = cmp["reference"], cmp["runs"]
    names = [ref] + [n for n in runs if n != ref]
    out = ["| Run | Final profit (EUR) | Gap to reference | Harvests | Harvest EUR | Planted m² | Orders | "
           "Failed actions | Days with damage | Diverged (first / for good) |", "|---|---:|---:|---:|---:|---:|---:|"
           "---:|---:|---|"]
    for n in names:
        r, t = runs[n], runs[n]["totals"]
        out.append(f"| {n} | {_eur(r['final_profit_eur'])} | {_eur(r['final_gap_eur'])} | {t['harvests']} | "
                   f"{_eur(t['harvest_eur'])} | {_eur(t['planted_m2'])} | {t['orders_placed']} | "
                   f"{t['actions_failed']}/{t['actions']} | {max(t['pane_days'], t['fault_days'])} | "
                   f"{r['first_diverged_day']} / {r['settled_diverged_day']} |")
    out += ["", f"Final gap to {ref} by ledger line, EUR ({focus} minus {ref}; most negative first):", ""]
    gap = runs[focus]["gap_by_ledger_eur"]
    out += ["| Ledger line | Gap |", "|---|---:|"] + [f"| {k} | {_eur(v)} |" for k, v in gap.items() if abs(v) >= 1]
    out += ["", f"Day by day, {focus} against {ref} (day = clock day from 0; money is end of day):", "",
            f"| Day | {focus} profit | {ref} profit | Gap | Harvests (run/ref) | Planted m² (run/ref) | "
            "Actions failed/total | Panes broken (run/ref) | Faults (run) |", "|---:|---:|---:|---:|---|---|---|---|---|"]
    rd = {row["day"]: row for row in runs[ref]["daily"]}
    for row in runs[focus]["daily"]:
        o = rd.get(row["day"], {})
        out.append(f"| {row['day']} | {_eur(row['profit'])} | {_eur(o.get('profit'))} | "
                   f"{_eur((o.get('profit') or 0) - (row['profit'] or 0))} | {row['harvests']}/{o.get('harvests', '–')} | "
                   f"{_eur(row['planted_m2'])}/{_eur(o.get('planted_m2'))} | {row['actions_failed']}/{row['actions']} | "
                   f"{row['panes_broken']}/{o.get('panes_broken', '–')} | {', '.join(row['faults']) or '–'} |")
    return "\n".join(out) + "\n"


def _compare_main(argv: list[str]) -> None:
    """python analytics.py compare --trace T [--trace T2 ...] --out-json J --out-md M
    Replays each agent trace and the named policies on the trace's scenario and seed (the policies play
    whole episodes through the real tools: on normal-winter this is a benchmark-length run)."""
    import argparse
    from pathlib import Path
    import replay as rp
    ap = argparse.ArgumentParser(prog="analytics.py compare")
    ap.add_argument("--trace", action="append", required=True, help="label=path/to/trace.jsonl")
    ap.add_argument("--policies", default="reference,rule-based,naive")
    ap.add_argument("--diverge-eur", type=float, default=DIVERGE_EUR)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md")
    a = ap.parse_args(argv)
    replays, scenario, seed = {}, None, None
    for spec in a.trace:
        label, _, path = spec.rpartition("=")
        out = rp.replay_trace(path, {"id": label or path, "kind": "agent"})
        replays[label or path] = out
        scenario, seed = out["meta"]["scenario"], out["meta"]["seed"]
        if out["meta"].get("replay_verified") is False:
            print(f"warning: {label}: replay does not match the recorded responses")
    pols = [p for p in a.policies.split(",") if p]
    for p in pols:
        replays[p] = rp.replay_policy(p, int(seed), str(scenario), {"id": f"policy:{p}:s{seed}", "kind": "policy"})
    cmp = compare_runs(replays, "reference" if "reference" in pols else pols[0], a.diverge_eur)
    cmp["scenario"], cmp["seed"] = scenario, seed
    Path(a.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out_json).write_text(json.dumps(cmp, indent=1), encoding="utf-8")
    if a.out_md:
        focus = next(iter(replays))
        Path(a.out_md).write_text(render_comparison_md(cmp, focus), encoding="utf-8")
    for n, r in cmp["runs"].items():
        print(f"{n}: profit {_eur(r['final_profit_eur'])}, gap {_eur(r['final_gap_eur'])}, "
              f"diverged day {r['first_diverged_day']} (for good from {r['settled_diverged_day']})")


# ---------------------------------------------------------------- demo helper: Harbor trial dirs

def runs_from_harbor(bench_dir: str):
    """RunMeta list + replay loader from Harbor trial dirs (artifacts/bench/*/<trial>/).
    Replays carry only the action list (from the envkit trace): enough for tool usage."""
    from pathlib import Path
    runs, traces = [], {}
    for res in sorted(Path(bench_dir).glob("*/*/result.json")):
        d = res.parent
        try:
            r = json.loads(res.read_text(encoding="utf-8"))
            cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        exc = r.get("exception_info") or {}
        reward = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        failure = None
        if exc:
            failure = f"{exc.get('exception_type', 'Error')}: {str(exc.get('exception_message', ''))[:600]}"
        status = "failed" if exc and not reward else ("partial" if exc else ("complete" if reward is not None else "failed"))
        model = (cfg.get("agent") or {}).get("model_name")
        scenario, seed = "unknown", None
        score_json = d / "verifier" / "score.json"
        if score_json.exists():
            try:
                sj = json.loads(score_json.read_text(encoding="utf-8"))
                scenario, seed = sj.get("scenario", scenario), sj.get("seed")
            except ValueError:
                pass
        rid = f"{res.parent.parent.name}/{d.name}"
        runs.append({"id": rid, "label": f"{model} {d.name[-7:]}", "kind": "agent", "model": model, "policy": None,
                     "scenario": scenario, "seed": seed, "score": reward, "profit_eur": None,
                     "baseline_profit_eur": None, "days": None, "status": status, "failure": failure,
                     "started": r.get("started_at"), "source": "harbor"})
        traces[rid] = d / "artifacts" / "var" / "lib" / "envkit" / "trace.jsonl"

    def load(rid: str) -> dict:
        acts = []
        for line in traces[rid].read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("k") == "call":
                resp = rec.get("response") or {}
                acts.append({"h": rec.get("i", 0), "day": 1 + int(rec.get("window", 0) or 0), "tool": rec.get("tool"),
                             "args": rec.get("args", {}), "ok": bool(rec.get("ok")), "err": resp.get("error"),
                             "resp_summary": ""})
        return {"meta": {}, "frames": [], "actions": acts, "events": [], "alarms": [], "daily": []}
    return runs, load


if __name__ == "__main__":
    import argparse
    import sys
    from pathlib import Path
    if sys.argv[1:2] == ["compare"]:
        _compare_main(sys.argv[2:])
        raise SystemExit(0)
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rs, ld = runs_from_harbor(a.bench)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(compute_stats(rs, ld), indent=1), encoding="utf-8")
    print(f"wrote {a.out} ({len(rs)} runs)")
