#!/usr/bin/env bash
# The fine-tuned model through the official harness: Harbor + OpenCode on a held-out seed,
# with OpenCode pointed at the vLLM endpoint on Modal.
#
#   bash scripts/finetune/harbor_run.sh 101                 # model "greenhouse" (the LoRA)
#   FT_MODEL=Qwen/Qwen3-4B-Instruct-2507 bash scripts/finetune/harbor_run.sh 101   # the base model
#
# Needs FT_BASE_URL (the Modal URL ending in /v1) and VLLM_API_KEY in .env, and Docker or
# Podman. Builds the task if missing (scripts/finetune/harbor_task.py), runs one attempt, then
# writes <job>/summary.json with the verifier's score.
#
# OpenCode keeps every briefing in its context (about 5k tokens a day), so the server runs
# with a 128k context (scripts/finetune/modal_serve.py); OpenCode compacts beyond that.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
seed="${1:?usage: harbor_run.sh <seed> [extra harbor args]}"
shift || true
if [[ -f .env ]]; then set -a; . ./.env; set +a; fi
: "${FT_BASE_URL:?set FT_BASE_URL in .env (the Modal URL plus /v1)}"
: "${VLLM_API_KEY:?set VLLM_API_KEY in .env (the same value as the Modal secret greenhouse-vllm)}"
model="${FT_MODEL:-greenhouse}"
scenario="${FT_SCENARIO:-normal-winter}"
backend="${FT_BACKEND:-}"
if [[ -z "$backend" ]]; then
  if command -v docker > /dev/null; then backend=docker; elif command -v podman > /dev/null; then backend=podman;
  else echo "Docker or Podman is needed"; exit 1; fi
fi
task="artifacts/finetune/tasks/${scenario}-s${seed}"
if [[ ! -d "$task" ]]; then
  uv run --no-sync python scripts/finetune/harbor_task.py build --scenario "$scenario" --seed "$seed"
fi
safe_model="$(echo "$model" | tr '/:' '--')"
job="s${seed}-${safe_model}-$(date +%H%M%S)"
jobs_dir="artifacts/finetune/harbor"
mkdir -p "$jobs_dir"
# "vllm/<name>": a provider OpenCode does not know, so Harbor writes an
# @ai-sdk/openai-compatible provider with this base URL and key into opencode.json.
cmd=(uv run --no-sync harbor run --path "$task" --env "$backend"
     --n-attempts 1 --n-concurrent 1 --jobs-dir "$jobs_dir" --job-name "$job"
     --max-retries 0 --delete --yes
     --agent opencode --model "vllm/${model}" --agent-kwarg version=1.19.5
     --base-url "$FT_BASE_URL" --api-key-name VLLM_API_KEY --api-format openai_chat_completions
     --ae 'VLLM_API_KEY=${VLLM_API_KEY}' "$@")
echo "== ${cmd[*]}"
set +e
"${cmd[@]}" 2>&1 | tee "$jobs_dir/$job.log"
status=${PIPESTATUS[0]}
set -e
uv run --no-sync python scripts/finetune/harbor_task.py collect --job "$jobs_dir/$job" || true
echo "job folder: $jobs_dir/$job   log: $jobs_dir/$job.log   (harbor exit $status)"
exit "$status"
