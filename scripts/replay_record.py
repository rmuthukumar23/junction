"""Hour-by-hour recorder used by scripts/analyze_runs.py and scripts/trajectories.py (a frozen
copy of the earlier viewer server's game recorder; the viewer itself lives in scripts/viz).

Original notes: plays a real 42-day game in-process and serves a pixel-art replay.

    .venv/bin/python scripts/viz/server.py            # then open http://localhost:8765
    .venv/bin/python scripts/viz/server.py --port 9000

The game is the real simulator (src/greenhouse) on the benchmark scenario
scenarios/normal-winter.toml. A scripted policy plays it through the same tools an
agent gets; every simulated hour is recorded and sent to the page, which replays it.
Reading state for the page uses separate named random streams, so it never
changes the game's result.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from envkit.clients import InProcessClient  # noqa: E402
from envkit.core import Episode  # noqa: E402
from envkit.policies import DoNothing, StopPolicy  # noqa: E402
from envkit.scenario import load_scenario  # noqa: E402
from envkit.trace import Trace  # noqa: E402
from greenhouse.env import GreenhouseBench  # noqa: E402

HERE = Path(__file__).resolve().parent
POLICIES = {**{k: GreenhouseBench.policies()[k] for k in ("reference", "rule-based", "naive")}, "do-nothing": DoNothing}
FREE_TOOLS_SHOWN = {"set_climate", "set_energy", "place_order", "cancel_order", "hire", "release",
                    "plant", "harvest", "repair", "advance", "finish_episode"}


def r(x: Any, n: int = 2) -> Any:
    return round(x, n) if isinstance(x, float) else x


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
        "faults": sorted(sim.effects),
        "money": {k: r(v) for k, v in biz["money"].items()},
        "staff": biz["staff"]["crew"],
        "tasks": [{"kind": t["kind"], "target": t["target"], "done": r(t["worker_hours_done"], 1),
                   "need": r(t["worker_hours_needed"], 1), "st": t["status"]} for t in biz["task_queue"]],
        "orders": [{"id": o["order_id"], "item": o["item"], "qty": o["quantity"], "eta": o["expected_arrival_hour"],
                    "st": o["status"]} for o in biz["open_orders"]],
        "stock": {k: r(v, 0) for k, v in biz["stock"].items()},
        "b": batches,
    }


class Recorder(InProcessClient):
    def __init__(self, episode: Episode, log: list):
        super().__init__(episode)
        self.log, self.sim = log, episode.env.sim

    def call(self, tool: str, **args: Any) -> dict[str, Any]:
        hour = self.sim.hour
        resp = super().call(tool, **args)
        err = None if resp.get("ok") else str(resp.get("error", ""))[:200]
        if tool == "submit_day":
            # One call is one day: log the turn, then each action in it with its own outcome.
            self.log.append({"h": hour, "tool": tool, "args": {"actions": len(args.get("actions", []))},
                             "ok": bool(resp.get("ok")), "err": err})
            results = (resp.get("result") or {}).get("results", []) if resp.get("ok") else []
            for i, action in enumerate(args.get("actions", [])):
                res = results[i] if i < len(results) else {}
                self.log.append({"h": hour, "tool": action.get("tool", "?"),
                                 "args": {k: v for k, v in action.items() if k != "tool"},
                                 "ok": bool(res.get("ok")), "err": None if res.get("ok") else str(res.get("error", err or ""))[:200]})
        elif tool in FREE_TOOLS_SHOWN:
            self.log.append({"h": hour, "tool": tool, "args": args, "ok": bool(resp.get("ok")), "err": err})
        return resp


RUNS = ROOT / "runs"          # committed model runs (Harbor + OpenCode), replayed call for call


def recorded_runs() -> dict[str, dict[str, Any]]:
    """Committed model trajectories: runs/<scenario>/<name>/{trace.jsonl, score.json}."""
    out = {}
    for trace in sorted(RUNS.glob("normal-winter/*/trace.jsonl")):
        head = json.loads(trace.read_text().split("\n", 1)[0])
        out[trace.parent.name] = {"trace": trace, "seed": int(head.get("seed", 1))}
    return out


def play(policy: str, seed: int, runner: Any = None) -> dict[str, Any]:
    """Play one episode and record every hour. `runner` overrides the named policy
    (the analysis script passes edited replays through it)."""
    t0 = time.time()
    if runner is not None:
        pass
    elif policy.startswith("run:"):                 # a recorded model run, re-issued call for call
        run = recorded_runs()[policy[4:]]
        from envkit.policies import Replay
        from envkit.trace import read_trace
        runner, seed = Replay(read_trace(run["trace"])), run["seed"]
    else:
        runner = POLICIES[policy]()
    sc = load_scenario(SCENARIO)
    ep = Episode(sc, seed, Trace(None), "")
    sim = ep.env.sim
    frames = [frame(sim)]
    inner = sim.run_hour

    def run_hour():
        alarms = inner()
        frames.append(frame(sim))
        return alarms

    sim.run_hour = run_hour
    calls: list = []
    try:
        runner.run(Recorder(ep, calls))
    except StopPolicy:
        pass
    ep.finalize()
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
    biz = sim.business
    market = {"loss_eur": round(getattr(biz, "market_loss_eur", 0.0), 2), "over_demand_units": round(getattr(biz, "over_demand_units", 0.0), 1),
              "demand_per_week": getattr(biz, "demand", {}),
              "sold_units": {c: round(sum(q for _, q in rows), 1) for c, rows in getattr(biz, "sales", {}).items()}}
    return {"policy": policy, "seed": seed, "hours": sim.horizon_h, "frames": frames, "alarms": alarms,
            "shift": shift, "market": market, "baseline_profit": baseline(seed), "max_calls": sc.shift.max_calls,
            "calls": calls, "compartments": compartments, "crops": crops,
            "objective": rl["objective"], "profit": round(sim.business.profit_eur(), 2),
            "elapsed_s": round(time.time() - t0, 2)}


_BASELINE: dict[int, float] = {}


def baseline(seed: int) -> float:
    """Profit of doing nothing on the same seed: what the grower has to beat."""
    if seed not in _BASELINE:
        ep = Episode(load_scenario(SCENARIO), seed, Trace(None), "")
        ep.finalize()
        _BASELINE[seed] = round(ep.env.sim.business.profit_eur(), 2)
    return _BASELINE[seed]


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

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        name = "index.html" if u.path == "/" else u.path.lstrip("/")
        if name in STATIC:
            self._send(200, (HERE / name).read_bytes(), STATIC[name])
            return
        if u.path == "/api/runs":
            body = json.dumps([{"id": f"run:{k}", "seed": v["seed"]} for k, v in recorded_runs().items()]).encode()
            self._send(200, body, "application/json")
            return
        if u.path == "/api/run":
            q = parse_qs(u.query)
            policy = q.get("policy", ["naive"])[0]
            try:
                seed = int(q.get("seed", ["1"])[0])
            except ValueError:
                seed = -1
            if u.path == "/api/run" and policy.startswith("run:") and policy[4:] in recorded_runs():
                pass
            elif policy not in POLICIES or not 1 <= seed <= 9999:
                self._send(400, b'{"error":"unknown policy, or seed outside 1-9999"}', "application/json")
                return
            try:
                body = json.dumps(play(policy, seed), separators=(",", ":")).encode()
            except Exception as exc:  # show the failure on the page, not just in the terminal
                self._send(500, json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode(), "application/json")
                raise
            self._send(200, body, "application/json")
            return
        self._send(404, b"not found", "text/plain")

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("viz: " + fmt % args + "\n")


SCENARIO = ROOT / "scenarios" / "normal-winter.toml"

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    print(f"Greenhouse viewer on http://localhost:{a.port}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
