"""Synthetic runs and replays in the site's contract shape (fast; no simulator, no model)."""
from __future__ import annotations

import math


def run(id, kind="agent", model=None, policy=None, seed=1, score=None, profit=None, base=None,
        status="complete", failure=None, started="2026-11-14T08:00:00Z", days=42):
    return {"id": id, "label": f"{model or policy} s{seed}", "kind": kind, "model": model, "policy": policy,
            "scenario": "normal-winter", "seed": seed, "score": score, "profit_eur": profit,
            "baseline_profit_eur": base, "days": days, "status": status, "failure": failure,
            "started": started, "source": "synthetic"}


def replay(days=42, profit_per_day=100.0, faults_days=(), invalid=0, lost=False, bankrupt=False, with_events=True):
    frames, daily = [], []
    for d in range(1, days + 1):
        for hod in range(24):
            h = (d - 1) * 24 + hod
            cash = 1000 + profit_per_day * d
            if bankrupt and d > 5:
                cash = -50.0
            frames.append({
                "day": d, "hod": hod, "out": {},
                "c": {"A": {"t": 20.0, "co2req": 0.5}},
                "ec": {"gas": 2.0, "imp": 1.0, "exp": 0.5, "heat": 10.0, "lost": 1.0, "chp": 1 if hod < 12 else 0,
                       "boiler": 0 if hod < 12 else 1, "p_gas": 0.5, "p_imp": 0.2, "p_exp": 0.1},
                "faults": ["pump_trip"] if d in faults_days else [],
                "money": {"cash": cash, "profit": cash - 1000},
                "b": [{"id": "B1", "crop": "lettuce", "st": "lost" if (lost and d > 30) else "growing",
                       "ready": -1 if 10 <= d < 12 else 5}],
            })
        daily.append({"day": d, "cash": 1000 + profit_per_day * d, "profit": profit_per_day * d,
                      "revenue": 0, "costs": 0, "harvested_kg": 0, "alarms": 0})
    actions = [{"h": 6 + 24 * i, "day": i + 1, "tool": "set_climate", "args": {"compartment": "A"}, "ok": True,
                "err": None, "resp_summary": ""} for i in range(days)]
    actions += [{"h": 7 + 24 * i, "day": i + 1, "tool": "plant", "args": {}, "ok": False,
                 "err": f"no free area {i + 1} m2", "resp_summary": ""} for i in range(invalid)]
    events = [{"h": 30, "day": 2, "kind": "pump_trip", "target": "pump", "text": "pump tripped", "severity": "high"}] if with_events else []
    alarms = [{"h": 100, "kind": "frost", "target": None, "text": "frost risk"}] if with_events else []
    return {"meta": {}, "frames": frames, "actions": actions, "events": events, "alarms": alarms, "daily": daily}


def sample():
    """(runs, replays-by-id): reference policy, do-nothing, two models with different outcomes, failures."""
    runs = [
        run("ref-1", "policy", policy="reference", seed=1, score=1.0, profit=9000, base=1000, started="2026-11-14T08:01:00Z"),
        run("dn-1", "policy", policy="do-nothing", seed=1, score=0.0, profit=1000, base=1000, started="2026-11-14T08:02:00Z"),
        run("m1-1", model="google/model-a", seed=1, score=0.7, profit=6000, base=1000, started="2026-11-14T08:03:00Z"),
        run("m1-2", model="google/model-a", seed=2, score=0.5, profit=-200, base=1000, status="partial",
            failure="bankrupt on day 6", started="2026-11-14T08:04:00Z", days=6),
        run("m2-1", model="google/model-b", seed=1, score=0.2, profit=500, base=1000, started="2026-11-14T08:05:00Z"),
        run("m2-2", model="google/model-b", seed=2, status="failed", failure="AgentSetupTimeoutError: Agent setup timed out after 360.0 seconds",
            started="2026-11-14T08:06:00Z", days=0),
        run("m2-3", model="google/model-b", seed=3, status="failed", failure=None, started="2026-11-14T08:07:00Z", days=0),
    ]
    replays = {
        "ref-1": replay(profit_per_day=190),
        "dn-1": replay(profit_per_day=0, with_events=False),
        "m1-1": replay(profit_per_day=120, faults_days=(3, 4, 5), invalid=4),
        "m1-2": replay(days=6, bankrupt=True, lost=False),
        "m2-1": replay(profit_per_day=10, lost=True, invalid=2),
    }
    return runs, replays


def fake_load(replays):
    def load(rid):
        if rid not in replays:
            raise KeyError(rid)
        return replays[rid]
    return load


if __name__ == "__main__":  # python synth.py OUT.json: stats JSON for the demo page
    import json
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "pixel"))
    from analytics import compute_stats
    rs, rp = sample()
    Path(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True)
    Path(sys.argv[1]).write_text(json.dumps(compute_stats(rs, fake_load(rp))), encoding="utf-8")
    assert not math.isnan(0)
