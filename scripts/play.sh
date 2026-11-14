#!/usr/bin/env bash
# Start the Root Cause dashboard. Needs only Python 3.12+: no packages, no build, no credentials.
#   bash scripts/play.sh [--port 8765] [--host 127.0.0.1] [--data artifacts/rootcause]
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m rootcause_app "$@"
