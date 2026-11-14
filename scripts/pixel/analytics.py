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
                pts[day] = {"day": day, "cash": _num(m.get("cash")), "profit": _num(m.get("profit"))}
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
                if rd is not None and rd <= 0:
                    ready_h[bid] += 1
        cash = _num((f.get("money") or {}).get("cash"))
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
    from pathlib import Path
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rs, ld = runs_from_harbor(a.bench)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(compute_stats(rs, ld), indent=1), encoding="utf-8")
    print(f"wrote {a.out} ({len(rs)} runs)")
