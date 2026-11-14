"""The Root Cause dashboard server: same engine as the agent path, persistent runs, no hidden state in play."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from envkit.clients import run_inprocess
from envkit.core import Episode
from envkit.policies import make_policy
from envkit.trace import read_trace

from rootcause_app.analysis import counterfactuals, substitute
from rootcause_app.compare import comparators
from rootcause_app.server import serve
from rootcause_app.store import load_default_scenario

SCENARIO = load_default_scenario()
SEED = 7


def plan(irrigation=230.0, fertilizer=120.0, flush=0.0, **overrides):
    out = {z: {"irrigation_l": irrigation, "fertilizer_g": fertilizer, "flush_l": flush} for z in "ABCD"}
    for zone, values in overrides.items():
        out[zone].update(values)
    return out


ACTIONS = [
    ("order_test", {"zone_id": "C"}),
    ("submit_day_plan", {"zone_plans": plan(C={"fertilizer_g": 500.0})}), ("advance_day", {}),
    ("submit_day_plan", {"zone_plans": plan(250.0, 150.0, C={"flush_l": 400.0, "fertilizer_g": 800.0})}), ("advance_day", {}),
    ("submit_day_plan", {"zone_plans": plan(2000.0)}),            # rejected
    ("advance_day", {}),
]


class Server:
    def __init__(self, data: Path):
        self.httpd = serve("127.0.0.1", 0, data)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def request(self, method, path, body=None, raw=None):
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        req = Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
        try:
            with urlopen(req, timeout=30) as response:
                return response.status, json.loads(response.read())
        except HTTPError as e:
            payload = e.read()
            try:
                return e.code, json.loads(payload)
            except json.JSONDecodeError:
                return e.code, payload.decode(errors="replace")

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body=None):
        return self.request("POST", path, body if body is not None else {})

    def call(self, run_id, tool, args=None, expect_day=None):
        body = {"tool": tool, "args": args or {}}
        if expect_day is not None:
            body["expect_day"] = expect_day
        return self.post(f"/api/runs/{run_id}/call", body)

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.server = Server(self.data)

    def tearDown(self):
        self.server.close()
        self.tmp.cleanup()

    def new_run(self, seed=SEED, player="Tester"):
        status, body = self.server.post("/api/runs", {"seed": seed, "player": player})
        self.assertEqual(status, 201)
        return body["run"]["run_id"]

    def play(self, run_id, actions=ACTIONS, finish=True):
        replies = [self.server.call(run_id, tool, args)[1] for tool, args in actions]
        if finish:
            replies.append(self.server.call(run_id, "finish_episode")[1])
        return replies

    def test_app_and_static_files_are_served_and_nothing_else(self):
        with urlopen(self.server.base + "/", timeout=10) as r:
            self.assertIn(b"Root Cause", r.read())
        with urlopen(self.server.base + "/static/js/app.js", timeout=10) as r:
            self.assertIn("javascript", r.headers["Content-Type"])
        for path in ("/static/../store.py", "/static/..%2f..%2fstore.py", "/static/js/../../server.py", "/store.py", "/static/nope.js"):
            self.assertEqual(self.server.get(path)[0], 404, path)
        self.assertEqual(self.server.get("/api/config")[1]["seeds"]["demo"], SEED)

    def test_bad_requests_are_refused_cleanly(self):
        run_id = self.new_run()
        self.assertEqual(self.server.get("/api/runs/../../etc/view")[0], 404)
        self.assertEqual(self.server.get("/api/runs/r20260101000000-abcdef/view")[0], 404)
        self.assertEqual(self.server.get("/api/runs/not-a-run/view")[0], 404)
        self.assertEqual(self.server.request("POST", f"/api/runs/{run_id}/call", raw=b"{not json")[0], 400)
        self.assertEqual(self.server.post(f"/api/runs/{run_id}/call", {"args": {}})[0], 400)
        self.assertEqual(self.server.request("POST", f"/api/runs/{run_id}/call", raw=b"x" * 70000)[0], 413)
        for seed in (-1, "7", 1.5, None, True, 10 ** 12):
            self.assertEqual(self.server.post("/api/runs", {"seed": seed})[0], 400, seed)
        status, reply = self.server.call(run_id, "set_state", {"fresh_water_l": 1e9})
        self.assertEqual((status, reply["ok"], reply["error"]["code"]), (200, False, "unknown_tool"))
        status, reply = self.server.call(run_id, "submit_day_plan", {"zone_plans": plan(A={"irrigation_l": "NaN"})})
        self.assertFalse(reply["ok"])
        self.assertEqual(self.server.get(f"/api/runs/{run_id}/view")[1]["status"]["costs_so_far"]["total_eur"], 0.0)
        hostile = self.new_run(player="<img src=x onerror=alert(1)>")
        listed = {r["run_id"]: r for r in self.server.get("/api/runs")[1]["runs"]}
        self.assertNotIn("<", listed[hostile]["player"])
        self.assertNotIn(">", listed[hostile]["player"])

    def test_live_view_has_the_agents_observations_and_no_hidden_state(self):
        run_id = self.new_run()
        self.play(run_id, ACTIONS[:3], finish=False)
        status, view = self.server.get(f"/api/runs/{run_id}/view")
        self.assertEqual(status, 200)
        episode = Episode(SCENARIO, SEED)
        for tool, args in ACTIONS[:3]:
            episode.call(tool, args)
        for key, tool in (("status", "get_status"), ("rules", "get_rules"), ("forecast", "get_forecast"),
                          ("tests", "get_pending_tests"), ("events", "get_events")):
            self.assertEqual(view[key], json.loads(json.dumps(episode.call(tool, {})["result"])), key)
        self.assertEqual(view["history"]["C"], json.loads(json.dumps(episode.call("get_history", {"zone_id": "C"})["result"])))
        text = json.dumps(view)
        for hidden in ("salty_hungry", "composition_type", "hidden_morning", "realized_temps", "profit_floor", "\"factors\"",
                       "abandon"):
            self.assertNotIn(hidden, text)
        # No result and no projection of one while the run is in progress.
        self.assertNotIn("result", view["run"])
        self.assertNotIn("profit", json.dumps(view["run"]))
        self.assertNotIn("profit", json.dumps([view["status"], view["forecast"], view["tests"], view["events"], view["history"]]))
        for path in ("report", "whatif"):
            status, body = self.server.get(f"/api/runs/{run_id}/{path}")
            self.assertEqual(status, 409, path)
            self.assertNotIn("analysis", body)

    def test_reading_never_moves_time_or_adds_to_the_action_log(self):
        run_id = self.new_run()
        trace = self.data / "runs" / run_id / "trace.jsonl"
        before = trace.read_text()
        for _ in range(10):
            self.assertEqual(self.server.get(f"/api/runs/{run_id}/view")[1]["status"]["day"], 0)
            self.server.get("/api/runs")
        self.assertEqual(trace.read_text(), before)

    def test_repeated_or_stale_advance_plays_one_day_only(self):
        run_id = self.new_run()
        first = self.server.call(run_id, "advance_day", expect_day=0)
        self.assertEqual((first[0], first[1]["header"]["day"]), (200, 1))
        for _ in range(3):   # the same click arriving again, or an old tab
            status, body = self.server.call(run_id, "advance_day", expect_day=0)
            self.assertEqual(status, 409)
            self.assertIn("Nothing was applied", body["error"])
        self.assertEqual(self.server.get(f"/api/runs/{run_id}/view")[1]["status"]["day"], 1)
        self.assertEqual(self.server.call(run_id, "submit_day_plan", {"zone_plans": plan()}, expect_day=0)[0], 409)

    def test_browser_run_scores_exactly_like_the_same_actions_through_the_agent_path(self):
        run_id = self.new_run()
        replies = self.play(run_id)
        self.assertFalse(replies[5]["ok"])                                  # the over-cap plan was rejected whole
        status, report = self.server.get(f"/api/runs/{run_id}/report")
        self.assertEqual(status, 200)

        episode = Episode(SCENARIO, SEED)
        for tool, args in [*ACTIONS, ("finish_episode", {})]:
            episode.call(tool, args)
        ledger = episode.result()
        self.assertEqual(report["result"]["profit_eur"], ledger["profit_eur"])
        self.assertEqual(report["result"]["reward"], round(ledger["normalized_profit"], 4))
        self.assertEqual(replies[-1]["result"]["final_result"]["profit_eur"], ledger["profit_eur"])
        self.assertTrue(report["replay"]["consistent"])
        self.assertEqual(report["days_played_by_player"], 3)
        self.assertEqual(report["result"]["conservation_ok"], 1.0)
        self.assertEqual(len(report["analysis"]["days"]), 14)
        self.assertIn("starting_composition_type", json.dumps(report["analysis"]))

    def test_end_report_carries_executed_comparators_and_an_honest_model_status(self):
        run_id = self.new_run()
        self.play(run_id, ACTIONS[:3])
        report = self.server.get(f"/api/runs/{run_id}/report")[1]
        runs = {c["policy"]: c for c in report["comparators"]["runs"]}
        self.assertEqual(set(runs), {"do-nothing", "stop-early", "rule-based", "reference"})
        for name, row in runs.items():   # each row equals a fresh execution of that policy
            fresh = run_inprocess(SCENARIO, SEED, make_policy(name, SCENARIO)).result()
            self.assertEqual(row["profit_eur"], fresh["profit_eur"], name)
            self.assertTrue(Path(row["trace"]).is_file())
        self.assertEqual(runs["do-nothing"]["reward"], 0.0)
        self.assertEqual(runs["do-nothing"]["profit_eur"], report["result"]["profit_floor_eur"])
        self.assertGreater(runs["reference"]["profit_eur"], runs["rule-based"]["profit_eur"])
        self.assertEqual(report["llm"]["status"], "not_run")
        self.assertIn("harbor run -p tasks/root-cause-s7 -a opencode", report["llm"]["command"])

    def test_runs_persist_across_a_restart_and_new_runs_do_not_erase_old_ones(self):
        finished = self.new_run(player="First")
        self.play(finished)
        before = self.server.get(f"/api/runs/{finished}/report")[1]["result"]
        open_run = self.new_run(player="Second")
        self.play(open_run, ACTIONS[:3], finish=False)

        self.server.close()
        self.server = Server(self.data)                                     # a new process over the same directory
        self.assertEqual(self.server.get(f"/api/runs/{finished}/report")[1]["result"], before)
        view = self.server.get(f"/api/runs/{open_run}/view")[1]
        self.assertEqual((view["status"]["day"], view["status"]["costs_so_far"]["tests_eur"]), (1, 25.0))
        self.assertEqual(self.server.call(open_run, "advance_day", expect_day=1)[1]["header"]["day"], 2)

        third = self.new_run(player="Third")
        listed = {r["run_id"]: r for r in self.server.get("/api/runs")[1]["runs"]}
        self.assertEqual(set(listed), {finished, open_run, third})
        self.assertEqual(listed[finished]["result"]["profit_eur"], before["profit_eur"])
        self.assertEqual(listed[third]["day"], 0)
        # An unfinished run has no result, and nothing about its future is projected.
        for unfinished in (open_run, third):
            self.assertNotIn("result", listed[unfinished])
            self.assertNotIn("profit", json.dumps(listed[unfinished]))

    def test_files_in_the_data_directory_cannot_raise_a_score(self):
        run_id = self.new_run()
        self.play(run_id, ACTIONS[:3])
        honest = self.server.get(f"/api/runs/{run_id}/report")[1]["result"]
        directory = self.data / "runs" / run_id
        (directory / "result.json").write_text(json.dumps({"profit_eur": 1e9, "reward": 1.0}))
        (directory / "score.txt").write_text("1.0")
        with open(directory / "trace.jsonl", "a") as fh:
            fh.write(json.dumps({"k": "score", "reward": 1.0, "profit_eur": 1e9}) + "\n")
            fh.write(json.dumps({"k": "call", "i": 99, "tool": "submit_day_plan", "ok": True,
                                 "args": {"zone_plans": plan(5000.0)}, "response": {"ok": True}}) + "\n")
        self.server.close()
        self.server = Server(self.data)
        after = self.server.get(f"/api/runs/{run_id}/report")[1]
        self.assertEqual(after["result"]["profit_eur"], honest["profit_eur"])
        self.assertEqual(after["result"]["reward"], honest["reward"])
        self.assertEqual(self.server.get("/api/runs")[1]["runs"][0]["result"]["profit_eur"], honest["profit_eur"])


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.trace = Path(self.tmp.name) / "t.jsonl"
        self.episode = run_inprocess(SCENARIO, SEED, make_policy("rule-based", SCENARIO), self.trace)

    def tearDown(self):
        self.tmp.cleanup()

    def test_substitution_changes_one_day_and_keeps_every_other_request(self):
        calls = [(r["tool"], r.get("args")) for r in read_trace(self.trace) if r["k"] == "call"]
        swapped = substitute(calls, 3, plan(111.0))
        inserted = swapped.index(("submit_day_plan", {"zone_plans": plan(111.0)}))
        self.assertEqual(sum(1 for tool, _ in swapped[:inserted] if tool == "advance_day"), 3)
        self.assertEqual(swapped[inserted + 1][0], "advance_day")
        original_other_days = [c for i, c in enumerate(calls)]
        kept = [c for c in swapped if c != ("submit_day_plan", {"zone_plans": plan(111.0)})]
        self.assertEqual(len(original_other_days) - len(kept), 1)           # only that day's own plan was dropped
        self.assertIsNone(substitute(calls[:4], 9, plan()))                 # a day the player never reached

    def test_whatif_reports_the_actual_profit_feasibility_and_real_replays(self):
        result = counterfactuals(SCENARIO, SEED, read_trace(self.trace))
        self.assertEqual(result["actual_profit_eur"], self.episode.result()["profit_eur"])
        self.assertEqual(result["days_played_by_player"], 14)
        self.assertEqual(len(result["points"]), 3)
        self.assertIn("not of an optimal plan", result["method"])
        evaluated = [alt for pt in result["points"] for alt in pt["alternatives"] if alt["feasible"]]
        self.assertGreaterEqual(len(evaluated), 6)
        for alt in evaluated:
            self.assertAlmostEqual(alt["delta_eur"], alt["profit_eur"] - result["actual_profit_eur"], places=2)
            self.assertGreaterEqual(alt["later_plans_rejected"], 0)
        self.assertTrue(any(abs(alt["delta_eur"]) > 1 for alt in evaluated), "a different day changes the outcome")

    def test_an_infeasible_alternative_is_reported_and_not_evaluated(self):
        calls = [{"k": "call", "tool": "advance_day", "args": {}} for _ in range(14)]
        episode = Episode(SCENARIO, SEED)
        episode.env.sim.fresh_water_l = 0.0     # not used: feasibility is judged on a fresh replay, below
        result = counterfactuals(SCENARIO, SEED, calls, days=[13])
        labels = {alt["alternative"]: alt for alt in result["points"][0]["alternatives"]}
        self.assertTrue(all("feasible" in alt for alt in labels.values()))
        for alt in labels.values():
            if not alt["feasible"]:
                self.assertIn("reason", alt)
                self.assertNotIn("profit_eur", alt)

    def test_comparator_cache_is_keyed_by_code_version_and_reproduces(self):
        first = comparators(SCENARIO, SEED, Path(self.tmp.name))
        again = comparators(SCENARIO, SEED, Path(self.tmp.name))
        self.assertEqual(first, again)
        self.assertIn(first["bundle"], str(Path(first["runs"][0]["trace"]).parent))


if __name__ == "__main__":
    unittest.main()
