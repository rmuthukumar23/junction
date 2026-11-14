import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from threading import Thread
import unittest
from junction_env.adapters.service import EpisodeHTTPServer, EpisodeService
from test_scheduling import fixture


@unittest.skipUnless(importlib.util.find_spec("mcp"), "install the mcp extra for transport test")
class MCPTests(unittest.TestCase):
    def test_real_stdio_bridge_to_trusted_service(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        with tempfile.TemporaryDirectory() as directory:
            service = EpisodeService(fixture(), Path(directory) / "live.json")
            server = EpisodeHTTPServer(("127.0.0.1", 0), service.handler())
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            async def exercise():
                params = StdioServerParameters(command=sys.executable, args=["-m", "junction_env.adapters.mcp_server",
                                               "--url", f"http://127.0.0.1:{server.server_port}"])
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write, read_timeout_seconds=10) as session:
                        await session.initialize()
                        names = {tool.name for tool in (await session.list_tools()).tools}
                        self.assertEqual(names, {"observe", "start_job", "advance", "finish"})
                        response = await session.call_tool("observe", {})
                        self.assertEqual(json.loads(response.content[0].text)["time"], 0)
                        response = await session.call_tool("advance", {"to_time": True})
                        self.assertTrue(response.is_error)
                        self.assertEqual(service.environment.actions_used, 1)
                        await session.call_tool("start_job", {"job_id": "a"})
                        await session.call_tool("advance", {"to_time": 2})
                        await session.call_tool("finish", {})
                        self.assertEqual(service.environment.score(), 4 / 12)
            try:
                asyncio.run(exercise())
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
