"""The scorer and calibration."""
import json

import pytest

from envkit.calibrate import calibrate, entry_for, load_calibration
from envkit.clients import run_inprocess
from envkit.policies import make_policy
from envkit.scoring import anchored, fit_anchor, mean_rate, score

from conftest import ROOT


def test_composite_matches_storebench_published_example():
    # StoreBench trajectory cash-crunch__s11__9oA5QFJ: 0.7*business + 0.2*reliability + 0.1*continuity
    business, reliability, continuity = 0.1854, 0.3742, 1.0
    assert 0.7 * business + 0.2 * reliability + 0.1 * continuity == pytest.approx(0.3046, abs=1e-4)


def test_anchor_fit_follows_storebench_definition():
    # zero = best of the do-nothing anchors; scale maps the best judgment anchor to 0.70
    zero, scale = fit_anchor([11040.79, 16356.10], [17626.42, 17626.42], 0.70)
    assert zero == 16356.10 and scale == 1814.74          # StoreBench cash-crunch seed 13
    assert anchored(17626.42, zero, scale) == pytest.approx(0.70, abs=1e-4)
    assert anchored(11040.79, zero, scale) == 0.0          # below zero clips to 0
    assert anchored(10**9, zero, scale) == 1.0             # and above the scale to 1


def test_undefined_rates_never_read_as_perfect():
    assert mean_rate([None, None]) == 0.0
    assert mean_rate([None, 0.5]) == 0.5
    assert mean_rate([2.0, -1.0]) == 0.5                   # clipped to [0, 1] first


def test_reward_is_linear_in_components_and_bounded(scenario):
    cal = calibrate(scenario, 7)
    ledger = run_inprocess(scenario, 7, make_policy("reference", scenario)).result()
    s = score(scenario, ledger, cal)
    expected = sum(s["weights"][k] * v for k, v in s["components"].items())
    assert s["reward"] == pytest.approx(expected, abs=1e-3)
    assert 0.0 <= s["reward"] <= 1.0
    assert sum(s["weights"].values()) == pytest.approx(1.0)


def test_anchor_ordering(scenario):
    for seed in (7, 11, 13):
        a = calibrate(scenario, seed)["anchors"]
        assert a["do-nothing"]["reward"] == 0.0
        assert a["absentee"]["reward"] <= 0.1001
        assert a["stop-early"]["reward"] < a["rule-based"]["reward"] < a["reference"]["reward"]
        assert a["rule-based"]["components"]["business"] == pytest.approx(0.70, abs=1e-3)


def test_committed_calibration_is_reproducible(scenario):
    committed = load_calibration(ROOT)
    for seed in scenario.seeds:
        fresh = json.loads(json.dumps(calibrate(scenario, seed)))
        assert entry_for(committed, scenario.id, seed) == fresh, "run `envkit build`"
