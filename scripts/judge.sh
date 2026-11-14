#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"
# ENVKIT_SCENARIO selects the scenario (default: root-cause).
exec uv run --locked --extra eval --extra mcp --extra harbor python -m envkit.cli eval --scenario "${ENVKIT_SCENARIO:-root-cause}" "$@"
