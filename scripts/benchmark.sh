#!/usr/bin/env bash
# Benchmark a model on the greenhouse in one command: one run, then its score against
# the reference and the scripted players, the gap, and where the money went.
#
#   bash scripts/benchmark.sh                      # dev-winter (14 days): a fast check that a model plays; not a skill score
#   bash scripts/benchmark.sh --runs 3             # three runs in parallel (the judges' protocol)
#   bash scripts/benchmark.sh --full               # normal-winter (42 days): the benchmark itself
#   bash scripts/benchmark.sh --backend docker     # local containers instead of Modal
#
# The model and key come from .env (AFTERQUERY_MODEL, GEMINI_API_KEY); the first run
# creates .env from the template. Writes artifacts/benchmark-<time>/benchmark.md.
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

scenario="dev-winter"
args=()
backend_given=0
for a in "$@"; do
  case "$a" in
    --full) scenario="normal-winter" ;;
    --backend) backend_given=1; args+=("$a") ;;
    *) args+=("$a") ;;
  esac
done
if [[ $backend_given -eq 0 ]]; then
  if [[ -f "$HOME/.modal.toml" || -n "${MODAL_TOKEN_ID:-}" ]]; then
    args+=(--backend modal)
  elif ! { docker info > /dev/null 2>&1 || podman info > /dev/null 2>&1; }; then
    echo "No Modal login and no Docker/Podman running. Run 'uv run --no-sync modal setup' or start Docker."
    exit 1
  fi
fi
[[ " ${args[*]-} " == *" --runs "* ]] || args+=(--runs 1)
[[ " ${args[*]-} " == *" --seeds "* ]] || args+=(--seeds 1)

out="artifacts/benchmark-$(date +%Y%m%d-%H%M%S)"
echo "Benchmarking on $scenario; results in $out"
[[ "$scenario" == "dev-winter" ]] && echo "Note: under the 10-day seed lead time almost nothing new can be sown in 14 days, so dev-winter checks that a model plays; use --full (normal-winter) for a score."
status=0
ENVKIT_SCENARIO="$scenario" bash scripts/judge.sh --agent-only --output "$out" "${args[@]}" || status=$?
if [[ -f "$out/results.json" ]]; then
  uv run --no-sync python scripts/benchmark_report.py "$out"
fi
exit "$status"
