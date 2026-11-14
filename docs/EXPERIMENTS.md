# Experiment evidence

## Local implementation check · 2026-11-14

Measured code: `ede974d5389090a3c65b3ae1fc57cb28a029ad7b`, clean working tree.
[Machine-readable compact evidence](local-evidence.json). Python 3.12.4, OR-Tools
9.15.6755, local runner v1, generator shift-v1; no model or model credentials.

```bash
uv sync --locked --extra eval --extra mcp --extra harbor
uv run --no-sync bash scripts/check.sh
uv run --no-sync shift-planner --verify-count 100 --output artifacts/reference-committed
uv run --no-sync shift-planner --output artifacts/development-committed
```

- 25 tests passed, including a real MCP stdio → bridge → trusted HTTP service episode.
- Reference seeds 0–99: **100/100 at reward 1.0**, at most **16/64 actions**.
- Reference batch: 2.048 seconds on this workstation, including solver import. This
  is a local observation, not a cloud-throughput or portable speed claim.
- Independent verifier checked replay, resources, prerequisites and completion credit.
- Held-out seeds **100–102 have not been evaluated**.

| Development seed | CP-SAT reference | Do nothing | Stop early | Earliest deadline heuristic |
|---|---:|---:|---:|---:|
| 0 | 1.0 | 0.0 | 0.0 | 1.0 |
| 1 | 1.0 | 0.0 | 0.0 | 1.0 |
| 2 | 1.0 | 0.0 | 0.0 | 1.0 |
| 3 | 1.0 | 0.0 | 0.0 | 1.0 |
| 4 | 1.0 | 0.0 | 0.0 | 1.0 |

**Difficulty risk:** a simple heuristic matches the reference on all development
seeds. These results prove basic solvability and baseline scoring, not meaningful
frontier difficulty. The first official frontier pilot is the highest-priority
next experiment. Preserve access to planning code/optimization tools; calibrate
job count only after measuring performance, then freeze before held-out runs.

## Integrity evidence

Tests cover exact/late deadlines, technician/equipment conflicts, dependencies,
duplicate starts, malformed types and IDs, backwards time, action exhaustion,
post-termination actions, every early-stop prefix in a representative trajectory,
mutable observations/actions, forged trace/reward rejection, parallel independent
episodes, service file isolation, timeout credit and infrastructure-error labels.

The construction witness is feasible across 60 tested 8/10/12-job instances; the
CP-SAT policy separately executes 15 development instances across these sizes.
The 100-run claim above is eight jobs. No construction witness is read by CP-SAT.

## Harness and frontier status

- Harbor 0.26 task schema validates against the installed package.
- Local MCP transport tested with MCP SDK 2.3.0.
- GitHub CI includes an actual Docker reference smoke; inspect its run result before claiming container execution.
- This workstation has no Docker, Modal configuration or frontier credentials.
- **No official frontier evaluation, repeated gap, cloud timing, local/cloud equality
  or frontier failure analysis has been recorded.** No sponsor runtime claim is made.

## Required final evidence

Freeze scenario/version/limits after development pilots. Run three attempts on each
of seeds 100–102 under the event-approved model budget. Retain every attempt,
including rate limits, with code SHA, instance/hash, seed, model, harness and agent
version, limits, score, duration and full trace. Never count infrastructure failures
as evidence of agent weakness. Report per-instance variability and analyze actual
start/advance choices, blocked resources, lost prerequisite opportunities and
missed deadlines. If there is no repeated reference advantage, mark the benchmark
incomplete. Do not replace missing frontier evidence with the heuristic results.
