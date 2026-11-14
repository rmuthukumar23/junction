"""The engine's contract: metering, validation, finalization, determinism."""
import pytest

from envkit.clients import InProcessClient, run_inprocess
from envkit.core import Episode, replay
from envkit.policies import make_policy
from envkit.trace import digest


def test_each_accepted_call_spends_one_operation(scenario):
    ep = Episode(scenario, 7)
    budget = scenario.shift.ops_per_window
    r = ep.call("view_inventory")
    assert r["ok"] and r["header"]["ops_left"] == budget - 1


def test_spending_the_last_operation_advances_the_clock(scenario):
    ep = Episode(scenario, 7)
    for _ in range(scenario.shift.ops_per_window):
        r = ep.call("view_inventory")
    assert r["header"]["window"] == 2
    assert r["header"]["ops_left"] == scenario.shift.ops_per_window


def test_end_window_is_free_and_counts_as_attendance(scenario):
    ep = Episode(scenario, 7)
    r = ep.call("end_window")
    assert r["ok"] and r["header"]["window"] == 2 and ep.ops_used == 0 and ep.acted[0]


@pytest.mark.parametrize("name,args,code", [
    ("no_such_tool", {}, "unknown_tool"),
    ("order_stock", {"item": "A"}, "invalid_arguments"),
    ("order_stock", {"item": "A", "qty": "many"}, "invalid_arguments"),
    ("order_stock", {"item": "A", "qty": 1, "rush": True}, "invalid_arguments"),
    ("order_stock", {"item": "A", "qty": 2.5}, "invalid_arguments"),
])
def test_malformed_calls_are_rejected_and_free(scenario, name, args, code):
    ep = Episode(scenario, 7)
    r = ep.call(name, args)
    assert not r["ok"] and r["error"]["code"] == code
    assert r["header"]["ops_left"] == scenario.shift.ops_per_window
    assert not ep.acted[0] and ep.rejected == 1


def test_loose_number_encodings_are_accepted(scenario):
    ep = Episode(scenario, 7)
    assert ep.call("order_stock", {"item": "A", "qty": "5"})["ok"]
    assert ep.call("order_stock", {"item": "A", "qty": 5.0})["ok"]


def test_domain_errors_spend_the_operation_and_change_nothing(scenario):
    ep = Episode(scenario, 7)
    cash = ep.env.cash
    r = ep.call("order_stock", {"item": "A", "qty": 10**6})
    assert not r["ok"] and r["error"]["code"] == "tool_error"
    assert r["header"]["ops_left"] == scenario.shift.ops_per_window - 1
    assert ep.env.cash == cash and not ep.env.incoming


def test_nothing_happens_after_the_episode_ends(scenario):
    ep = run_inprocess(scenario, 7, make_policy("absentee", scenario))
    before = ep.result()
    r = ep.call("ship_orders")
    assert r["error"]["code"] == "episode_over"
    assert ep.result() == before


def test_finalize_runs_the_remaining_windows_unattended(scenario):
    ep = Episode(scenario, 7)
    ep.call("ship_orders")
    ep.call("end_window")
    ledger = ep.result()
    assert ep.done and ledger["stopped_early"] and ledger["windows_played"] == scenario.shift.windows
    assert ledger["windows_acted"] == 1
    assert ledger["continuity"] == pytest.approx(1 / scenario.shift.windows)


def test_events_reach_the_agent_only_through_their_channel(scenario):
    ep = Episode(scenario, 7)
    client = InProcessClient(ep)
    while not client.done:
        client.call("end_window")
    alerts = ep.alerts
    by_channel = {a["channel"] for a in alerts}
    assert by_channel == {"announced", "rumored"}          # the silent event produced no alert
    assert len(alerts) == len(scenario.events) - 1
    rumor = next(a for a in alerts if a["channel"] == "rumored")
    assert rumor["text"] == next(e.rumor for e in scenario.events if e.channel == "rumored")


def test_same_seed_and_actions_give_identical_runs(scenario):
    a = run_inprocess(scenario, 7, make_policy("reference", scenario))
    b = run_inprocess(scenario, 7, make_policy("reference", scenario))
    assert [r["digest"] for r in a.trace.calls] == [r["digest"] for r in b.trace.calls]
    assert a.result() == b.result()


def test_different_seeds_give_different_worlds(scenario):
    a = run_inprocess(scenario, 7, make_policy("reference", scenario)).result()
    b = run_inprocess(scenario, 8, make_policy("reference", scenario)).result()
    assert a["business_raw"] != b["business_raw"]


def test_the_world_does_not_depend_on_how_many_calls_the_agent_makes(scenario):
    """Demand comes from its own random stream, so extra look-ups cannot shift it."""
    quiet = run_inprocess(scenario, 7, make_policy("absentee", scenario)).result()
    busy = run_inprocess(scenario, 7, make_policy("spam:view_inventory", scenario)).result()
    assert quiet["units_ordered"] == busy["units_ordered"]


def test_replay_reproduces_every_response(scenario):
    ep = run_inprocess(scenario, 7, make_policy("random:3", scenario))
    again, mismatches = replay(scenario, 7, ep.trace.records)
    assert mismatches == [] and again.result() == ep.result()


def test_replay_detects_a_tampered_trace(scenario):
    ep = run_inprocess(scenario, 7, make_policy("rule-based", scenario))
    records = [dict(r) for r in ep.trace.records]
    call = next(r for r in records if r.get("tool") == "ship_orders")
    call["digest"] = digest({"forged": True})
    _, mismatches = replay(scenario, 7, records)
    assert [m["i"] for m in mismatches] == [call["i"]]


def test_policies_see_only_the_client(scenario):
    """A policy is handed a client with no reference to the episode's internals."""
    client = InProcessClient(Episode(scenario, 7))
    public = [n for n in dir(client) if not n.startswith("_")]
    assert sorted(public) == ["call", "done", "last_header", "tools"]
