# Greenhouse Bench

An AfterQuery "Break the Agent" environment for Junction 2026. An agent runs a Dutch
winter greenhouse facility for 42 simulated days and is scored on net profit.

One energy centre (gas CHP, gas boiler, heat buffer, CO2 store, grid connection) serves
three compartments: broccoli microgreens in A and B, radish microgreens in C, each in
batches of different ages. The crop set is locked to lettuce, broccoli and radish
([docs/CROPS.md](docs/CROPS.md)); a scenario picks which compartment grows which. The
agent sets climate and energy settings, orders CO2 and seed that arrive
days later, hires staff with a notice period, and queues planting, harvests and contractor repairs
that use the crew's worker-hours. It acts once a day at 06:00 through one tool,
`submit_day` (up to 5 actions, then the day and night run); there are no read tools. Weather and energy prices are recorded Dutch series
(KNMI De Bilt, day-ahead electricity, TTF gas), the same for every agent on a seed.

Crops, the facility, the climate, the market and events are data files under `data/`,
so a new vegetable or facility is a new file, not new code.

## Why this setting

Running a greenhouse well is planning under lead times, with trade-offs that only show
days later. Every fact needed is in the task instruction (`Environment.opening()`: the growth equations, prices, lead
times, staff rules, event rates), so nothing is withheld. What is hard is using it:

- **Light is the main lever.** Lamps speed growth and cost electricity at hourly prices.
  Lettuce loses quality above a published daily light limit; the microgreens only lose
  quality in too little light, so for them the trade-off is cost alone.
- **Decisions that cannot be made late.** Seedlings take a week and a crop may only be
  planted while it can still finish, so replanting has to be ordered before the space is
  free.
- **Harvest timing is in the rules, not in the alarm.** A crop sold by weight keeps
  growing after the "ready" alarm and keeps its top grade for a published number of
  days; a harvest takes days of crew time and must finish before the grade drops.
- **Labour is a queue.** Tasks run in order on a fixed pool of worker-hours, and hiring
  has a notice period, so the last harvests must be staffed in advance.
- **Energy is a system.** The CHP makes lamp power, heat and CO2 from gas; whether that
  pays depends on hourly prices that sometimes go negative.

## Run it

You need Python 3.12+, [uv](https://docs.astral.sh/uv/), and Docker or Podman running.

```bash
bash scripts/judge.sh --output artifacts/judge-1
```

That one command runs the judging protocol through Harbor on every committed seed: the
reference run, a do-nothing baseline and a stop-early baseline, and fails if any of them
does not reproduce its calibrated score. With a model it also runs three agent attempts
through OpenCode:

```bash
cp .env.example .env        # put your provider key in it; it is git-ignored
bash scripts/judge.sh --model google/gemini-4-hydrogen --output artifacts/judge-2
bash scripts/judge.sh --seeds 101 --output artifacts/judge-3     # a held-out evaluation seed
bash scripts/model-smoke.sh                                      # one agent attempt on the 1-day smoke task
```

Checks that need no containers and no key:

```bash
uv sync --locked --extra eval --extra mcp --extra harbor
uv run --no-sync python -m pytest tests -q         # unit, scenario, ladder and integrity tests
uv run --no-sync envkit anchors normal-winter      # every scripted policy's score, per seed
uv run --no-sync envkit audit normal-winter        # reward-integrity audit
uv run --no-sync envkit play normal-winter         # play it yourself in the terminal
```

Each committed seed is also a plain Harbor task: `harbor run -p tasks/normal-winter-s1 -a opencode -m <provider/model>`.

## The score

`score = clip(0.8 × (profit − profit_nobody) / (profit_reference − profit_nobody), 0, 1)`

`profit_nobody` is the profit when nobody acts on that seed (the facility keeps its
baseline settings, wages and energy are paid, nothing is harvested). The reference
planner sits at 0.8, which leaves headroom above it. The constants per seed are in
`calibration.json`, and the verifier recomputes the profit by replaying the agent's
recorded calls in a fresh container. Nothing else is scored.

## Results

Scripted policies, played in-process (`envkit anchors`; SHA and commands in
[DECISIONS](docs/DECISIONS.md)). Profit in EUR, score in brackets.

| Seed | Nobody acts | Naive | Rule-based | Stop-early | Reference |
|---|---|---|---|---|---|
| 1 (dev) | −41,343 (0) | −16,576 (0.12) | 11,237 (0.26) | −18,277 (0.11) | 122,142 (0.80) |
| 2 (dev) | −43,026 (0) | −14,511 (0.13) | 10,266 (0.25) | 16,466 (0.28) | 126,984 (0.80) |
| 3 (dev) | −41,167 (0) | −18,707 (0.13) | 681 (0.24) | 6,100 (0.27) | 99,642 (0.80) |
| 101 (held out) | −53,837 (0) | −31,241 (0.12) | −7,533 (0.24) | −8,730 (0.23) | 103,931 (0.80) |
| 104 (held out) | −52,918 (0) | −29,299 (0.13) | −6,565 (0.25) | −34,063 (0.10) | 96,148 (0.80) |
| 107 (held out) | −52,894 (0) | −30,170 (0.11) | −4,333 (0.24) | −36,706 (0.08) | 106,565 (0.80) |

The same order holds on all six development seeds and all eight held-out seeds (101–108,
separate recorded weather and price windows, never used for tuning): naive 0.11–0.21,
rule-based 0.22–0.29, stop-early 0.08–0.28, reference 0.80.

- **Naive** sets the crop files' target temperatures and CO2 and harvests on the ready
  alarm. **Rule-based** adds lamps in cheap hours, reorder levels, contractor bookings and hiring.
- **Reference** ([src/greenhouse/policies/reference.py](src/greenhouse/policies/reference.py))
  plays through the same tools as the agent, in about 250 of the 400 calls. It measures
  the lamps in the first hour, holds lettuce just under its light limit, runs lamp power
  from the CHP, orders seed in the first hour and each day for the space that frees
  within the lead time, cuts microgreens when ready, and hires ahead for the last harvests. Its choices were tuned
  on development seeds 1–6 only.
- **Stop-early** is the reference for the first 30% of the hours, then nobody.

**Frontier agent: not measured yet.** See [DECISIONS](docs/DECISIONS.md) for the state of
the model runs. No gap is claimed until three agent runs exist.

## Reward integrity

`envkit audit normal-winter` plays the strategies a judge would try and fails if any pays
(seed 1 shown; it passes on seeds 1, 2 and 3, and `scripts/check.sh` runs it on every committed seed):

| Strategy | Score |
|---|---|
| Do nothing; show up daily and change nothing | 0.00 |
| Reference cut off after 4%, 10%, 30%, 50%, 70%, 90% of its calls | 0.00, 0.00, 0.11, 0.40, 0.68, 0.797 |
| Random calls (5 seeds) | at most 0.03 |
| Spam any single tool (16 tools) | 0.00 |
| Harvest everything every day | 0.05 |
| Never harvest; spam orders; extreme heat and CO2 | 0.00 |
| Spam repairs (pre-round-3 tool) | 0.07 |
| Rule-based plus: cut heat at the end, plant late, CHP flat out | 0.26, 0.27, 0.28 (rule-based alone: 0.26) |

Why they fail: standing crop is worth nothing; produce under the minimum sellable weight
sells for nothing; wages are charged from hour 0; stopping keeps the last settings with
nobody harvesting, so stopping is never better than playing on; a refused call changes
nothing; every order, hire and contractor visit costs money. Running the CHP flat out adds a
little because CHP power is simply good play here, and the reference uses it too.

Trust boundary: the agent's container holds no scenario, seed or engine. The world runs
in a sidecar reachable only over MCP, and a separate verifier container replays the
recorded calls ([BACKEND](docs/BACKEND.md), [HARNESS](docs/HARNESS.md)).

## Known limits

- **Round 3 is built; the numbers above predate it.** The agent now plays a daily turn
  (`submit_day`, 06:00, at most 5 actions, no read tools) with a night schedule, persistent
  damage fixed by contractors and parts, and news signals ([context section 0](docs/GREENHOUSE_BENCH_CONTEXT.md),
  [spec 14](docs/GREENHOUSE_SPEC.md)). The ladder, audit table and calibration above were
  measured on the old rules (any-hour tools, `repair`) and are stale until `normal-winter`
  is rebuilt and re-measured. No model has played the current rules. The viewer
  (`uv run python scripts/viz/server.py`, then http://localhost:8765) plays six growers side
  by side on the current rules: scripted ones live, model runs replayed from their trace
  under `artifacts/`, each decision shown and outlined at the hour it was made.
- **Lettuce sells per head at any weight above the minimum.** Cutting at the minimum
  sellable weight earns as much per head as waiting, and the reference does it. Weight
  grades would change that; it is an open question for the crop and market files.
- **Microgreens carry the profit, with no demand cap yet.** At the prices in the market
  file a square metre of microgreens earns about 16 times what lettuce does, and any
  amount sells at list price (DECISIONS, "Locked crop set").
- **One model result is not a gap.** The rubric needs three agent runs.
- **Official kit.** Harbor 0.26.0 and OpenCode 1.19.5 are pinned; AfterQuery's own starter
  kit has not been run against this task.

## Repository map

| Path | Purpose |
|---|---|
| `src/greenhouse/` | The environment: tools (`env.py`), simulator (`world/`), data schemas (`config/`), scripted policies (`policies/`) |
| `data/` | Crop, facility, climate, market, energy-price and event files, with sources |
| `scenarios/normal-winter.toml` | The task: prompt, clock, data files, scoring, seeds |
| `tasks/`, `calibration.json` | Generated by `envkit build`; committed; do not edit by hand |
| `src/envkit/` | Evaluation backend: episode engine, MCP server, trace-replay verifier, Harbor task generator, calibration, audit, judge ([BACKEND](docs/BACKEND.md)) |
| `src/envs/` | Small fixtures for the backend's own tests; not part of the submission |
| `scripts/quick.sh` | The quick check (about 30 s, no benchmark scenario): run after every change |
| `scripts/judge.sh`, `scripts/model-smoke.sh` | The judge command (benchmark; only when asked); one agent attempt on the smoke task. Both read `.env` |
| `scripts/check.sh` | CI's check; the reward audit runs only with `ENVKIT_TEST_SCENARIO=normal-winter` |
| `docs/` | [SPEC](docs/GREENHOUSE_SPEC.md), [CONTEXT](docs/GREENHOUSE_BENCH_CONTEXT.md), [BACKEND](docs/BACKEND.md), [HARNESS](docs/HARNESS.md), [MODAL](docs/MODAL.md), [DECISIONS](docs/DECISIONS.md), [WORKFLOW](docs/WORKFLOW.md) |
