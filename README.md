# Greenhouse Bench

An AfterQuery "Break the Agent" environment for Junction 2026. An agent runs a Dutch
winter greenhouse facility for 42 simulated days and is scored on net profit.

One energy centre (gas CHP, gas boiler, heat buffer, CO2 store, grid connection) serves
three compartments: broccoli microgreens in A and B, radish microgreens in C, each in
batches of different ages. The crop set is locked to lettuce, broccoli and radish
([docs/CROPS.md](docs/CROPS.md)); a scenario picks which compartment grows which. The
agent sets day climate and energy settings and a night schedule, orders seed, CO2 and
spare parts that arrive days later, hires staff with a notice period, and queues planting,
harvests and contractor repairs that use the crew's worker-hours. Microgreens sell into a
published weekly demand. Storms on the recorded wind break roof glass and the boiler can
trip; both stay broken until a booked contractor has the parts. It acts once a day at
06:00 through one tool, `submit_day` (up to 5 actions, then the day and night run with
nobody acting); there are no read tools. Weather and energy prices are recorded Dutch series
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
- **Decisions that cannot be made late.** Seed takes 10 days to arrive and a crop may
  only be planted while it can still finish, so sowing is ordered about two weeks before
  the demand it serves.
- **Demand is limited.** Each microgreen has a published weekly demand; sales above it
  fetch a falling price, so planting everything is not the answer.
- **Nobody acts at night or during the day.** The night runs on a schedule set in the
  morning; storm damage and a boiler trip wait until the next turn, and a repair needs a
  contractor, the parts on site and day-shift hours.
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

Scripted policies on the current rules, played in-process (`envkit anchors normal-winter
--seed N`, code on `main` after the demand limit). Profit in EUR, score in brackets.

| Seed | Nobody acts | Naive | Rule-based | Stop-early | Harvest-early (exploit) | Reference |
|---|---|---|---|---|---|---|
| 1 (dev) | −22,806 (0) | −27,311 (0) | −50,001 (0) | 150,090 (0.18) | 92,381 (0.12) | 726,445 (0.80) |
| 2 (dev) | −22,201 (0) | −23,956 (0) | −50,006 (0) | 147,554 (0.18) | 93,838 (0.12) | 728,860 (0.80) |
| 3 (dev) | −22,941 (0) | −30,947 (0) | −50,016 (0) | 178,032 (0.21) | 102,604 (0.13) | 755,476 (0.80) |
| 101 (held out) | −22,350 (0) | −24,614 (0) | −50,005 (0) | 109,302 (0.13) | 101,794 (0.13) | 760,997 (0.80) |
| 104 (held out) | −22,722 (0) | −26,700 (0) | −50,039 (0) | 127,328 (0.15) | 103,209 (0.12) | 792,530 (0.80) |
| 107 (held out) | −23,291 (0) | −30,650 (0) | −50,044 (0) | 124,152 (0.17) | 93,148 (0.13) | 685,883 (0.80) |

Held-out seeds (101–108) use separate recorded weather and price windows and were never
used for tuning.

- **Naive** sets the crop files' target temperatures and CO2, copies them to the night and
  harvests on the ready alarm; it never repairs. **Rule-based** adds lamps in cheap hours,
  reorder levels, contractor bookings and hiring; under the current rules it goes bankrupt
  (cash below 0 ends the episode) on days 34–38.
- **Reference** ([src/greenhouse/policies/reference.py](src/greenhouse/policies/reference.py))
  plays through the same `submit_day` turn as the agent (one call a day). It sows the bench
  area that meets the demand in the week of sale, keeps seed in flight for beds freeing
  within the lead time, cuts microgreens when ready, books contractors and orders parts for
  damage, and hires ahead for the last harvests. Tuned on seeds 4–6 only; models are scored
  on 1–3.
- **Stop-early** is the reference for the first 30% of the episode, then nobody.

**Model runs.** Harbor 0.26 + OpenCode 1.19.5, 42-day `normal-winter`, scored on the rules
of their day and archived per rule set under [runs/archive](runs/) ([TRAJECTORIES](runs/TRAJECTORIES.md),
DECISIONS 2026-11-15). On the last finished rule set (weekly demand, 3-day seed; 15 runs):
Gemini 4 Hydrogen 0.75–0.82 (mean 0.79), Claude Sonnet 5.5 0.71–0.82 (0.78), Claude
Haiku 5.5 0.46–0.72 (0.54), reference 0.80. **No model has a committed run on the current
rules (10-day seed); no frontier gap is claimed.**

## Reward integrity

`envkit audit normal-winter` plays the strategies a judge would try and fails if any pays
(seed 1 shown; it passes 8 of 8 checks on seeds 1, 2 and 3; `scripts/check.sh` runs it on every committed seed):

| Strategy | Score |
|---|---|
| Do nothing; show up daily and change nothing | 0.00 |
| Reference cut off after 4%, 10%, 30%, 50%, 70%, 90% of its calls | 0.00, 0.02, 0.18, 0.35, 0.50, 0.79 |
| Random calls (5 seeds) | 0.00 |
| Spam `submit_day` | 0.00 |
| Harvest everything every day | 0.12–0.13 |
| Never harvest; spam orders; spam repairs; extreme heat and CO2 | 0.00 |
| Rule-based plus: cut heat at the end, plant late, CHP flat out | 0.00 (rule-based goes bankrupt) |

Why they fail: standing crop is worth nothing; produce under the minimum sellable weight
sells for nothing; wages are charged from hour 0; stopping keeps the last settings with
nobody harvesting, so stopping is never better than playing on; a refused call changes
nothing; every order, hire and contractor visit costs money. Harvesting everything at once
still sells what has reached sellable weight, which is why it earns 0.12 (an open issue below).

Trust boundary: the agent's container holds no scenario, seed or engine. The world runs
in a sidecar reachable only over MCP, and a separate verifier container replays the
recorded calls ([BACKEND](docs/BACKEND.md), [HARNESS](docs/HARNESS.md)).

## Known limits

- **No model run on the current rules yet.** The model results above are from earlier
  round-3 rule sets; the 10-day seed lead time came after them.
- **Rule-based goes bankrupt.** Under the current rules the rule-based grower (and the three
  exploits built on it) runs out of cash on days 34–38, so the ladder between nobody and the
  reference has only stop-early and harvest-early on it. The benchmark tests that expect
  rule-based to beat naive and to finish the season fail for this reason
  (`ENVKIT_TEST_SCENARIO=normal-winter pytest`; the audit itself passes).
- **Harvest-early earns 0.12–0.13.** Cutting everything as soon as it is sellable is a crude
  strategy that still scores; the benchmark test that wants it near 0 fails.
- **The 14-day `dev-winter` is a plumbing check, not a skill test.** With a 10-day seed lead
  time almost nothing new can be sown in 14 days; models scored 1.0 there by cutting costs.
- **Lettuce sells per head at any weight above the minimum** (it is in the crop set but no
  compartment grows it in `normal-winter`). Weight grades would change that.
- **Official kit.** Harbor 0.26.0 and OpenCode 1.19.5 are pinned; AfterQuery's own starter
  kit has not been run against this task.

## Repository map

| Path | Purpose |
|---|---|
| `src/greenhouse/` | The environment: tools (`env.py`), simulator (`world/`), data schemas (`config/`), scripted policies (`policies/`) |
| `data/` | Crop, facility, climate, market, energy-price and event files, with sources |
| `scenarios/normal-winter.toml` | The task: prompt, clock, data files, scoring, seeds. `dev-winter` is the same game for 14 days (plumbing check); `smoke` is 1 day |
| `tasks/`, `calibration.json` | Generated by `envkit build`; committed; do not edit by hand |
| `src/envkit/` | Evaluation backend: episode engine, MCP server, trace-replay verifier, Harbor task generator, calibration, audit, judge ([BACKEND](docs/BACKEND.md)) |
| `src/envs/` | Small fixtures for the backend's own tests; not part of the submission |
| `scripts/quick.sh` | The quick check (about 30 s, no benchmark scenario): run after every change |
| `scripts/judge.sh`, `scripts/model-smoke.sh` | The judge command (benchmark; only when asked); one agent attempt on the smoke task. Both read `.env` |
| `scripts/check.sh` | CI's check; the reward audit runs only with `ENVKIT_TEST_SCENARIO=normal-winter` |
| `scripts/benchmark.sh` | One model run plus a report of its score against the scripted ladder (`--full` for normal-winter) |
| `runs/`, `scripts/{collect_runs,trajectories,analyze_runs}.py` | Committed model runs with trajectories and day-by-day logs, and the tools that collect and analyse them |
| `scripts/viz/` | The viewer: `uv run python scripts/viz/server.py`, then http://localhost:8765. Six growers side by side on one clock, model runs replayed from their trace, each decision shown with the change it measured in the simulator; `check_viewer.py` checks it shows the real game exactly |
| `docs/` | [SPEC](docs/GREENHOUSE_SPEC.md), [CONTEXT](docs/GREENHOUSE_BENCH_CONTEXT.md), [BACKEND](docs/BACKEND.md), [HARNESS](docs/HARNESS.md), [MODAL](docs/MODAL.md), [DECISIONS](docs/DECISIONS.md), [WORKFLOW](docs/WORKFLOW.md) |
