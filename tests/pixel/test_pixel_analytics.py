"""Fast tests for scripts/pixel/analytics.py on synthetic fixtures (no simulator, no model)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "pixel"))

import analytics  # noqa: E402
import synth  # noqa: E402


def stats(**kw):
    runs, rp = synth.sample()
    return analytics.compute_stats(runs, synth.fake_load(rp), **kw)


def test_json_safe_and_deterministic():
    a, b = stats(), stats()
    assert a == b
    json.dumps(a, allow_nan=False)
    assert {"leaderboard", "runs", "profit_curves", "tool_usage", "mistakes", "energy", "meta"} <= set(a)


def test_failure_classes_never_blame_agent_for_infrastructure():
    c = analytics.classify_failure
    assert c("failed", "AgentSetupTimeoutError: Agent setup timed out after 360.0 seconds") == "infrastructure"
    assert c("failed", "NonZeroAgentExitCodeError ... 'status': 'NOT_FOUND'") == "infrastructure"
    assert c("partial", "bankrupt on day 6") == "agent"
    assert c("failed", None) == "unknown"
    assert c("failed", "something odd") == "unknown"
    assert c("complete", None) == "none"
    s = stats()
    b = next(g for g in s["leaderboard"] if g["name"] == "google/model-b")
    assert b["failures"] == {"agent": 0, "infrastructure": 1, "unknown": 1}
    a = next(g for g in s["leaderboard"] if g["name"] == "google/model-a")
    assert a["failures"]["agent"] == 1 and a["n_partial"] == 1
    assert s["meta"]["failures_by_class"] == {"agent": 1, "infrastructure": 1, "unknown": 1}


def test_leaderboard_scores_baseline_and_reference_gap():
    s = stats()
    names = [g["name"] for g in s["leaderboard"]]
    assert names[0] == "reference"  # highest mean score first
    a = next(g for g in s["leaderboard"] if g["name"] == "google/model-a")
    assert a["n_complete"] == 1 and a["mean_score"] == 0.7  # the partial run is not a complete run
    assert a["mean_profit_vs_baseline_eur"] == 5000
    assert a["gap_to_reference_eur"] == 6000 - 9000 and a["n_paired_with_reference"] == 1
    d = next(g for g in s["leaderboard"] if g["name"] == "do-nothing")
    assert d["mean_profit_vs_baseline_eur"] == 0 and d["beats_baseline"] == 0


def test_profit_curves_capped_and_only_for_replayed_runs():
    s = stats()
    ids = {c["run"] for c in s["profit_curves"]}
    assert "m2-2" not in ids and "m1-1" in ids
    for c in s["profit_curves"]:
        assert len(c["points"]) <= 43
    thin = analytics._thin([{"day": i} for i in range(200)])
    assert len(thin) == 43 and thin[0]["day"] == 0 and thin[-1]["day"] == 199


def test_tool_usage_and_invalid_grouping():
    s = stats()
    tu = s["tool_usage"]
    assert tu["by_tool"]["plant"]["invalid"] == 6  # 4 + 2 invalid plant actions
    assert tu["by_tool"]["set_climate"]["invalid"] == 0
    assert 0 < tu["invalid_rate"] < 1
    inv = s["mistakes"]["invalid_actions"]
    assert len(inv) == 1 and inv[0]["count"] == 6 and "#" in inv[0]["err"]  # numbers normalised
    row = next(r for r in tu["per_run"] if r["run"] == "m1-1")
    assert row["actions_per_day"] > 1


def test_mistakes_damage_harvest_loss_bankruptcy_energy():
    s = stats()
    pr = {m["run"]: m for m in s["mistakes"]["per_run"]}
    assert pr["m1-1"]["damage_days"] == 3 and pr["m1-1"]["fault_hours"] == {"pump_trip": 72}
    assert pr["m1-1"]["missed_harvest_days"] == 2.0  # ready for 2 days
    assert pr["m2-1"]["crops_lost"] == 1 and pr["m2-1"]["crops_lost_by_crop"] == {"lettuce": 1}
    assert pr["m1-2"]["bankrupt_day"] == 6 and pr["m1-2"]["early_stop"] is True
    en = {e["run"]: e for e in s["energy"]["per_run"]}["m1-1"]
    assert en["hours"] == 42 * 24
    assert abs(en["gas_cost_eur"] - 42 * 24 * 2.0 * 0.5) < 1e-6
    assert en["chp_hours"] == 42 * 12 and en["boiler_hours"] == 42 * 12
    assert abs(en["heat_lost_share"] - 0.1) < 1e-9
    rc = s["mistakes"]["reaction"]
    assert rc["signals"] > 0 and rc["median_latency_h"] is not None


def test_reaction_latency_uses_target_and_window():
    rep = {"actions": [{"h": 40, "tool": "repair", "args": {"target": "pump"}, "ok": True},
                       {"h": 50, "tool": "set_climate", "args": {}, "ok": True}],
           "events": [{"h": 30, "kind": "trip", "target": "pump", "text": "x"},
                      {"h": 30, "kind": "trip", "target": "fan", "text": "y"}],
           "alarms": []}
    r = analytics._reaction(rep)
    by = {x["target"]: x for x in r["rows"]}
    assert by["pump"]["latency_h"] == 10 and by["fan"]["reacted"] is False and r["unreacted"] == 1


def test_degrades_when_replay_fails_and_respects_cap():
    runs, rp = synth.sample()
    calls = []

    def load(rid):
        calls.append(rid)
        if rid == "m1-1":
            raise RuntimeError("boom")
        return rp[rid]

    s = analytics.compute_stats(runs, load, max_replays=2)
    assert len(calls) == 2  # cap: only the 2 most recent complete/partial runs are loaded
    assert s["meta"]["replays_analysed"] + len(s["meta"]["replays_failed"]) == 2
    s2 = analytics.compute_stats(runs, lambda rid: (_ for _ in ()).throw(OSError("gone")))
    assert s2["meta"]["replays_analysed"] == 0 and len(s2["leaderboard"]) == 4  # leaderboard needs no replay


def test_empty_and_nan_inputs():
    assert analytics.compute_stats([], lambda r: {})["meta"]["runs"] == 0
    runs = [synth.run("x", model="m", score=float("nan"), profit=float("inf"), base=1.0)]
    s = analytics.compute_stats(runs, lambda r: {"frames": [{"ec": {"gas": float("nan")}}]})
    json.dumps(s, allow_nan=False)
    assert s["runs"][0]["score"] is None


def _hourly(days, profit_per_day, harvest_day=None, panes=0):
    """A replay in the real frame shape (frame h = state after hour h-1), for compare_runs."""
    frames = []
    for h in range(days * 24 + 1):
        day = (h - 1) // 24 if h else 0
        p = profit_per_day * (day + 1) if h else 0.0
        frames.append({"h": h, "day": h // 24, "hod": h % 24,
                       "c": {"A": {"lamp": 10.0, "sp_co2": 800.0}}, "faults": [], "panes": {"A": panes},
                       "money": {"profit_so_far_eur": p, "cash_eur": 1000 + p, "harvest_revenue_eur": max(p, 0.0)},
                       "b": [{"id": "A1", "area": 50.0, "st": "growing"}], "staff": 3})
    events = [{"h": 24 * harvest_day + 8, "day": harvest_day, "kind": "harvest", "target": "A1",
               "text": "Harvested 10 kg (10.0 kg) of x for 123.00 EUR."}] if harvest_day is not None else []
    actions = [{"h": 6, "day": 0, "tool": "place_orders", "args": {"orders": {"part": 1}}, "ok": False,
                "err": "nothing was accepted: part: unknown item 'part'"},
               {"h": 6, "day": 0, "tool": "submit_day", "args": {}, "ok": True, "err": None}]
    return {"frames": frames, "events": events, "actions": actions, "alarms": [], "daily": []}


def test_compare_runs_divergence_and_ledger_gap():
    ref = _hourly(5, 3000.0, harvest_day=1)
    run = _hourly(5, 100.0, panes=4)
    cmp = analytics.compare_runs({"run": run, "reference": ref}, "reference", diverge_eur=5000.0)
    json.dumps(cmp, allow_nan=False)
    r = cmp["runs"]["run"]
    assert [row["day"] for row in r["daily"]] == [0, 1, 2, 3, 4]
    # gap = 2900 * (day + 1): 5800 on day 1 is the first at or above 5000, and it never comes back
    assert r["first_diverged_day"] == 1 and r["settled_diverged_day"] == 1
    assert r["final_gap_eur"] == 2900 * 5
    assert r["gap_by_ledger_eur"]["harvest_revenue_eur"] == 500 - 15000
    assert r["totals"]["actions"] == 1 and r["totals"]["actions_failed"] == 1  # submit_day is not an action
    assert r["errors"][0]["count"] == 1 and r["totals"]["pane_days"] == 5
    assert cmp["runs"]["reference"]["totals"]["harvest_eur"] == 123.0
    assert r["daily"][0]["lamp_kwh"] == 240.0  # 24 hours at 10 kW
    md = analytics.render_comparison_md(cmp, "run")
    assert "| run |" in md and "harvest_revenue_eur" in md
