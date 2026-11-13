import unittest

from junction_env.runner import run_episode
from examples.toy_environment import ToyEnvironment, do_nothing, reference, stop_early


class RunnerTests(unittest.TestCase):
    def test_reference_beats_trivial_baselines_for_repeated_seeds(self) -> None:
        for seed in range(20):
            with self.subTest(seed=seed):
                self.assertEqual(run_episode(ToyEnvironment(), reference, seed=seed, max_steps=2).score, 1.0)
                self.assertEqual(run_episode(ToyEnvironment(), do_nothing, seed=seed, max_steps=2).score, 0.0)
                self.assertEqual(run_episode(ToyEnvironment(), stop_early, seed=seed, max_steps=2).score, 0.0)

    def test_repeated_reset_is_deterministic(self) -> None:
        env = ToyEnvironment()
        first = run_episode(env, reference, seed=9, max_steps=2)
        second = run_episode(env, reference, seed=9, max_steps=2)
        self.assertEqual(first, second)

    def test_invalid_action_consumes_turn_without_reward(self) -> None:
        env = ToyEnvironment()
        env.reset(3)
        result = env.step({"name": "unknown"})
        self.assertEqual(result.observation["turns_left"], 1)
        self.assertEqual(result.observation["error"], "invalid action; turn consumed")
        env.step({"name": "commit", "value": 1})
        self.assertEqual(env.score(), 0.0)

    def test_step_limit_and_early_stop_score_incomplete_work(self) -> None:
        self.assertEqual(run_episode(ToyEnvironment(), reference, seed=2, max_steps=1).score, 0.0)
        self.assertEqual(run_episode(ToyEnvironment(), stop_early, seed=2, max_steps=2).stop_reason, "policy_stop")


if __name__ == "__main__":
    unittest.main()
