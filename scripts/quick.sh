#!/usr/bin/env bash
# One model attempt on the committed seed, then the explanation. The fastest feedback loop.
#
#   bash scripts/quick.sh                   # model and key from .env
#   bash scripts/quick.sh --runs 3          # three attempts in parallel
#   bash scripts/quick.sh --backend podman  # any other judge.sh option
#
# Skips the scripted Harbor runs (their scores are fixed in calibration.json; run
# `bash scripts/judge.sh --output DIR` once to confirm the containers reproduce them).
# Writes artifacts/quick-<time>/ and prints the trial report.
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
out="artifacts/quick-$(date +%Y%m%d-%H%M%S)"
runs=(--runs 1)
[[ " $* " == *" --runs "* ]] && runs=()
status=0
bash scripts/judge.sh --agent-only ${runs[@]+"${runs[@]}"} --output "$out" "$@" || status=$?
if compgen -G "$out/trials/*/*/result.json" > /dev/null; then
  uv run --no-sync envkit report "$out"
fi
exit "$status"
