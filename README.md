# Junction AfterQuery environments: Root Cause and Shift Planner

Two reproducible environments for Junction 2026's AfterQuery "Break the Agent"
challenge, served and graded by one backend (`src/envkit`): an MCP server in a
trusted sidecar, a verifier that replays the sidecar's action trace in a
separate container, and a Harbor task generator.

- **[Root Cause](#root-cause)**: a greenhouse operations simulator that a person
  plays in the browser and an agent plays through MCP tools. Built 2026-11-14.
- **[Shift Planner](#shift-planner)**: a workshop scheduling environment.

# Root Cause

Four tomato zones, fourteen days, limited fresh water. Each zone's solution
holds useful nutrients and unwanted salts as separate quantities, and the EC
sensor reports only their sum. Fertilizer fixes a shortage but raises EC;
flushing removes salt but also nutrients and scarce water; heat raises water
demand; damage to the crop shows the next day and heals slowly. The goal is
net profit at the end of the last day.

**A transparent, simplified research simulator. It is not a validated
agronomic model and predicts nothing about a real farm.**
Model, rules and scoring: [docs/GREENHOUSE.md](docs/GREENHOUSE.md).

**Status.** Engine, browser app, four comparator policies, suite evaluation,
what-if analysis and the Harbor task are implemented and were run (results
below). **No model has played it**: no provider credential was available, so
there is no agent result and no measured human/agent gap yet.

## Play it

Needs Python 3.12 or newer. No packages, no build step, no credentials.

```bash
bash scripts/play.sh            # then open http://127.0.0.1:8765/
```

Options: `--port`, `--host`, `--data DIR` (default `artifacts/rootcause`; runs
are stored there and survive a restart).

### Two-minute judge demo

1. **Start screen (20 s).** Read the two bars under "What EC tells you": same
   EC, opposite problems. Keep "Demo scenario (seed 7)" and press *Start the season*.
2. **Day 0 (40 s).** Zones B and C show almost the same EC (3.46 and 3.29).
   Nothing on screen says which one is starving. Press *Order test* on B and C:
   €25 each appears in "Costs so far" at once, and the results are due tomorrow.
   Type 9999 into an irrigation box: the plan summary says why it cannot be
   applied and the Advance button is disabled. Press *Default plan*, then
   *Apply plan and advance to day 1*.
3. **Day 1 (30 s).** The lab results have arrived, stamped "sampled day 0": B is
   rich in nutrients, C is short of them and salty. Give C fertilizer and a
   flush, stop feeding B, and watch the summary show the water and cost before
   committing. Open *History and charts* on a zone; note that the day did not move.
4. **Finish (15 s).** Press *Stop deciding…* and confirm. The remaining days
   run on the default plan: stopping does not freeze the result.
5. **End screen (15 s).** Net profit, the itemized calculation, the reward, and
   the same scenario played by the do-nothing, stop-early, rule-based and
   reference policies. The "AI agent" row says *not run* and gives the command.
   *What each zone really was* reveals the hidden split. *Replay day by day*
   steps through observations, actions and outcomes.

A full season, played properly, takes about 5 to 8 minutes.

## Setup for tests, evaluation and Harbor

```bash
bash scripts/check.sh                                         # plain Python: unit tests, no packages
uv sync --locked --extra eval --extra mcp --extra harbor      # the locked environment (uv 0.13.8)
uv run --no-sync bash scripts/check.sh                        # adds backend tests, task freshness, reward audit
```

Environment variables, by name:

| Variable | Needed for |
|---|---|
| A provider credential, e.g. `GEMINI_API_KEY`, `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` | Model runs through Harbor. `GEMINI_API_KEY` is the default for `google/...` models, else `OPENAI_API_KEY`; name another with `--credential-env`. Put it in a git-ignored `.env` (see `.env.example`), which `scripts/judge.sh` reads; never put its value in a command |
| `ENVKIT_SCENARIO=root-cause` | Selecting this scenario in `scripts/judge.sh` |
| `CHROME` | Optional: path to Chrome for the browser smoke test |
| `TSC` | Optional: path to a TypeScript compiler for the JavaScript type check |

## Commands

```bash
# Tests
bash scripts/check.sh                                          # all unit tests (Root Cause: tests/test_rootcause_*.py)
uv run --no-sync python scripts/browser_smoke.py               # a full season in headless Chrome
bash scripts/check_frontend.sh                                 # JavaScript syntax; types if a compiler is present

# Reference and baselines, in-process
uv run --no-sync envkit anchors root-cause                     # every comparator on seed 7
uv run --no-sync envkit run root-cause --policy reference --seed 101 --trace artifacts/rootcause/ref-101.jsonl
uv run --no-sync envkit replay root-cause artifacts/rootcause/ref-101.jsonl
uv run --no-sync envkit audit root-cause                       # degenerate strategies must not score

# Suite evaluation (writes traces under artifacts/, compact evidence under docs/)
PYTHONPATH=src python3 -m rootcause_app.evaluate --suite all --evidence docs/root-cause-evidence.json

# Harbor (needs a running Docker or Podman daemon)
harbor run -p tasks/root-cause-s7 -a oracle                                  # reference
harbor run -p tasks/root-cause-s7 -a opencode -m <provider/model>            # agent
harbor run -p tasks/root-cause-s7 -a nop                                     # do-nothing
harbor run -p tasks/root-cause-s7 -a oracle --ae ENVKIT_POLICY=stop-early    # stop-early
ENVKIT_SCENARIO=root-cause bash scripts/judge.sh --output artifacts/rootcause/judge                       # the three scripted runs
ENVKIT_SCENARIO=root-cause bash scripts/judge.sh --model <provider/model> --credential-env ANTHROPIC_API_KEY --output artifacts/rootcause/judge-model
```

### A model run with a Gemini key

```bash
cp .env.example .env            # then set GEMINI_API_KEY=... in .env (git-ignored)
ENVKIT_SCENARIO=root-cause bash scripts/judge.sh --model google/gemini-3.1-flash-lite \
    --runs 1 --seeds 7 --output artifacts/rootcause/gemini-test-1
```

This runs the reference, one OpenCode attempt with the model, do-nothing and
stop-early on seed 7, and stops at the first problem; the reference goes first,
so a broken container setup fails before any tokens are spent. `envkit eval`
hands the key to OpenCode as `GOOGLE_GENERATIVE_AI_API_KEY` (the only name
OpenCode's Google provider reads) through a template Harbor expands, so the
value is not on any command line or in the logs. Use `--runs 3` for the judging
protocol, `--backend podman|docker|modal` to choose where containers run, and
a new `--output` directory each time. The agent's score is in
`<output>/report.md`, its transcript under `<output>/trials/`. A provider error
(bad key, unknown model, quota) makes OpenCode stop without playing, which
scores 0.0 like doing nothing and may still be labelled `completed`; a zero
with 0 `calls` in the report is a provider problem until the trial's agent log
says otherwise. To list the models your key can use:
`curl -s -H "x-goog-api-key: $GEMINI_API_KEY" https://generativelanguage.googleapis.com/v1beta/models | grep '"name"'`.

After changing anything under `src/rootcause/`, `src/envkit/` or
`scenarios/root-cause.toml`, run `uv run --no-sync envkit build root-cause` and
keep the regenerated `tasks/root-cause-s7/` and `calibration.json`.

The Harbor task is `tasks/root-cause-s7`: `instruction.md`, `task.toml`,
`environment/` (agent image plus the `sim` sidecar), `tests/` (the verifier,
which writes `/logs/verifier/reward.txt`) and `solution/` (the reference,
played through MCP). `task.toml` declares the MCP server `greenhouse` at
`http://sim:8000/mcp`; Harbor 0.26.0's OpenCode agent writes that into
OpenCode's config as a remote MCP server (checked in the installed source,
`harbor/agents/installed/opencode.py`).

## Scoring

- **Raw:** `profit = €2.00 × harvest kg − water − fertilizer − discharge − tests`,
  taken at the end of day 13 whatever the player did.
- **Reward:** `clamp((profit − floor) / (ceiling − floor), 0, 1)`. Floor is the
  profit of the default plan on the same instance, so doing nothing scores 0.
  Ceiling is a proven upper bound on profit for the instance that no plan
  reaches. Both are fixed by the instance, not by any player.
- Stopping early, `finish_episode`, a closed browser or a dead agent all run
  the default plan for the remaining days. Tests stay charged. Nothing is
  rewarded except profit, and no model grades anything.

## Scenarios and actual results

A seed fixes everything exogenous: each zone's growth potential, water demand,
starting volume and condition, its hidden starting split of nutrients and
salts, the weather and every forecast, and the season's water allocation.

| Suite | Seeds | Use |
|---|---|---|
| Demo | 7 | The committed Harbor task and the judge demo |
| Development | 1–6 | Reported tuning suite. Seeds 1–12 were looked at while tuning the mechanics |
| Evaluation | 101–108 | First run after the mechanics were fixed; not used for tuning |

Mean reward (and mean net profit) from real runs of each comparator,
`python -m rootcause_app.evaluate --suite all`, 2026-11-14:

| Policy | Demo (7) | Development (1–6) | Evaluation (101–108) |
|---|---:|---:|---:|
| Do nothing (default plan) | 0.000 (€1,608) | 0.000 (€1,563) | 0.000 (€1,478) |
| Stop early (reference for 4 days) | 0.090 (€1,696) | 0.149 (€1,747) | 0.169 (€1,708) |
| Rule-based (EC rules, no tests) | 0.035 (€1,643) | 0.213 (€1,816) | 0.214 (€1,755) |
| Reference planner | 0.666 (€2,261) | 0.735 (€2,437) | 0.748 (€2,464) |
| **Model through OpenCode** | **pending** | – | – |

Every row and trace is in [docs/root-cause-evidence.json](docs/root-cause-evidence.json).
No run raised an internal error and every run's water, nutrient and salt
balances closed.

- **Stopping early earns little.** The crop needs more nutrient per kg every
  day (a published schedule), so a plan that is right on day 1 starves the
  crop by week two. Playing the reference for four days and then leaving the
  default plan to run keeps only about a fifth of the reference's gain.
- **Reading EC as a nutrient gauge fails.** The rule-based policy never tests
  and scores 0.00–0.44 on the evaluation seeds; on seed 106 it earns less than
  doing nothing.
- **Healthy management is achievable.** The reference scores 0.68–0.79 on every
  evaluation seed. It is a strong comparator, not a proven optimum; see
  [docs/GREENHOUSE.md](docs/GREENHOUSE.md).

## Limitations and open blockers

- **No model run.** There is no agent trace, so nothing can be said about
  whether or how a model mismanages this task. The hypotheses (coupled water
  limits, timing, delayed feedback, state estimation, the value of testing)
  are untested. Prerequisite: a provider credential and model id; then
  `ENVKIT_SCENARIO=root-cause bash scripts/judge.sh --model <provider/model> --credential-env <NAME> --output <new dir>`.
- **OpenCode has not connected to this MCP server.** Harbor's config
  generation was read in the installed source, and the scripted policies play
  over the same MCP endpoint through Harbor, but OpenCode itself is untested.
- **The trust boundary was probed by a script, not attacked by a model.**
  `bash scripts/harbor_boundary_probe.sh` runs a hostile shell script in the
  agent's container through Harbor: it found no task data, its forged reward
  file and trace were ignored, and it scored 0. That covers the attacks it
  tries, on local Docker only.
- **Event-kit compatibility is unverified**, as for Shift Planner.
- **JavaScript type check not run.** No TypeScript compiler is installed here;
  the modules were syntax-checked and exercised in Chrome. Run
  `bash scripts/check_frontend.sh --fetch` to type-check.
- **Difficulty is unknown.** A careful agent with code tools can implement the
  published formulas and plan; it may match or beat the reference. If it
  does, that is the result to report.
- Model simplifications, and the fact that repeated testing has little value
  in this version, are listed in [docs/GREENHOUSE.md](docs/GREENHOUSE.md).
- The browser server binds to this machine only and has no accounts; whoever
  can write to its data directory can change which actions a run replays
  (never a score directly). It is a demo server, not the trusted grader.

# Shift Planner

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

## Quick start (Shift Planner and shared setup)

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
sidecar; on 2026-11-14 the scripted runs and three concurrent OpenCode + Gemini
attempts passed on Modal (see [docs/MODAL.md](docs/MODAL.md)). That is not the official
event kit. No Verda training, Entire setup, database or UI is required.

## Repository map

| Path | Purpose |
|---|---|
| `src/junction_env/scheduling/` | Public types, deterministic generator/core, reference, verifier, and the binding that serves Shift Planner through the backend |
| `src/junction_env/runner.py` | Detached traces and interruption/error accounting |
| `src/junction_env/evaluation.py` | Credential-free reports and reference validation |
| `src/envkit/` | Evaluation backend: episode engine, MCP server, trace-replay verifier, Harbor task generator, audit, judge and reports |
| `src/envs/depot/` | Example environment for the backend features Shift Planner does not use |
| `src/rootcause/` | Root Cause engine, tools and comparator policies (goes into its Harbor bundle) |
| `src/rootcause_app/` | Root Cause browser app, comparator runs, what-if analysis, suite evaluation |
| `scenarios/` | One TOML file per task: prompt, limits, scoring |
| `tasks/` | Generated Harbor tasks, committed; do not edit by hand |
| `calibration.json` | Committed scores of every scripted policy per scenario and seed |
| `harness/requirements.txt` | Hashed agent- and sidecar-image dependencies exported from `uv.lock` |
| `tests/` | Resource rules, early stops, replay, tampering, transport and configuration tests |
| `tests/envkit/` | Backend tests (pytest, locked environment) |
| `docs/BACKEND.md` | How the backend works, its commands, and how to add an environment |
| `docs/SCENARIO.md` | Exact public contract and calibration rules |
| `docs/HARNESS.md` | Runtime requirements, isolation, official compatibility gates |
| `docs/MODAL.md` | Modal setup for teammates, verification scripts, measured results |
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
