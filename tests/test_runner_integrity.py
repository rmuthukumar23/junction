import unittest
from junction_env import StepResult, run_episode
from junction_env.scheduling import ShiftPlanner
from test_scheduling import fixture


class RunnerIntegrityTests(unittest.TestCase):
    def test_mutable_trace_snapshots(self):
        class MutableEnvironment:
            def reset(self, seed):
                self.obs = {"nested": {"turn": 0}}
                return self.obs
            def step(self, action):
                self.obs["nested"]["turn"] += 1
                action["nested"]["x"] = 99
                return StepResult(self.obs, self.obs["nested"]["turn"] == 2)
            def score(self):
                return 1.0
        def policy(obs):
            obs["nested"]["turn"] = 100
            return {"nested": {"x": 1}}
        result = run_episode(MutableEnvironment(), policy, seed=0, max_steps=4)
        self.assertEqual([t.observation["nested"]["turn"] for t in result.turns], [0, 1])
        self.assertEqual([t.next_observation["nested"]["turn"] for t in result.turns], [1, 2])
        self.assertEqual(result.turns[0].action["nested"]["x"], 1)
        result.turns[0].next_observation["nested"]["turn"] = 999
        self.assertEqual(result.turns[1].observation["nested"]["turn"], 1)

    def test_timeout_preserves_completed_work(self):
        def policy(obs):
            if not obs["starts"]:
                return {"tool": "start_job", "job_id": "a"}
            if not obs["completed"]:
                return {"tool": "advance", "to_time": 2}
            raise TimeoutError("deadline")
        result = run_episode(ShiftPlanner(fixture()), policy, seed=0, max_steps=64)
        self.assertEqual(result.score, 4 / 12)
        self.assertEqual(result.stop_reason, "policy_timeout")
        self.assertEqual(result.status, "interrupted")

    def test_infrastructure_error_has_no_agent_score(self):
        class Broken(ShiftPlanner):
            def step(self, action):
                raise OSError("service unavailable")
        result = run_episode(Broken(), lambda obs: {"tool": "finish"}, seed=0, max_steps=4)
        self.assertIsNone(result.score)
        self.assertEqual(result.status, "infrastructure_failure")

    def test_invalid_score_is_infrastructure_failure(self):
        class Broken(ShiftPlanner):
            def score(self):
                return float("nan")
        result = run_episode(Broken(), lambda obs: None, seed=0, max_steps=4)
        self.assertEqual(result.status, "infrastructure_failure")
