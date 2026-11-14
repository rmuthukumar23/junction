"""The MCP server: one process, one episode.

Run inside the `sim` sidecar. The agent's container can reach this process
only through the MCP endpoint, so the scenario file, the seed, the hidden
state and the trace are out of its reach. There is deliberately no reset and
no admin endpoint: the episode starts when the container starts and is graded
from the trace this process writes.

    python -m envkit.server            # serves the bundle it was started from

Environment variables:
    ENVKIT_BUNDLE      bundle directory (default: the directory above this package)
    ENVKIT_STATE_DIR   where trace.jsonl is written (default: /var/lib/envkit)
    ENVKIT_HOST / ENVKIT_PORT          default 0.0.0.0:8000
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .bundle import load_bundle
from .core import Episode
from .scenario import Scenario
from .trace import Trace, read_trace


def resume(scenario: Scenario, seed: int, trace_path: Path, bundle_hash: str) -> Episode:
    """Start an episode, rebuilding state from an existing trace if there is one."""
    previous = read_trace(trace_path)
    trace = Trace(trace_path)
    trace.records = list(previous)
    episode = Episode(scenario, seed, trace, bundle_hash)
    calls = [r for r in previous if r.get("k") == "call"]
    for rec in calls:
        episode.call(rec["tool"], rec.get("args"), record=False)
    episode._n_recorded = len(calls)
    return episode


def instructions(scenario: Scenario) -> str:
    s = scenario.shift
    return (
        f"{scenario.title}. Time is windowed: {s.windows} windows of {s.window_hours:g} hours, "
        f"{s.ops_per_window} operations per window. Each tool call spends one operation unless its "
        "description says otherwise. Spending the last operation, or calling end_window, advances the "
        "clock. Every result carries a header with the current window, operations left and status. "
        "When the last window closes the episode is over."
    )


def build_app(episode: Episode) -> Any:
    import mcp.types as types
    from mcp.server.lowlevel import Server
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    def describe(spec: Any) -> str:
        return spec.description if spec.cost == 1 or spec.name == "end_window" else (
            f"{spec.description} Costs {spec.cost} operations."
        )

    async def on_list_tools(ctx: Any, params: Any) -> Any:
        return types.ListToolsResult(tools=[
            types.Tool(name=s.name, description=describe(s), input_schema=s.input_schema)
            for s in episode.tools.values()
        ])

    async def on_call_tool(ctx: Any, params: Any) -> Any:
        # Synchronous on purpose: calls are applied one at a time, in arrival order.
        response = episode.call(params.name, params.arguments or {})
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(response, allow_nan=False))],
            is_error=not response["ok"],
        )

    async def healthz(request: Any) -> Any:
        return JSONResponse({"status": "ok"})

    server = Server(
        "envkit",
        version=__version__,
        instructions=instructions(episode.scenario),
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )
    return server.streamable_http_app(
        json_response=True,
        stateless_http=True,
        host="0.0.0.0",
        # Reachable only on the task's private network; the Host header there is "sim:8000".
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        custom_starlette_routes=[Route("/healthz", healthz)],
    )


def main() -> None:
    import uvicorn

    bundle = Path(os.environ.get("ENVKIT_BUNDLE", Path(__file__).resolve().parent.parent))
    state = Path(os.environ.get("ENVKIT_STATE_DIR", "/var/lib/envkit"))
    scenario, manifest, _ = load_bundle(bundle)
    episode = resume(scenario, manifest["seed"], state / "trace.jsonl", manifest["bundle"])
    print(f"envkit {__version__}: scenario={scenario.id} seed={manifest['seed']} "
          f"tools={len(episode.tools)} resumed_calls={episode.calls}", file=sys.stderr, flush=True)
    uvicorn.run(build_app(episode), host=os.environ.get("ENVKIT_HOST", "0.0.0.0"),
                port=int(os.environ.get("ENVKIT_PORT", "8000")), log_level="warning")


if __name__ == "__main__":
    main()
