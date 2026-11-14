#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"
# Credentials and the model id come from `.env` (ignored by git; template: .env.example).
# Variables already set in the shell take precedence.
if [[ -f .env ]]; then
  while IFS='=' read -r key value; do
    [[ -z "$key" || "$key" == \#* ]] && continue
    key="${key//[[:space:]]/}"
    if [[ -n "$value" && -z "${!key:-}" ]]; then export "$key=$value"; fi
  done < .env
fi
model_args=()
if [[ -n "${AFTERQUERY_MODEL:-}" && " $* " != *" --model "* ]]; then
  model_args=(--model "$AFTERQUERY_MODEL")
fi
# ENVKIT_SCENARIO selects the scenario (default: root-cause).
exec uv run --locked --extra eval --extra mcp --extra harbor python -m envkit.cli eval \
  --scenario "${ENVKIT_SCENARIO:-root-cause}" ${model_args[@]+"${model_args[@]}"} "$@"
