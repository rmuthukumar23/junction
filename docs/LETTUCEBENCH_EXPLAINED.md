# LettuceBench, explained step by step

**One-sentence version:** LettuceBench is a deterministic 42-day simulation in
which an agent operates a small Dutch winter greenhouse and is rewarded only for
net profit. It tests whether an agent can maintain an economically sensible plan
when crop biology, market windows, energy, delayed deliveries, labour and faults
interact over time.

## 0. Start with the problem, not the simulator

Modern language models can often produce a plausible one-off plan. Operating a
greenhouse is different: an action today can make money or cause loss ten days
later. The operator must remember outstanding orders, anticipate crop maturity,
allocate constrained heat and labour, react to what actually happened, and avoid
selling into a market that is already full.

That is a useful benchmark target because greenhouse optimisation is a real
sequential-control problem. Wageningen research on a complete lettuce crop cycle
found that a policy ignoring uncertainty earned 15% less net revenue, and one
without dynamic feedback produced a 19% loss in its case study. [van Mourik,
van 't Ooster and Vellekoop (2025)](https://doi.org/10.1016/j.biosystemseng.2025.104250)

Our claim is deliberately narrower than “AI cannot operate greenhouses”:

> In our reproducible, 42-day Dutch-winter task, the evaluated frontier models
> were variable and on average did not match the scripted reference planner.
> Their recorded failures reveal concrete planning and execution problems.

This is stronger and more defensible than claiming a universal inability, and it
points at a capability gap that can be measured and improved.

## 1. Why a Dutch winter greenhouse?

We chose a Dutch glasshouse because it gives the scenario a coherent, researched
industrial setting: winter heating and lighting matter, gas-fired combined heat
and power (CHP) is relevant, and greenhouse climate-control research is unusually
strong. Dutch greenhouse horticulture used nearly 95 PJ in 2024, or 0.99 GJ/m²
after temperature correction, so energy is not decorative in this setting; it is
part of the business decision. [WUR, *Energiemonitor van de Nederlandse
glastuinbouw 2024*](https://edepot.wur.nl/702373)

The facility has three crop compartments and one shared energy centre:

```text
outside weather + energy prices
              |
              v
  CHP + boiler + heat buffer + CO2 store + grid
              |
       scarce heat / CO2
       /        |        \
      v         v         v
  House A   House B   House C
   crops      crops      crops
              |
              v
      harvest, labour, sales, profit
```

This is not a digital twin of one named commercial farm. It is a deliberately
small, auditable abstraction of a Dutch production system. The *structure* is
grounded: CHP, buffers and CO2 enrichment are a recognised coupled greenhouse
control problem. Research using Dutch-characteristic greenhouse conditions finds
that CHP, buffer and crop/electricity interactions can be economically important.
[Seginer, van Beveren and van Straten (2018)](https://doi.org/10.1016/j.biosystemseng.2018.05.006)

The *numbers* have three labels in the repository:

| Label | Meaning | Example |
|---|---|---|
| Sourced | A published or primary-data value | KNMI hourly weather; crop-cycle evidence |
| Calibrated | Tuned so the implemented model reaches a sourced target | canopy closure for a target harvest time |
| Design | A transparent benchmark choice where no usable universal value exists | grade-loss rate, simplified prices, event rate |

That distinction is crucial. Say “realistic, research-informed abstraction,” not
“an exact replica of Dutch greenhouse economics.”

## 2. What is actually simulated?

The episode lasts 42 simulated days. Internally, the world advances **hour by
hour**, so climate, energy costs, crop growth and damage accumulate continuously.
The agent gets exactly one decision point each morning at 06:00. It calls one
tool, `submit_day`, with at most five actions; then the simulator runs the full
day and night.

This interaction design is intentional:

- It prevents a model from continuously correcting a bad plan every hour.
- It makes lead times and overnight consequences real.
- It keeps the task tractable: the agent receives one structured morning briefing
  rather than a stream of low-level control calls.
- It mirrors the distinction between a human day operator and the local climate
  computer. The climate computer can execute a published thermostat/dispatch
  rule, but it does not invent a new business plan overnight.

The tool can set day climate and energy settings, submit a fixed night schedule,
order seed/CO2/parts, manage staff, plant, harvest and book a contractor. A
briefing reports the state, previous-night results, alerts, crop estimates,
orders, market information, forecast and cash. No secret action is needed to
succeed: the growth equations, price rules, leads and event rates are described
to the agent.

The core dynamics are deliberately coupled:

1. Weather, lamps, heating, ventilation and CO2 affect climate.
2. Climate affects growth, quality and readiness.
3. Readiness plus the rolling market window determines sale revenue.
4. Energy, labour, seed, orders and repairs affect cash.
5. Cash, stock, staff availability and lead times constrain tomorrow's actions.

This follows the real optimisation question rather than a simple “keep the room
at 20 °C” puzzle. Greenhouse-control research explicitly models temperature,
humidity and CO2 jointly because the energy/crop trade-off cannot be understood
from one variable alone. [van Beveren et al., *Optimal control of greenhouse
climate using minimal energy and grower-defined bounds*](https://research.wur.nl/en/publications/optimal-control-of-greenhouse-climate-using-minimal-energy-and-gr/)

## 3. Which parts come from the real Netherlands?

The outside world is recorded, fixed input—not live data and not a random
weather generator.

- Weather: hourly KNMI observations from station 260, De Bilt, using selected
  January windows. The data file records its source and is bundled with the task.
  KNMI provides historical hourly data for De Bilt and other Dutch stations.
  [KNMI hourly observations](https://www.knmi.nl/nederland-nu/klimatologie/uurgegevens)
- Energy: recorded winter electricity and TTF gas series stored in
  `data/energy_prices/l_winter.toml`; the benchmark never fetches prices during
  a run.
- Crop models: the leafy-crop core comes from Van Henten's greenhouse lettuce
  model, with crop-specific cycle and yield targets documented in
  [`CROPS.md`](CROPS.md) and each crop data file.
- Facility logic: CHP, peak boiler, heat buffer, grid import/export and purchased
  CO2 are a simplified but recognisable Dutch greenhouse energy configuration.

We then make benchmark choices on top of these sources. For example, the task
uses broccoli and radish microgreens because their 12- and 8-day cycles create
several sow/harvest decisions inside 42 days. It uses a firm, uneven weekly order
book because the benchmark needs a clear economic reason not to harvest every
ready crop at once. These are useful abstractions, not assertions that every
Dutch farm grows these exact crops under these contracts.

## 4. Why these crops and market rules?

Two broccoli-microgreen compartments and one radish-microgreen compartment begin
with staggered batches. Microgreens are short-cycle, so the agent faces multiple
harvest and replacement decisions in one episode. The data sources support the
order of magnitude: broccoli microgreens are commonly harvested around day 12–13
and radish around day 8–10; see the crop-source table in [`CROPS.md`](CROPS.md).

The market is intentionally not an unlimited commodity sink. Each crop has a
published, uneven weekly demand schedule. Sales are allowed while the rolling
seven-day total stays within demand. Beyond 1.25× that volume, the price reaches
zero. Ready batches retain top quality only briefly, then sell at 60%, then become
waste. Seeds take ten days to arrive.

Those rules create a concrete planning chain:

```text
today's seed order → arrives in 10 days → planting → 8/12 days of growth
→ narrow quality window → a particular weekly demand window → revenue
```

The chain is why a “reasonable” daily action can still be globally wrong. If an
agent delays an order, it cannot recover the lost cycle. If it harvests every
batch together, it can fill the current market window and sell the rest for €0.
If it waits, quality decays. The agent must therefore schedule volume, not merely
notice that a crop is ready.

## 5. Why faults, forecasts and the daily boundary?

The scenario includes storms that damage roof glass and boiler trips. Repairs
need a contractor and, where applicable, ordered parts. A forecast/news signal
can raise concern about a storm or cold weather, but it never names a future
random equipment failure. Forecasts contain seeded error.

This avoids a common benchmark failure mode: hidden information that turns an
evaluation into guessing. An agent can make a sensible precaution—fill the heat
buffer, use screens, keep a repair contingency—but cannot magically know when a
boiler will fail. The same rules, data and observable evidence apply to the
reference planner and all models.

It is also important to separate automation from agency. The simulation permits
ordinary thermostat dispatch among **already enabled** sources; it does not let
the system re-plan its business strategy or call a human at night. This is a
modelling decision that creates a planning test, not a claim that Dutch
greenhouses lack on-call staff.

## 6. Why should this expose an LLM-agent weakness?

LettuceBench is hard for an agent for three measurable reasons, not because of a
riddle or inaccessible information.

1. **Interacting constraints.** The agent must reconcile inventory, a 10-day
   lead time, crop age, labour, price windows and quality decay. Local rules such
   as “harvest when ready” are insufficient.
2. **Closed-loop revision.** Each morning provides new evidence. A plan must be
   revised when a boiler trips, a delivery fails or crop maturity changes.
3. **Persistent task state.** Orders and repairs are not completed when requested;
   they must be tracked until arrival or completion across 42 daily turns.

This is aligned with existing agent-evaluation research. SimuHome argues that
temporal dependencies, persistent state and reproducible continuous environmental
feedback are necessary to evaluate planning rather than isolated commands.
[SimuHome, ICLR 2026](https://openreview.net/pdf/8275b246b5397f38c541a164b593b2b3568f3dad.pdf)
LettuceBench contributes a different domain: economic crop operations with
delayed biological and market consequences.

The benchmark does **not** prove why a model failed internally. It records the
behavioural pattern. The safe wording is: “The trajectories show missed
constraints, missed revisions and lost pending work.” Do not say that a trace
proves a model's hidden reasoning process or a general cognitive mechanism.

## 7. The architecture: how we make a result trustworthy

The architecture exists to ensure the score represents completed simulated work,
not a model's self-report or an exploit.

```text
agent container ──MCP submit_day──> simulator sidecar
                                      │
                              deterministic hourly world
                                      │
recorded calls / trace <──────────────┘
          │
          v
separate verifier replays the calls in a fresh container
          │
          v
one reward written to reward.txt
```

Key design choices and their justification:

| Choice | Why it matters |
|---|---|
| Deterministic seed | Same seed + same actions gives the same world, so comparisons and replay are meaningful. |
| Recorded inputs | Agents face identical weather and price paths on a seed; no live-data timing advantage. |
| Sidecar world | The agent container does not contain the scenario, seed or simulator implementation, limiting information leakage and self-scoring. |
| Fresh replay verifier | The score is reconstructed from recorded tool calls, rather than trusting a claimed outcome. |
| Profit-only reward | It rewards the operational goal, not verbose explanations or intermediate tool use. |
| Scripted audit policies | We test do-nothing, stop-early, spam, random, harvest-everything and other shortcuts so they do not pay. |

The implementation boundary follows the same logic: `src/greenhouse/` contains
the task and simulator; `src/envkit/` contains the episode engine, MCP serving,
task packaging and replay verifier. Scenario values are data files, not hidden
Python constants. See [`BACKEND.md`](BACKEND.md) for the exact verifier and
scoring contract.

## 8. What exactly is the score?

The terminal metric is net profit, including harvest revenue and costs for gas,
electricity, CO2, labour, seed, ordering, repairs and contractors. It is mapped
to a bounded reward using per-seed calibration:

```text
score = clip(0.8 × (profit − profit_nobody)
                   / (profit_planner − profit_nobody), 0, 1)
```

The reference planner is deliberately placed at 0.8, not 1.0. That leaves room
to identify a better policy. This mattered: the best recorded Gemini run exceeded
the planner on one seed, which tells us the planner is a useful baseline rather
than an oracle.

The reference planner gets the same published briefing as the agent. It uses a
small dynamic programme for market/sowing choices and books repairs when it sees
damage. It does not receive hidden state. The benchmark therefore measures an
agent against a repeatable operational policy, not against an omniscient optimum.

## 9. What did we run, and what happened?

The current report covers 17 Harbor + OpenCode trials on the `normal-winter`
task: seven Gemini 4 Hydrogen trials, seven Claude Sonnet 5.5 trials and three
Claude Haiku 5.5 trials. Each trial has the Harbor record, full trajectory,
replayed trace, final ledger and a readable day-by-day log committed under
`runs/normal-winter/`.

| Grower | Mean score | Runs | Interpretation |
|---|---:|---:|---|
| Reference planner | 0.800 | 3 deterministic seeds | The planned comparison point |
| Gemini 4 Hydrogen | 0.781 (95% CI 0.751–0.814) | 7 | Close on average; 2/7 runs beat the planner |
| Claude Sonnet 5.5 | 0.695 (95% CI 0.518–0.799) | 7 | Below planner with high variation; one run ended on day 9 |
| Claude Haiku 5.5 | 0.622 (95% CI 0.539–0.668) | 3 | Clearly lower in this small sample |
| Stop early / harvest early / naive / nobody | 0.24 / 0.10 / 0 / 0 | deterministic | Sanity checks that shortcuts do not score well |

The analysis found these trajectory-level behaviours:

- **Market-window errors:** a Haiku run sold 2.2 t of broccoli for €0 after
  filling the rolling-week window; 6 of 17 runs held radish past its strongest
  market week.
- **Failure to revise:** 8 of 17 runs left a boiler broken for more than a week;
  the reference books repair on the first morning it observes the damage.
- **Lost pending work:** 10 of 17 runs attempted planting before their seed order
  had landed.
- **Tool-schema fragility:** 6 of 7 Gemini runs made malformed actions of one
  observed kind (`part` instead of `part:glass_pane`).

These are not anecdotes extracted from chat text. The analysis replays each
recorded trace hour by hour against the simulator. The source tables and links
are in [`runs/ANALYSIS.md`](../runs/ANALYSIS.md) and
[`runs/TRAJECTORIES.md`](../runs/TRAJECTORIES.md).

## 10. How to explain the “gap” honestly

Use this sequence in a presentation:

1. A single decision is easy to make plausible: heat a cold greenhouse, harvest
   a ready crop, order seed.
2. The environment makes each decision depend on delayed downstream state.
3. The reference planner converts the same observations into a stable policy.
4. Frontier runs can sometimes beat it, proving the task is not impossible.
5. Yet their average result is lower and their traces reveal repeatable failure
   patterns: over-selling, unrepaired failures and forgotten pending orders.
6. Therefore the gap is not raw language knowledge; it is reliable execution of
   a stateful, constrained plan over many irreversible turns.

Avoid these overclaims:

| Do not say | Say instead |
|---|---|
| “LLMs cannot do this.” | “The evaluated models were not reliably as good as the reference policy on this task.” |
| “This is a real Dutch farm.” | “This is a research-informed, Dutch-winter greenhouse abstraction.” |
| “All parameters are real-world measured.” | “Inputs and model structure are sourced where possible; calibrated and design values are explicitly labelled.” |
| “The planner is optimal.” | “The planner is a transparent, beatable comparison baseline.” |
| “17 runs prove a frontier-wide ranking.” | “17 runs provide initial evidence with wide uncertainty, especially for Sonnet and Haiku.” |

## 11. Limitations to volunteer before a judge finds them

Being candid increases credibility.

- The sample is small: two or three attempts per model/seed in most cells, and
  the confidence intervals overlap in places.
- The best Gemini run beat the reference, so there is no claim of an absolute
  frontier gap.
- The reference is a heuristic planner, not a solved optimum.
- Some rules are deliberately sharp—for example the rolling demand window—and
  should be explained as published rules tested equally for everyone.
- There is an open repair-rule issue: storm-glass outages were not fully repaired
  in the current recorded runs, including the reference. It is ranking-neutral in
  those comparisons but remains a design concern.
- Harbor and OpenCode versions are pinned and used, but the official AfterQuery
  starter kit has not yet been run against the task. Do not claim official
  event-kit compatibility until that test is complete.

## 12. A five-minute walkthrough script

1. “LettuceBench asks an agent to run a Dutch winter greenhouse for 42 days.
   Profit—not narration—is the only score.”
2. “Every morning it sees operations, crops, forecast and market state, then has
   one `submit_day` call. The hourly world runs until tomorrow.”
3. “It must coordinate three crop houses with a shared CHP, boiler, buffer, CO2
   and grid; weather and energy inputs are recorded Dutch series.”
4. “The hard part is delayed coupling: seed ordered today arrives in ten days;
   then crops grow for 8–12 days; then a short quality window must coincide with
   a weekly buyer window.”
5. “We replay every agent call in a separate verifier. The model cannot see the
   seed or award itself a score.”
6. “A transparent planner sees the same briefing and scores 0.8 by construction.
   The evaluated models were close but less reliable on average. We can point to
   specific replayed failures rather than just a final number.”
7. “The benchmark is realistic in structure and data-informed in parameters, but
   it is not a claim to be a complete commercial-farm digital twin.”

## 13. Where to inspect or reproduce the evidence

- Benchmark and current headline results: [`README.md`](../README.md)
- Full mechanics: [`GREENHOUSE_SPEC.md`](GREENHOUSE_SPEC.md)
- Design rationale and decisions: [`GREENHOUSE_BENCH_CONTEXT.md`](GREENHOUSE_BENCH_CONTEXT.md), [`DECISIONS.md`](DECISIONS.md)
- Crop source tags and calibration rationale: [`CROPS.md`](CROPS.md)
- Verifier/trust boundary: [`BACKEND.md`](BACKEND.md), [`HARNESS.md`](HARNESS.md)
- Replayed results: [`runs/ANALYSIS.md`](../runs/ANALYSIS.md), [`runs/TRAJECTORIES.md`](../runs/TRAJECTORIES.md)

For a code/data check after editing this document, run:

```bash
bash scripts/quick.sh
```

No model run is needed to validate this explanatory-document change. Full
benchmark commands are intentionally excluded because they run 42-day episodes.
