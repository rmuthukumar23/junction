# Root Cause: incident response in a lettuce greenhouse

An AfterQuery "Break the Agent" environment for Junction 2026. An agent runs
three hydroponic lettuce benches for the last six days before harvest. On the
morning of day 1 the water utility switches the site to a backup source. The
notice says only that the source changed. The new water is brackish, and the
sensors show only one symptom: EC rising on every bench.

EC measures nutrients and salt together. A player who reads the rise as
"plenty of nutrients" cuts feeding and starves the crop. A player who ignores
the notice keeps topping up with salty water and burns the crop. A player
who diagnoses the cause, by testing the water or by checking the EC rise
against the published formulas, can switch the benches to a limited, more
expensive clean reserve and keep feeding normally.

**A transparent, simplified research simulator.** It is not a validated
agronomic model. Model and rules: [docs/GREENHOUSE.md](docs/GREENHOUSE.md).

**Status.** The engine, task, reference, comparators, failure analysis,
verifier and tests are implemented and pass (results below). **No model has
played this version yet.** An earlier 14-day tomato version showed no gap:
Gemini 4 Hydrogen beat its weaker reference (0.67) in 4 of 4 seasons
([EXPERIMENTS](docs/EXPERIMENTS.md)). This version was redesigned in response.
It has one diagnosable incident, a reference that scores 0.90, and runs of a
few minutes.

## Run it

You need Python 3.12+, [uv](https://docs.astral.sh/uv/), and Docker or Podman running.

```bash
bash scripts/quick.sh        # first time: creates .env and asks for your key
# open .env, paste the key after GEMINI_API_KEY=, save
bash scripts/quick.sh        # one Gemini attempt on seed 7, then the explanation
```

`quick.sh` runs one model attempt through Harbor and OpenCode, then writes
`artifacts/quick-<time>/analysis.md`. That file gives:
- the reward and whether the run passed;
- the failure modes;
- a day-by-day table of each decision next to the hidden salt and nutrient levels;
- what the agent wrote.

The model is set in `.env`: `AFTERQUERY_MODEL=google/gemini-4-hydrogen` by
default, which has already played this harness. Use `bash scripts/quick.sh --runs 3`
for three attempts in parallel. Any `judge.sh` option passes through, e.g.
`--backend podman`.

**Time.** A season takes about 10 tool calls: `get_rules`, `get_status`, any
tests, then one `advance_day` per day with the plan inline. At the ~18 s per
call measured for Gemini, that is 3–4 minutes. Harbor stops the agent at 7
minutes, and the session allows at most 60 calls; both are safety nets a
normal run does not reach. The first run also builds the container images,
which takes a few minutes once.

**A reward of 0 with 0 calls is a provider problem** (bad key, unknown model,
quota), not an agent result; `analysis.md` says so. To list the models your
key can use:
`curl -s -H "x-goog-api-key: $GEMINI_API_KEY" https://generativelanguage.googleapis.com/v1beta/models | grep '"name"'`.

The full judging protocol also re-runs the scripted comparators in Harbor:
the reference, do-nothing and stop-early must reproduce their calibrated
scores, or the command fails.

```bash
uv sync --locked --extra eval --extra mcp --extra harbor
bash scripts/judge.sh --output artifacts/judge-1        # reference, 3 model attempts, do-nothing, stop-early
PYTHONPATH=src python3 scripts/analyze.py artifacts/judge-1
```

Checks that need no Docker and no key:

```bash
bash scripts/check.sh                          # unit tests (plain Python)
uv run --no-sync bash scripts/check.sh         # + backend tests, task freshness, reward audit
PYTHONPATH=src python3 scripts/compare.py 7    # all comparators with failure modes, in-process
```

## The task

| | |
|---|---|
| Benches | 3 NFT benches of butterhead lettuce (A, B, C), each about 2,000 heads with its own recirculating tank |
| Horizon | 6 days (day 0 normal, the incident from the morning of day 1), one decision per day |
| Daily plan per bench | `mains_l`, `reserve_l` (clean RO water, 4× the price, shared 2,400 L tank, never refilled), `fertilizer_g`, `flush_l` |
| Observations | EC (noisy), volume, crop condition, growth; a day-0 lab report; notices; forecast |
| Hidden | each bench's split of EC into nutrients and salt after day 0; the backup water's salinity (1.2–1.5 g/L, against 0.10 normally) |
| Diagnosis tools | `order_test(bench)` and `order_water_test()`, €15 each, results the next morning; or infer the salt from EC against the published formulas |
| One call per day | `advance_day(bench_plans)` sets and applies the day's plan; a rejected plan moves nothing |
| Objective | profit at the end of day 5: €2.50/kg of head weight added, minus water, fertilizer, discharge and tests |

Everything except the incident's salinity is public: `get_rules` returns every
formula and parameter. The difficulty lies in reading the situation, not in
hidden rules. The notice is given to every player, and the right response
(test, or reason from EC, then protect the benches with clean water while
still feeding) is within reach of a careful agent.

## Reward

```
reward = clamp((profit − floor) / (informed − floor), 0, 1)
```

- **floor**: the profit of the default plan on the same instance, which is
  what happens if nobody acts. Doing nothing scores exactly 0.
- **informed**: the profit of the reference planner when it is told the
  backup salinity at the moment of the notice. **1.0 therefore means "as good
  as a planner that knew the root cause immediately."**
- Both are computed by the verifier from the instance alone, never from
  anything a player did.

Why this shape:
- **Only the outcome counts.** Tests, calls, explanations and diagnosis
  steps earn nothing directly, so there is nothing to spam. A correct
  diagnosis pays off only through the profit it protects.
- **The scale is explainable.** The gap between the reference (which must
  diagnose) and 1.0 is the cost of one day of uncertainty. The gap between
  an agent and the reference is what the agent failed to work out.
- **Pass line: reward ≥ 0.5,** i.e. it recovered at least half of what
  knowing the root cause at once is worth. The reference passes on all 15
  seeds measured; the blind planner and EC rules on none.
- **Stopping never pays.** Every run is scored at the end of day 5, and
  remaining days run on the default plan. A dead agent, `finish_episode`,
  the call limit and a timeout all end the same way.
- **The reward survives tampering.** The verifier replays the sidecar's
  trace in a separate container and never reads a number the trace claims.
  The audit checks that doing nothing, idling, random calls, spamming any
  tool and cutting the reference short all score below the reference.

## Comparators (seed 7, and suite means)

The same engine, in-process (`scripts/compare.py`); the verifier gives the
same numbers.

| Policy | Seed 7 reward | Profit | Dev 1–6 mean | Eval 101–108 mean | How it fails |
|---|---:|---:|---:|---:|---|
| Do nothing (default plan) | 0.000 | €563 | 0.000 | 0.000 | salt builds up; nobody reacts |
| Stop early (reference, then stops) | 0.000 | €460 | 0.000 | 0.000 | stops before the incident is handled |
| EC rules (reads EC as nutrient) | 0.000 | €481 | 0.000 | 0.000 | cuts feeding as EC rises: 9 starved bench-days; flushes with the salty water itself; below doing nothing |
| Blind planner (ignores the notice) | 0.000 | €542 | 0.064 | 0.099 | a good planner that never asks why EC rose: no test, no reserve, salt damage |
| **Reference (diagnoses)** | **0.882** | **€711** | **0.899** | **0.908** (0.82–0.94) | tests the water on the notice day, then uses the reserve and keeps feeding |
| Informed (yardstick, = 1.0) | 1.000 | €731 | | | knows the salinity at once |
| **Gemini via OpenCode** | **pending** | | | | run `judge.sh` |

The development seeds 1–6 were used for tuning; the evaluation seeds 101–108
were first run after the mechanics were fixed. All rows:
[docs/root-cause-evidence.json](docs/root-cause-evidence.json).

## Failure modes

These are computed from hidden state after the run (`rootcause/outcome.py:failure_modes`),
reported in every trial's `score.json` ledger as `fm_*` fields and explained by
`scripts/analyze.py`. They are evidence only and never enter the reward.

| Signal | Meaning |
|---|---|
| `days_to_first_test` | days from the notice to the first test; `null` = never tested |
| `mains_test_day` | when the water itself was tested |
| `fed_less_while_short_bench_days` | bench-days fed below the default while the crop was short of nutrient: the misread-EC signature |
| `salt_stress_bench_days` | bench-days with growth cut by salinity |
| `flushed_after_incident_l` | litres flushed after the switch; each flush refills the tank with the salty water |
| `reserve_used_l` / `reserve_left_l` | how the remedy was used |
| `lost_{salinity,nutrient,water,carried_damage}_eur` | crop value lost by cause; the shares add up exactly |
| `default_plan_days` | days the player let the default plan run |

## The reference solution

Code: `src/rootcause/planner.py`. Every morning it:

1. **Diagnoses.** On the notice day it orders a mains water test. Until the
   result arrives it assumes the water is five times saltier than usual,
   because the rules say a backup source can carry several times the salt.
   When the result arrives, it replays every day since the notice with the
   measured salinity. Without a test result, it fits the salinity that best
   explains the benches' EC readings under the published formulas.
2. **Tracks state.** It keeps each bench's nutrient and salt mass from the
   day-0 lab report, rolled forward with the published daily update.
3. **Plans.** For each bench it searches a grid: flush today × nutrient
   level × volume level × reserve share today × reserve share later. It
   simulates each candidate to the last day and keeps the one with the best
   profit. The shared reserve is allocated by raising an internal price on
   reserve water until the benches' total plans fit the tank.

The **blind** comparator is the same planner without step 1. The **informed**
yardstick is the same planner with the true salinity from the notice on.
Their gap isolates the value of finding the root cause.

## Verification and integrity

```
 main container            sim container (sidecar)         verifier container
 +---------------+   MCP   +-------------------------+     +--------------------+
 | OpenCode agent| ------> | MCP server              |     | replays the trace  |
 | or the oracle | <------ | engine + greenhouse     |     | in a fresh process |
 +---------------+ results | trace.jsonl ------------+---> | writes reward.txt  |
   no task data            +-------------------------+     +--------------------+
```

- The agent's container holds no scenario, seed, engine or scoring code.
- The sidecar appends every call to an append-only trace. The verifier
  replays it with its own copy of the code and checks that water, nutrient
  and salt balances close. A missing trace is an infrastructure failure, not
  a zero.
- Tests cover: forged responses and claimed scores, injected impossible
  actions, reseeded traces, a standard-library-only verifier, every way of
  stopping, the call limit, and no hidden state in any live response.

## Limitations and open items

- **No model run yet.** There is no measured agent result and no
  human/agent gap. Prerequisite: a Gemini key in `.env`.
- **Harbor was not run on this branch.** The workspace it was built in cannot
  pull Docker images. In-process runs, the verifier bundle and the generated
  task are tested; the earlier version of this task passed scripted Harbor
  runs on Docker. Run `bash scripts/judge.sh --output artifacts/scripted`
  first to confirm.
- Event-kit compatibility is unverified.
- **The browser UI (`src/rootcause_app`) still targets the earlier tomato
  version**, so it is out of date and outside the submission path. It will be
  reworked for the demo.
- One fixed incident type. A careful agent with code tools can match the
  reference. If it does, that is the result to report.

## Repository map

| Path | Purpose |
|---|---|
| `src/rootcause/` | The greenhouse: model, generator, simulator, views, scoring and failure modes, tools, planners |
| `src/envkit/` | Evaluation backend: episode engine, MCP server, trace-replay verifier, Harbor task generator, audit, judge |
| `scenarios/root-cause.toml` | The task: prompt, clock, call limit, scoring, Harbor limits |
| `tasks/root-cause-s7/` | Generated Harbor task, committed; do not edit by hand (`envkit build`) |
| `calibration.json` | Committed comparator scores; the judge checks scripted runs against it |
| `scripts/quick.sh` | One model attempt plus its analysis: the fast feedback loop |
| `scripts/judge.sh` | The full judge command; reads `.env` |
| `scripts/compare.py`, `scripts/analyze.py` | Comparator table; trial explanations |
| `tests/` | Greenhouse tests; `tests/envkit/` backend tests (with depot and strict fixtures) |
| `src/rootcause_app/` | Browser app (pending rework for the demo) |
| `docs/` | [GREENHOUSE](docs/GREENHOUSE.md), [BACKEND](docs/BACKEND.md), [HARNESS](docs/HARNESS.md), [EXPERIMENTS](docs/EXPERIMENTS.md), [DECISIONS](docs/DECISIONS.md), [MODAL](docs/MODAL.md), [WORKFLOW](docs/WORKFLOW.md) |
