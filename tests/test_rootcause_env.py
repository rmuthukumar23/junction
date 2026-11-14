"""Root Cause (lettuce incident) on the envkit backend: tools, time, fixed-horizon scoring, replay and tampering."""
import json
import math
from pathlib import Path
import tempfile
import unittest

from envkit.bundle import bundle_hash, source_files
from envkit.calibrate import entry_for, load_calibration
from envkit.clients import InProcessClient, run_inprocess
from envkit.core import Episode, replay
from envkit.harbor import check_task, task_name
from envkit.policies import make_policy
from envkit.scenario import load_scenario
from envkit.scoring import score
from envkit.server import resume
from envkit.trace import Trace, read_trace, write_trace
from envkit.verify import grade
from envkit.verify import main as verify_main

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = load_scenario(ROOT / "scenarios" / "root-cause.toml")
SEED = SCENARIO.seeds[0]
VERIFIER_BUNDLE = ROOT / "tasks" / task_name(SCENARIO, SEED) / "tests" / "bundle"
REQUIRED_TOOLS = {"get_status", "get_history", "get_tests", "order_test", "order_water_test",
                  "submit_day_plan", "advance_day", "finish_episode"}
DAYS = 6


def plan(mains=230.0, fertilizer=90.0, flush=0.0, reserve=0.0, **overrides):
    out = {z: {"mains_l": mains, "reserve_l": reserve, "fertilizer_g": fertilizer, "flush_l": flush} for z in "ABC"}
    for bench, values in overrides.items():
        out[bench].update(values)
    return out


# A fixed, mixed sequence of requests: reads, tests, plans, an invalid plan, advances.
ACTIONS = [
    ("get_rules", {}), ("get_status", {}), ("order_test", {"bench_id": "C"}), ("order_test", {"bench_id": "B"}),
    ("submit_day_plan", {"bench_plans": plan(C={"fertilizer_g": 300.0})}), ("advance_day", {}),
    ("get_tests", {}), ("submit_day_plan", {"bench_plans": plan(900.0)}),          # rejected: over the top-up limit
    ("order_water_test", {}),
    ("submit_day_plan", {"bench_plans": plan(0.0, 120.0, reserve=230.0, C={"flush_l": 50.0, "fertilizer_g": 200.0},
                                             B={"fertilizer_g": 60.0})}),
    ("advance_day", {}), ("get_history", {"bench_id": "C"}),
    ("submit_day_plan", {"bench_plans": plan(0.0, 100.0, reserve=230.0)}), ("advance_day", {}),
    ("submit_day_plan", {"bench_plans": plan(40.0, 100.0, reserve=200.0)}), ("advance_day", {}),
]


def new_episode(seed=SEED, path=None):
    return Episode(SCENARIO, seed, Trace(path))


def state(episode):
    sim = episode.env.sim
    return json.dumps({"day": sim.day, "reserve": sim.reserve_l, "plan": sim.plan, "costs": sim.costs,
                       "tests": sim.tests, "benches": {z: [x.volume, x.nutrient, x.salt, x.condition, x.harvest]
                                                       for z, x in sim.benches.items()}}, sort_keys=True)


def run_actions(episode, actions=ACTIONS):
    return [episode.call(tool, dict(args)) for tool, args in actions]


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.episode = new_episode()

    def call(self, tool, **args):
        return self.episode.call(tool, args)

    def test_the_contract_tools_exist_with_schemas(self):
        tools = {t["name"]: t for t in self.episode.describe_tools()}
        self.assertEqual(set(tools), REQUIRED_TOOLS | {"get_rules", "get_events"})
        self.assertEqual(tools["order_test"]["input_schema"]["required"], ["bench_id"])
        self.assertEqual(tools["submit_day_plan"]["input_schema"]["required"], ["bench_plans"])
        self.assertEqual({n for n, t in tools.items() if t["cost"]}, {"advance_day"})

    def test_reads_never_move_time_or_change_state(self):
        before, header = state(self.episode), self.episode.header()
        for _ in range(8):     # 48 reads: within the call limit
            for tool, args in (("get_status", {}), ("get_rules", {}), ("get_tests", {}),
                               ("get_events", {}), ("get_history", {"bench_id": "A"}),
                               ("get_history", {"bench_id": "C", "first_day": 0, "last_day": 5})):
                response = self.call(tool, **args)
                self.assertTrue(response["ok"], response)
        self.assertEqual(state(self.episode), before)
        self.assertEqual(self.episode.header(), header)
        self.assertEqual((self.episode.window, self.episode.ops_left), (0, 1))
        first, second = self.call("get_status"), self.call("get_status")
        self.assertEqual(first, second)

    def test_only_advance_day_moves_time(self):
        self.call("order_test", bench_id="A")
        self.call("order_water_test")
        self.call("submit_day_plan", bench_plans=plan())
        self.assertEqual(self.episode.header()["day"], 0)
        response = self.call("advance_day")
        self.assertEqual((response["result"]["completed_day"], response["header"]["day"]), (0, 1))
        self.assertEqual(response["result"]["status"]["day"], 1)

    def test_malformed_and_out_of_range_requests_change_nothing(self):
        before = state(self.episode)
        bad = [
            ("submit_day_plan", {"bench_plans": plan(A={"mains_l": float("nan")})}, "invalid_arguments"),
            ("submit_day_plan", {"bench_plans": plan(A={"mains_l": float("inf")})}, "invalid_arguments"),
            ("submit_day_plan", {"bench_plans": plan(A={"mains_l": -math.inf})}, "invalid_arguments"),
            ("submit_day_plan", {"bench_plans": plan(A={"mains_l": "abc"})}, "invalid_arguments"),
            ("submit_day_plan", {"bench_plans": plan(A={"mains_l": None})}, "invalid_arguments"),
            ("submit_day_plan", {"bench_plans": plan(A={"mains_l": True})}, "invalid_arguments"),
            ("submit_day_plan", {"bench_plans": [plan()]}, "invalid_arguments"),
            ("submit_day_plan", {"bench_plans": "A=220"}, "invalid_arguments"),
            ("submit_day_plan", {}, "invalid_arguments"),
            ("submit_day_plan", {"bench_plans": plan(), "profit_eur": 10 ** 9}, "invalid_arguments"),
            ("submit_day_plan", {"bench_plans": plan(A={"mains_l": -1.0})}, "tool_error"),
            ("submit_day_plan", {"bench_plans": plan(A={"mains_l": 1e9})}, "tool_error"),
            ("submit_day_plan", {"bench_plans": plan(A={"fertilizer_g": 1e9})}, "tool_error"),
            ("submit_day_plan", {"bench_plans": plan(A={"flush_l": 1e9})}, "tool_error"),
            ("submit_day_plan", {"bench_plans": {**plan(), "E": plan()["A"]}}, "tool_error"),
            ("submit_day_plan", {"bench_plans": {"A": plan()["A"]}}, "tool_error"),
            ("submit_day_plan", {"bench_plans": plan(A={"nutrient_g": 5000.0})}, "tool_error"),
            ("submit_day_plan", {"bench_plans": plan(0.0, reserve=900.0)}, "tool_error"),   # 2700 L > the reserve
            ("submit_day_plan", {"bench_plans": plan(300.0, reserve=200.1)}, "tool_error"),  # over the top-up limit
            ("order_test", {"bench_id": "E"}, "tool_error"),
            ("order_test", {"bench_id": 3}, "invalid_arguments"),
            ("order_test", {"bench_id": "A", "test_type": "truth"}, "invalid_arguments"),
            ("order_water_test", {"source": "rain"}, "invalid_arguments"),
            ("order_test", {}, "invalid_arguments"),
            ("get_history", {"bench_id": "Q"}, "tool_error"),
            ("get_history", {"bench_id": "A", "first_day": -1}, "tool_error"),
            ("get_history", {"bench_id": "A", "first_day": 1.5}, "invalid_arguments"),
            ("get_events", {"since_day": -3}, "tool_error"),
            ("advance_day", {"days": 3}, "invalid_arguments"),
            ("set_state", {"reserve_l": 10 ** 9}, "unknown_tool"),
            ("reset", {}, "unknown_tool"),
            ("get_analysis", {}, "unknown_tool"),
        ]
        for tool, args, code in bad:
            with self.subTest(tool=tool, args=str(args)[:60]):
                response = self.episode.call(tool, args)
                self.assertFalse(response["ok"])
                self.assertEqual(response["error"]["code"], code, response["error"])
                self.assertEqual(state(self.episode), before)
        self.assertEqual((self.episode.header()["day"], self.episode.faults), (0, 0))
        self.assertEqual(sum(self.episode.env.sim.costs.values()), 0.0)

    def test_an_inline_plan_is_applied_in_one_call_and_a_rejected_one_moves_nothing(self):
        before = state(self.episode)
        refused = self.call("advance_day", bench_plans=plan(900.0))
        self.assertEqual(refused["error"]["code"], "tool_error")
        self.assertIn("not advanced", refused["error"]["message"])
        self.assertEqual(state(self.episode), before)
        self.assertEqual((self.episode.header()["day"], self.episode.ops_left), (0, 1))
        done = self.call("advance_day", bench_plans=plan(0.0, reserve=200.0))
        self.assertTrue(done["ok"])
        self.assertEqual((done["header"]["day"], done["result"]["plan_source"]), (1, "submitted"))
        self.assertEqual(self.episode.env.sim.days[0]["benches"]["A"]["plan"]["reserve_l"], 200.0)

    def test_a_rejected_plan_leaves_the_previous_plan_in_force(self):
        good = plan(200.0, 100.0)
        self.assertTrue(self.call("submit_day_plan", bench_plans=good)["ok"])
        error = self.call("submit_day_plan", bench_plans=plan(900.0))["error"]["message"]
        self.assertIn("nothing was changed", error)
        self.assertEqual(self.episode.env.sim.plan, good)
        self.call("advance_day")
        self.assertEqual(self.episode.env.sim.days[0]["benches"]["A"]["plan"], good["A"])

    def test_duplicate_test_order_is_refused_and_charged_once(self):
        self.assertTrue(self.call("order_test", bench_id="A")["ok"])
        self.assertTrue(self.call("order_water_test")["ok"])
        self.assertEqual(self.call("order_test", bench_id="A")["error"]["code"], "tool_error")
        self.assertEqual(self.call("order_water_test")["error"]["code"], "tool_error")
        self.assertEqual(self.episode.env.sim.costs["tests"], 30.0)
        self.assertEqual(len(self.call("get_tests")["result"]["pending"]), 2)

    def test_hidden_state_is_never_in_a_live_response(self):
        sim = self.episode.env.sim
        responses = [self.call("get_rules"), self.call("get_status")]
        while sim.day <= sim.instance.incident_day:      # play into the incident without a mains test
            responses.append(self.call("advance_day"))
            responses += [self.call("get_status"), self.call("get_events"), self.call("get_tests")]
        text = json.dumps(responses)
        for hidden in ("backup_salt", "hidden_morning", "realized_temps", "profit_floor", "profit_informed",
                       f"{sim.instance.backup_salt_g_l:.3f}", "failure_modes"):
            self.assertNotIn(hidden, text)
        self.assertIn("backup source", text)             # the notice itself is public
        future = sim.instance.temps[sim.day + sim.p.forecast_days:]
        self.assertNotIn(json.dumps(list(future))[1:-1], json.dumps(self.call("get_status")))


class TimeAndTerminalTests(unittest.TestCase):
    def test_the_call_limit_ends_the_episode_like_stopping(self):
        limit = SCENARIO.shift.max_calls
        self.assertIsNotNone(limit)
        capped = new_episode()
        for _ in range(limit):
            capped.call("get_status", {})
        self.assertTrue(capped.done)
        self.assertEqual(capped.end_reason, "call_limit")
        self.assertEqual(capped.call("get_status", {})["error"]["code"], "episode_over")
        nothing = run_inprocess(SCENARIO, SEED, make_policy("do-nothing", SCENARIO))
        self.assertEqual(capped.env.ledger(), nothing.env.ledger())
        self.assertLess(len(run_inprocess(SCENARIO, SEED, make_policy("reference", SCENARIO)).trace.calls), limit // 4)

    def test_six_advances_end_the_episode_and_then_everything_is_refused(self):
        episode = new_episode()
        for day in range(DAYS):
            response = episode.call("advance_day", {})
            self.assertTrue(response["ok"])
            self.assertEqual(response["header"]["done"], day == DAYS - 1)
        final = response["result"]["final_result"]
        self.assertEqual(final, episode.env.ledger())
        self.assertEqual(episode.end_reason, "horizon")
        before = state(episode)
        for tool, args in (("advance_day", {}), ("submit_day_plan", {"bench_plans": plan()}), ("order_test", {"bench_id": "A"}),
                           ("finish_episode", {}), ("get_status", {})):
            response = episode.call(tool, args)
            self.assertEqual(response["error"]["code"], "episode_over")
        self.assertEqual(state(episode), before)
        self.assertEqual(episode.result()["profit_eur"], final["profit_eur"])

    def test_doing_nothing_is_the_default_plan_through_the_last_day(self):
        nothing = run_inprocess(SCENARIO, SEED, make_policy("do-nothing", SCENARIO))
        attend = run_inprocess(SCENARIO, SEED, make_policy("absentee", SCENARIO))
        self.assertEqual(nothing.env.sim.day, DAYS)
        self.assertEqual(nothing.env.ledger(), attend.env.ledger())
        ledger = nothing.result()
        self.assertEqual((ledger["normalized_profit"], ledger["stopped_early"], ledger["windows_played"]), (0.0, True, DAYS))
        self.assertTrue(all(d["plan_source"] == "default" for d in nothing.env.sim.days))

    def test_every_way_of_stopping_early_gives_the_same_final_day_result(self):
        """finish_episode, a closed session, and advancing without plans all end on the last day with the same score."""
        prefix = ACTIONS[:10]
        finished = new_episode()
        run_actions(finished, prefix)
        response = finished.call("finish_episode", {})
        self.assertTrue(response["ok"] and response["header"]["done"])

        abandoned = new_episode()            # the browser closes or the agent process dies
        run_actions(abandoned, prefix)
        frozen = abandoned.env.snapshot()["profit_so_far"]
        abandoned.finalize()

        walked = new_episode()
        run_actions(walked, prefix)
        while not walked.done:
            walked.call("advance_day", {})

        ledgers = [e.env.ledger() for e in (finished, abandoned, walked)]
        self.assertEqual(ledgers[0], ledgers[1])
        self.assertEqual(ledgers[1], ledgers[2])
        self.assertEqual([e.env.sim.day for e in (finished, abandoned, walked)], [DAYS] * 3)
        self.assertEqual(response["result"]["final_result"], ledgers[0])
        self.assertNotEqual(frozen, ledgers[1]["profit_eur"], "stopping must not freeze the position")
        self.assertEqual(ledgers[0]["cost_tests_eur"], 45.0, "tests ordered before stopping stay charged")

    def test_stop_early_baseline_never_beats_playing_on(self):
        cal = entry_for(load_calibration(ROOT), SCENARIO.id, SEED)
        anchors = {name: a["reward"] for name, a in cal["anchors"].items()}
        self.assertEqual(anchors["do-nothing"], 0.0)
        self.assertEqual(anchors["absentee"], 0.0)
        self.assertLess(anchors["stop-early"], anchors["reference"])
        self.assertLess(anchors["ec-rules"], anchors["reference"])
        self.assertLess(anchors["blind"], anchors["reference"])
        self.assertGreater(anchors["reference"], 0.7)


class ReplayAndEquivalenceTests(unittest.TestCase):
    def test_same_seed_and_trace_give_identical_outcome(self):
        a, b = new_episode(), new_episode()
        self.assertEqual(run_actions(a), run_actions(b))
        self.assertEqual(a.result(), b.result())
        self.assertEqual([r["digest"] for r in a.trace.calls], [r["digest"] for r in b.trace.calls])
        other = new_episode(seed=SEED + 1)
        run_actions(other)
        self.assertNotEqual(other.result()["profit_eur"], a.result()["profit_eur"])

    def test_browser_agent_and_replay_paths_score_identically(self):
        """The browser posts {tool, args}; an agent calls tools through a client; the verifier replays the trace."""
        with tempfile.TemporaryDirectory() as tmp:
            browser = new_episode(path=Path(tmp) / "human.jsonl")
            for tool, args in ACTIONS:                               # what rootcause_app does per request
                browser.call(tool, json.loads(json.dumps(args)))
            browser.finalize()
            browser.trace.close()

            agent = new_episode()
            client = InProcessClient(agent)                          # what a policy or an MCP agent does
            for tool, args in ACTIONS:
                client.call(tool, **args)
            agent.finalize()

            replayed, mismatches = replay(SCENARIO, SEED, read_trace(Path(tmp) / "human.jsonl"))
            self.assertEqual(mismatches, [])
            results = [e.result() for e in (browser, agent, replayed)]
            self.assertEqual(results[0], results[1])
            self.assertEqual(results[1], results[2])
            cal = entry_for(load_calibration(ROOT), SCENARIO.id, SEED)
            scores = [score(SCENARIO, r, cal)["reward"] for r in results]
            self.assertEqual(len(set(scores)), 1)
            self.assertGreater(scores[0], 0.0)

    def test_a_run_survives_a_server_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            first = resume(SCENARIO, SEED, path, "h")
            run_actions(first, ACTIONS[:9])
            first.trace.close()
            second = resume(SCENARIO, SEED, path, "h")               # a new process, same file
            self.assertEqual(state(second), state(first))
            self.assertEqual(second.header(), first.header())
            run_actions(second, ACTIONS[9:])
            second.trace.close()
            uninterrupted = new_episode()
            run_actions(uninterrupted)
            self.assertEqual(second.result(), uninterrupted.result())
            self.assertEqual(sum(1 for r in read_trace(path) if r["k"] == "call"), len(ACTIONS))

    def test_new_runs_are_isolated_from_earlier_ones(self):
        played = new_episode()
        run_actions(played)
        fresh = new_episode()
        self.assertEqual(state(fresh), state(new_episode()))
        self.assertEqual(fresh.header()["day"], 0)
        self.assertEqual(fresh.env.sim.reserve_l, fresh.env.sim.instance.reserve_l)

    def test_scripted_policies_touch_only_the_public_tools(self):
        for name in ("reference", "blind", "ec-rules", "stop-early"):
            episode = run_inprocess(SCENARIO, SEED, make_policy(name, SCENARIO))
            used = {r["tool"] for r in episode.trace.calls}
            self.assertLessEqual(used, REQUIRED_TOOLS | {"get_rules", "get_events"}, name)
            self.assertEqual(episode.faults, 0)
            self.assertEqual(episode.env.sim.day, DAYS)

    def test_reference_does_not_depend_on_hidden_state(self):
        """Give the planner a client that hides the episode object entirely."""
        episode = new_episode()

        class Wire:   # only what crosses the wire: JSON in, JSON out
            last_header = None

            def call(self, tool, **args):
                response = json.loads(json.dumps(episode.call(tool, json.loads(json.dumps(args)))))
                self.last_header = response["header"]
                return response

            def tools(self):
                return json.loads(json.dumps(episode.describe_tools()))

            @property
            def done(self):
                return bool(self.last_header and self.last_header["done"])

        make_policy("reference", SCENARIO).run(Wire())
        direct = run_inprocess(SCENARIO, SEED, make_policy("reference", SCENARIO))
        self.assertEqual(episode.result()["profit_eur"], direct.result()["profit_eur"])


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cal = entry_for(load_calibration(ROOT), SCENARIO.id, SEED)

    def tearDown(self):
        self.tmp.cleanup()

    def record(self, policy, name="trace.jsonl"):
        run_inprocess(SCENARIO, SEED, make_policy(policy, SCENARIO), self.dir / name, bundle_hash(source_files(SCENARIO)))
        return self.dir / name

    def test_generated_task_is_current_and_the_agent_image_holds_no_task_data(self):
        self.assertEqual(check_task(SCENARIO, SEED, self.cal, ROOT / "tasks"), [], "run `envkit build root-cause`")
        env = ROOT / "tasks" / task_name(SCENARIO, SEED) / "environment"
        outside = [p for p in env.rglob("*") if p.is_file() and "sim" not in p.relative_to(env).parts]
        self.assertEqual(sorted(p.name for p in outside), ["Dockerfile", "docker-compose.yaml", "requirements.txt"])
        self.assertNotIn("bundle", (env / "Dockerfile").read_text())

    def test_verifier_regrades_the_reference_from_its_trace(self):
        out = grade(VERIFIER_BUNDLE, self.record("reference"))
        self.assertEqual(out["reward"], self.cal["anchors"]["reference"]["reward"])
        self.assertTrue(out["replay"]["consistent"])
        self.assertEqual(out["notes"], [])
        self.assertEqual(out["ledger"]["conservation_ok"], 1.0)
        self.assertEqual(out["ledger"]["days_played"], DAYS)

    def test_empty_trace_is_graded_as_doing_nothing_and_missing_trace_gives_no_reward(self):
        out = grade(VERIFIER_BUNDLE, self.record("do-nothing"))
        self.assertEqual((out["reward"], out["replay"]["calls"]), (0.0, 0))
        code = verify_main(["--bundle", str(VERIFIER_BUNDLE), "--trace", str(self.dir / "absent.jsonl"),
                            "--out", str(self.dir / "out")])
        self.assertEqual(code, 1)
        self.assertFalse((self.dir / "out" / "reward.txt").exists())

    def test_reward_file_holds_one_number_between_zero_and_one(self):
        code = verify_main(["--bundle", str(VERIFIER_BUNDLE), "--trace", str(self.record("ec-rules")),
                            "--out", str(self.dir / "out")])
        self.assertEqual(code, 0)
        text = (self.dir / "out" / "reward.txt").read_text().split()
        self.assertEqual(len(text), 1)
        self.assertTrue(0.0 <= float(text[0]) <= 1.0)
        self.assertEqual(float(text[0]), self.cal["anchors"]["ec-rules"]["reward"])

    def test_forged_responses_and_claimed_scores_gain_nothing(self):
        """The verifier replays actions; it never reads a number the trace claims."""
        honest = grade(VERIFIER_BUNDLE, self.record("blind"))
        records = read_trace(self.dir / "trace.jsonl")
        for r in records:
            if r.get("k") == "call":
                r["response"] = {"ok": True, "result": {"final_result": {"profit_eur": 10 ** 9, "normalized_profit": 1.0}},
                                 "header": {"done": True}}
                r["digest"] = "0" * 16
                r["ok"] = True
        records.append({"k": "score", "reward": 1.0, "profit_eur": 10 ** 9})
        records.append({"k": "state", "reserve_l": 10 ** 9, "benches": {"A": {"harvest": 10 ** 6}}})
        write_trace(self.dir / "forged.jsonl", records)
        forged = grade(VERIFIER_BUNDLE, self.dir / "forged.jsonl")
        self.assertEqual(forged["reward"], honest["reward"])
        self.assertEqual(forged["ledger"]["profit_eur"], honest["ledger"]["profit_eur"])
        self.assertFalse(forged["replay"]["consistent"])
        self.assertTrue(any("did not reproduce" in n for n in forged["notes"]))

    def test_a_trace_cannot_choose_an_easier_seed_or_scenario(self):
        records = read_trace(self.record("do-nothing"))
        records[0].update({"seed": 12345, "scenario": "something-easier", "bundle": "ffff"})
        write_trace(self.dir / "reseeded.jsonl", records)
        out = grade(VERIFIER_BUNDLE, self.dir / "reseeded.jsonl")
        self.assertEqual((out["seed"], out["reward"]), (SEED, 0.0))
        self.assertTrue(any("does not match" in n for n in out["notes"]))

    def test_injected_impossible_actions_are_rejected_on_replay(self):
        """Calls written into a trace go through the same validation as live calls."""
        records = read_trace(self.record("do-nothing"))
        injected = [
            {"k": "call", "i": 0, "tool": "submit_day_plan", "args": {"bench_plans": plan(5000.0, 0.0)}},
            {"k": "call", "i": 1, "tool": "submit_day_plan", "args": {"bench_plans": plan(A={"mains_l": -9999.0})}},
            {"k": "call", "i": 2, "tool": "set_profit", "args": {"profit_eur": 10 ** 9}},
            {"k": "call", "i": 3, "tool": "advance_day", "args": {"harvest_kg": 10 ** 6}},
        ]
        write_trace(self.dir / "injected.jsonl", records + injected)
        out = grade(VERIFIER_BUNDLE, self.dir / "injected.jsonl")
        self.assertEqual(out["reward"], 0.0)
        self.assertEqual(out["ledger"]["profit_eur"], out["ledger"]["profit_floor_eur"])
        self.assertEqual(out["ledger"]["conservation_ok"], 1.0)


if __name__ == "__main__":
    unittest.main()
