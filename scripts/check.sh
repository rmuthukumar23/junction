#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
export PYTHONPATH="$repo_root/src:$repo_root${PYTHONPATH:+:$PYTHONPATH}"
python3 -m compileall -q src tests
python3 -m unittest discover -s tests/greenhouse -t tests/greenhouse -v
# The remaining checks need the locked environment (pytest, MCP SDK).
if python3 -c "import pytest, mcp" 2>/dev/null; then
  python3 -m pytest tests/envkit
  if compgen -G "scenarios/*.toml" > /dev/null; then
    python3 -m envkit.cli check
    # The reward audit plays whole episodes of the submitted task: benchmark time only.
    if [ "${ENVKIT_TEST_SCENARIO:-}" = "normal-winter" ]; then
      python3 -m envkit.cli audit normal-winter
    else
      echo "Skipped the reward audit (benchmark check): set ENVKIT_TEST_SCENARIO=normal-winter to run it."
    fi
  else
    echo "Skipped task freshness and reward audit: no scenario in scenarios/ yet."
  fi
else
  echo "Skipped backend tests, task freshness and reward audit: run inside the locked environment (see README)."
fi
