import json
from pathlib import Path
import tempfile
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import unittest

from junction_env.adapters.mcp_server import request_action
from junction_env.adapters.service import EpisodeHTTPServer, EpisodeService, collect
from junction_env.scheduling.verifier import verify_record
from test_scheduling import fixture


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.service = EpisodeService(fixture(), self.root / "live.json")
        self.server = EpisodeHTTPServer(("127.0.0.1", 0), self.service.handler())
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def test_agent_file_edits_do_not_affect_trusted_score(self):
        (self.root / "agent_reward.txt").write_text("1.0")
        request_action(self.url, {"tool": "start_job", "job_id": "a"})
        request_action(self.url, {"tool": "advance", "to_time": 2})
        collect(self.root / "live.json", self.root / "episode.json", self.url)
        record = json.loads((self.root / "episode.json").read_text())
        self.assertEqual(verify_record(record, fixture()), 4 / 12)
        self.assertEqual(record["final"]["termination"], "harness_interruption")
        for path in ("/reset", "/record", "/state/live.json", "/score", "/../state/live.json"):
            with self.assertRaises(HTTPError) as error:
                urlopen(self.url + path)
            self.assertEqual(error.exception.code, 404)

    def test_malformed_json_is_counted(self):
        request = Request(self.url + "/action", data=b"{broken", method="POST")
        with urlopen(request) as response:
            self.assertIn("error", json.load(response))
        self.assertEqual(self.service.environment.actions_used, 1)

    def test_failed_persistence_prevents_verified_collection(self):
        (self.root / "live.error").touch()
        with self.assertRaises(RuntimeError):
            collect(self.root / "live.json", self.root / "episode.json", self.url)
        self.assertFalse((self.root / "episode.json").exists())
