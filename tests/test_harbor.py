import importlib.util
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from junction_env.adapters.harbor_task import build_task
from junction_env.adapters.harbor_results import read_trial, summarize
from junction_env.scheduling import ShiftPlanner, generate


class HarborTaskTests(unittest.TestCase):
    def test_task_has_separate_trusted_collection_and_no_agent_solution(self):
        with tempfile.TemporaryDirectory() as directory:
            task = build_task(Path(directory) / "task", 0)
            data = tomllib.loads((task / "task.toml").read_text())
            self.assertEqual(data["verifier"]["environment_mode"], "separate")
            self.assertEqual(data["artifacts"][0]["service"], "environment")
            self.assertEqual(data["verifier"]["collect"][0]["service"], "environment")
            agent_image = (task / "environment/Dockerfile").read_text()
            self.assertNotIn("COPY src", agent_image)
            self.assertNotIn("solution", agent_image)
            self.assertNotIn("docker.sock", (task / "environment/docker-compose.yaml").read_text())
            self.assertNotIn("witness", (task / "environment/instance.json").read_text())
            if importlib.util.find_spec("harbor"):
                from harbor.models.task.config import TaskConfig
                TaskConfig.model_validate(data)
            with self.assertRaises(FileExistsError):
                build_task(task, 0)

    def test_reporting_keeps_timeout_credit_and_rate_limit_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            trial = Path(directory)
            (trial / "artifacts/trusted").mkdir(parents=True)
            env = ShiftPlanner(generate(0))
            record = env.record()
            (trial / "artifacts/trusted/episode.json").write_text(json.dumps(record))
            raw = {"verifier_result": {"rewards": {"reward": 0}},
                   "exception_info": {"exception_type": "AgentTimeoutError"}}
            path = trial / "result.json"
            path.write_text(json.dumps(raw))
            timeout = read_trial(path, env.instance, "frontier", "test-model")
            self.assertEqual(timeout["episode"]["status"], "interrupted")
            self.assertEqual(timeout["episode"]["score"], 0)
            raw["exception_info"]["exception_type"] = "ApiRateLimitError"
            path.write_text(json.dumps(raw))
            rate_limit = read_trial(path, env.instance, "frontier", "test-model")
            self.assertIsNone(rate_limit["episode"]["score"])
            self.assertTrue(rate_limit["provider_rate_limit"])
            self.assertIn("infra", summarize([timeout, rate_limit]))
            raw["exception_info"] = None
            raw["verifier_result"]["rewards"]["reward"] = 1
            path.write_text(json.dumps(raw))
            self.assertEqual(read_trial(path, env.instance, "frontier", "test-model")["episode"]["status"], "infrastructure_failure")
