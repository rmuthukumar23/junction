"""Replay builder for the pixel site: turns a recorded trace (or a scripted policy) into
per-hour frames, actions, events, alarms and a daily table by running the real simulator.

Nothing here changes an outcome: frames read the simulator through separate named random
streams ("pixel/..."), and the recorded calls are fed through Episode.call in order, exactly as
the verifier does (src/envkit/core.py `replay`).

Day numbering: `day` is the clock day, hour // 24, starting at 0 (what the game's own
briefing calls "day"). The agent's turn is at hour 6 of each day; the day's alarms and
results appear in the frames of hours 24*day .. 24*day+23.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from envkit.clients import InProcessClient  # noqa: E402
from envkit.core import Episode  # noqa: E402
from envkit.policies import DoNothing, StopPolicy  # noqa: E402
from envkit.scenario import load_scenario  # noqa: E402
from envkit.scoring import score as score_ledger  # noqa: E402
from envkit.trace import Trace, digest, read_trace  # noqa: E402
from greenhouse import views  # noqa: E402
from greenhouse.env import GreenhouseBench  # noqa: E402
from greenhouse.world.sim import Greenhouse  # noqa: E402

SCENARIOS = ROOT / "scenarios"
POLICY_NAMES = ("reference", "rule-based", "naive", "do-nothing")


def policy_classes() -> dict[str, Any]:
    pol = GreenhouseBench.policies()
    return {**{k: pol[k] for k in ("reference", "rule-based", "naive")}, "do-nothing": DoNothing}


def r(x: Any, n: int = 2) -> Any:
    return round(x, n) if isinstance(x, float) else x


# -- frames ---------------------------------------------------------------------------------


def panes_by_compartment(sim) -> dict[str, int]:
    """Broken panes per compartment, from the glass outages the simulation holds."""
    out: dict[str, int] = {}
    outages = getattr(getattr(sim.business, "events", None), "outages", [])
    for o in outages:
        if o.target.endswith(".glass") and o.target in sim.effects and o.repaired_hour is None and o.panes:
            out[o.target[: -len(".glass")]] = int(o.panes)
    return out


def max_panes(sim) -> float:
    spec = getattr(getattr(sim.business, "events", None), "specs", {})
    vals = [s.panes_max for s in spec.values() if getattr(s, "kind", "") == "storm" and s.panes_max > 0]
    return float(max(vals)) if vals else 12.0


def frame(sim) -> dict[str, Any]:
    """One hour of state: same shape as scripts/viz/server.py frame(), plus day, hod, damage, panes."""
    h = sim.history[-1] if sim.history else None
    rd = sim.readings
    comps = {}
    for cid, c in rd["compartments"].items():
        a = c.get("actuators", {})
        cl = sim.climate[cid]
        comps[cid] = {"t": r(c.get("temp_c")), "rh": r(c.get("rh_pct"), 1), "co2": r(c.get("co2_ppm"), 0),
                      "par": r(c.get("par_umol_m2_s", 0.0), 1), "dli": r(c.get("dli_mol_m2", 0.0)),
                      "vent": r(a.get("vent_pct", 0.0), 1), "screen": bool(a.get("screen_closed", False)),
                      "lamp": r(a.get("lamp_kw", 0.0), 1),
                      "heat": r(a.get("heat_request_kw", 0.0), 1), "co2req": r(a.get("co2_request_kg_h", 0.0)),
                      "sp_day": cl.heat_day_c, "sp_night": cl.heat_night_c, "sp_co2": cl.co2_ppm,
                      "free": r(sim.free_area_m2(cid), 1)}
    m = h.metered if h else {}
    biz = sim.business.view(sim.hour, sim.rng.stream(f"pixel/business/{sim.hour}"))
    batches = []
    for b in sim.batches.values():
        est = sim.growth[b.crop_id].estimate(b, sim.hour, sim.rng.stream(f"pixel/estimate/{b.id}/{sim.hour}"))
        batches.append({"id": b.id, "crop": b.crop_id, "c": b.compartment_id, "area": r(b.area_m2, 1),
                        "age": r((sim.hour - b.planted_hour) / 24, 1), "st": b.status,
                        "q": b.id in sim.queued_harvests, "w": r(est.fresh_weight_g_per_unit, 1),
                        "qual": r(est.quality, 3),
                        "ready": r(est.days_to_ready, 1) if est.days_to_ready is not None else None,
                        "units": round(est.units)})
    e = sim.energy
    panes = panes_by_compartment(sim)
    cap = max_panes(sim)
    return {
        "h": sim.hour, "day": sim.hour // 24, "hod": sim.hour % 24,
        "out": {"t": rd["outside"]["temp_c"], "rh": rd["outside"]["rh_pct"], "sun": rd["outside"]["solar_w_m2"],
                "wind": rd["outside"]["wind_m_s"]},
        "c": comps,
        "ec": {"buffer": r(rd["energy_centre"]["buffer_kwh"], 0), "co2": r(rd["energy_centre"]["co2_store_kg"], 0),
               "chp": e.chp_load, "boiler": e.boiler, "bufmode": e.buffer, "extco2": e.external_co2_kg_h,
               "gas": r(m.get("gas_m3", 0.0)), "imp": r(m.get("electricity_import_kwh", 0.0)),
               "exp": r(m.get("electricity_export_kwh", 0.0)), "heat": r(m.get("heat_produced_kwh", 0.0)),
               "lost": r(m.get("heat_lost_kwh", 0.0)), "p_gas": m.get("gas_eur_per_m3"),
               "p_imp": m.get("import_eur_per_kwh"), "p_exp": m.get("export_eur_per_kwh")},
        "faults": sorted(sim.effects),
        "damage": {cid: round(min(1.0, panes.get(cid, 0) / cap), 3) for cid in sim.facility.compartment_ids},
        "panes": {cid: panes.get(cid, 0) for cid in sim.facility.compartment_ids},
        "money": {k: r(v) for k, v in biz["money"].items()},
        "staff": biz["staff"]["crew"],
        "tasks": [{"kind": t["kind"], "target": t["target"], "done": r(t["worker_hours_done"], 1),
                   "need": r(t["worker_hours_needed"], 1), "st": t["status"]} for t in biz["task_queue"]],
        "orders": [{"id": o["order_id"], "item": o["item"], "qty": o["quantity"], "eta": o["expected_arrival_hour"],
                    "st": o["status"], "placed": o["placed_hour"]} for o in biz["open_orders"]],
        "stock": {k: r(v, 0) for k, v in biz["stock"].items()},
        "b": batches,
    }


# -- recorder: hooks Greenhouse.run_hour so every hour (the handover prelude too) is captured ----

_tls = threading.local()
_orig_run_hour = Greenhouse.run_hour


def _patched_run_hour(self):
    rec = getattr(_tls, "rec", None)
    if rec is None or (rec.sim is not None and rec.sim is not self):
        return _orig_run_hour(self)
    return rec.run_hour(self)


Greenhouse.run_hour = _patched_run_hour  # type: ignore[method-assign]


def _alarm_event(a) -> dict[str, Any] | None:
    """Map a real alarm to an event. Equipment and glass events come from effect diffs instead."""
    k, text = a.kind, a.text
    if k == "equipment":
        return None
    if k == "delivery":
        if "late" in text:
            return {"kind": "late_delivery", "severity": "warn"}
        return {"kind": "order_arrived", "severity": "info"}
    if k == "bankrupt":
        return {"kind": "bankruptcy", "severity": "bad"}
    if k == "storm":
        return {"kind": "storm", "severity": "warn"}
    if k == "staff":
        return {"kind": "crew_started" if "started" in text else "staff", "severity": "info"}
    sev = {"batch_lost": "bad", "frost_risk": "warn", "stock_low": "warn", "price": "info",
           "batch_ready": "info", "contractor": "info"}.get(k, "info")
    return {"kind": k, "severity": sev}


class Recorder:
    def __init__(self) -> None:
        self.sim = None
        self.frames: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.alarms: list[dict[str, Any]] = []
        self.actions: list[dict[str, Any]] = []
        self._prev: dict[str, Any] | None = None
        self.harvest_kg_by_day: dict[int, float] = {}

    def _state(self, sim) -> dict[str, Any]:
        biz = sim.business.view(sim.hour, sim.rng.stream(f"pixel/state/{sim.hour}"))
        return {"effects": {t: (e.capacity_factor, e.leakage_factor) for t, e in sim.effects.items()},
                "panes": panes_by_compartment(sim),
                "orders": {o["order_id"]: o for o in biz["open_orders"]},
                "batches": set(sim.batches), "harvests": len(sim.harvests)}

    def run_hour(self, sim):
        if self.sim is None:
            self.sim = sim
        if not self.frames:
            self.frames.append(frame(sim))
            self._prev = self._state(sim)
        new = _orig_run_hour(sim)
        h = sim.hour - 1
        self.frames.append(frame(sim))
        self._events(sim, h, new)
        return new

    def _events(self, sim, h: int, new) -> None:
        prev, now = self._prev, self._state(sim)
        day = h // 24
        ev = self.events

        def add(hour: int, kind: str, target: str, text: str, severity: str = "info") -> None:
            ev.append({"h": hour, "day": hour // 24, "kind": kind, "target": target, "text": text,
                       "severity": severity})

        for a in new:
            self.alarms.append({"h": a.hour, "kind": a.kind, "target": a.target, "text": a.text})
            m = _alarm_event(a)
            if m:
                add(a.hour, m["kind"], a.target, a.text, m["severity"])
        by_target = {a.target: a.text for a in new if a.kind in ("equipment", "contractor")}
        # equipment effects appearing / disappearing (glass is reported as window events below)
        for t, v in now["effects"].items():
            if t not in prev["effects"] and not t.endswith(".glass"):
                add(h, "equipment", t, by_target.get(t, f"{t} fault: capacity {v[0]:.0%} of normal."),
                    "bad" if v[0] <= 0 else "warn")
        for t in prev["effects"]:
            if t not in now["effects"] and not t.endswith(".glass"):
                add(h, "equipment", t, by_target.get(t, f"{t} is working again."), "info")
        # glass: panes broken / repaired, per compartment
        for cid in sim.facility.compartment_ids:
            a, b = prev["panes"].get(cid, 0), now["panes"].get(cid, 0)
            if b > a:
                add(h, "window_break", cid, f"{cid}: {b - a} pane(s) broken ({b} broken in all).", "bad")
            elif b < a:
                add(h, "window_repaired", cid,
                    f"{cid}: glass repaired." if b == 0 else f"{cid}: repaired, {b} pane(s) still broken.", "info")
        for t in prev["effects"]:  # glass effect gone without a pane count (defensive)
            if t.endswith(".glass") and t not in now["effects"] and prev["panes"].get(t[:-6], 0) == 0:
                add(h, "window_repaired", t[:-6], f"{t[:-6]}: glass repaired.", "info")
        for oid, o in now["orders"].items():
            if oid not in prev["orders"]:
                add(o["placed_hour"], "order_placed", oid,
                    f"Ordered {o['quantity']:g} {o['item']} (due hour {o['expected_arrival_hour']}).", "info")
        for bid in sorted(now["batches"] - prev["batches"]):
            b = sim.batches[bid]
            add(h, "plant", bid, f"Planted {b.area_m2:.1f} m2 of {b.crop_id} in {b.compartment_id} ({bid}).", "info")
        for entry in sim.harvests[prev["harvests"]:]:
            kg = entry["units"] * entry["fresh_weight_g_per_unit"] / 1000.0
            self.harvest_kg_by_day[day] = self.harvest_kg_by_day.get(day, 0.0) + kg
            add(entry["hour"], "harvest", entry["batch_id"],
                f"Harvested {entry['units']:.0f} {entry['unit']} ({kg:.1f} kg) of {entry['crop_id']} for "
                f"{entry['eur']:.2f} EUR" + ("" if entry["sellable"] else " (unsellable)") + ".",
                "info" if entry["sellable"] else "warn")
        self._prev = now


# -- feeding calls ---------------------------------------------------------------------------


def _summ(obj: Any, n: int = 160) -> str:
    try:
        s = json.dumps(obj, separators=(",", ":"), default=str)
    except Exception:
        s = str(obj)
    return s if len(s) <= n else s[: n - 1] + "…"


def log_call(rec: Recorder, ep: Episode, hour: int, tool: str, args: Any, resp: dict[str, Any]) -> None:
    """Record one call as action rows (a submit_day expands into its actions)."""
    day = hour // 24
    ok = bool(resp.get("ok"))
    if tool == "submit_day" and ok:
        acts = (args or {}).get("actions") or []
        results = resp["result"].get("results", [])
        for i, act in enumerate(acts):
            res = results[i] if i < len(results) else {}
            name = str(act.get("tool"))
            a_ok = bool(res.get("ok"))
            rec.actions.append({"h": hour, "day": day, "tool": name,
                                "args": {k: v for k, v in act.items() if k != "tool"}, "ok": a_ok,
                                "err": None if a_ok else str(res.get("error", ""))[:300],
                                "resp_summary": _summ(res.get("result"))})
            if a_ok and name in ("hire", "release", "book_contractor"):
                kind = {"hire": "hire", "release": "release", "book_contractor": "contractor_booked"}[name]
                rec.events.append({"h": hour, "day": day, "kind": kind, "target": name,
                                   "text": f"{name} {_summ(act, 100)}", "severity": "info"})
        if not acts:
            rec.actions.append({"h": hour, "day": day, "tool": "submit_day", "args": {"actions": []}, "ok": True,
                                "err": None, "resp_summary": "no actions"})
    elif not tool.startswith("get_"):
        err = resp.get("error") or {}
        rec.actions.append({"h": hour, "day": day, "tool": tool, "args": args if isinstance(args, dict) else {},
                            "ok": ok, "err": None if ok else str(err.get("message", err))[:300],
                            "resp_summary": _summ(resp.get("result")) if ok else ""})


class _RecordingClient(InProcessClient):
    def __init__(self, ep: Episode, rec: Recorder):
        super().__init__(ep)
        self.rec = rec

    def call(self, tool: str, **args: Any) -> dict[str, Any]:
        hour = self._episode.env.sim.hour
        resp = super().call(tool, **args)
        log_call(self.rec, self._episode, hour, tool, args, resp)
        return resp


# -- the builders ----------------------------------------------------------------------------


def scenario_path(scenario_id: str) -> Path:
    p = SCENARIOS / f"{scenario_id}.toml"
    if "/" in scenario_id or "\\" in scenario_id or not p.is_file():
        raise FileNotFoundError(f"scenario '{scenario_id}' is not in this checkout (scenarios/)")
    return p


def _calibration(scenario_id: str, seed: int) -> dict[str, Any] | None:
    try:
        cal = json.loads((ROOT / "calibration.json").read_text(encoding="utf-8"))
        return cal["tasks"][scenario_id][str(seed)]
    except Exception:
        return None


def baseline_profit(scenario_id: str, seed: int) -> float | None:
    """Profit of doing nothing on this seed, from calibration.json (the score's zero point)."""
    cal = _calibration(scenario_id, seed)
    try:
        return float(cal["components"]["profit"]["zero"])
    except Exception:
        try:
            return float(cal["anchors"]["do-nothing"]["metrics"]["profit_eur"])
        except Exception:
            return None


def _finish(sc, ep: Episode, rec: Recorder, meta: dict[str, Any], t0: float, verified: bool | None,
            mismatches: list[dict[str, Any]]) -> dict[str, Any]:
    ep.finalize()
    sim = ep.env.sim
    ledger = ep.result()
    rl = views.rules(sim)
    crops = {}
    for cid, d in rl["crops"].items():
        d = d if isinstance(d, dict) else {}
        crops[cid] = {k: d.get(k) for k in ("name", "climate_targets", "harvest", "market") if k in d}
    compartments = {cid: {"crop": sim.facility.crop_id(cid)} for cid in sim.facility.compartment_ids}
    shift = sim.business.view(sim.hour, sim.rng.stream("pixel/shift"))["staff"].get("shift", "06:00-14:00")
    profit = round(sim.business.profit_eur(), 2)
    cal = _calibration(sc.id, ep.seed)
    sc_res = None
    try:
        sc_res = score_ledger(sc, ledger, cal)
    except Exception:
        pass
    daily = []
    for d in range(sim.horizon_h // 24):
        end = next((f for f in rec.frames if f["h"] == 24 * (d + 1)), None)
        if end is None:
            continue
        mo = end["money"]
        revenue = mo.get("harvest_revenue_eur", 0.0) + mo.get("electricity_sold_eur", 0.0)
        daily.append({"day": d, "cash": mo.get("cash_eur"), "profit": mo.get("profit_so_far_eur"),
                      "revenue": round(revenue, 2), "costs": round(revenue - mo.get("profit_so_far_eur", 0.0), 2),
                      "harvested_kg": round(rec.harvest_kg_by_day.get(d, 0.0), 1),
                      "alarms": sum(1 for a in rec.alarms if a["h"] // 24 == d)})
    rec.events.sort(key=lambda e: (e["h"], e["kind"]))
    full_meta = {**meta, "scenario": sc.id, "seed": ep.seed, "days": sim.horizon_h // 24,
                 "profit_eur": profit, "baseline_profit_eur": baseline_profit(sc.id, ep.seed),
                 "shift": shift, "max_calls": sc.shift.max_calls, "compartments": compartments, "crops": crops,
                 "objective": rl["objective"], "hours": sim.horizon_h, "replay_verified": verified,
                 "mismatches": mismatches[:10], "end_reason": ep.end_reason, "calls_used": ep.calls,
                 "ledger_score": sc_res["reward"] if sc_res else None,
                 "build_s": round(time.time() - t0, 2)}
    return {"meta": full_meta, "frames": rec.frames, "actions": rec.actions, "events": rec.events,
            "alarms": rec.alarms, "daily": daily}


def replay_trace(trace_path: str | Path, meta: dict[str, Any], scenario_id: str | None = None,
                 seed: int | None = None) -> dict[str, Any]:
    """Rebuild an episode from a recorded trace and capture every hour."""
    t0 = time.time()
    records = read_trace(trace_path)
    header = next((x for x in records if x.get("k") == "header"), {}) or {}
    sid = scenario_id or header.get("scenario")
    seed = int(header.get("seed", 0) if seed is None else seed)
    sc = load_scenario(scenario_path(str(sid)))
    rec = Recorder()
    _tls.rec = rec
    try:
        ep = Episode(sc, seed, Trace(None), "")
        mismatches: list[dict[str, Any]] = []
        n = 0
        for x in records:
            if x.get("k") != "call" or ep.done:
                continue
            n += 1
            hour = ep.env.sim.hour
            tool, args = str(x.get("tool")), x.get("args")
            resp = ep.call(tool, args, record=True)
            log_call(rec, ep, hour, tool, args, resp)
            exp = x.get("digest")
            if exp is not None and digest(resp) != exp:
                mismatches.append({"i": x.get("i"), "tool": tool, "window": x.get("window")})
        verified = (not mismatches) if n else None
        return _finish(sc, ep, rec, meta, t0, verified, mismatches)
    finally:
        _tls.rec = None


def replay_policy(policy: str, seed: int, scenario_id: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Play a scripted policy through the tools (as an agent would) and capture every hour."""
    t0 = time.time()
    classes = policy_classes()
    if policy not in classes:
        raise KeyError(f"unknown policy '{policy}'")
    sc = load_scenario(scenario_path(scenario_id))
    rec = Recorder()
    _tls.rec = rec
    try:
        ep = Episode(sc, seed, Trace(None), "")
        try:
            classes[policy]().run(_RecordingClient(ep, rec))
        except StopPolicy:
            pass
        return _finish(sc, ep, rec, meta, t0, True, [])
    finally:
        _tls.rec = None


def selftest(scenario_id: str = "smoke") -> dict[str, Any]:
    """Replay a scripted policy on the smoke scenario, then replay its own trace."""
    t0 = time.time()
    sc = load_scenario(scenario_path(scenario_id))
    trace = Trace(None)
    ep = Episode(sc, sc.seeds[0], trace, "")
    try:
        policy_classes()["reference"]().run(InProcessClient(ep))
    except StopPolicy:
        pass
    ep.finalize()
    out = replay_trace_records(trace.records, {"id": "selftest"}, sc)
    out["meta"]["selftest_s"] = round(time.time() - t0, 2)
    return out


def replay_trace_records(records: list[dict[str, Any]], meta: dict[str, Any], sc) -> dict[str, Any]:
    """Same as replay_trace for records already in memory (tests, synthetic traces)."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "trace.jsonl"
        p.write_text("".join(json.dumps(x) + "\n" for x in records), encoding="utf-8")
        return replay_trace(p, meta, scenario_id=sc.id, seed=int(records[0].get("seed", sc.seeds[0])))
