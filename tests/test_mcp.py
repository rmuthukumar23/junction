"""The MCP path: a policy played over MCP scores exactly as it does in-process."""
import socket
import threading
import time

import pytest

from envkit.bundle import bundle_hash, source_files
from envkit.calibrate import calibrate
from envkit.clients import run_inprocess, run_over_mcp
from envkit.core import replay
from envkit.policies import make_policy
from envkit.scoring import score
from envkit.server import build_app, resume
from envkit.trace import read_trace

uvicorn = pytest.importorskip("uvicorn")
pytest.importorskip("mcp")


@pytest.fixture
def live_server(scenario, tmp_path):
    seed = scenario.seeds[0]
    episode = resume(scenario, seed, tmp_path / "trace.jsonl", bundle_hash(source_files(scenario)))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(build_app(episode), host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}/mcp", episode, tmp_path / "trace.jsonl"
    server.should_exit = True
    thread.join(timeout=5)


def test_policy_over_mcp_matches_in_process(scenario, live_server):
    url, episode, trace_path = live_server
    seed = scenario.seeds[0]
    header = run_over_mcp(url, make_policy("reference", scenario))
    assert header["done"]

    cal = calibrate(scenario, seed)
    local = run_inprocess(scenario, seed, make_policy("reference", scenario))
    assert score(scenario, episode.result(), cal) == score(scenario, local.result(), cal)

    # What the verifier does: rebuild the run from the file the server wrote.
    rebuilt, mismatches = replay(scenario, seed, read_trace(trace_path))
    assert mismatches == [] and rebuilt.result() == local.result()


def test_tools_are_listed_with_schemas(scenario, live_server):
    url, episode, _ = live_server
    seen = {}

    class Lister:
        name = "lister"

        def run(self, client):
            seen["tools"] = client.tools()

    run_over_mcp(url, Lister())
    by_name = {t["name"]: t for t in seen["tools"]}
    assert set(by_name) == set(episode.tools)
    assert by_name["order_stock"]["input_schema"]["required"] == ["item", "qty"]
    assert episode.calls == 0  # listing tools is not an action


def test_server_rebuilds_state_from_its_trace_after_a_restart(scenario, tmp_path):
    seed = scenario.seeds[0]
    first = resume(scenario, seed, tmp_path / "trace.jsonl", "h")
    first.call("ship_orders")
    first.call("order_stock", {"item": "A", "qty": 20})
    first.call("end_window")
    first.trace.close()

    second = resume(scenario, seed, tmp_path / "trace.jsonl", "h")
    assert second.header() == first.header() and second.env.cash == first.env.cash
    second.call("ship_orders")
    second.trace.close()
    calls = [r for r in read_trace(tmp_path / "trace.jsonl") if r["k"] == "call"]
    assert [c["i"] for c in calls] == [0, 1, 2, 3]
    assert sum(1 for r in read_trace(tmp_path / "trace.jsonl") if r["k"] == "header") == 1
