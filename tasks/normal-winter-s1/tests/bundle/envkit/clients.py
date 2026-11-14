"""The two ways a policy reaches an episode: directly, or over MCP."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .core import Episode
from .policies import Client, Policy, StopPolicy
from .scenario import Scenario
from .trace import Trace


class InProcessClient(Client):
    def __init__(self, episode: Episode):
        self._episode = episode

    def call(self, tool: str, **args: Any) -> dict[str, Any]:
        response = self._episode.call(tool, args)
        self.last_header = response["header"]
        return response

    def tools(self) -> list[dict[str, Any]]:
        return self._episode.describe_tools()


def run_inprocess(scenario: Scenario, seed: int, policy: Policy,
                  trace_path: str | Path | None = None, bundle_hash: str = "") -> Episode:
    """Play a policy to the end and return the finalized episode."""
    episode = Episode(scenario, seed, Trace(trace_path), bundle_hash)
    try:
        policy.run(InProcessClient(episode))
    except StopPolicy:
        pass
    episode.finalize()
    episode.trace.close()
    return episode


class McpClient(Client):
    """A synchronous facade over an MCP session, used from a worker thread."""

    def __init__(self, session: Any):
        self._session = session
        self._tools: list[dict[str, Any]] | None = None

    def call(self, tool: str, **args: Any) -> dict[str, Any]:
        from anyio import from_thread

        result = from_thread.run(self._session.call_tool, tool, args)
        text = next((c.text for c in result.content if getattr(c, "type", "") == "text"), None)
        if text is None:
            raise RuntimeError(f"tool '{tool}' returned no text content")
        response = json.loads(text)
        self.last_header = response["header"]
        return response

    def tools(self) -> list[dict[str, Any]]:
        from anyio import from_thread

        if self._tools is None:
            listed = from_thread.run(self._session.list_tools)
            self._tools = [
                {"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
                for t in listed.tools
            ]
        return self._tools


def run_over_mcp(url: str, policy: Policy) -> dict[str, Any] | None:
    """Play a policy against a live MCP server. Returns the last header seen."""
    import anyio
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    last: dict[str, Any] = {}

    def play(client: McpClient) -> None:
        try:
            policy.run(client)
        except StopPolicy:
            pass
        last["header"] = client.last_header

    async def main() -> None:
        async with streamable_http_client(url) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                await anyio.to_thread.run_sync(play, McpClient(session))

    anyio.run(main)
    return last.get("header")
