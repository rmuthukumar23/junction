import importlib.util
import unittest
from junction_env import run_episode
from junction_env.scheduling import ShiftPlanner
from junction_env.scheduling.reference import ReferencePolicy
from junction_env.scheduling.verifier import verify_record


@unittest.skipUnless(importlib.util.find_spec("ortools"), "install the eval extra for CP-SAT tests")
class ReferenceTests(unittest.TestCase):
    def test_reference_from_public_data(self):
        for count in (8, 10, 12):
            for seed in range(5):
                env = ShiftPlanner(job_count=count)
                result = run_episode(env, ReferencePolicy(), seed=seed, max_steps=64)
                self.assertEqual(result.score, 1)
                self.assertEqual(verify_record(env.record(), env.instance), 1)
                self.assertLess(env.actions_used, 32)
