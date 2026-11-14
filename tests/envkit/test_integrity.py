"""Reward integrity, the verifier, and the generated Harbor tasks."""
import json
import os
import subprocess
import sys

import pytest

from envkit.audit import audit
from envkit.bundle import bundle_hash, source_files
from envkit.calibrate import entry_for, load_calibration
from envkit.clients import run_inprocess
from envkit.harbor import check_task, task_name
from envkit.policies import make_policy
from envkit.trace import read_trace, write_trace
from envkit.verify import grade
from envkit.verify import main as verify_main

from envkit.scenario import load_scenario

from conftest import ROOT


@pytest.fixture(scope="module")
def scenario():
    """These checks run on the committed task: the greenhouse."""
    return load_scenario(ROOT / "scenarios" / "root-cause.toml")


def test_audit_passes(scenario):
    for seed in scenario.seeds:
        report = audit(scenario, seed)
        failed = [c for c in report["checks"] if not c["ok"]]
        assert not failed, failed


def test_generated_tasks_are_current(scenario):
    committed = load_calibration(ROOT)
    for seed in scenario.seeds:
        entry = entry_for(committed, scenario.id, seed)
        assert check_task(scenario, seed, entry, ROOT / "tasks") == [], "run `envkit build`"


def test_agent_image_contains_no_task_data(scenario):
    """Only `sim`, the verifier and the oracle get the bundle."""
    for seed in scenario.seeds:
        env = ROOT / "tasks" / task_name(scenario, seed) / "environment"
        outside_sim = [p for p in env.rglob("*") if p.is_file() and "sim" not in p.relative_to(env).parts]
        assert sorted(p.name for p in outside_sim) == ["Dockerfile", "docker-compose.yaml", "requirements.txt"]
        dockerfile = (env / "Dockerfile").read_text()
        assert "bundle" not in dockerfile and "COPY --from=node" in dockerfile


def _verifier_bundle(scenario):
    return ROOT / "tasks" / task_name(scenario, scenario.seeds[0]) / "tests" / "bundle"


def test_verifier_regrades_a_trace(scenario, tmp_path):
    seed = scenario.seeds[0]
    ep = run_inprocess(scenario, seed, make_policy("reference", scenario), tmp_path / "trace.jsonl",
                       bundle_hash(source_files(scenario)))
    out = grade(_verifier_bundle(scenario), tmp_path / "trace.jsonl")
    cal = entry_for(load_calibration(ROOT), scenario.id, seed)
    assert out["reward"] == cal["anchors"]["reference"]["reward"]
    assert out["replay"]["consistent"] and out["replay"]["calls"] == ep.calls and out["notes"] == []


def test_verifier_grades_an_empty_trace_as_doing_nothing(scenario, tmp_path):
    run_inprocess(scenario, scenario.seeds[0], make_policy("do-nothing", scenario), tmp_path / "trace.jsonl",
                  bundle_hash(source_files(scenario)))
    out = grade(_verifier_bundle(scenario), tmp_path / "trace.jsonl")
    assert out["reward"] == 0.0 and out["replay"]["calls"] == 0 and out["notes"] == []


def test_missing_trace_writes_no_reward(scenario, tmp_path):
    """Failed collection is an infrastructure failure, never a score of zero."""
    with pytest.raises(FileNotFoundError):
        grade(_verifier_bundle(scenario), tmp_path / "absent.jsonl")
    code = verify_main(["--bundle", str(_verifier_bundle(scenario)), "--trace", str(tmp_path / "absent.jsonl"),
                        "--out", str(tmp_path / "out")])
    assert code == 1 and not (tmp_path / "out" / "reward.txt").exists()
    assert json.loads((tmp_path / "out" / "score.json").read_text())["reward"] is None


def test_verifier_ignores_recorded_responses(scenario, tmp_path):
    """A trace that claims better outcomes than its actions produce gains nothing."""
    seed = scenario.seeds[0]
    run_inprocess(scenario, seed, make_policy("absentee", scenario), tmp_path / "t.jsonl")
    records = read_trace(tmp_path / "t.jsonl")
    for r in records:
        if r.get("k") == "call":
            r["response"] = {"ok": True, "result": {"cash": 10**9}}
    write_trace(tmp_path / "forged.jsonl", records)
    out = grade(_verifier_bundle(scenario), tmp_path / "forged.jsonl")
    assert out["reward"] <= 0.1001


def test_verifier_runs_with_the_standard_library_only(scenario, tmp_path):
    seed = scenario.seeds[0]
    run_inprocess(scenario, seed, make_policy("ec-rules", scenario), tmp_path / "trace.jsonl")
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "VIRTUAL_ENV")}
    proc = subprocess.run(
        [sys.executable, "-S", "-m", "envkit.verify", "--bundle", ".", "--trace", str(tmp_path / "trace.jsonl"),
         "--out", str(tmp_path / "out")],
        cwd=_verifier_bundle(scenario), env={**env, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    reward = float((tmp_path / "out" / "reward.txt").read_text())
    assert 0.0 <= reward <= 1.0
    assert json.loads((tmp_path / "out" / "score.json").read_text())["reward"] == reward
