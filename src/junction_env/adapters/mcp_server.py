"""Untrusted stdio MCP bridge to the trusted episode service (MCP SDK 2.3)."""
import argparse
import asyncio
import json
from urllib.request import Request, urlopen


TOOL_SCHEMAS = {
    "observe": ("Inspect all jobs, resources and current state. Does not consume an action.", {}),
    "start_job": ("Start a pending job at current virtual time; no time passes. Cannot cancel it.",
                  {"job_id": {"type": "string"}}),
    "advance": ("Advance strictly forward, at most to shift_end; process every intervening completion.",
                {"to_time": {"type": "integer"}}),
    "finish": ("End now. Only already completed, on-time jobs receive credit.", {}),
}


def request_action(base_url: str, action: dict) -> dict:
    request = Request(base_url.rstrip("/") + "/action", data=json.dumps(action).encode(),
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=10) as response:
        return json.load(response)


async def serve(base_url: str):
    from mcp import types
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server

    async def list_tools(ctx, params):
        return types.ListToolsResult(tools=[types.Tool(
            name=name, description=description,
            input_schema={"type": "object", "properties": properties,
                         "required": list(properties), "additionalProperties": False})
            for name, (description, properties) in TOOL_SCHEMAS.items()])

    async def call_tool(ctx, params):
        arguments = params.arguments or {}
        action = {**arguments, "tool": params.name}
        if "tool" in arguments:
            action["unexpected_tool_argument"] = arguments["tool"]
        observation = await asyncio.to_thread(request_action, base_url, action)
        return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(observation))],
                                    is_error="error" in observation)

    # Validation belongs to the trusted service so malformed tool arguments count.
    server = Server("shift-planner", version="1", on_list_tools=list_tools, on_call_tool=call_tool)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://environment:8000")
    args = parser.parse_args()
    asyncio.run(serve(args.url))


if __name__ == "__main__":
    main()
