"""Pixel site backend: replay, discovery and HTTP, all on the 1-day smoke scenario (seconds)."""
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

PIXEL = Path(__file__).resolve().parents[2] / "scripts" / "pixel"
sys.path.insert(0, str(PIXEL))

import replay as rp  # noqa: E402
import runs as runs_mod  # noqa: E402
import server  # noqa: E402


def synthetic_trace(path: Path, calls: list[dict]) -> None:
    recs = [{"k": "header", "scenario": "smoke", "seed": 1, "bundle": "", "engine": "0"}]
    recs += [{"k": "call", "i": i, **c} for i, c in enumerate(calls)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")


def test_selftest_replays_and_verifies():
    out = rp.selftest("smoke")
    assert out["meta"]["replay_verified"] is True
    assert len(out["frames"]) == 25 and [f["h"] for f in out["frames"]][:3] == [0, 1, 2]
    assert {"day", "hod", "damage", "panes"} <= set(out["frames"][5])
    assert len(out["daily"]) == 1 and out["daily"][0]["day"] == 0
    assert any(a["tool"] == "harvest" and a["ok"] for a in out["actions"])
    assert any(e["kind"] == "harvest" for e in out["events"])


def test_synthetic_trace_with_bad_calls_does_not_crash(tmp_path):
    t = tmp_path / "a" / "artifacts" / "var" / "lib" / "envkit" / "trace.jsonl"
    synthetic_trace(t, [{"tool": "advance", "args": {"hours": 3}, "digest": "x"},
                        {"tool": "submit_day", "args": {"actions": []}}])
    out = rp.replay_trace(t, {"id": "x"})
    assert out["meta"]["replay_verified"] is False      # the first digest cannot match
    assert len(out["frames"]) == 25 and out["actions"][0]["ok"] is False
    assert out["meta"]["hours"] == 24


def test_discovery_tolerates_odd_trials(tmp_path):
    good = tmp_path / "run1" / "t__a"
    synthetic_trace(good / "artifacts" / "var" / "lib" / "envkit" / "trace.jsonl",
                    [{"tool": "submit_day", "args": {"actions": []}}])
    (good / "result.json").write_text(json.dumps({"verifier_result": {"rewards": {"reward": 0.5}},
                                                  "started_at": "2026-11-14T10:00:00Z"}))
    (good / "config.json").write_text(json.dumps({"agent": {"model_name": "x/model-1"}}))
    bad = tmp_path / "run2" / "t__b"
    (bad / "artifacts" / "var" / "lib" / "envkit").mkdir(parents=True)
    (bad / "artifacts" / "var" / "lib" / "envkit" / "trace.jsonl").write_text("{torn")
    (bad / "result.json").write_text("not json")
    (bad / "exception.txt").write_text("boom")
    metas = runs_mod.Runs(tmp_path).list()
    agents = {m["label"]: m for m in metas if m["kind"] == "agent"}
    g = next(m for m in agents.values() if m["model"] == "x/model-1")
    assert g["status"] == "complete" and g["score"] == 0.5 and g["scenario"] == "smoke" and g["days"] == 1
    b = next(m for m in agents.values() if m["model"] is None)
    assert b["status"] == "failed" and b["failure"] == "boom"
    assert len([m for m in metas if m["kind"] == "policy"]) == 12
    assert not any(k.startswith("_") for m in metas for k in m)


@pytest.fixture()
def http(tmp_path):
    synthetic_trace(tmp_path / "r" / "t__a" / "artifacts" / "var" / "lib" / "envkit" / "trace.jsonl",
                    [{"tool": "submit_day", "args": {"actions": []}}])
    server.STATE["runs"] = runs_mod.Runs(tmp_path, policy_scenario="smoke")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", tmp_path
    srv.shutdown()


def get(url):
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def test_http_api(http):
    base, _ = http
    st, h, body = get(base + "/api/runs")
    runs = json.loads(body)["runs"]
    assert st == 200 and h["Cache-Control"] == "no-store" and len(runs) == 1 + 12
    agent = next(r for r in runs if r["kind"] == "agent")
    st, _, body = get(base + "/api/runs/" + agent["id"])
    rep = json.loads(body)
    assert st == 200 and set(rep) == {"meta", "frames", "actions", "events", "alarms", "daily", "replayable"}
    st, _, body = get(base + "/api/runs/policy:reference:s1")
    assert st == 200 and json.loads(body)["meta"]["replay_verified"] is True
    assert get(base + "/api/runs/nope")[0] == 404
    assert get(base + "/api/runs/policy:bogus:s1")[0] == 404
    assert get(base + "/api/stats")[0] == 200


def test_static_and_traversal(http):
    base, _ = http
    st, h, _ = get(base + "/")
    assert st == 200 and "text/html" in h["Content-Type"]
    for bad in ("/../server.py", "/%2e%2e/server.py", "/server.py", "/..%5cserver.py", "/analytics.py"):
        assert get(base + bad)[0] in (404, 400), bad
