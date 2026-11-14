from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import unittest
from junction_env import run_episode
from junction_env.scheduling import Instance, Job, ShiftPlanner, generate
from junction_env.scheduling.generator import generate_with_witness
from junction_env.scheduling.reference import do_nothing, stop_early
from junction_env.scheduling.verifier import VerificationError, check_intervals, verify_record


def fixture():
    return Instance(0, (
        Job("a", 2, 1, "lathe", (), 2, 4),
        Job("b", 3, 1, "bench", (), 3, 3),
        Job("c", 2, 2, None, ("a",), 6, 3),
        Job("d", 1, 1, "lathe", (), 1, 2),
    ), shift_end=10)


class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.env = ShiftPlanner(fixture())

    def act(self, tool, **kwargs):
        return self.env.step({"tool": tool, **kwargs}).observation

    def test_resources_dependencies_and_deadlines(self):
        self.assertIn("error", self.act("start_job", job_id="c"))
        self.act("start_job", job_id="a")
        self.assertEqual(self.env.time, 0)
        self.assertIn("equipment", self.act("start_job", job_id="d")["error"])
        self.act("start_job", job_id="b")
        self.act("advance", to_time=2)
        self.assertEqual(self.env.completed, {"a": 2})
        self.assertIn("technicians", self.act("start_job", job_id="c")["error"])
        self.act("advance", to_time=3)
        self.act("start_job", job_id="c")
        self.act("advance", to_time=5)
        self.act("start_job", job_id="d")
        self.act("advance", to_time=6)
        self.assertTrue(self.env.done)
        self.assertEqual(self.env.score(), 10 / 12)
        self.assertEqual(verify_record(self.env.record(), fixture()), 10 / 12)

    def test_invalid_actions_consume_budget_without_changing_work(self):
        invalid = [None, [], {}, {"tool": []}, {"tool": "start_job", "job_id": []},
                   {"tool": "start_job", "job_id": "unknown"},
                   {"tool": "advance", "to_time": True}, {"tool": "advance", "to_time": 2.0},
                   {"tool": "advance", "to_time": 0}, {"tool": "advance", "to_time": 11},
                   {"tool": "finish", "score": 1}, {"tool": "reset", "seed": 1}]
        for index, action in enumerate(invalid, 1):
            result = self.env.step(action)
            self.assertIn("error", result.observation)
            self.assertEqual(self.env.starts, {})
            self.assertEqual(self.env.time, 0)
            self.assertEqual(self.env.actions_used, index)
        while not self.env.done:
            self.env.step({"tool": "invalid"})
        self.assertEqual(self.env.actions_used, 64)
        self.assertEqual(self.env.termination, "action_limit")
        self.assertEqual(verify_record(self.env.record(), fixture()), 0)

    def test_duplicate_reverse_and_after_termination(self):
        self.act("start_job", job_id="a")
        self.assertIn("error", self.act("start_job", job_id="a"))
        self.act("advance", to_time=2)
        self.assertIn("error", self.act("advance", to_time=1))
        self.act("finish")
        record = self.env.record()
        self.act("advance", to_time=10)
        self.assertEqual(record, self.env.record())
        self.assertEqual(self.env.score(), 4 / 12)

    def test_inspection_and_unfinished_work_get_no_credit(self):
        for _ in range(80):
            self.env.step({"tool": "observe"})
        self.assertEqual(self.env.actions_used, 0)
        self.act("start_job", job_id="a")
        self.act("finish")
        self.assertEqual(self.env.score(), 0)
        for policy in (do_nothing, stop_early):
            self.assertEqual(run_episode(ShiftPlanner(), policy, seed=2, max_steps=64).score, 0)

    def test_shift_end_does_not_credit_running_work(self):
        self.act("advance", to_time=9)
        self.act("start_job", job_id="a")
        self.act("advance", to_time=10)
        self.assertEqual(self.env.termination, "shift_end")
        self.assertEqual(verify_record(self.env.record(), fixture()), 0)

    def test_observations_actions_and_records_are_detached(self):
        obs = self.env.observe()
        obs["instance"]["jobs"][0]["value"] = 10000
        obs["starts"]["a"] = 0
        action = {"tool": "start_job", "job_id": "a"}
        self.env.step(action)
        action["job_id"] = "b"
        record = self.env.record()
        record["history"][0]["action"]["job_id"] = "b"
        self.assertEqual(self.env.record()["history"][0]["action"]["job_id"], "a")
        self.assertEqual(self.env.instance, fixture())

    def test_tampering_is_rejected(self):
        self.act("start_job", job_id="a")
        self.act("advance", to_time=2)
        record = self.env.record()
        mutations = [lambda r: r.update(score=1), lambda r: r["final"]["starts"].update(b=0),
                     lambda r: r["history"][0]["action"].update(job_id="b"),
                     lambda r: r.update(instance_hash="fake")]
        for mutate in mutations:
            altered = deepcopy(record)
            mutate(altered)
            with self.assertRaises(VerificationError):
                verify_record(altered, fixture())
        with self.assertRaises(VerificationError):
            check_intervals(fixture(), {"a": 0, "d": 0}, 2)
        with self.assertRaises(VerificationError):
            check_intervals(fixture(), {"c": 0}, 2)

    def test_witness_feasibility_and_deterministic_replay(self):
        for count in (8, 10, 12):
            for seed in range(20):
                instance, starts = generate_with_witness(seed, count)
                self.assertEqual(generate(seed, count), instance)
                self.assertEqual(check_intervals(instance, starts, instance.shift_end), 1)
                a, b = ShiftPlanner(instance), ShiftPlanner(instance)
                actions = []
                for key, start in sorted(starts.items(), key=lambda p: (p[1], p[0])):
                    if start > a.time:
                        actions.append({"tool": "advance", "to_time": start})
                        a.step(actions[-1])
                    actions.append({"tool": "start_job", "job_id": key})
                    a.step(actions[-1])
                actions.append({"tool": "advance", "to_time": instance.shift_end})
                a.step(actions[-1])
                for action in actions:
                    b.step(action)
                self.assertEqual(a.record(), b.record())
                self.assertEqual(verify_record(a.record(), instance), 1)
                self.assertLess(a.actions_used, 32)

    def test_all_prefixes_score_only_completed_work(self):
        actions = [{"tool": "start_job", "job_id": "a"}, {"tool": "advance", "to_time": 2},
                   {"tool": "start_job", "job_id": "c"}, {"tool": "advance", "to_time": 4}]
        for count, expected in enumerate((0, 0, 4/12, 4/12, 7/12)):
            env = ShiftPlanner(fixture())
            for action in actions[:count]:
                env.step(action)
            env.interrupt()
            self.assertEqual(verify_record(env.record(), fixture()), expected)

    def test_parallel_episode_isolation(self):
        def episode(seed):
            env = ShiftPlanner()
            run_episode(env, stop_early, seed=seed, max_steps=64)
            return env.record()
        with ThreadPoolExecutor(max_workers=4) as pool:
            concurrent = list(pool.map(episode, range(20)))
        self.assertEqual(concurrent, [episode(seed) for seed in range(20)])


if __name__ == "__main__":
    unittest.main()
