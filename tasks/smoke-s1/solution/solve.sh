#!/bin/bash
# The oracle. Plays a scripted policy through the same MCP tools the agent has.
#   ENVKIT_POLICY=reference    (default) the scenario's reference run
#   ENVKIT_POLICY=stop-early   the reference for the first 30% of windows, then stop
#   ENVKIT_POLICY=<name>       any other policy; see envkit/policies.py
set -euo pipefail
cd "$(dirname "$0")/bundle"
exec python3 -m envkit.oracle --url http://sim:8000/mcp --policy "${ENVKIT_POLICY:-reference}"
