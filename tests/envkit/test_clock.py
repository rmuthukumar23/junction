"""Multi-window advances (Environment.close_windows) and bundled data files."""
import shutil

from envkit.bundle import bundle_hash, source_files
from envkit.core import Episode, replay
from envkit.scenario import load_scenario

from conftest import ROOT

FIXTURE = ROOT / "tests" / "envkit" / "fixtures" / "clock.toml"


def scenario():
    return load_scenario(FIXTURE)


def test_one_call_closes_as_many_windows_as_it_ran():
    ep = Episode(scenario(), 0)
    r = ep.call("advance", {"hours": 5})
    assert r["ok"] and r["result"] == {"ran": 5, "alarm": False, "hour": 5}
    assert r["header"]["window"] == 6 and ep.windows_played == 5
    assert ep.ops_used == 1 and ep.calls == 1


def test_a_long_advance_equals_single_steps():
    long_ep, short_ep = Episode(scenario(), 0), Episode(scenario(), 0)
    long_ep.call("advance", {"hours": 5})
    for _ in range(5):
        short_ep.call("advance", {"hours": 1})
    assert long_ep.env.log == short_ep.env.log and long_ep.window == short_ep.window


def test_an_alarm_stops_the_advance_early():
    ep = Episode(scenario(), 0)
    r = ep.call("advance", {"hours": 24})
    assert r["result"] == {"ran": 7, "alarm": True, "hour": 7}
    assert ep.window == 7


def test_the_last_advance_ends_the_episode_without_overrunning():
    ep = Episode(scenario(), 0)
    while not ep.done:
        ep.call("advance", {"hours": 24})
    assert ep.env.hour == 30 and ep.windows_played == 30 and ep.end_reason == "horizon"
    assert all(mode == "played" for _, mode in ep.env.log)


def test_a_rejected_advance_moves_nothing():
    ep = Episode(scenario(), 0)
    r = ep.call("advance", {"hours": 0})
    assert not r["ok"] and ep.window == 0 and ep.env.hour == 0


def test_stopping_runs_the_rest_unattended():
    ep = Episode(scenario(), 0)
    ep.call("advance", {"hours": 3})
    ep.finalize()
    assert ep.env.hour == 30 and ep.done
    assert [m for _, m in ep.env.log].count("played") == 3


def test_replay_reproduces_multi_window_calls():
    ep = Episode(scenario(), 0)
    for h in (5, 24, 2, 24):
        ep.call("advance", {"hours": h})
    again, mismatches = replay(scenario(), 0, ep.trace.records)
    assert mismatches == [] and again.env.log == ep.env.log


def test_data_files_are_bundled_and_hashed(tmp_path):
    files = source_files(scenario())
    assert "tests/envkit/fixtures/clock-data.toml" in files
    before = bundle_hash(files)
    root = tmp_path / "proj"
    shutil.copytree(ROOT / "tests" / "envkit" / "fixtures", root / "tests" / "envkit" / "fixtures")
    (root / "tests/envkit/fixtures/clock-data.toml").write_text("alarm_every = 8\n")
    after = bundle_hash(source_files(scenario(), root=root))
    assert before != after
