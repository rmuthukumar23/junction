Smoke test of a greenhouse simulator. You run a two-compartment winter greenhouse
for 1 day (24 one-hour windows) with 12 tool calls.
Call get_rules once, then get_batches, harvest every batch whose status is
"ready", and call advance with hours=12 until the episode is done.

## Interface

Every action goes through the tools of the MCP server `env` (`http://sim:8000/mcp`), which is already connected. Nothing in this container's filesystem affects your result.

- Each tool call spends one operation, unless the tool's description says otherwise. A call rejected for malformed arguments spends nothing.
- Every result is JSON with `ok`, then `result` or `error`, then a `header` with the operations left (`ops_left`) and status. When `header.done` is true the episode is over.
- `header.calls_left` is the number of tool calls you have left in the whole episode, every request counted. `header.ops_left` only counts operations in the current window.
- There is no reset and no second attempt. Your result is computed from the state of the world when the episode ends.
