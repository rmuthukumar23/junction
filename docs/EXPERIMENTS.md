# Experiment evidence

## Backend merge check · 2026-11-14

Measured code: `b5bdf44033127d2bf7696cda3120da35cde07f9f`, clean working tree,
fresh clone. Python 3.12.16, OR-Tools 9.15.6755, MCP SDK 2.3.0, Harbor 0.26.0,
uv 0.13.8 for the locked install, Podman 5.8.9 with podman-compose 1.6.0.
No model or model credentials.

```bash
bash scripts/check.sh                                   # Python 3.12, no packages
uv sync --locked --extra eval --extra mcp --extra harbor
uv run --no-sync bash scripts/check.sh
uv run --no-sync python -m junction_env.evaluation --verify-count 100 --output artifacts/reference-100
bash scripts/judge.sh --output artifacts/judge          # no --model: scripted runs only
```

- Without packages: 33 tests, 3 skipped, toy example passed.
- Locked environment: 33 unittest tests and 59 backend pytest tests passed;
  committed `tasks/` and `calibration.json` matched the source; reward audit
  passed for `shift-planner` seed 0 and `depot-basic` seed 7.
- Reference seeds 0–99 on the local runner: **100/100 at reward 1.0**, at most
  **16/64 actions**, 1.928 seconds on this workstation.
- Backend scores equal the local runner for the earliest-deadline and
  stop-early policies on seeds 0–4 at 8, 10 and 12 jobs (test).
- Harbor on Podman, Shift Planner seed 0, through the `envkit` sidecar and
  separate verifier:

| Run | Harbor agent | Reward | Calls | Trial seconds | Status |
|---|---|---:|---:|---:|---|
| reference | oracle | 1.0 | 15 (14 actions + one free observe) | 93.8 | completed |
| do-nothing | nop | 0.0 | 0 | 82.3 | interrupted |
| stop-early | oracle, `ENVKIT_POLICY=stop-early` | 0.0 | 3 | 75.6 | completed |

  Each run reproduced its calibrated score; sidecar trace collection and
  replay verification completed for all three. Batch 274.0 seconds.
- Before commit, on the same code with a dirty tree: `judge.sh --smoke` passed,
  and `depot-basic` seed 7 scored reference 0.8451, do-nothing 0.0, stop-early 0.2042.

**Not run on this path:** Docker (this workstation has Podman only), GitHub CI,
OpenCode with any model, Modal, seeds other than 0 through Harbor, held-out
seeds. The difficulty risk below is unchanged: the earliest-deadline heuristic
still matches the reference on development seeds.

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
- The Docker and CI results in this list were measured on the previous adapter (HTTP service and stdio bridge), before the backend merge.
- **Docker reference smoke passed** in [CI run 43537261501](https://github.com/rmuthukumar23/junction/actions/runs/43537261501): seed 0, reward 1.0, 14 actions; separate verification and trusted sidecar collection both completed.
- CI tested PR merge SHA `a85d0fafc2a59b88c29507e62413e212404c3edd` for source head `b69719510066ba5ce327bfc1a98676911ab47415`. Docker trial 73.143 s; entire Harbor invocation 80.705 s including setup. This is not a Modal timing.
- Downloaded the CI sidecar artifact and independently replayed it locally: 1.0, matching instance `eb85920cd8fffb6e504179970b350967d48f966b40f91ec9c19aec848a3e94f2`.
- Earlier CI runs [43536868023](https://github.com/rmuthukumar23/junction/actions/runs/43536868023) and [43536872234](https://github.com/rmuthukumar23/junction/actions/runs/43536872234) failed trusted artifact collection with `RewardFileNotFoundError`. The sidecar record on tmpfs could not be retrieved by Docker's copy path. Moving it to the sidecar's private filesystem fixed collection. Both failures were reported as infrastructure failures with no agent score; no failed attempt is omitted from this handoff.
- This workstation had no Docker, Modal configuration or frontier credentials when the CI results above were taken.

## Modal and Gemini development pilot (2026-11-14, Windows 11, seed 0 only)

Harbor 0.26.0, OpenCode 1.19.5, local checkout of `main` after 4aff1fa plus the changes in
this PR. Commands and tables are in [MODAL.md](MODAL.md).

- Scripted reference/do-nothing/stop-early passed on Modal (`--env modal`, Compose sidecar,
  separate verification): 1.0, 0.0, 0.0, 389 s sequentially.
- `google/gemini-4-hydrogen`, 3 concurrent attempts: Modal 1.0, 1.0, 1.0 in 223 s; local
  Docker 1.0 plus two `AgentSetupTimeoutError` infrastructure failures (not agent failures) in 486 s.
- `google/gemini-3.1-flash-lite`, 3 concurrent attempts, Modal: 1.0, 1.0, 1.0 in 220 s.
- `gemini-2.5-flash-lite` was rejected by the API (not available to new users); those
  zeros are excluded.
- Seed 0 does not separate models, so **no performance gap has been shown**. Held-out seeds
  100-102 were not run; the official kit and frontier models were not used.
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
