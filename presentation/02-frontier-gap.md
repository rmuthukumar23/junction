# Part 2: Why a model that knows every rule still loses (the planning gap)

Draft for the presentation. Numbers come from `runs/ANALYSIS.md` (17 model runs on `normal-winter`, seeds 1-3) unless stated. Read the honesty box (section d) before changing any wording.

## (a) Slides

### Slide 2.1: "Knowing the rules is not the same as playing the game"

- Chess: the best language models know every rule and still lose to an engine, because a game is many interacting moves and the engine never stops checking them.
- Long-horizon agent benchmarks report the same shape of failure: forgotten orders, delivery timing, drifting off plan (Vending-Bench, StoreBench, tau-bench).
- Our hypothesis: three failure patterns. (1) Missing interacting constraints. (2) Not revising after new information. (3) Losing track of unfinished work.
- We built the greenhouse so each pattern has a concrete place to bite, with nothing hidden.

**Big number:** 3 patterns, 0 hidden information.
**Visual:** left, a chess board; right, a greenhouse tile; between them the three patterns as icons. Keep the Elo equation off the slide (backup slide only).

### Slide 2.2: "Each pattern maps to one greenhouse mechanic"

- Interacting constraints: demand is counted over a rolling 168 h window, seed takes 10 days, a harvest keeps top grade about 2 days, lamps heat the house and buy cycle time, the energy centre couples power, heat and CO2. One decision touches all of them.
- Not revising: the boiler outage and storm damage appear in every morning briefing; the agent must change the plan, not repeat it.
- Unfinished work: seed ordered today lands in 10 days; a plan that was never finished (sow, then wait, then harvest into the right week) has to be carried across 42 daily turns through one tool, `submit_day`.
- Information is complete: our scripted planner reads exactly the briefing the agent reads, so a gap is a decision, not a hidden fact.

**Big number:** 10 days (seed lead time), 168 h (rolling demand window).
**Visual:** a timeline strip: order seed on day 0, seed lands day 10, sow, harvest about a cycle later, sell inside a rolling-week bracket. Mark where each pattern bites.

### Slide 2.3: "What we observe in 17 runs" (the evidence slide)

- Interacting constraints: in `claude-haiku-5-5-s2-sugfugl` the agent cut 2.2 t of broccoli into a week whose demand was already filled and sold it for EUR 0 (README figure `docs/img/market-window.svg`).
- Not revising: a tripped boiler stayed broken for over a week in 7 of the 17 runs (Sonnet 5 of 7); the reference repairs it in about 4 days.
- Unfinished work: 10 of 17 runs tried to sow with no seed in stock because the order had not landed; one run (`claude-sonnet-5-5-s2-ny8magu`) stopped acting on day 9 and the farm ran on unattended.
- Frontier-class runs average just under the planner: Gemini 4 Hydrogen 0.781 (7 runs), Claude Sonnet 5.5 0.695 (7 runs; 0.781 without the day-9 stop), Haiku 5.5 0.622 (3 runs), reference 0.800.

**Big number:** 7 of 17 (boiler left broken) next to 10 of 17 (seed stock-outs).
**Visual:** the market-window chart (`docs/img/market-window.svg`): weekly demand bars, planner sales as a steady stream placed inside the window, Haiku's burst overflowing it. Second option: `docs/img/matrix.svg` (score by seed and grower) as a small inset.

### Slide 2.4: "How we made the gap honest" (optional)

- v1 was too forgiving: selling 20 percent over demand still paid about 80 percent, and top models tied the reference (0.79 vs 0.80).
- We made oversupply cost money (price reaches 0 at 1.25x weekly demand). Two runs then scored 0.99 and 1.00, above our reference.
- Trajectories showed why: the models sold in weekly bursts, the reference dribbled into full weeks. So our reference was weak, not the models strong.
- We rebuilt the reference as a planner (+14 percent profit on held-out seeds it was not tuned on). Frontier runs then landed just below it with wide spread; 5 of 14 beat it.

**Big number:** 5 of 14 frontier runs beat the planner.
**Visual:** a dot plot of 14 frontier run scores per seed against a line at 0.800, Gemini and Sonnet in two colours, Haiku separately. Source data: `runs/ANALYSIS.md` "Every run" table.

### Slide 2.5: "What we claim, and what we do not" (closing)

- We claim: a reproducible environment where three named failure patterns are measurable run by run, with every loss traced to a decision.
- We observe, in 17 runs: the patterns above, and a spread of 0.72-0.86 (Gemini) and 0.73-0.82 (Sonnet, excluding the day-9 stop).
- We do not claim: that frontier models fail this task, a measured performance gap, or compatibility with AfterQuery's official starter kit (not run).
- Next step: more runs per cell, held-out seeds 101-108, official kit.

**Big number:** "17 runs, 3 patterns, gap not yet shown".
**Visual:** a two-column Claim / Not claimed table.

## (b) Speaker notes

**2.1.** Start from the intuition, not the Elo. A chess model knows how every piece moves. It loses because the moves interact and nothing re-checks them. That is the sentence to keep. If asked about the number: published ratings for language models vary widely by benchmark (roughly 750 to 1,800 in the 2026 sources we found), Stockfish is around 3,600, so the gap is over 1,500 points in every source. Do not say "2000" aloud unless you have checked it; the README says about 2000 and we could not confirm that figure. Then the benchmarks: Vending-Bench (Andon Labs) found runs derail over long horizons even though each step is simple; tau-bench showed GPT-4o at about 61 percent pass^1 on retail but under 25 percent pass^8, meaning consistency across repeats collapses. StoreBench is AfterQuery's own benchmark; we cite it from the challenge material, see sources. Say these are the literature's patterns and our design hypothesis, not our result.

**2.2.** Walk the timeline left to right. Seed ordered on day 0 arrives day 10, so the first fresh sale is about day 17 (the 12 starting batches cover the early weeks; days 9-17 have no sales for anyone). Demand is a rolling 168 hour window, not a calendar week: a burst that finishes an hour earlier than last week's is still inside the window and must wait a day (README "Known limits"). That is why interacting constraints bite: when to sow depends on seed arrival, grow time depends on light, light costs power at hourly prices, and sale timing depends on the window. Energy centre: the CHP makes heat, power and CO2 together, so running it for CO2 wastes heat. Say honestly that in our runs the energy centre was not where the measured losses came from; the losses were in sowing, selling and repairs (README: the money is lost in the market). Do not claim an energy-coupling failure.

**2.3.** This is the evidence slide. Every number is replayed hour by hour in the simulator and the score equals the verifier reward (`runs/ANALYSIS.md` header). Open one trajectory live: `runs/TRAJECTORIES.md` has a `DAYS.md` per run, day by day, with what the agent said, did and had refused. Best case to show: Haiku seed 2, 2.2 t broccoli for EUR 0. For not revising, point out that the outage is in every morning briefing, so it was visible, not hidden. For unfinished work, be exact: the 10 of 17 are mostly a day-11 sowing a few hours before the day-1 order landed (one day lost), per the worklog correction, not a catastrophe. The day-9 stop was an output-length step with no tool call (`"reason":"length"` in the OpenCode log); the harness ended the attempt. We keep it in the table but label it. Quote the spread honestly: the best Gemini run (0.86, seed 2) beat the planner.

**2.4.** This slide is credibility. We did not hand-pick a weak reference. We caught our own reference being beaten, found out why from trajectories, and rebuilt it. The README says the old reference was weak, not the models strong. Mention that held-out seeds 101/104/107 confirm the rebuilt planner (EUR 834 / 867 / 861 k) but the model runs are on seeds 1-3 only. Cut this slide if time is short.

**2.5.** Read the claim column slowly. Judges score "the gap" at 30 points, so the temptation is to oversell; the rubric in `docs/GREENHOUSE_BENCH_CONTEXT.md` asks for a consistent gap, reproducible across repeats. We have a measured, explained set of mistakes, not yet a consistent gap. Say so, then say what closes it: more runs per cell, held-out seeds, the official kit.

## (c) Sources

| Claim | Source |
|---|---|
| Leaderboard: reference 0.800; Gemini 4 Hydrogen 0.781 (CI 0.751-0.814, 7 runs); Sonnet 5.5 0.695 (CI 0.518-0.799, 7 runs); Haiku 5.5 0.622 (3 runs); 17 runs total | `runs/ANALYSIS.md` (Leaderboard) |
| Per-run scores, profits, failure modes (Seed stock-outs 10, Boiler left broken 7 by my count of the table, Malformed actions Gemini 6/7, Session ended early 1) | `runs/ANALYSIS.md` "Every run" table; definitions in "Failure-mode definitions" |
| Day-9 stop: one step spent its 32k-token output budget on reasoning, no tool call, OpenCode ended the attempt | `docs/WORKLOG-planning-gap.md` ("First batch"); run `runs/normal-winter/claude-sonnet-5-5-s2-ny8magu` |
| Haiku sold 2.2 t broccoli for EUR 0 into a full week | `README.md` "What we noticed", `docs/img/market-window.svg`; worklog "First batch" |
| First-run result that opened no gap (Gemini 0.99, Sonnet 1.00 against the older reference); old reference was weak; rebuilt planner +14 percent on held-out seeds | `README.md` "How we found the problem"; `docs/WORKLOG-planning-gap.md` |
| 5 of 14 frontier runs beat the reference | `docs/WORKLOG-planning-gap.md` "Final batch and report" |
| Corrections already made (glass not a model failure; radish week 0 is 6 of 17) | `docs/WORKLOG-planning-gap.md` last section |
| Rolling-window knife edge; no frontier gap; official kit not run | `README.md` "Known limits"; `AGENTS.md` |
| Rubric: gap scored on consistent score below a stronger reference | `docs/GREENHOUSE_BENCH_CONTEXT.md` (lines 159-160) |
| Do not use the Gemini 3.1 Flash-Lite run (reward 0.002) as agent failure evidence: its order failures may be a tool-schema or transport problem | `docs/analysis/r3-gemini-flash-lite-s1.md` ("Not yet attributable") |
| Vending-Bench: simple sub-tasks, long horizon, runs derail, some never sell; models tried to contact a nonexistent FBI office | https://arxiv.org/abs/2502.15840 (Andon Labs, Feb 2025) |
| tau-bench: GPT-4o about 61 percent pass^1 on retail, pass^8 below 25 percent | https://arxiv.org/pdf/2406.12045 ; ICLR 2025 abstract https://proceedings.iclr.cc/paper_files/paper/2025/hash/1b126cc38b8638e07bef37e7b2bb72bf-Abstract-Conference.html ; https://sierra.ai/blog/benchmarking-ai-agents |
| StoreBench (AfterQuery, Oct 2026): Fable 5.2 0.835; 26 percent of runs underbought; 60 runs never placed a PO | Only from the coordinator digest `presentation/00-uploaded-research-digest.md` and `docs/GREENHOUSE_BENCH_CONTEXT.md`. A web search found only an aggregator (https://welcome.ai/content/storebench-evaluating-autonomous-agents-in-live-commerce-settings) and could not confirm AfterQuery as author or the date. Re-verify at AfterQuery's own page before quoting numbers |
| Other 2026 long-horizon retail evals (optional context): RetailBench, 180-day horizon, only a small subset survives; E-Commerce Bench, year-long operation | https://arxiv.org/abs/2606.15862 ; https://www.alphaxiv.org/abs/2608.30730 (summaries only; I did not read the papers) |
| Chess: LLMs far below Stockfish. Sources disagree on the LLM number: about 750 (LLM CHESS paper, o3, different pool) to about 1,800 (one secondary report); Stockfish about 3,650 on CCRL | https://arxiv.org/html/2509.24239 ; https://github.com/lightnesscaster/Chess-LLM-Benchmark ; secondary report https://bbridgford-site.pages.dev/research/ai-chess/Reports/LLM-vs-Traditional-Chess-AI.html. The README's "about 2000 Elo" and "about 3600" are not confirmed by these; the Stockfish figure fits, the 2000 figure does not |
| Real-world CHP/energy facts used for the energy-centre note | `presentation/00-uploaded-research-digest.md` (verify before quoting) |

## (d) Honesty box

**We can say**
- "We replayed 17 Harbor + OpenCode runs of three models on `normal-winter` seeds 1-3 and read every trajectory. We observe three failure patterns in them."
- "Frontier-class runs averaged just under our scripted planner (Gemini 0.781, Sonnet 0.695 or 0.781 without one session stop, planner 0.800), with a wide spread. 5 of 14 beat it."
- "Nothing is hidden: the planner reads the same briefing the agent reads, so each lost euro is a decision."
- "Haiku 5.5 is clearly below the planner (0.622 over 3 runs, none beat it)."

**We cannot say**
- "Frontier models fail at this task" or "we have a performance gap". The mean gap is small and inside run-to-run spread, and the best runs beat the planner. AGENTS.md: no frontier gap is claimed.
- "Compatible with AfterQuery's official starter kit". Harbor 0.26.0 and OpenCode 1.19.5 are pinned; the official kit has not been run.
- Any claim about held-out seeds 101-108 for model runs; models were run on seeds 1-3 only (2-3 runs per cell, Haiku 1 per seed).
- "Energy-centre coupling causes failures". The measured losses are sowing, selling and repairs.
- Anything from the Gemini 3.1 Flash-Lite run as agent failure (possible tool-schema artefact).
- The StoreBench numbers until re-verified at the primary source; "about 2000 Elo" for chess models.

**Wording to use**
- Instead of "frontier models fail": "In 17 runs we observe three recurring failure patterns, and we can point to the day each one happens."
- Instead of "we proved a gap": "The gap to our reference is small on average and noisy; Haiku's is clear. More runs are the next step."
- Instead of "official benchmark": "Runs as a standard Harbor task; official-kit compatibility is unverified."

**Items to resolve before presenting (inconsistencies I found)**
1. AGENTS.md says model runs exist only on earlier round-3 rule sets in `runs/archive/`. README, `runs/TRAJECTORIES.md` and `runs/ANALYSIS.md` present 17 runs in `runs/normal-winter/` as "current rules" (git: commit 72f6758 "Model runs on the current rules (17)"). AGENTS.md looks stale, or the rules changed since. Confirm with the coordinator and the code SHA of those runs; until then say "on the rule set of 15 Nov" and cite `runs/ANALYSIS.md`.
2. README says the boiler was left broken in 8 of 17 runs (Sonnet 6 of 7). The table in `runs/ANALYSIS.md` flags 7 runs (Sonnet 5 of 7). I used 7. Fix README or recount.
3. The README's chess figure (about 2000 Elo) is not supported by the sources I found (range about 750-1,800 depending on benchmark). Suggest "well under 2000 on most benchmarks, Stockfish about 3,600".
4. Scores in runs are rescored against the current reference, and some verifier rewards (1.0, 0.9905) were against an earlier reference (`runs/TRAJECTORIES.md` footnote). Quote the `ANALYSIS.md` scores, not the verifier column.
