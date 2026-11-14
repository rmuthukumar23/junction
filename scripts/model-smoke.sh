#!/usr/bin/env bash
# One model attempt on the 1-day smoke task (scenarios/smoke.toml), then the report.
# Checks the agent chain (Harbor, MCP tools, model, replay, verifier), not skill.
#
#   bash scripts/model-smoke.sh                    # model and key from .env
#   bash scripts/model-smoke.sh --backend modal    # any other judge.sh option
#
# Benchmark runs use scripts/judge.sh on normal-winter, and only when explicitly asked.
#
# Skips the scripted Harbor runs (their scores are fixed in calibration.json; run
# `bash scripts/judge.sh --output DIR` once to confirm the containers reproduce them).
# Writes artifacts/model-smoke-<time>/ and prints the trial report.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env. Open it, paste your key after GEMINI_API_KEY=, save, and run this again."
  exit 1
fi
if ! grep -Eq '^[[:space:]]*GEMINI_API_KEY=.+' .env && [[ -z "${GEMINI_API_KEY:-}" ]]; then
  echo "GEMINI_API_KEY is empty in .env. Paste your key after GEMINI_API_KEY= and run this again."
  exit 1
fi
command -v uv > /dev/null || { echo "uv is not installed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
if ! { docker info > /dev/null 2>&1 || podman info > /dev/null 2>&1; }; then
  echo "Neither Docker nor Podman is running. Start one (or pass --backend modal after 'modal setup')."
  [[ " $* " == *" modal"* ]] || exit 1
fi
out="artifacts/model-smoke-$(date +%Y%m%d-%H%M%S)"
export ENVKIT_SCENARIO="${ENVKIT_SCENARIO:-smoke}"
runs=(--runs 1)
[[ " $* " == *" --runs "* ]] && runs=()
status=0
bash scripts/judge.sh --agent-only ${runs[@]+"${runs[@]}"} --output "$out" "$@" || status=$?
if compgen -G "$out/trials/*/*/result.json" > /dev/null; then
  uv run --no-sync envkit report "$out"
fi
exit "$status"
