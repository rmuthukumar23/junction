"""Greenhouse Bench viewer: six growers on the same greenhouse, side by side, replayed from the real simulator.

    .venv/bin/python scripts/viz/server.py            # then open http://localhost:8765
    .venv/bin/python scripts/viz/server.py --port 9000 --scenario quick-winter

Every panel is a real game of the simulator in src/greenhouse, played through the same
`submit_day` tool an agent gets:

  * scripted growers (reference, rule-based, naive, nobody, exploits) play live here;
  * a model run (e.g. Gemini through Harbor) is replayed from the trace its trial left in
    artifacts/**/trace.jsonl: each recorded call is sent to a fresh simulator in order and
    its response is checked against the recorded digest, so the panel shows exactly what
    the model did and saw ("replay verified").

Every simulated hour and every decision (each action inside each daily turn, with its
outcome) is recorded and sent to the page. Games run in worker processes, one per core.
Reading state for the page uses separate named random streams, so it never changes a
game's result.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from concurrent.futures import Future, ProcessPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from envkit.clients import InProcessClient, run_inprocess  # noqa: E402
from envkit.core import Episode  # noqa: E402
from envkit.policies import Policy, StopPolicy, make_policy  # noqa: E402
from envkit.scenario import load_scenario  # noqa: E402
from envkit.trace import Trace, digest, read_trace  # noqa: E402

HERE = Path(__file__).resolve().parent
ARTIFACTS = ROOT / "artifacts"
SCENARIO = ROOT / "scenarios" / "normal-winter.toml"     # replaced by --scenario
FREE_TOOLS_SHOWN = {"set_climate", "set_energy", "place_order", "cancel_order", "hire", "release",
                    "plant", "harvest", "repair", "advance", "finish_episode"}


def r(x: Any, n: int = 2) -> Any:
    return round(x, n) if isinstance(x, float) else x


# ---------------------------------------------------------------- players

def builtin_players(sc) -> list[dict[str, str]]:
    """Scripted growers that can fill a panel; `id` is an envkit policy spec."""
    days = max(1, round(sc.shift.windows * sc.shift.window_hours / 24))
    names = {"reference": "Reference solution", "rule-based": "Rule-based grower", "naive": "Naive grower",
             "do-nothing": "Nobody (do nothing)", "absentee": "Absentee (looks, never acts)"}
    out = [{"id": k, "label": v, "kind": "scripted"} for k, v in names.items()]
    out.append({"id": f"stop-after:reference@{max(1, days // 2)}", "label": "Reference, stops halfway", "kind": "scripted"})
    for a in sc.anchors:
        if a.startswith("exploit:"):
            out.append({"id": a, "label": "Exploit: " + a.split(":", 1)[1].replace("-", " "), "kind": "exploit"})
    return out


def trace_players() -> list[dict[str, Any]]:
    """Recorded runs under artifacts/: model runs first, newest first."""
    found = []
    for path in ARTIFACTS.glob("**/var/lib/envkit/trace.jsonl") if ARTIFACTS.exists() else []:
        trial = path.parents[4] if len(path.parents) > 4 else path.parent
        try:
            header = next((rec for rec in read_trace(path) if rec.get("k") == "header"), {})
        except Exception:
            continue
        job = trial.parent.name
        model = None
        try:
            model = json.loads((trial / "config.json").read_text())["agent"].get("model_name")
        except Exception:
            pass
        reward = None
        try:
            reward = json.loads((trial / "verifier" / "score.json").read_text()).get("reward")
        except Exception:
            pass
        is_agent = job.endswith("agent")
        who = (model or "model") if is_agent else job.split("-", 1)[-1]
        found.append({"id": "trace:" + path.relative_to(ROOT).as_posix(), "kind": "model" if is_agent else "recorded",
                      "label": f"{who} · {trial.name.split('__')[-1]}", "model": model, "job": job,
                      "scenario": header.get("scenario"), "seed": header.get("seed"), "reward": reward,
                      "run": trial.parents[2].name if len(trial.parents) > 2 else "", "mtime": path.stat().st_mtime})
    found.sort(key=lambda p: (p["kind"] != "model", -p["mtime"]))
    return found


class TracePolicy(Policy):
    """Sends a recorded run's calls to a fresh simulator, in order: the model's own decisions."""

    def __init__(self, calls: list[dict[str, Any]]):
        self.calls = calls

    def run(self, client) -> None:
        for rec in self.calls:
            client.call(str(rec.get("tool")), **(rec.get("args") or {}))


# ---------------------------------------------------------------- what an action changed

DISCRETE = {"harvest_revenue", "repairs", "seedlings", "orders", "fines", "contractors", "parts", "express", "hiring", "co2"}
CLIMATE_FIELDS = {"heat_day_c": ("day heating", "°C"), "heat_night_c": ("night heating", "°C"), "co2_ppm": ("CO2 target", " ppm"),
                  "vent_min_pct": ("vents min", "%"), "vent_max_pct": ("vents max", "%"), "screen": ("screen", ""),
                  "lamp_intensity_pct": ("lamp intensity", "%"), "lamp_hours": ("lamp hours", "")}


def state(sim) -> dict[str, Any]:
    """The simulator state an action can change, read without touching any random stream."""
    biz, ops = sim.business, sim.business.ops.view()
    return {
        "climate": {c: asdict(sp) for c, sp in sim.climate.items()},
        "energy": asdict(sim.energy),
        "night": {e.hour: {"climate": {c: asdict(sp) for c, sp in e.climate.items()}, "energy": asdict(e.energy)} for e in sim.night},
        "orders": {o["order_id"]: o for o in ops["open_orders"]},
        "staff": {"crew": ops["staff"]["crew"], "leaving": ops["staff"]["leaving"],
                  "arriving": [(a["start_hour"], a["workers"]) for a in ops["staff"]["arriving"]]},
        "tasks": {t["task_id"]: t for t in ops["task_queue"]},
        "bookings": {b.id: {"trade": b.trade, "target": b.target, "earliest": b.earliest_visit_hour, "parts": dict(b.parts_needed)}
                     for b in biz.contractors.bookings},
        "stock": {k: round(v, 3) for k, v in biz.ops.stock.items()},
        "cash": round(biz.ledger.cash_eur, 2),
    }


def _fmt(k: str, v: Any) -> str:
    if k == "lamp_hours":
        return f"{len(v)} h" if v else "off"
    name, unit = CLIMATE_FIELDS.get(k, (k.replace("_", " "), ""))
    return f"{v:g}{unit}" if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)


def _when(h: int) -> str:
    return f"day {h // 24 + 1} {h % 24:02d}:00"


def _grouped(per_comp: dict[str, dict[str, Any]], before: dict[str, dict[str, Any]]) -> list[str]:
    """'A,B,C day heating 20°C→18°C': one line per field and change, compartments grouped."""
    groups: dict[tuple, list[str]] = {}
    for c in sorted(per_comp):
        for k, v in per_comp[c].items():
            old = before.get(c, {}).get(k)
            if old != v:
                groups.setdefault((k, json.dumps(old), json.dumps(v)), []).append(c)
    out = []
    for (k, old, new), comps in groups.items():
        name = CLIMATE_FIELDS.get(k, (k.replace("_", " "), ""))[0]
        out.append(f"{''.join(comps)} {name} {_fmt(k, json.loads(old))}→{_fmt(k, json.loads(new))}")
    return out


def diff(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    """Every difference between two states, in plain words."""
    out = _grouped(b["climate"], a["climate"])
    for k, v in b["energy"].items():
        if a["energy"].get(k) != v:
            out.append(f"energy {k.replace('_', ' ')} {json.dumps(a['energy'].get(k))}→{json.dumps(v)}")
    for hour in sorted(set(a["night"]) | set(b["night"]), key=lambda h: (h - 18) % 24):
        old, new = a["night"].get(hour), b["night"].get(hour)
        if old == new:
            continue
        if new is None:
            out.append(f"night entry {hour:02d}:00 removed")
            continue
        base = old or a["night"][max((h for h in a["night"] if (h - 18) % 24 <= (hour - 18) % 24), key=lambda h: (h - 18) % 24)]
        lines = _grouped(new["climate"], base["climate"])
        lines += [f"{k.replace('_', ' ')} {json.dumps(base['energy'].get(k))}→{json.dumps(v)}" for k, v in new["energy"].items() if base["energy"].get(k) != v]
        out.append(f"night {hour:02d}:00{'' if old else ' (new entry)'}: " + ("; ".join(lines) if lines else "same values"))
    for oid, o in b["orders"].items():
        if oid not in a["orders"]:
            out.append(f"order {oid}: {o['quantity']:,.0f} {o['item']}, arrives {_when(o['expected_arrival_hour'])}"
                       f"{' (express)' if o.get('express') else ''}, paid on delivery")
    for oid in a["orders"]:
        if oid not in b["orders"]:
            out.append(f"order {oid} cancelled")
    if a["staff"] != b["staff"]:
        sa, sb = a["staff"], b["staff"]
        new_arr = [x for x in sb["arriving"] if x not in sa["arriving"]]
        out += [f"{n} worker(s) start {_when(h)}" for h, n in new_arr]
        if sb["leaving"] != sa["leaving"]:
            out.append(f"workers leaving {sa['leaving']}→{sb['leaving']}")
        if sb["crew"] != sa["crew"]:
            out.append(f"crew {sa['crew']}→{sb['crew']}")
    for tid, t in b["tasks"].items():
        if tid not in a["tasks"]:
            out.append(f"task {tid}: {t['kind']} {t['target']} queued, {t['worker_hours_needed']:g} worker-h")
    for bid, bk in b["bookings"].items():
        if bid not in a["bookings"]:
            have = {i: b["stock"].get(i, 0) for i in bk["parts"]}
            parts = ", ".join(f"{n} {i.split(':')[-1].replace('_', ' ')} (in stock {have[i]:g})" for i, n in bk["parts"].items())
            out.append(f"{bk['trade'].replace('_', ' ')} {bid} booked for {bk['target']}: visit from {_when(bk['earliest'])}"
                       + (f", needs {parts}" if parts else ""))
    for item in sorted(set(a["stock"]) | set(b["stock"])):
        d = b["stock"].get(item, 0) - a["stock"].get(item, 0)
        if abs(d) > 1e-6:
            out.append(f"stock {item} {d:+,.0f}")
    if abs(b["cash"] - a["cash"]) > 0.005:
        out.append(f"cash {b['cash'] - a['cash']:+,.2f} €")
    return out


def instrument(env, log: list) -> None:
    """Wrap each daily action so the state just before and just after it is compared.
    submit_day calls the action on the instance, so this sees every action that passed
    argument checks, accepted or refused, in order."""
    from greenhouse.env import ACTION_NAMES
    for name in ACTION_NAMES:
        inner = getattr(env, name)

        def wrapped(*args, _inner=inner, _name=name, **kwargs):
            before = state(env.sim)
            try:
                out = _inner(*args, **kwargs)
            except Exception:
                log.append({"tool": _name, "kwargs": kwargs, "raised": True, "changes": diff(before, state(env.sim))})
                raise
            log.append({"tool": _name, "kwargs": kwargs, "raised": False, "changes": diff(before, state(env.sim))})
            return out

        setattr(env, name, wrapped)


# ---------------------------------------------------------------- recording one game

def frame(sim) -> dict[str, Any]:
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
    biz = sim.business.view(sim.hour, sim.rng.stream(f"viz/business/{sim.hour}"))
    batches = []
    for b in sim.batches.values():
        est = sim.growth[b.crop_id].estimate(b, sim.hour, sim.rng.stream(f"viz/estimate/{b.id}/{sim.hour}"))
        batches.append({"id": b.id, "crop": b.crop_id, "c": b.compartment_id, "area": r(b.area_m2, 1),
                        "age": r((sim.hour - b.planted_hour) / 24, 1), "st": b.status,
                        "q": b.id in sim.queued_harvests, "w": r(est.fresh_weight_g_per_unit, 1),
                        "qual": r(est.quality, 3), "ready": r(est.days_to_ready, 1) if est.days_to_ready is not None else None,
                        "units": round(est.units)})
    e = sim.energy
    return {
        "h": sim.hour,
        "out": {"t": rd["outside"]["temp_c"], "rh": rd["outside"]["rh_pct"], "sun": rd["outside"]["solar_w_m2"],
                "wind": rd["outside"]["wind_m_s"]},
        "c": comps,
        "ec": {"buffer": r(rd["energy_centre"]["buffer_kwh"], 0), "co2": r(rd["energy_centre"]["co2_store_kg"], 0),
               "chp": e.chp_load, "boiler": e.boiler, "bufmode": e.buffer, "extco2": e.external_co2_kg_h,
               "gas": r(m.get("gas_m3", 0.0)), "imp": r(m.get("electricity_import_kwh", 0.0)),
               "exp": r(m.get("electricity_export_kwh", 0.0)), "heat": r(m.get("heat_produced_kwh", 0.0)),
               "lost": r(m.get("heat_lost_kwh", 0.0)), "p_gas": m.get("gas_eur_per_m3"),
               "p_imp": m.get("import_eur_per_kwh"), "p_exp": m.get("export_eur_per_kwh")},
        "hd": {c: r(v, 1) for c, v in (m.get("heat_delivered_kwh") or {}).items()},
        "faults": sorted(sim.effects),
        "money": {k: r(v) for k, v in biz["money"].items()},
        "staff": biz["staff"]["crew"],
        "tasks": [{"kind": t["kind"], "target": t["target"], "done": r(t["worker_hours_done"], 1),
                   "need": r(t["worker_hours_needed"], 1), "st": t["status"]} for t in biz["task_queue"]],
        "orders": [{"id": o["order_id"], "item": o["item"], "qty": o["quantity"], "eta": o["expected_arrival_hour"],
                    "st": o["status"]} for o in biz["open_orders"]],
        "stock": {k: r(v, 0) for k, v in biz["stock"].items()},
        "b": batches,
        "dmg": [{"eq": o["equipment"], "panes": o.get("panes_broken", 0), "since": o["since_hour"],
                 "rep": (o.get("repair") or {}).get("status")} for o in biz["outages"]],
        "crew_on": [{"id": b.id, "trade": b.trade, "target": b.target, "st": b.status, "done": r(b.hours_done, 1),
                     "need": r(b.job_hours, 1)} for b in sim.business.contractors.bookings
                    if b.status == "on_site" or (b.done_hour is not None and b.done_hour >= sim.hour - 1)],
    }


class Recorder(InProcessClient):
    """Logs every decision: each daily turn, and each action inside it with its own outcome.
    `turn` numbers the agent's tool calls, as the call budget counts them."""

    def __init__(self, episode: Episode, log: list, expected: list[str | None] | None = None):
        super().__init__(episode)
        self.log, self.sim, self.turn = log, episode.env.sim, 0
        self.expected, self.matched = expected, 0
        self.effects: list[dict[str, Any]] = []
        instrument(episode.env, self.effects)

    def call(self, tool: str, **args: Any) -> dict[str, Any]:
        hour = self.sim.hour
        self.effects.clear()
        resp = super().call(tool, **args)
        effects = list(self.effects)
        if self.expected is not None and self.turn < len(self.expected) and digest(resp) == self.expected[self.turn]:
            self.matched += 1
        self.turn += 1
        err = None if resp.get("ok") else str(resp.get("error", ""))[:200]
        if tool == "submit_day":
            actions = args.get("actions", []) or []
            self.log.append({"h": hour, "turn": self.turn, "tool": tool, "args": {"actions": len(actions)},
                             "ok": bool(resp.get("ok")), "err": err})
            results = (resp.get("result") or {}).get("results", []) if resp.get("ok") else []
            for i, action in enumerate(actions):
                res = results[i] if i < len(results) else {}
                ok = bool(res.get("ok"))
                # The state change this action made, measured on the simulator. An action refused by
                # its argument check never reached the simulator, so it has no record.
                rec = None
                if effects and effects[0]["tool"] == action.get("tool") and effects[0]["raised"] == (not ok):
                    rec = effects.pop(0)
                self.log.append({"h": hour, "turn": self.turn, "i": i, "tool": action.get("tool", "?"),
                                 "args": {k: v for k, v in action.items() if k != "tool"},
                                 "ok": ok, "err": None if ok else str(res.get("error", err or ""))[:200],
                                 "fx": rec["changes"] if rec else [], "reached": rec is not None})
        else:
            self.log.append({"h": hour, "turn": self.turn, "tool": tool, "args": args, "ok": bool(resp.get("ok")), "err": err})
        return resp


def resolve_trace(spec: str) -> Path:
    path = (ROOT / spec.split(":", 1)[1]).resolve()
    if ARTIFACTS.resolve() not in path.parents or path.name != "trace.jsonl" or not path.is_file():
        raise ValueError("not a trace under artifacts/")
    return path


def play(spec: str, seed: int, scenario_path: str) -> dict[str, Any]:
    """One whole game with every hour and every decision recorded. Runs in a worker process."""
    t0 = time.time()
    expected = None
    if spec.startswith("trace:"):
        records = read_trace(resolve_trace(spec))
        header = next((rec for rec in records if rec.get("k") == "header"), {})
        scenario_path = str(ROOT / "scenarios" / f"{header.get('scenario')}.toml")
        seed = int(header.get("seed", seed))
        calls = [rec for rec in records if rec.get("k") == "call"]
        policy, expected = TracePolicy(calls), [rec.get("digest") for rec in calls]
    sc = load_scenario(scenario_path)
    if not spec.startswith("trace:"):
        policy = make_policy(spec, sc)
    ep = Episode(sc, seed, Trace(None), "")
    sim = ep.env.sim
    frames = [frame(sim)]
    inner = sim.run_hour

    def run_hour():
        alarms = inner()
        frames.append(frame(sim))
        return alarms

    sim.run_hour = run_hour
    calls_log: list = []
    rec = Recorder(ep, calls_log, expected)
    try:
        policy.run(rec)
    except StopPolicy:
        pass
    ep.finalize()
    ledger = ep.result()
    # Frames are indexed by hour: the handover hours ran before recording started, and a
    # bankrupt run stops early, so pad both ends to cover 0..horizon.
    first, last = frames[0], frames[-1]
    frames = [{**first, "h": h} for h in range(first["h"])] + frames
    frames += [{**last, "h": h} for h in range(last["h"] + 1, sim.horizon_h + 1)]
    from greenhouse import views
    rl = views.rules(sim)
    crops = {}
    for cid, d in rl["crops"].items():
        d = d if isinstance(d, dict) else {}
        crops[cid] = {k: d.get(k) for k in ("name", "climate_targets", "harvest", "market") if k in d}
    alarms = [{"h": a.hour, "kind": a.kind, "target": a.target, "text": a.text} for a in sim.alarms]
    compartments = {}
    for cid in sim.facility.compartment_ids:
        crop = next((b.crop_id for b in sim.batches.values() if b.compartment_id == cid), "")
        compartments[cid] = {"crop": crop}
    shift = sim.business.view(sim.hour, sim.rng.stream("viz/shift"))["staff"].get("shift", "07:00-15:00")
    led = sim.business.ledger
    money = frames[-1]["money"]
    parts = sum(v for k, v in money.items() if k not in ("cash_eur", "profit_so_far_eur"))
    checks = {
        "ledger_profit_eur": round(led.profit_eur, 2),
        "last_frame_profit_eur": money["profit_so_far_eur"],
        "categories_sum_eur": round(parts, 2),
        "conservation_error_eur": round(led.conservation_error(), 6),
    }
    checks["ok"] = (abs(checks["ledger_profit_eur"] - checks["last_frame_profit_eur"]) < 0.05
                    and abs(checks["categories_sum_eur"] - checks["ledger_profit_eur"]) < 0.5
                    and checks["conservation_error_eur"] < 0.01)
    entries = [{"h": e.hour, "cat": e.category, "eur": round(e.eur, 2), "note": e.note} for e in led.entries if e.category in DISCRETE]
    out = {"policy": spec, "seed": seed, "scenario": sc.id, "checks": checks, "entries": entries,
           "substeps": sim.substeps, "hours": sim.horizon_h, "frames": frames, "alarms": alarms,
           "shift": shift, "max_calls": sc.shift.max_calls, "turns": rec.turn,
           "calls": calls_log, "compartments": compartments, "crops": crops,
           "objective": rl["objective"], "profit": round(float(ledger.get("profit_eur", sim.business.profit_eur())), 2),
           "bankrupt": bool(ledger.get("bankrupt")), "end_reason": ledger.get("end_reason"),
           "elapsed_s": round(time.time() - t0, 2)}
    if expected is not None:
        out["replay"] = {"calls": len(expected), "matched": rec.matched}
    return out


def anchor_profits(seed: int, scenario_path: str) -> dict[str, float]:
    """Profit of the scoring anchors on this seed: the official score is pinned to them."""
    sc = load_scenario(scenario_path)
    names = dict.fromkeys(n for c in sc.components if c.kind == "anchored" for n in (*c.zero_anchors, *c.top_anchors))
    return {n: float(run_inprocess(sc, seed, make_policy(n, sc)).result()[sc.components[0].metrics[0]]) for n in names}


def official_score(sc, profit: float, anchors: dict[str, float]) -> float | None:
    """The benchmark's anchored score (envkit.scoring): 0 = best zero anchor, target = best top anchor."""
    comp = next((c for c in sc.components if c.kind == "anchored"), None)
    if comp is None:
        return None
    zero = max(anchors[n] for n in comp.zero_anchors)
    scale = round((max(anchors[n] for n in comp.top_anchors) - zero) / comp.target, 2)
    return None if scale <= 0 else round(max(0.0, min(1.0, (profit - zero) / scale)), 4)



# ---------------------------------------------------------------- launching a model run

JOBS: dict[str, dict[str, Any]] = {}


def env_model() -> str | None:
    """AFTERQUERY_MODEL from the environment or .env (the key itself is never read here)."""
    if os.environ.get("AFTERQUERY_MODEL"):
        return os.environ["AFTERQUERY_MODEL"]
    try:
        for line in (ROOT / ".env").read_text().splitlines():
            if line.strip().startswith("AFTERQUERY_MODEL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    except OSError:
        pass
    return None


def default_backend() -> str:
    return "modal" if (Path.home() / ".modal.toml").exists() or os.environ.get("MODAL_TOKEN_ID") else "docker"


def launch(model: str, seed: int, scenario: str, backend: str) -> dict[str, Any]:
    """Start the official benchmark run for one model (scripts/judge.sh: Harbor + OpenCode, the
    same path the judges use) in the background. Its trace lands under artifacts/viewer-runs/."""
    job_id = time.strftime("%Y%m%d-%H%M%S")
    out = ARTIFACTS / "viewer-runs" / job_id
    out.mkdir(parents=True, exist_ok=True)
    cmd = ["bash", "scripts/judge.sh", "--agent-only", "--runs", "1", "--seeds", str(seed),
           "--model", model, "--backend", backend, "--output", str(out.relative_to(ROOT))]
    log = open(out / "launch.log", "w")
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                            env={**os.environ, "ENVKIT_SCENARIO": scenario})
    JOBS[job_id] = {"id": job_id, "model": model, "seed": seed, "scenario": scenario, "backend": backend,
                    "started": time.time(), "proc": proc, "dir": out, "cmd": " ".join(cmd)}
    return job_view(JOBS[job_id])


def job_view(j: dict[str, Any]) -> dict[str, Any]:
    code = j["proc"].poll()
    traces = sorted("trace:" + p.relative_to(ROOT).as_posix() for p in j["dir"].glob("**/var/lib/envkit/trace.jsonl"))
    try:
        tail = (j["dir"] / "launch.log").read_text(errors="replace").splitlines()[-6:]
    except OSError:
        tail = []
    status = "running" if code is None else ("finished" if traces else "failed")
    return {"id": j["id"], "model": j["model"], "seed": j["seed"], "scenario": j["scenario"], "backend": j["backend"],
            "status": status, "exit": code, "elapsed_s": round(time.time() - j["started"]), "traces": traces,
            "log": tail, "cmd": j["cmd"]}

# ---------------------------------------------------------------- serving

POOL: ProcessPoolExecutor | None = None
CACHE: dict[tuple, Future] = {}
LOCK = threading.Lock()


def submit(fn, *args) -> Future:
    with LOCK:
        key = (fn.__name__, *args)
        if key not in CACHE or (CACHE[key].done() and CACHE[key].exception() is not None):
            CACHE[key] = POOL.submit(fn, *args)
        return CACHE[key]


def run_for(spec: str, seed: int) -> dict[str, Any]:
    if spec.startswith("trace:"):
        resolve_trace(spec)      # reject anything that is not a trace under artifacts/
        seed = 0                 # a recorded run carries its own seed; one cache entry per trace
    game = submit(play, spec, seed, str(SCENARIO)).result()
    scenario_path = str(ROOT / "scenarios" / f"{game['scenario']}.toml")
    anchors = submit(anchor_profits, game["seed"], scenario_path).result()
    sc = load_scenario(scenario_path)
    game["score"] = official_score(sc, game["profit"], anchors)
    game["anchors"] = anchors
    return game


STATIC = {"index.html": "text/html; charset=utf-8", "scene.js": "text/javascript; charset=utf-8",
          "ui.js": "text/javascript; charset=utf-8", "style.css": "text/css; charset=utf-8"}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: Any) -> None:
        body = json.dumps(obj, separators=(",", ":")).encode()
        if "gzip" in self.headers.get("Accept-Encoding", "") and len(body) > 4096:
            body = gzip.compress(body, compresslevel=5)     # a 42-day game is ~6 MB of JSON, ~0.5 MB gzipped
            self.send_response(code)
            for k, v in (("Content-Type", "application/json"), ("Content-Encoding", "gzip"),
                         ("Content-Length", str(len(body))), ("Cache-Control", "no-store")):
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
            return
        self._send(code, body, "application/json")

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        name = "index.html" if u.path == "/" else u.path.lstrip("/")
        if name in STATIC:
            self._send(200, (HERE / name).read_bytes(), STATIC[name])
            return
        q = parse_qs(u.query)
        if u.path == "/api/players":
            sc = load_scenario(SCENARIO)
            builtin, traces = builtin_players(sc), trace_players()
            model = next((t["id"] for t in traces if t["kind"] == "model"), "model:none")
            half = next(p["id"] for p in builtin if p["id"].startswith("stop-after:"))
            self._json(200, {"scenario": sc.id, "title": sc.title, "builtin": builtin, "traces": traces,
                             "slots": ["reference", model, "rule-based", "naive", half, "do-nothing"]})
            return
        if u.path == "/api/jobs":
            self._json(200, {"jobs": [job_view(j) for j in sorted(JOBS.values(), key=lambda j: -j["started"])],
                             "env_model": env_model(), "backend": default_backend()})
            return
        if u.path == "/api/run":
            spec = q.get("player", ["naive"])[0]
            try:
                seed = int(q.get("seed", ["1"])[0])
            except ValueError:
                seed = -1
            sc = load_scenario(SCENARIO)
            known = {p["id"] for p in builtin_players(sc)}
            if not (spec in known or spec.startswith("trace:")) or not 1 <= seed <= 9999:
                self._json(400, {"error": "unknown player, or seed outside 1-9999"})
                return
            try:
                self._json(200, run_for(spec, seed))
            except Exception as exc:  # show the failure on the page, not just in the terminal
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/launch":
            self._send(404, b"not found", "text/plain")
            return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0) or 0)) or b"{}")
            model = str(body.get("model", "")).strip()
            seed = int(body.get("seed", 1))
            scenario = str(body.get("scenario") or SCENARIO.stem)
            backend = str(body.get("backend") or default_backend())
            if not model or any(ch.isspace() for ch in model) or not 1 <= seed <= 9999 \
                    or not (ROOT / "scenarios" / f"{scenario}.toml").exists() or backend not in ("modal", "docker"):
                raise ValueError("give a model id like provider/model, a seed 1-9999, a scenario and modal or docker")
            self._json(200, launch(model, seed, scenario, backend))
        except Exception as exc:
            self._json(400, {"error": str(exc)})

    def log_message(self, fmt: str, *args: Any) -> None:
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write("viz: " + fmt % args + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--scenario", default="normal-winter", help="scenario the scripted growers play")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1, help="games simulated at once")
    a = ap.parse_args()
    SCENARIO = ROOT / "scenarios" / f"{a.scenario}.toml"
    POOL = ProcessPoolExecutor(max_workers=max(1, a.jobs))
    print(f"Greenhouse viewer on http://localhost:{a.port}  ({a.scenario}, {a.jobs} worker(s); Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
