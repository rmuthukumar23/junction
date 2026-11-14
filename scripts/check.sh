#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
export PYTHONPATH="$repo_root/src:$repo_root${PYTHONPATH:+:$PYTHONPATH}"
python3 -m compileall -q src examples tests
python3 -m unittest discover -s tests -v
python3 examples/toy_environment.py
# The remaining checks need the locked environment (pytest, MCP SDK, OR-Tools).
if python3 -c "import pytest, mcp, ortools" 2>/dev/null; then
  python3 -m pytest tests/envkit
  python3 -m envkit.cli check
  python3 -m envkit.cli audit
else
  echo "Skipped backend tests, task freshness and reward audit: run inside the locked environment (see README)."
fi
