# AfterQuery MVP: Shift Planner

A reproducible workshop scheduling environment for Junction 2026: eight jobs,
two technicians, two shared equipment types, prerequisites, deadlines and values.
All information is public. The agent chooses concurrent starts and advances
virtual time. Reward measures only genuinely completed, on-time work.

**Implemented:** deterministic core, public-data CP-SAT reference, independent
verifier, MCP bridge, isolated Harbor task builder, local reports and judge wrapper.
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

## Candidate judge command

With Docker running, the event-approved model ID and its credentials available:

```bash
bash scripts/judge.sh --model "$AFTERQUERY_MODEL" --output artifacts/judge
```

This runs one reference, **three OpenCode frontier attempts**, one do-nothing
baseline and one stop-early baseline on seed 0. It uses Harbor **0.26.0**,
OpenCode **1.19.5**, MCP **2.3.0**, and the committed dependency lock. It expects
`OPENAI_API_KEY`; use `--credential-env NAME` for another provider's environment
variable. Set secrets in your shell, never in a command argument or repository.
Verify the event's model/provider settings with its mentors before spending credits.

**This is a candidate Harbor integration, not yet an event-certified judge path.**
The supplied Harbor repository does not include the AfterQuery scoring skeleton.
See [harness status and trust boundary](docs/HARNESS.md).

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
pass trusted sidecar collection and separate verification. No custom backend,
Verda training, Entire setup, database or UI is required.

## Repository map

| Path | Purpose |
|---|---|
| `src/junction_env/scheduling/` | Public types, deterministic generator/core, reference, verifier |
| `src/junction_env/runner.py` | Detached traces and interruption/error accounting |
| `src/junction_env/evaluation.py` | Credential-free reports and reference validation |
| `src/junction_env/adapters/` | Trusted HTTP service, MCP bridge, Harbor tasks/judge/results |
| `harness/requirements.txt` | Hashed agent-image dependencies exported from `uv.lock` |
| `tests/` | Resource rules, early stops, replay, tampering, transport and configuration tests |
| `docs/SCENARIO.md` | Exact public contract and calibration rules |
| `docs/HARNESS.md` | Runtime requirements, isolation, official compatibility gates |
| `docs/EXPERIMENTS.md` | Observed evidence and remaining evaluation work |
| `docs/WORKFLOW.md` | Flexible task claims and integration workflow |

## Submission gate

1. Confirm the event kit's exact interface and scoring skeleton; run its unchanged example.
2. Run the Docker reference smoke, then the first official frontier pilot on development seeds 0–4.
3. Calibrate eight → ten → twelve jobs only if needed (`--jobs`); preserve fair access to code/solvers.
4. Freeze the generator, contract, code and limits before opening held-out seeds 100–102.
5. Run three frontier attempts per held-out instance; retain failures and rate limits separately.
6. Show a repeated reference advantage and explain actual decisions. If absent, report the benchmark incomplete.
7. Rehearse the candidate judge command against the event kit from a fresh clone and conduct 15 minutes of exploit testing.

Any of the four teammates, including the coordinator, can claim any package.
Use separate worktrees, temporary file claims, small PRs and rotating integration.
[Stack](docs/STACK.md) · [decisions](docs/DECISIONS.md) · [sponsors](docs/SPONSORS.md)
