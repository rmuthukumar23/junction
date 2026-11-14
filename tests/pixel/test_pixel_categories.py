"""Run classification, status honesty and the non-replayable fallback (synthetic traces, no simulator)."""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "pixel"))

import runs as runs_mod  # noqa: E402
import server  # noqa: E402

SUBMIT = [{"tool": "submit_day", "args": {"actions": []}, "ok": True}]
EXIT_ERR = {"exception_info": {"exception_type": "NonZeroAgentExitCodeError",
                               "exception_message": "Command failed (exit 1): [ -f ~/.nvm/nvm.sh ] && opencode run "
                                                    + "x" * 3000 + "\nstderr: None"}}


def trial(root: Path, name: str, scenario: str, calls: list[dict], result: dict | None = None,
          exc_txt: str | None = None, reward: float | None = None) -> Path:
    t = root / name / "t__x"
    tp = t / "artifacts" / "var" / "lib" / "envkit" / "trace.jsonl"
    tp.parent.mkdir(parents=True, exist_ok=True)
    recs = [{"k": "header", "scenario": scenario, "seed": 1, "bundle": "", "engine": "0"}]
    recs += [{"k": "call", "i": i, **c} for i, c in enumerate(calls)]
    tp.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    res = dict(result or {})
    if reward is not None:
        res["verifier_result"] = {"rewards": {"reward": reward}}
    (t / "result.json").write_text(json.dumps(res))
    if exc_txt is not None:
        (t / "exception.txt").write_text(exc_txt)
    return t


def meta_of(root: Path) -> dict:
    metas = [m for m in runs_mod.Runs(root, policy_scenario="smoke").list() if m["kind"] == "agent"]
    assert len(metas) == 1
    return metas[0]


def test_category_replayable(tmp_path):
    trial(tmp_path, "a", "smoke", SUBMIT, reward=0.4)
    m = meta_of(tmp_path)
    assert m["category"] == "replayable" and m["status"] == "complete" and m["category_reason"]
    assert m["agent_exit_error"] is None


def test_category_legacy(tmp_path):
    trial(tmp_path, "a", "smoke", [{"tool": "advance", "args": {"hours": 3}}, {"tool": "set_climate", "args": {}}],
          reward=0.1)
    m = meta_of(tmp_path)
    assert m["category"] == "legacy" and "advance" in m["category_reason"]


def test_category_legacy_for_missing_scenario(tmp_path):
    trial(tmp_path, "a", "no-such-scenario", SUBMIT, reward=0.1)
    m = meta_of(tmp_path)
    assert m["category"] == "legacy" and "not in this checkout" in m["category_reason"]


def test_category_shift_planner(tmp_path):
    trial(tmp_path, "a", "shift-planner", [{"tool": "observe", "args": {}}, {"tool": "finish", "args": {}}],
          result={"task_name": "junction/shift-planner-s0"}, reward=1.0)
    m = meta_of(tmp_path)
    assert m["category"] == "shift_planner" and m["status"] == "complete" and m["score"] == 1.0


def test_category_infra_setup_timeout(tmp_path):
    trial(tmp_path, "a", "smoke", [], exc_txt="Traceback (most recent call last):\n  File x\n"
          "harbor.trial.errors.AgentSetupTimeoutError: Agent setup timed out after 360.0 seconds\n")
    m = meta_of(tmp_path)
    assert m["category"] == "infra" and m["status"] == "failed"
    assert m["failure"] == "Agent setup timed out after 360 s"


def test_category_infra_provider_error(tmp_path):
    res = {"exception_info": {"exception_type": "NonZeroAgentExitCodeError",
                              "exception_message": "Command failed (exit 1): opencode ... ProviderAuthError"}}
    trial(tmp_path, "c", "smoke", [], result=res, reward=0.0)
    m = meta_of(tmp_path)
    assert m["category"] == "infra" and m["failure"] == "Agent process exited with code 1 (provider API key missing)"
    assert m["score"] is None


def test_policy_category(tmp_path):
    pol = [m for m in runs_mod.Runs(tmp_path, policy_scenario="smoke").list() if m["kind"] == "policy"]
    assert pol and all(m["category"] == "policy" and m["category_reason"] for m in pol)


def test_exit_code_with_profit_is_complete_not_failed(tmp_path):
    trial(tmp_path, "a", "smoke", SUBMIT, result=EXIT_ERR, reward=0.3)
    m = meta_of(tmp_path)
    assert m["status"] == "complete" and m["failure"] is None and m["score"] == 0.3
    assert m["agent_exit_error"] == "Agent process exited with code 1"
    assert "\n" not in m["agent_exit_error"] and len(m["agent_exit_error"]) <= 160


def test_exit_code_with_nothing_graded_is_failed(tmp_path):
    trial(tmp_path, "q", "smoke", SUBMIT, result=EXIT_ERR)
    m = meta_of(tmp_path)
    assert m["status"] == "failed" and m["failure"] == "Agent process exited with code 1"


def test_exit_code_before_last_day_is_partial(tmp_path):
    trial(tmp_path, "a", "normal-winter", SUBMIT * 2, result=EXIT_ERR, reward=0.1)    # 2 of 42 days
    m = meta_of(tmp_path)
    assert m["status"] == "partial" and m["failure"] == m["agent_exit_error"] == "Agent process exited with code 1"


def test_meta_cache_follows_file_mtime(tmp_path):
    t = trial(tmp_path, "a", "smoke", SUBMIT, reward=0.4)
    assert meta_of(tmp_path)["score"] == 0.4
    (t / "result.json").write_text(json.dumps({"verifier_result": {"rewards": {"reward": 0.9}}}))
    later = time.time_ns() + 10 ** 10
    os.utime(t / "result.json", ns=(later, later))
    assert meta_of(tmp_path)["score"] == 0.9


@pytest.fixture()
def http(tmp_path):
    trial(tmp_path, "rep", "smoke", SUBMIT, reward=0.4)
    trial(tmp_path, "leg", "smoke", [{"tool": "get_rules", "args": {}},
                                     {"tool": "advance", "args": {"hours": 3}, "ok": False,
                                      "response": {"ok": False, "error": {"message": "nope"}}}], reward=0.1)
    trial(tmp_path, "inf", "smoke", [], exc_txt="x.AgentSetupTimeoutError: Agent setup timed out after 360.0 seconds")
    server.STATE["runs"] = runs_mod.Runs(tmp_path, policy_scenario="smoke")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def get(url):
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_http_nonreplayable_fallback_and_404(http):
    runs = json.loads(get(http + "/api/runs")[1])["runs"]
    by = {r["category"]: r for r in runs if r["kind"] == "agent"}
    assert set(by) == {"replayable", "legacy", "infra"}
    st, body = get(http + "/api/runs/" + by["replayable"]["id"])
    assert st == 200 and json.loads(body)["replayable"] is True
    for cat in ("legacy", "infra"):
        st, body = get(http + "/api/runs/" + by[cat]["id"])
        d = json.loads(body)
        assert st == 200 and d["replayable"] is False and d["reason"]
        assert d["meta"]["category"] == cat
        assert d["frames"] == d["events"] == d["alarms"] == d["daily"] == []
    d = json.loads(get(http + "/api/runs/" + by["legacy"]["id"])[1])
    assert [a["tool"] for a in d["actions"]] == ["advance"]       # get_* calls are not actions
    assert d["actions"][0]["ok"] is False and d["actions"][0]["err"] == "nope"
    assert json.loads(get(http + "/api/runs/" + by["infra"]["id"])[1])["actions"] == []
    assert get(http + "/api/runs/agent:doesnotexist")[0] == 404
