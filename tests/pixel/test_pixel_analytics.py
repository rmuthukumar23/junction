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
