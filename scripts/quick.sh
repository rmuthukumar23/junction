#!/usr/bin/env bash
# The quick check: catches compile errors and breaking changes in about 30 s.
# Plays no benchmark scenario (only the 1-day smoke task). Run it after every change.
#   bash scripts/quick.sh
# Benchmark checks are separate and run only when explicitly asked (see AGENTS.md).
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
unset ENVKIT_TEST_SCENARIO
uv run --no-sync python -m compileall -q src tests
uv run --no-sync python -m pytest tests -q
uv run --no-sync envkit build >/dev/null   # quick scenarios only; seconds
uv run --no-sync envkit check
