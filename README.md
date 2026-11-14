# AfterQuery MVP: Shift Planner

A reproducible workshop scheduling environment for Junction 2026: eight jobs,
two technicians, two shared equipment types, prerequisites, deadlines and values.
All information is public. The agent chooses concurrent starts and advances
virtual time. Reward measures only genuinely completed, on-time work.

**Implemented:** deterministic core, public-data CP-SAT reference, independent
verifier, and the `envkit` evaluation backend: an MCP server in a trusted sidecar,
a verifier that replays the sidecar's action trace, a Harbor task generator,
reward-integrity audit, local reports and judge wrapper.
**Submission gates still open:** event-kit confirmation, frontier runs, repeated
reference advantage, failure analysis and Modal execution. Local baseline success
is not a frontier-agent gap.

## Quick start

Python 3.12 and [uv](https://docs.astral.sh/uv/getting-started/installation/).
The core check has no packages, model keys, containers or cloud prerequisites:

```bash
git clone https://github.com/rmuthukumar23/junction.git
cd junction
bash scripts/check.sh
```

Run all transport/reference tests and produce an inspectable local demo:

```bash
uv sync --locked --extra eval --extra mcp --extra harbor
uv run --no-sync bash scripts/check.sh
uv run --no-sync shift-planner --output artifacts/local-demo
uv run --no-sync shift-planner --verify-count 100 --output artifacts/reference-100
```

Each output directory must be new. Reports include the full public instances,
hashes, solver/version, actions, scores, timelines and code provenance. The local
suite runs reference, do-nothing, stop-early and an earliest-deadline heuristic.
The toy example remains a smoke test only.

In the locked environment `scripts/check.sh` also runs the backend tests, checks
that the committed Harbor tasks match the source, and runs the reward audit.
After changing anything under `src/` or `scenarios/`, regenerate and commit them:

```bash
uv run --no-sync envkit build
```

## Candidate judge command

The submission is the committed Harbor task `tasks/shift-planner-s0`. Judges can
run it directly:

```bash
harbor run -p tasks/shift-planner-s0 -a oracle                                # reference
harbor run -p tasks/shift-planner-s0 -a opencode -m <provider/model> -k 3     # agent
harbor run -p tasks/shift-planner-s0 -a nop                                   # do-nothing
harbor run -p tasks/shift-planner-s0 -a oracle --ae ENVKIT_POLICY=stop-early  # stop-early
```

The wrapper runs the same set from the working tree and checks the results.
With Docker or Podman running, the event-approved model ID and its credentials available:

```bash
bash scripts/judge.sh --model "$AFTERQUERY_MODEL" --output artifacts/judge
```

This runs one reference, **three OpenCode frontier attempts**, one do-nothing
baseline and one stop-early baseline on seed 0. It uses Harbor **0.26.0**,
OpenCode **1.19.5**, MCP **2.3.0**, and the committed dependency lock. It expects
`OPENAI_API_KEY`; use `--credential-env NAME` for another provider's environment
variable. Set secrets in your shell, never in a command argument or repository.
Verify the event's model/provider settings with its mentors before spending credits.
Without `--model`, the three scripted runs execute and need no credentials. Each
scripted run must reproduce the score calibration computed for it, or the command fails.
`--backend` selects `docker`, `podman` or `modal`; the default is Docker if present, else Podman.

**This is a candidate Harbor integration, not yet an event-certified judge path.**
The supplied Harbor repository does not include the AfterQuery scoring skeleton.
No run with OpenCode and a model has been made on this path.
See [harness status and trust boundary](docs/HARNESS.md) and [backend](docs/BACKEND.md).

Credential-free container smoke:

```bash
bash scripts/judge.sh --smoke --output artifacts/docker-smoke
```

Optional Modal (CPU Sandboxes; authenticate with `modal setup` first):

```bash
bash scripts/judge.sh --backend modal --smoke --output artifacts/modal-smoke
bash scripts/judge.sh --backend modal --model "$AFTERQUERY_MODEL" --output artifacts/modal-pilot
```

Use one smoke trial before three concurrent frontier attempts. Docker/Modal must
pass trusted sidecar collection and separate verification. The task uses a Compose
sidecar, which Harbor documents as unsupported on its cloud sandboxes, so treat
Modal as unverified. No Verda training, Entire setup, database or UI is required.

## Repository map

| Path | Purpose |
|---|---|
| `src/junction_env/scheduling/` | Public types, deterministic generator/core, reference, verifier, and the binding that serves Shift Planner through the backend |
| `src/junction_env/runner.py` | Detached traces and interruption/error accounting |
| `src/junction_env/evaluation.py` | Credential-free reports and reference validation |
| `src/envkit/` | Evaluation backend: episode engine, MCP server, trace-replay verifier, Harbor task generator, audit, judge and reports |
| `src/envs/depot/` | Example environment for the backend features Shift Planner does not use |
| `scenarios/` | One TOML file per task: prompt, limits, scoring |
| `tasks/` | Generated Harbor tasks, committed; do not edit by hand |
| `calibration.json` | Committed scores of every scripted policy per scenario and seed |
| `harness/requirements.txt` | Hashed agent- and sidecar-image dependencies exported from `uv.lock` |
| `tests/` | Resource rules, early stops, replay, tampering, transport and configuration tests |
| `tests/envkit/` | Backend tests (pytest, locked environment) |
| `docs/BACKEND.md` | How the backend works, its commands, and how to add an environment |
| `docs/SCENARIO.md` | Exact public contract and calibration rules |
| `docs/HARNESS.md` | Runtime requirements, isolation, official compatibility gates |
| `docs/EXPERIMENTS.md` | Observed evidence and remaining evaluation work |
| `docs/WORKFLOW.md` | Flexible task claims and integration workflow |

## Submission gate

1. Confirm the event kit's exact interface and scoring skeleton; run its unchanged example.
2. Run the Docker reference smoke, then the first official frontier pilot on development seeds 0–4.
3. Calibrate eight → ten → twelve jobs only if needed (copy `scenarios/shift-planner.toml` under a new id and change `jobs`); preserve fair access to code/solvers.
4. Freeze the generator, contract, code and limits before opening held-out seeds 100–102.
5. Run three frontier attempts per held-out instance; retain failures and rate limits separately.
6. Show a repeated reference advantage and explain actual decisions. If absent, report the benchmark incomplete.
7. Rehearse the candidate judge command against the event kit from a fresh clone and conduct 15 minutes of exploit testing.

Any of the four teammates, including the coordinator, can claim any package.
Use separate worktrees, temporary file claims, small PRs and rotating integration.
[Stack](docs/STACK.md) · [decisions](docs/DECISIONS.md) · [sponsors](docs/SPONSORS.md)
