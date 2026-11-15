# Part 3: What we built and the baseline results

Draft of 5 slides. Every number is in table (c) with its source file. Nothing here was re-run; all figures are read from committed files.

---

## (a) Slides and (b) speaker notes

### Slide 1. A standard Harbor task, graded by replay

**Title:** One tool, one decision a day, graded by replay

- Each seed is a plain Harbor task: `harbor run -p tasks/normal-winter-s1 -a opencode -m <model>`.
- The world runs in a sidecar over MCP. The agent's container holds no scenario, seed or engine.
- A separate verifier container replays the recorded calls and writes the reward. No model, no text matching.
- The agent's only tool is `submit_day`: up to 5 actions, then 24 simulated hours run with nobody acting.

**Big number:** **1 tool, 42 calls**

**Suggested chart:** architecture box diagram (not data). Boxes: `OpenCode agent container` -> (MCP over HTTP) -> `sim sidecar: MCP server + engine + world` -> (trace.jsonl) -> `verifier container: replay, score`. Label "no scenario / seed / engine" on the agent box.

| Chart element | Label |
|---|---|
| Box 1 | OpenCode 1.19.5 in agent container |
| Arrow 1 | MCP, `submit_day` |
| Box 2 | Sidecar: engine, world, scenario, seed, `trace.jsonl` |
| Arrow 2 | Harbor 0.26.0 collects trace after agent stops |
| Box 3 | Fresh verifier container: replays all calls, writes `reward.txt` |

**Speaker notes:** The agent plays one daily turn through one tool. `submit_day` takes up to five actions (climate settings, night schedule, orders, hiring, planting, harvest, repairs). A day is 24 one-hour windows run in a single call. The backend is `envkit`: it serves the world over MCP, appends every call to an append-only trace, and a separate verifier replays that trace in a fresh process. The agent never sees the seed or the engine. A missing or ungradeable trace is an infrastructure failure, not a zero for the agent. Harbor 0.26.0 and OpenCode 1.19.5 are pinned. The whole thing also ran on Modal for the scripted policies.

---

### Slide 2. Deterministic, seeded, anchored on net profit

**Title:** Same seed, same world, one number: net profit

- Deterministic for a fixed seed and action list; named random streams, so an extra call cannot change the world.
- Dev seeds 1-6 are for tuning. Evaluation seeds 101-108 use separate recorded weather and price windows and are never tuned on.
- Score = `clip(0.8 x (profit - profit_nobody) / (profit_reference - profit_nobody), 0, 1)`.
- Zero = nobody acts on that seed. 0.8 = the scripted reference planner. Headroom above it.

**Big number:** **0 -> 0.8 -> 1**  (do nothing, reference planner, cap)

**Suggested chart:** a horizontal score ruler with three ticks. Optionally a second small panel: seed 1 anchor profits in EUR.

| Tick | Score | Seed 1 profit (EUR) |
|---|---:|---:|
| Nobody acts (zero anchor) | 0.00 | -22,806 |
| Reference planner (target) | 0.80 | 876,586 |
| Scale (profit_ref - profit_nobody) | - | 1,124,239 |

**Speaker notes:** The raw metric is euros of net profit at the last hour: harvest revenue and electricity sold, minus gas, electricity, CO2, wages, hiring, contractors, parts and orders. Standing crop and leftover parts are worth nothing. The score rescales it so a do-nothing run is 0 and our reference planner is 0.8. Constants are per seed in `calibration.json`. Seeds 1-3 are the committed task seeds; held-out seeds 101, 104 and 107 are calibrated in the README ladder. Be precise: the dev/eval split is a project rule and the scenario file states it; the committed calibration covers seeds 1-3 only.

---

### Slide 3. The baseline ladder

**Title:** Scripted ladder: doing nothing is not rewarded

- Do-nothing, naive and rule-based all score 0.00 on every seed. Rule-based goes bankrupt on days 34-38.
- Two partial strategies pay something: stop-early (0.24) and harvest-early (0.10).
- The reference planner scores 0.80 on every seed, EUR 834k to 908k.
- Held-out seeds 101, 104, 107: same pattern, reference EUR 834k / 867k / 861k.

**Big number:** **0.80** reference vs **0.00** for do-nothing, naive and rule-based

**Suggested chart:** grouped bar of score by policy (x: policy, y: score 0-1, one bar per seed, or just seed 1). Optional second chart of profit.

Score by policy (seed 1 / seed 2 / seed 3):

| Policy | Seed 1 | Seed 2 | Seed 3 |
|---|---:|---:|---:|
| Do-nothing | 0.000 | 0.000 | 0.000 |
| Naive | 0.000 | 0.000 | 0.000 |
| Rule-based | 0.000 | 0.000 | 0.000 |
| Harvest-early (exploit) | 0.0993 | 0.0966 | 0.0975 |
| Stop-early | 0.2369 | 0.2375 | 0.2426 |
| Reference planner | 0.800 | 0.800 | 0.800 |

Profit in EUR (same order):

| Policy | Seed 1 | Seed 2 | Seed 3 |
|---|---:|---:|---:|
| Do-nothing | -22,806 | -22,201 | -22,941 |
| Naive | -27,311 | -23,956 | -30,947 |
| Rule-based | -50,001 | -50,006 | -50,016 |
| Harvest-early | 88,789 | 88,350 | 90,453 |
| Stop-early | 243,578 | 249,618 | 259,294 |
| Reference | 876,586 | 893,506 | 907,765 |

**Speaker notes:** Do-nothing is the scoring zero by construction. Naive sets each crop's target climate and harvests on the ready alarm but never orders seed, so it never replants. Rule-based adds lamps in cheap hours, reorder levels, contractors and hiring, but it goes bankrupt (cash below 0 ends the episode) on days 34-38, so it scores 0. That means the ladder between nobody and the reference really has two rungs, stop-early and harvest-early. Say plainly that this is a known weakness: harvest-early earning 0.10 means cutting everything as soon as it is sellable still pays a little, and rule-based as a middle rung is broken. The reference reads exactly the briefing the agent reads. Its edge is decisions, not hidden information.

---

### Slide 4. Anti-exploit tests

**Title:** We tried to cheat our own score

- `envkit audit` plays the strategies a judge would try and fails if any pays. It passes 8 of 8 checks on seeds 1, 2 and 3.
- Do nothing or show up and change nothing: 0.00. Random calls, spam `submit_day`, spam orders, spam repairs, never harvest, extreme heat and CO2: 0.00.
- Stopping early is monotone: reference cut off after 4 / 10 / 30 / 50 / 70 / 90 % of its calls scores 0.00 / 0.00 / 0.24 / 0.31 / 0.49 / 0.69.
- Invalid actions: a refused action changes nothing; every order, hire and contractor visit costs money; wages run from hour 0.

**Big number:** **8 of 8** audit checks pass

**Suggested chart:** bar chart of the early-stop curve (x: fraction of reference calls kept, y: score). Overlay the reference at 0.80.

| Fraction of calls kept | Score |
|---:|---:|
| 4% | 0.00 |
| 10% | 0.00 |
| 30% | 0.24 |
| 50% | 0.31 |
| 70% | 0.49 |
| 90% | 0.69 |
| 100% (full reference) | 0.80 |

**Speaker notes:** Four classes we care about. Do-nothing: 0, by the zero anchor. Early stop: when the agent stops, every remaining day runs with the last settings and nobody harvesting, so partial credit rises smoothly with work done and never beats finishing. Replay: the verifier replays the trace in a fresh process and checks it reproduces the recorded responses; a trace that does not reproduce counts as an infrastructure failure, and the audit also checks the reference run is identical when repeated and when replayed. Invalid actions: a refused action changes nothing and the other actions in the same call still apply; malformed arguments are rejected before mutating state. The honest weak point is harvest-early at 0.10 and the broken rule-based rung (slide 3). Also note: the audit lists those figures in the README; it was run at an earlier commit than this draft and the audit itself is a benchmark-class command that we did not re-run for this slide.

---

### Slide 5. Model runs vs the ladder

**Title:** Frontier models land just under the planner

- 17 Harbor + OpenCode runs on the current `normal-winter` rules, seeds 1-3 only: Gemini 4 Hydrogen x7, Claude Sonnet 5.5 x7, Claude Haiku 5.5 x3.
- Means: Gemini 0.781, Sonnet 0.695 (0.781 without the run that ended on day 9), Haiku 0.622, reference planner 0.800.
- Best single run, Gemini seed 2: 0.861, EUR 963k vs the planner's EUR 894k. Spread within a model is wide.
- Failures: sells into a full demand window, boiler left broken, planting before seed lands, one early session end.

**Big number:** **0.78 vs 0.80**  (best model mean vs reference planner)

**Suggested chart:** dot plot, one dot per run, x = grower, y = score; horizontal line at 0.80 (planner) and shaded band at 0 to 0.24 (stop-early ceiling). Plus a summary bar of means with 95% CI.

Summary (current rules, `runs/ANALYSIS.md`):

| Grower | Mean score | 95% CI low | 95% CI high | Runs |
|---|---:|---:|---:|---:|
| Reference planner | 0.800 | - | - | 3 |
| Gemini 4 Hydrogen | 0.781 | 0.751 | 0.814 | 7 |
| Claude Sonnet 5.5 | 0.695 | 0.518 | 0.799 | 7 |
| Claude Haiku 5.5 | 0.622 | 0.539 | 0.668 | 3 |
| Stop-early | 0.239 | - | - | 3 |
| Nobody / naive / rule-based | 0.000 | - | - | 3 each |

Every run (score rescored against the current reference, `runs/ANALYSIS.md`):

| Seed | Gemini | Sonnet | Haiku |
|---:|---|---|---|
| 1 | 0.826, 0.752, 0.724 | 0.730, 0.816, 0.806 | 0.657 |
| 2 | 0.861, 0.768 | 0.176, 0.758 | 0.668 |
| 3 | 0.756, 0.777 | 0.816, 0.762 | 0.539 |

Archived runs (earlier rule sets; not comparable, do not put on one chart with the above):

| Archive folder | Rules | Runs | Verifier scores |
|---|---|---:|---|
| `no-demand-limit` | no demand cap | 9 | Haiku 0.40-0.81, Sonnet 1.0, Gemini 0.22-1.0 |
| `order-key-bug` | ':' ordering bug | 3 | Gemini 0.25-0.68 (excluded from comparisons) |
| `steady-demand` | cap, constant demand | 13 | Gemini 0.63-0.83, Haiku 0.56-0.83, Sonnet 0.72-0.75 |
| `schedule-3day-seed` | weekly schedule, 72 h seed, gentler glut | 15 | Gemini mean 0.791, Sonnet 0.776, Haiku 0.543; reference 0.800 |

**Speaker notes:** These are real trajectories, replayed hour by hour; each score equals the verifier's reward on the current reference. Gemini averages 0.78 and Sonnet 0.70, both just under the planner, with wide spread (Gemini 0.72-0.86, Sonnet 0.73-0.82 excluding the day-9 run). Haiku is clearly below. The best Gemini run beat the planner, so 0.8 is not a ceiling. Do not claim a frontier-versus-planner gap: the differences between Gemini, Sonnet and the planner are inside run-to-run spread with 2-3 runs per cell. Be upfront about the history: the first version was too forgiving, top models tied or beat the old reference (Gemini 0.99, Sonnet 1.00), so we steepened the oversupply price and rebuilt the planner. The archived runs are kept for the record but played earlier rules; do not mix them in. Two current-rules runs (Sonnet s1 `qxhrmeh`, Gemini s1 `hiup4hw`) show verifier rewards 1.0 and 0.9905 because they were played before the reference was improved; the analysis rescored them to 0.806 and 0.752.

---

## (c) Data table: every number and its source

| Number | Value | Source file |
|---|---|---|
| Tool and turn | one tool `submit_day`, up to 5 actions/day | `scenarios/normal-winter.toml` (`actions_per_day = 5`), `docs/BACKEND.md` Engine rules |
| Episode length | 42 days, 1008 hourly windows | `scenarios/normal-winter.toml` `[shift]` |
| Tool call budget | 400 calls | `scenarios/normal-winter.toml` `max_calls = 400` |
| Pinned versions | Harbor 0.26.0, OpenCode 1.19.5, MCP SDK 2.3.0 | `docs/HARNESS.md` |
| Dev / eval seeds | 1-6 dev; 101-108 evaluation | `AGENTS.md`, `scenarios/normal-winter.toml` comment |
| Committed task seeds | 1, 2, 3 | `scenarios/normal-winter.toml` `seeds`, `calibration.json` |
| Score formula | `clip(0.8 x (profit - nobody) / (ref - nobody), 0, 1)` | `README.md` "The score"; `scenarios/normal-winter.toml` `target = 0.8` |
| Seed 1 zero / scale | -22,805.57 / 1,124,239.29 | `calibration.json` tasks.normal-winter.1.components |
| Seed 2 zero / scale | -22,201.16 / 1,144,633.87 | `calibration.json` tasks.normal-winter.2.components |
| Seed 3 zero / scale | -22,940.67 / 1,163,382.21 | `calibration.json` tasks.normal-winter.3.components |
| Ladder profits and scores, seeds 1-3 | slide 3 tables | `calibration.json` tasks.normal-winter.{1,2,3}.anchors; mirrored in `README.md` Scripted ladder and `runs/ANALYSIS.md` |
| Harvest-early score | 0.0993 / 0.0966 / 0.0975 | `calibration.json` anchors `exploit:harvest-early` |
| Stop-early score | 0.2369 / 0.2375 / 0.2426 | `calibration.json` anchors `stop-early` |
| Held-out ladder (101/104/107) | reference EUR 834,036 / 867,196 / 861,105; stop-early 0.19 / 0.22 / 0.22; harvest-early 0.10 | `README.md` Scripted ladder (not in `calibration.json`, which holds seeds 1-3 only) |
| Rule-based bankruptcy | days 34-38 | `README.md` Scripted ladder and Known limits |
| Audit | 8 of 8 checks on seeds 1, 2, 3 | `README.md` Reward integrity; `docs/BACKEND.md` "What the audit checks" |
| Early-stop curve | 0.00, 0.00, 0.24, 0.31, 0.49, 0.69 at 4/10/30/50/70/90% | `README.md` Reward integrity table |
| Model run count | 17 (7 Gemini, 7 Sonnet, 3 Haiku) | `runs/ANALYSIS.md` Every run; `runs/TRAJECTORIES.md` |
| Means and CIs | slide 5 summary table | `runs/ANALYSIS.md` Leaderboard |
| Beat the planner | Gemini 2 of 7, Sonnet 3 of 7, Haiku 0 of 3 | `README.md` "What the runs show" |
| Sonnet without day-9 run | 0.781 | `README.md` table footnote |
| Best run | Gemini s2 `2tvqbki`, 0.861, EUR 963,158 vs planner EUR 893,506 | `runs/ANALYSIS.md` Every run |
| Per-run scores | slide 5 table | `runs/ANALYSIS.md` Every run |
| Verifier rewards that differ (older reference) | Sonnet s1 `qxhrmeh` 1.0; Gemini s1 `hiup4hw` 0.9905 | `runs/TRAJECTORIES.md` footnote 1, `runs/ANALYSIS.md` |
| Day-9 session end | Sonnet s2 `ny8magu`, 0.176 (rerun 0.76) | `runs/ANALYSIS.md`, `README.md` failure table |
| Failure-pattern counts | boiler left broken in 8 of 17; planted before seed landed in 10 of 17; malformed actions in 6 of 7 Gemini runs | `README.md` "What we noticed", "Other failures" |
| Archived runs | 9 / 3 / 13 / 15 runs by rule set | `runs/TRAJECTORIES.md` archive tables |
| `schedule-3day-seed` means | Gemini 0.791, Sonnet 0.776, Haiku 0.543, reference 0.800 | `docs/DECISIONS.md` Model runs so far |
| Old-reference results that prompted the rebuild | Gemini 0.99, Sonnet 1.00 on first steep-glut runs; held-out reference old 761/793/686k, new 834/867/861k | `docs/DECISIONS.md` (night entry, 2026-11-15) |
| Reference +14% on held-out | "+14 % profit on held-out seeds" | `README.md` "How we found the problem" |
| Modal gate | reference, do-nothing, stop-early passed on Modal, 2026-11-14 | `docs/MODAL.md`, `docs/HARNESS.md` |
| Policy ladder files | `naive.py`, `rule_based.py`, `reference.py`, `market_plan.py`, `exploiter.py` | `src/greenhouse/policies/` |

## (d) Honesty box

Put this on the slide or say it aloud.

- **Official AfterQuery event kit: not run.** Harbor 0.26.0 and OpenCode 1.19.5 are the pinned candidates; AfterQuery's own starter kit has not been run against this task (`docs/HARNESS.md`, `README.md` Known limits). Do not say "official-compatible".
- **No frontier gap is claimed.** Frontier models score 0.70-0.78 mean against a 0.80 planner built by us. With 2-3 runs per model per seed and wide confidence intervals, the differences between Gemini, Sonnet and the planner are within run-to-run spread. Only Haiku is clearly lower.
- **Seeds 1-3 only for model runs.** No model run on held-out seeds 101-108. Held-out numbers are scripted policies only.
- **The reference is ours.** It was tuned on dev seeds 1-6 (it reads the same briefing as the agent) and 0.8 is a calibration choice, not a measured human or optimum level. It was rebuilt after models beat the first version.
- **Ladder weaknesses we know about:** rule-based goes bankrupt (0.00, so the middle rung is empty); harvest-early still earns 0.10; the 14-day `dev-winter` is a plumbing check, not a skill test; roof-glass storm damage never fully clears for any grower.
- **Rule-set era caveat.** README and `runs/TRAJECTORIES.md` label the 17 runs in `runs/normal-winter/` as "current rules", but two of them (verifier rewards 1.0 and 0.9905) were played before the last reference improvement, and `AGENTS.md` still says model runs exist only on earlier rule sets. Scores quoted here are the `runs/ANALYSIS.md` rescored ones. Runs in `runs/archive/` (40 runs, four earlier rule sets) are not comparable and must not be mixed into one chart.
- **Not re-verified for this draft.** The audit and anchors are quoted from committed files; we did not run any benchmark, test or `envkit` command to write this section. Re-run `envkit anchors`/`envkit audit` before presenting if the environment changed.
- **Local vs Modal score equality** was checked only for the scripted policies, on an earlier version of the game (`docs/HARNESS.md`).
