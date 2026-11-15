# Greenhouse Bench

An agent runs a Dutch winter greenhouse for 42 simulated days, one decision a morning, and is
scored on net profit against a scripted production planner. Built for AfterQuery's "Break the
Agent" (Junction 2026). Harbor task, MCP sidecar, trace-replay verifier.

![Score by seed and grower](docs/img/matrix.svg)

**Leaderboard** (normal-winter, seeds 1-3, Harbor 0.26 + OpenCode 1.19.5; 95 % bootstrap CI over runs):

| Grower | Score | 95% CI | Runs | Runs above the reference |
|---|---:|---|---:|---:|
| Reference planner (scripted) | 0.800 | deterministic | 3 | – |
| Gemini 4 Hydrogen | 0.781 | 0.751 – 0.814 | 7 | 2 of 7 |
| Claude Sonnet 5.5 | 0.695 (0.781 without the run that ended on day 9) | 0.518 – 0.799 | 7 | 3 of 7 |
| Claude Haiku 5.5 | 0.622 | 0.539 – 0.668 | 3 | 0 of 3 |
| Stop-early / harvest-early / naive / nobody | 0.24 / 0.10 / 0 / 0 | deterministic | 3 each | – |

**What we found** ([runs/ANALYSIS.md](runs/ANALYSIS.md), every run replayed hour by hour):

- **On average, the frontier models land just under the planner, with a wide spread.** Gemini scores 0.72-0.86
  and Sonnet 0.73-0.82 (seeds 1-3). Five of 14 runs beat the reference, so it is not a ceiling. The best
  run (Gemini, seed 2, EUR 963 k) staggered several partial sales a week, each timed to land as an older
  sale left the rolling demand window. Eight of the other nine leave EUR 37-86 k on the table against it (the ninth ended on day 9).
- **The market is the failure mode.** Demand is a published, uneven order book counted over a rolling
  week. Runs that sell into a window the previous week already filled get nothing for it. Haiku sold
  2.1 t of radish for EUR 2 and 2.2 t of broccoli for EUR 0 (seed 2), and met only 61-78 % of demand at
  full price (reference 85-87 %). Every model under-sold radish in week 0, its biggest week (2.1-2.9 t of 3.5 t).
- **Housekeeping slips under the daily turn.** Storm glass was left broken for over two weeks in 17 of
  17 model runs (the reference repairs it the morning it sees damage). 10 of 17 runs tried to sow without
  seed in stock, missing the 10-day lead time. Gemini sent malformed actions in 6 of 7 runs.
- **One Sonnet run ended on day 9.** A single reasoning step used its whole 32 k-token output budget,
  returned no tool call, and the harness ended the attempt. The farm then ran on unattended (score 0.18).
  It is reported, not excluded.


```bash
bash scripts/judge.sh --output artifacts/judge-1                                   # reference + baselines, every seed
bash scripts/judge.sh --model anthropic/claude-sonnet-5-5 --output artifacts/judge-2 # plus 3 agent attempts (key in .env)
```

Every number above is reproducible: model runs are committed with their Harbor trajectory, the
verifier's trace and a day-by-day log ([runs/TRAJECTORIES.md](runs/TRAJECTORIES.md)), and
[runs/ANALYSIS.md](runs/ANALYSIS.md) replays each one hour by hour (`scripts/analyze_runs.py`).

### Training a small model on the environment (stretch goal)

Qwen3-4B-Instruct-2507 fine-tuned with LoRA (on Modal) on the reference planner's daily
decisions from development seeds 1-6, then compared with the untouched base model on held-out
seeds 101, 104 and 107 that it never saw. Steps and commands: [docs/FINETUNE.md](docs/FINETUNE.md).

**What it learned.** The base model goes bankrupt by day 24-27 on every seed: it hires past the
crew cap and orders an express CO2 delivery that does not exist every day (113 refused actions).
Round 1 (192 examples, 16 min on one H100) learned the planner's daily routine: valid actions every
morning, climate and energy settings, harvesting ready batches, booking a contractor for damage.
It played all 42 days on every seed with no refused action and earned EUR 184 k on seed 104
(score 0.19; mean profit +EUR 46 k against -EUR 50 k for the base model). It never ordered seed or
planted, so once the starting batches were sold nothing new grew. Round 2 (256 more examples, 75 %
of them ordering or planting days) learned to order seed and plant, but not the arithmetic behind
them: it ordered about 100x too little seed (round numbers such as 1,000,000 against the planner's
164 million), so its plantings found too little seed in stock (33 times), and it tried to plant
into full compartments (58 refused actions in all); it did worse than round 1. Imitation transfers the routine but not the quantities and
lead times, the same interacting constraints the frontier models miss, only far more often.

<!-- finetune:start -->

In-process loop (normal-winter, held-out seeds [101, 104, 107]; score 0 = nobody acts, 0.80 = the reference planner). Score with profit in brackets.

| Seed | Reference profit | base (`Qwen/Qwen3-4B-Instruct-2507`) | round 1 (`greenhouse`) | round 2 (`greenhouse`) | Days played (base, round 1, round 2) |
|---|---|---|---|---|---|
| 101 | 834 k | 0.00 (-50 k) | 0.00 (-22 k) | 0.00 (-50 k) | 27 (bankrupt), 42, 32 (bankrupt) |
| 104 | 867 k | 0.00 (-50 k) | 0.19 (184 k) | 0.00 (-29 k) | 24 (bankrupt), 42, 42 |
| 107 | 861 k | 0.00 (-50 k) | 0.00 (-23 k) | 0.00 (-37 k) | 25 (bankrupt), 42, 42 |
| **Mean** | | **0.00** (-50 k) | **0.06** (46 k) | **0.00** (-39 k) | |

- **base**: refused actions 113, sowings without seed 0, over-limit days 0, infrastructure failures 0.
- **round 1**: refused actions 0, sowings without seed 0, over-limit days 0, infrastructure failures 0.
- **round 2**: refused actions 58, sowings without seed 33, over-limit days 0, infrastructure failures 0.

<details><summary>How these numbers were made</summary>

- Data: reference planner on normal-winter seeds [1, 2, 3, 4, 5, 6], 6 variants per seed (drop probability 0.1), 32 episodes kept, 1344 rows, ~18,124,989 tokens; code `e5f87b93b2`.
- Training round 1: LoRA r=32 (alpha 64) on Qwen/Qwen3-4B-Instruct-2507, from the base model; 192 examples, 1.0 epoch, lr 0.0002, loss 0.358 → 0.059, 15.7 min on one H100 (Modal).
- Training round 2: LoRA r=32 (alpha 64) on Qwen/Qwen3-4B-Instruct-2507, continued from round 1, 75 % of examples using place_orders, plant; 256 examples, 1.0 epoch, lr 0.0001, loss 0.093 → 0.051, 21.3 min on one H100 (Modal).
- base: `uv run --no-sync python scripts/finetune/play_llm.py --model Qwen/Qwen3-4B-Instruct-2507 --label base` (code `e5f87b93b2`, 2026-11-15 07:26:34 EET, temperature 0.0, tool_choice auto).
- round 1: `uv run --no-sync python scripts/finetune/play_llm.py --model greenhouse --label finetuned` (code `e5f87b93b2`, 2026-11-15 07:25:40 EET, temperature 0.0, tool_choice auto).
- round 2: `uv run --no-sync python scripts/finetune/play_llm.py --model greenhouse --label finetuned-r2` (code `e5f87b93b2`, 2026-11-15 08:02:50 EET, temperature 0.0, tool_choice auto).
- The in-process loop is not the Harbor/OpenCode harness; its prompt is the training prompt (a compact system prompt, own recent actions, today's briefing). Steps: [docs/FINETUNE.md](docs/FINETUNE.md).

</details>

<!-- finetune:end -->

<details>
<summary><b>The task</b>: what the agent controls and sees</summary>

One energy centre (gas CHP, gas boiler, heat buffer, CO2 store, grid connection) serves three
compartments: broccoli microgreens in A and B, radish microgreens in C, each holding batches of
different ages at the start. Each morning at 06:00 the agent makes one call, `submit_day`, with up
to 5 actions; then the day and the night run with nobody acting. There are no read tools: the
briefing returned by each call is everything it sees.

Actions: day climate and energy settings, a night schedule, orders (seed, CO2, spare parts) that
arrive days later, hiring and releasing staff (with a notice period), planting, harvests and
contractor repairs (queued on the crew's worker-hours). Storms on the recorded wind break roof
glass and the boiler can trip; both stay broken until a booked contractor has the parts. Weather
and energy prices are recorded Dutch series (KNMI De Bilt, day-ahead electricity, TTF gas), the
same for every agent on a seed.

Everything needed is in the task instruction (`Environment.opening()`): the growth equations,
prices, lead times, staff rules, event rates and the buyers' weekly order book. Nothing is hidden
that a careful planner would need. Crops, facility, climate, market and events are data files
under `data/`, so a new vegetable or facility is a new file, not new code.
</details>

<details>
<summary><b>Why it is hard</b>: the decisions that separate growers</summary>

- **Demand is a firm, uneven order book.** Buyers take a published volume a week (broccoli 4 t x
  [0.6, 1.5, 0.5, 1.4, 0.7, 1.3], radish 2.5 t x [1.4, 0.6, 1.3, 0.5, 1.5, 0.7]) in any rolling
  168 h, at full price; beyond it the price falls to 0 at 1.25x. Selling a steady stream into a
  small week that follows a big one sells into the glut the big week left in the window.
- **Lead times.** Seed takes 10 days to arrive and a crop may only be planted while it can still
  finish, so the sowing for a week is ordered about two weeks before it, and the last sowings
  close 8-12 days before the end.
- **Harvest timing is in the rules.** A ready crop keeps its top grade for 1.9 (radish) to 2.5
  (broccoli) days, then sells at 60 %. Holding a batch for a better week has a deadline.
- **The starting batches ripen in week 0, the big broccoli week is week 1.** Full light ripens
  them into a glut; fewer lamp hours delay them into the week that wants them (and save power).
- **Nobody acts at night or during the day.** Storm damage and a boiler trip wait until the next
  morning, and a repair needs a contractor, the parts on site and day-shift hours.
- **Energy is a system.** The CHP makes lamp power, heat and CO2 from gas; whether that pays
  depends on hourly prices that sometimes go negative.
</details>

<details>
<summary><b>The score</b></summary>

`score = clip(0.8 x (profit - profit_nobody) / (profit_reference - profit_nobody), 0, 1)`

`profit_nobody` is the profit when nobody acts on that seed (baseline settings kept, wages and
energy paid, nothing harvested). The reference planner sits at 0.8, which leaves headroom above
it. Constants per seed are in `calibration.json`; the verifier recomputes the profit by replaying
the agent's recorded calls in a fresh container. Nothing else is scored.

**The reference planner** ([reference.py](src/greenhouse/policies/reference.py),
[market_plan.py](src/greenhouse/policies/market_plan.py)) plays through the same `submit_day`
turn and reads only what the agent reads. It prices every ready batch at every hour it could
still sell, against its own sales log and the published market rule, and cuts only on the best
one; it picks the week's sale hours with a small dynamic programme (one window apart, inside the
planting deadline) and sows each burst to ripen just before its hour, with the grow time measured
from its own sowings; it dims the lamps of the starting batches whose market is next week; it
books contractors and orders parts the morning it sees damage. Tuned on dev seeds 1-6; on the
held-out seeds 101, 104 and 107 (never tuned on) it earns EUR 834-867 k, as on the dev seeds.
</details>

<details>
<summary><b>Scripted ladder</b>: every seed, deterministic</summary>

`envkit anchors normal-winter --seed N`. Profit in EUR, score in brackets.

| Seed | Nobody acts | Naive | Rule-based | Harvest-early (exploit) | Stop-early | Reference |
|---|---|---|---|---|---|---|
| 1 (dev) | −22,806 (0.00) | −27,311 (0.00) | −50,001 (0.00) | 88,789 (0.10) | 243,578 (0.24) | 876,586 (0.80) |
| 2 (dev) | −22,201 (0.00) | −23,956 (0.00) | −50,006 (0.00) | 88,350 (0.10) | 249,618 (0.24) | 893,506 (0.80) |
| 3 (dev) | −22,941 (0.00) | −30,947 (0.00) | −50,016 (0.00) | 90,453 (0.10) | 259,294 (0.24) | 907,765 (0.80) |
| 101 (held out) | −22,350 (0.00) | −24,614 (0.00) | −50,005 (0.00) | 87,824 (0.10) | 182,627 (0.19) | 834,036 (0.80) |
| 104 (held out) | −22,722 (0.00) | −26,700 (0.00) | −50,039 (0.00) | 90,912 (0.10) | 216,835 (0.22) | 867,196 (0.80) |
| 107 (held out) | −23,291 (0.00) | −30,650 (0.00) | −50,044 (0.00) | 88,798 (0.10) | 214,474 (0.22) | 861,105 (0.80) |

**Naive** sets the crop files' target climate and harvests on the ready alarm; it never orders
seed or repairs. **Rule-based** adds lamps in cheap hours, reorder levels, contractors and hiring;
it goes bankrupt (cash below 0 ends the episode) on days 34-38. **Stop-early** is the reference
for the first 30 % of the episode, then nobody. **Harvest-early** cuts everything as soon as it is
sellable. Held-out seeds use separate recorded weather and price windows.
</details>

<details>
<summary><b>Reward integrity</b>: what a judge would try</summary>

`envkit audit normal-winter` plays the strategies a judge would try and fails if any pays (it
passes 8 of 8 checks on seeds 1, 2 and 3; `scripts/check.sh` runs it on every committed seed):

| Strategy | Score |
|---|---|
| Do nothing; show up daily and change nothing | 0.00 |
| Reference cut off after 4 %, 10 %, 30 %, 50 %, 70 %, 90 % of its calls | 0.00, 0.00, 0.24, 0.31, 0.49, 0.69 |
| Random calls (5 seeds) | 0.00 |
| Spam `submit_day` | 0.00 |
| Harvest everything every day | 0.10 |
| Never harvest; spam orders; spam repairs; extreme heat and CO2 | 0.00 |
| Rule-based plus: cut heat at the end, plant late, CHP flat out | 0.00 (rule-based goes bankrupt) |

Why they fail: standing crop is worth nothing; produce under the minimum sellable weight sells
for nothing; wages are charged from hour 0; stopping keeps the last settings with nobody
harvesting; a refused call changes nothing; every order, hire and contractor visit costs money.

Trust boundary: the agent's container holds no scenario, seed or engine. The world runs in a
sidecar reachable only over MCP, and a separate verifier container replays the recorded calls
([BACKEND](docs/BACKEND.md), [HARNESS](docs/HARNESS.md)).
</details>

<details>
<summary><b>Known limits</b></summary>

- **Few runs per cell.** 2-3 runs per model per seed (Haiku 1); the CIs say so. The gap between the frontier
  models and the reference is small and within run-to-run spread; Haiku's is not.
- **The reference is beatable.** It sells at most once per demand window and cannot slow its last sowings
  to ripen after the planting deadline; the best Gemini run did both.
- **The rolling window has a knife edge.** A burst that finishes an hour earlier in the day than
  last week's is still inside the window and must wait a day. It is the published rule and the
  same for everyone, but it makes the last hour of a harvest matter.
- **Rule-based goes bankrupt** on days 34-38, so the ladder between nobody and the reference has
  only stop-early and harvest-early on it.
- **Harvest-early earns 0.10.** Cutting everything as soon as it is sellable still scores.
- **The 14-day `dev-winter` is a plumbing check, not a skill test** (with a 10-day seed lead time
  almost nothing new can be sown in 14 days).
- **Lettuce sells per head at any weight above the minimum** (in the crop set, not grown in
  `normal-winter`).
- **Official kit.** Harbor 0.26.0 and OpenCode 1.19.5 are pinned; AfterQuery's own starter kit has
  not been run against this task.
</details>

<details>
<summary><b>Run it</b>: requirements and every check</summary>

You need Python 3.12+, [uv](https://docs.astral.sh/uv/), and Docker or Podman running.

```bash
cp .env.example .env        # put your provider key in it; it is git-ignored
bash scripts/judge.sh --output artifacts/judge-1                                 # reference and baselines, every seed
bash scripts/judge.sh --model google/gemini-4-hydrogen --output artifacts/judge-2 # plus three agent attempts
bash scripts/judge.sh --seeds 101 --output artifacts/judge-3                     # a held-out evaluation seed
bash scripts/model-smoke.sh                                                      # one agent attempt on the 1-day smoke task
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
After a batch of runs: `scripts/collect_runs.py <eval dir>`, `scripts/trajectories.py`, `scripts/analyze_runs.py`.
</details>

<details>
<summary><b>Repository map</b></summary>

| Path | Purpose |
|---|---|
| `src/greenhouse/` | The environment: tools (`env.py`), simulator (`world/`), data schemas (`config/`), scripted policies (`policies/`) |
| `data/` | Crop, facility, climate, market, energy-price and event files, with sources |
| `scenarios/normal-winter.toml` | The task: prompt, clock, data files, scoring, seeds. `dev-winter` is the same game for 14 days (plumbing check); `smoke` is 1 day |
| `tasks/`, `calibration.json` | Generated by `envkit build`; committed; do not edit by hand |
| `src/envkit/` | Evaluation backend: episode engine, MCP server, trace-replay verifier, Harbor task generator, calibration, audit, judge ([BACKEND](docs/BACKEND.md)) |
| `src/envs/` | Small fixtures for the backend's own tests; not part of the submission |
| `runs/` | Committed model runs (trace, verifier score, Harbor trajectory, `DAYS.md`), `ANALYSIS.md`, `TRAJECTORIES.md`; earlier rule sets under `runs/archive/` |
| `scripts/{collect_runs,trajectories,analyze_runs}.py` | Collect Harbor trials, write day-by-day logs, replay and analyse every run (matrix, leaderboard, failure modes) |
| `scripts/quick.sh`, `scripts/check.sh` | The 30 s check after every change; CI's check (the reward audit runs with `ENVKIT_TEST_SCENARIO=normal-winter`) |
| `scripts/release_check.py` | Before a merge to main or the submission: quick check, benchmark tasks current, audit on every seed, scripted growers and viewer exact, README numbers vs calibration (about 4 min) |
| `scripts/judge.sh`, `scripts/model-smoke.sh`, `scripts/benchmark.sh` | The judge command; one agent attempt on the smoke task; one model run plus a report. All read `.env` |
| `scripts/finetune/` | The stretch goal: expert data from the reference (`gen_data.py`), LoRA training and vLLM serving on Modal (`modal_train.py`, `modal_serve.py`), the local benchmark (`play_llm.py`), the Harbor check (`harbor_run.sh`) and the README table (`report.py`). [FINETUNE](docs/FINETUNE.md) |
| `scripts/viz/` | The viewer: `uv run python scripts/viz/server.py`, then http://localhost:8765. Six growers side by side on one clock, model runs replayed from their trace; `check_viewer.py` checks it shows the real game exactly |
| `docs/` | [SPEC](docs/GREENHOUSE_SPEC.md), [CONTEXT](docs/GREENHOUSE_BENCH_CONTEXT.md), [BACKEND](docs/BACKEND.md), [HARNESS](docs/HARNESS.md), [MODAL](docs/MODAL.md), [DECISIONS](docs/DECISIONS.md), [WORKFLOW](docs/WORKFLOW.md) |
</details>
