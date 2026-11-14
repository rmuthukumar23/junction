#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
# Provider keys (e.g. GEMINI_API_KEY) may live in a git-ignored .env at the repo root.
# Variables already set in the shell win. Values are never printed.
if [[ -f .env ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
    name="${BASH_REMATCH[2]}" value="${BASH_REMATCH[3]}"
    [[ -n "${!name:-}" ]] && continue
    value="${value%$'\r'}"
    if [[ "$value" =~ ^\"(.*)\"$ || "$value" =~ ^\'(.*)\'$ ]]; then value="${BASH_REMATCH[1]}"; fi
    export "$name=$value"
  done < .env
fi
export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"
# ENVKIT_SCENARIO selects the scenario: shift-planner (default) or root-cause.
exec uv run --locked --extra eval --extra mcp --extra harbor python -m envkit.cli eval --scenario "${ENVKIT_SCENARIO:-shift-planner}" "$@"
