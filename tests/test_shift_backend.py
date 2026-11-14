"""Shift Planner on the envkit backend: contract rules, trust boundary, reporting.

These replace the tests of the retired HTTP service, stdio bridge and task
builder, and keep the same guarantees on the path that is now used.
"""
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import socket
import tempfile
from threading import Thread
import time
import tomllib
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from envkit.clients import run_inprocess
from envkit.core import Episode, replay
from envkit.policies import make_policy
from envkit.report import read_trial, summarize
from envkit.scenario import load_scenario
from envkit.trace import read_trace, write_trace
from envkit.verify import grade
from junction_env import run_episode
from junction_env.scheduling import ShiftPlanner, generate
from junction_env.scheduling.reference import earliest_deadline, stop_early
from test_scheduling import fixture

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = load_scenario(ROOT / "scenarios/shift-planner.toml")
TASK = ROOT / "tasks/shift-planner-s0"


def fixture_scenario():
    return replace(SCENARIO, env_config={"instance": fixture().public()})


class ContractOnBackendTests(unittest.TestCase):
    def setUp(self):
        self.episode = Episode(fixture_scenario(), 0)
        self.core = self.episode.env.core

    def act(self, tool, **arguments):
        return self.episode.call(tool, arguments)

    def test_exactly_the_four_contract_tools(self):
        self.assertEqual(set(self.episode.tools), {"observe", "start_job", "advance", "finish"})

    def test_resources_dependencies_and_deadlines(self):
        self.assertFalse(self.act("start_job", job_id="c")["ok"])
        self.act("start_job", job_id="a")
        self.assertIn("equipment", self.act("start_job", job_id="d")["error"]["message"])
        self.act("start_job", job_id="b")
        self.act("advance", to_time=2)
        self.assertEqual(self.core.completed, {"a": 2})
        self.act("advance", to_time=3)
        self.act("start_job", job_id="c")
        self.act("advance", to_time=5)
        self.act("start_job", job_id="d")
        response = self.act("advance", to_time=6)
        self.assertTrue(response["header"]["done"])
        self.assertEqual(response["header"]["end_reason"], "terminated:all_completed")
        self.assertEqual(self.episode.result()["score"], 10 / 12)

    def test_invalid_requests_consume_budget_without_changing_work(self):
        invalid = [("start_job", None), ("start_job", []), ("start_job", {}), ("start_job", {"job_id": []}),
                   ("start_job", {"job_id": "unknown"}), ("advance", {"to_time": True}),
                   ("advance", {"to_time": 2.0}), ("advance", {"to_time": "2"}), ("advance", {"to_time": 0}),
                   ("advance", {"to_time": 11}), ("finish", {"score": 1}), ("reset", {"seed": 1}),
                   ("observe", {"extra": 1}), ("start_job", {"job_id": "a", "tool": "finish"})]
        for index, (tool, arguments) in enumerate(invalid, 1):
            response = self.episode.call(tool, arguments)
            self.assertFalse(response["ok"], (tool, arguments))
            self.assertEqual((self.core.starts, self.core.time), ({}, 0))
            self.assertEqual(self.core.actions_used, index)
            self.assertEqual(response["header"]["ops_left"], 64 - index)
        while not self.episode.done:
            self.episode.call("invalid", {})
        self.assertEqual(self.core.actions_used, 64)
        self.assertEqual(self.core.termination, "action_limit")
        self.assertEqual(self.episode.result()["score"], 0)

    def test_observe_is_free_and_unfinished_work_gets_no_credit(self):
        for _ in range(80):
            self.assertTrue(self.act("observe")["ok"])
        self.assertEqual(self.core.actions_used, 0)
        self.act("start_job", job_id="a")
        self.act("finish")
        self.assertEqual(self.episode.result()["score"], 0)

    def test_nothing_changes_after_termination(self):
        self.act("start_job", job_id="a")
        self.act("advance", to_time=2)
        self.act("finish")
        before = self.episode.result()
        self.assertEqual(self.act("advance", to_time=10)["error"]["code"], "episode_over")
        self.assertEqual(self.episode.result(), before)
        self.assertEqual(before["score"], 4 / 12)

    def test_all_prefixes_score_only_completed_work(self):
        calls = [("start_job", {"job_id": "a"}), ("advance", {"to_time": 2}),
                 ("start_job", {"job_id": "c"}), ("advance", {"to_time": 4})]
        for count, expected in enumerate((0, 0, 4 / 12, 4 / 12, 7 / 12)):
            episode = Episode(fixture_scenario(), 0)
            for tool, arguments in calls[:count]:
                episode.call(tool, arguments)
            ledger = episode.result()   # the harness stopping the agent here
            self.assertEqual(ledger["score"], expected)
            self.assertEqual(episode.env.core.termination, "harness_interruption")

    def test_backend_scores_equal_the_local_runner(self):
        for jobs in (8, 10, 12):
            scenario = replace(SCENARIO, env_config={"jobs": jobs})
            for seed in range(5):
                for name, policy in (("earliest-deadline", earliest_deadline), ("stop-early", stop_early)):
                    local = run_episode(ShiftPlanner(generate(seed, jobs)), policy, seed=seed, max_steps=64)
                    backend = run_inprocess(scenario, seed, make_policy(name, scenario)).result()
                    self.assertEqual(backend["score"], local.score, (jobs, seed, name))


class TrustBoundaryTests(unittest.TestCase):
    def test_verifier_replays_actions_and_ignores_recorded_responses(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            run_inprocess(SCENARIO, 0, make_policy("stop-early", SCENARIO), path)
            records = read_trace(path)
            for record in records:
                if record.get("k") == "call":
                    record["response"] = {"ok": True, "result": {"score": 1.0}}
            write_trace(path, records)
            graded = grade(TASK / "tests/bundle", path)
            self.assertEqual(graded["reward"], 0.0)
            self.assertTrue(graded["replay"]["consistent"])   # digests still match the real responses

    def test_forged_digest_is_detected(self):
        episode = run_inprocess(SCENARIO, 0, make_policy("earliest-deadline", SCENARIO))
        records = [dict(r) for r in episode.trace.records]
        records[2]["digest"] = "0" * 16
        _, mismatches = replay(SCENARIO, 0, records)
        self.assertEqual([m["i"] for m in mismatches], [records[2]["i"]])

    def test_missing_trace_is_an_infrastructure_failure_not_a_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                grade(TASK / "tests/bundle", Path(directory) / "absent.jsonl")

    def test_task_keeps_world_and_grading_away_from_the_agent(self):
        data = tomllib.loads((TASK / "task.toml").read_text())
        self.assertEqual(data["verifier"]["environment_mode"], "separate")
        self.assertEqual(data["artifacts"][0]["service"], "sim")
        self.assertEqual(data["environment"]["mcp_servers"][0]["transport"], "streamable-http")
        agent_image = (TASK / "environment/Dockerfile").read_text()
        copied = [line for line in agent_image.splitlines() if line.startswith("COPY")]
        self.assertEqual(copied, ["COPY --from=node /usr/local/bin/node /usr/local/bin/node",
                                  "COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules",
                                  "COPY requirements.txt /tmp/requirements.txt"])
        self.assertIn("--require-hashes", agent_image)
        self.assertIn("@sha256:", agent_image)
        self.assertNotIn("docker.sock", (TASK / "environment/docker-compose.yaml").read_text())
        outside_sim = [p.name for p in (TASK / "environment").iterdir() if p.is_file()]
        self.assertEqual(sorted(outside_sim), ["Dockerfile", "docker-compose.yaml", "requirements.txt"])
        if importlib.util.find_spec("harbor"):
            from harbor.models.task.config import TaskConfig
            TaskConfig.model_validate(data)


class ReportingTests(unittest.TestCase):
    def test_reporting_keeps_timeout_credit_and_rate_limit_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            trial = Path(directory) / "s0-agent" / "trial"
            (trial / "verifier").mkdir(parents=True)
            with tempfile.TemporaryDirectory() as scratch:
                path = Path(scratch) / "trace.jsonl"
                run_inprocess(SCENARIO, 0, make_policy("stop-after:earliest-deadline@6", SCENARIO), path)
                score = grade(TASK / "tests/bundle", path)
            (trial / "verifier/score.json").write_text(json.dumps(score))
            raw = {"verifier_result": {"rewards": {"reward": score["reward"]}},
                   "exception_info": {"exception_type": "AgentTimeoutError"}}
            result = trial / "result.json"
            result.write_text(json.dumps(raw))
            timeout = read_trial(result)
            self.assertEqual(timeout["status"], "interrupted")
            self.assertEqual(timeout["reward"], score["reward"])
            self.assertGreater(timeout["reward"], 0)
            raw["exception_info"]["exception_type"] = "ApiRateLimitError"
            result.write_text(json.dumps(raw))
            rate_limit = read_trial(result)
            self.assertIsNone(rate_limit["reward"])
            self.assertTrue(rate_limit["provider_rate_limit"])
            self.assertIn("infra", summarize([timeout, rate_limit]))
            self.assertIn("| job | start | completion |", summarize([timeout]))
            raw["exception_info"] = None
            raw["verifier_result"]["rewards"]["reward"] = 1
            result.write_text(json.dumps(raw))
            self.assertEqual(read_trial(result)["status"], "infrastructure_failure")


@unittest.skipUnless(importlib.util.find_spec("mcp") and importlib.util.find_spec("uvicorn"),
                     "install the mcp extra for the transport test")
class TransportTests(unittest.TestCase):
    def setUp(self):
        import uvicorn
        from envkit.server import build_app, resume
        self.tmp = tempfile.TemporaryDirectory()
        self.episode = resume(fixture_scenario(), 0, Path(self.tmp.name) / "trace.jsonl", "test")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(build_app(self.episode), host="127.0.0.1", port=port, log_level="error"))
        self.thread = Thread(target=self.server.run, daemon=True)
        self.thread.start()
        while not self.server.started:
            time.sleep(0.02)
        self.url = f"http://127.0.0.1:{port}"

    def tearDown(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def test_real_mcp_episode_against_the_sidecar_server(self):
        import anyio
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        core = self.episode.env.core

        async def exercise():
            async with streamable_http_client(self.url + "/mcp") as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    names = {tool.name for tool in (await session.list_tools()).tools}
                    self.assertEqual(names, {"observe", "start_job", "advance", "finish"})
                    response = await session.call_tool("observe", {})
                    self.assertEqual(json.loads(response.content[0].text)["result"]["time"], 0)
                    response = await session.call_tool("advance", {"to_time": True})
                    self.assertTrue(response.is_error)
                    self.assertEqual(core.actions_used, 1)
                    await session.call_tool("start_job", {"job_id": "a"})
                    await session.call_tool("advance", {"to_time": 2})
                    await session.call_tool("finish", {})
                    self.assertEqual(core.score(), 4 / 12)
        anyio.run(exercise)

    def test_server_has_no_reset_state_or_score_routes(self):
        with urlopen(self.url + "/healthz") as response:
            self.assertEqual(response.status, 200)
        for path in ("/reset", "/record", "/score", "/state/live.json", "/trace.jsonl", "/../var/lib/envkit/trace.jsonl"):
            with self.assertRaises(HTTPError) as error:
                urlopen(self.url + path)
            self.assertEqual(error.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
