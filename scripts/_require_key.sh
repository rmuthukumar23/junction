#!/usr/bin/env bash
# Sourced by benchmark.sh and model-smoke.sh: fail early if the key for the chosen model's
# provider is missing. The model is --model in the arguments, else AFTERQUERY_MODEL (shell or .env).
# Usage: require_provider_key "$@"
require_provider_key() {
  local model="" prev="" a
  for a in "$@"; do
    [[ "$prev" == "--model" ]] && model="$a"
    prev="$a"
  done
  if [[ -z "$model" ]]; then
    model="${AFTERQUERY_MODEL:-}"
    if [[ -z "$model" && -f .env ]]; then
      model="$(sed -n -E "s/^[[:space:]]*AFTERQUERY_MODEL=[\"']?([^\"'#[:space:]]*).*/\1/p" .env | tail -1)"
    fi
  fi
  local var
  case "${model%%/*}" in
    google|gemini) var=GEMINI_API_KEY ;;
    anthropic)     var=ANTHROPIC_API_KEY ;;
    openai)        var=OPENAI_API_KEY ;;
    *) return 0 ;;   # unknown provider: envkit eval reports a missing credential itself
  esac
  if [[ -z "${!var:-}" ]] && ! grep -Eq "^[[:space:]]*(export[[:space:]]+)?${var}=[^[:space:]]+" .env 2>/dev/null; then
    echo "$var is empty. The model '${model:-?}' needs it: put it in .env after $var= (or export it) and run this again."
    return 1
  fi
}
