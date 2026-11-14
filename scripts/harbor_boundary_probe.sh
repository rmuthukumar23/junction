#!/usr/bin/env bash
# Probe the Harbor execution boundary of a generated task.
#
# Copies a task from tasks/ (the first one, or TASK=<name>), replaces the oracle's solution with a hostile shell
# script (scripts/boundary_probe_agent.sh) and no task bundle, runs it through Harbor
# in the agent's container, and prints what it could see and reach. The run passes
# only if the separate verifier still awards exactly 0: the score of playing nothing.
#
#   bash scripts/harbor_boundary_probe.sh [OUTPUT_DIR]        (needs Docker and the locked environment)
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
out="${1:-artifacts/boundary-probe}"
task="${TASK:-$(ls tasks | head -1)}"
[[ -n "$task" && -d "tasks/$task" ]] || { echo "no generated task in tasks/; run envkit build" >&2; exit 2; }
if [[ -e "$out" ]]; then echo "$out already exists; choose a new directory" >&2; exit 2; fi
harbor="$(command -v harbor || echo "$repo_root/.venv/bin/harbor")"

mkdir -p "$out"
cp -R "tasks/$task" "$out/task"
rm -rf "$out/task/solution/bundle"                 # an agent is never given the scenario, seed or engine
cp scripts/boundary_probe_agent.sh "$out/task/solution/solve.sh"
chmod +x "$out/task/solution/solve.sh"

"$harbor" run --path "$out/task" --env docker --agent oracle --jobs-dir "$out/trials" --job-name probe \
  --max-retries 0 --delete --yes --quiet > "$out/harbor.log" 2>&1 || { tail -30 "$out/harbor.log"; exit 1; }

trial="$(find "$out/trials/probe" -mindepth 1 -maxdepth 1 -type d | head -1)"
echo "---- what the hostile script saw (agent log) ----"
cat "$trial/agent/oracle.txt"
echo "---- verifier ----"
reward="$(cat "$trial/verifier/reward.txt")"
echo "reward: $reward"
python3 - "$trial/verifier/score.json" <<'PY'
import json, sys
s = json.load(open(sys.argv[1]))
print("calls replayed:", s["replay"]["calls"], "notes:", s["notes"])
PY
if [[ "$reward" != "0.0000" ]]; then echo "FAILED: a script that played nothing was awarded $reward" >&2; exit 1; fi
echo "Boundary probe passed: nothing the script wrote or requested changed the score."
