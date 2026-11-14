# Greenhouse Bench: recovery redesign research and implementation blueprint

**Status:** research and proposed work, not a claim that the changes below are built.
**Code snapshot reviewed:** `main` at `62e0ffb` (2026-11-15).
**Branch purpose:** let the team review a fundamental benchmark change without touching the active simulator or `main`.

## Decision

Make **autonomous greenhouse recovery** the main task. The present 42-day `normal-winter` task primarily rewards repeated microgreen production. A competent agent can ignore broken glass and boiler faults and still nearly match the reference. A stronger heuristic alone may improve the score gap, but it would leave the task's most distinctive decision economically optional. Build a separate, shorter `winter-recovery` scenario on the existing simulator, with consequential and physically defensible damage, competing crop value, limited heat and repair resources, and a reference that chooses recovery actions from the same public information as the agent. Retain `normal-winter` as a regression and comparison task until the new scenario wins a genuine evaluation.

Do not claim that this change will produce a gap. The current 10-day-seed rules have **no completed frontier run in this commit**. Inspect those new runs before changing mechanics; use them as a diagnostic, not as proof of either success or failure.

## What changed on the new `main`

Commit `62e0ffb` adds:

| Change | What it does | Assessment |
|---|---|---|
| Weekly microgreen demand | Broccoli 4,000 kg/week and radish 2,500 kg/week, multiplied by a published six-week order book; marginal sale price falls to zero by twice demand. `sold_last_7_days` is public. | Addresses unlimited full-price sales, but quantities and week factors are marked `[DES]`; they are scenario assumptions, not Dutch market measurements. |
| Microgreen seed lead time | Both seed types move from 72 to 240 hours. | Makes forward planning matter in 42 days. The “phytosanitary paperwork from Italy” explanation is unsupported for this particular EU shipment; do not present it as verified fact. The 14-day `dev-winter` scenario is acknowledged as broken for planting; `quick-winter` uses the same market file and also needs a feasibility check. |
| Demand-aware reference | Plants only up to estimated future buyer demand and carries seed in flight. | Meaningful improvement, but the policy still books every repair and can keep crew and lights on when no more crops can be sown. Its actual score against current models is unknown. |
| Ordering compatibility | Adds `order_list` and normalizes escaped or alternate separators in item IDs. | Necessary fairness fix: earlier Gemini calls lost `:` in seed item keys. Validate through the pinned Harbor/OpenCode stack, not only unit tests. |
| Run analysis | Adds collection, day logs, replay, charts and archived trajectories. | Useful evidence, but this one commit adds **1,185 tracked files** and about **257,000 lines**; `runs/` is about 26 MB and generated `tasks/` about 20 MB. Keep a small, curated public evidence set and check full agent trajectories for sensitive text before publication. The new `runs/TRAJECTORIES.md` points at `runs/normal-winter/`, which is absent in this commit. |

The README still says no current model has played, reports pre-round-3 scores, says there is no microgreen demand cap, and gives obsolete seed-lead guidance. Update it only after new results are verified.

## Why the gap is structurally small

The last comparable stored evaluation is **`runs/archive/schedule-3day-seed/`**, before the new 240-hour lead time. Across five runs each, Sonnet averaged **0.776** and Gemini **0.790** against the reference's fixed **0.800** anchor; Sonnet beat it on two of five runs. These are archived rules, not a score for `62e0ffb`. Every one of those five Sonnet runs left at least three outages unrepaired, and four runs left all four unrepaired; its scores still ranged **0.708–0.818**. This is evidence that the task does not presently force recovery reasoning.

The mechanism explains the result:

- Broken glass only multiplies compartment air leakage by `1 + panes × 0.08`. A storm draws **0–12 panes per compartment** on a **1,450–1,950 m²** house. This is a relatively small roof opening, and the model has no direct crop damage from rain or exposure. The only path to lost value is through the compartment-average climate and its growth/stress response.
- Microgreen cold-quality stress starts below **6 °C**; growth may slow at warmer temperatures, but a house can suffer many “damage-hours” without losing much grade. The boiler also has substitutes: CHP heat and a buffer. Repair costs, meanwhile, are tiny compared with six-figure crop sales.
- The current reference calls `repair_damage` for every outage. That can be worse than an agent that rationally leaves a low-value fault alone. More “repairs performed” is not by itself a better policy.
- The score is anchored to reference profit and clipped to `[0,1]`. Always report **raw euro profit** and the unclipped advantage as well; a score near 0.8 alone does not reveal where recovery value came from.

The current `calibration.json` gives reference profits of about **€1.35m, €1.43m and €1.60m** on development seeds 1–3 over 42 days, for a facility of about 4,350–5,850 m². This is a plausibility warning, not a direct contradiction: [WUR Agrimatie](https://agrimatie.nl/ThemaResultaat.aspx?indicatorID=3179&subpubID=2232&themaID=2272) estimates about **€4.20/m² annual net operating result** for an *average Dutch greenhouse vegetable business*, a different crop mix and accounting basis. [Penn State Extension](https://extension.psu.edu/growing-microgreens) stresses that microgreen price and quantity depend on actual buyers and short post-harvest life. Do not use the WUR average as a literal target for a specialty crop, but do explain and sanity-check any very large modeled margin.

## The replacement task: `winter-recovery`

### Episode contract

Use a **21-day** winter episode. The agent receives the same public rules, forecasts, morning briefing and `submit_day` tool as the current game. Start with staggered, valuable crops already growing, published buyer commitments and a limited stock of glass/boiler parts. Let the episode include a recorded Dutch storm window followed by cold weather. Freeze the weather-window selection rule and development/evaluation seeds *before* frontier runs. The scenario title and prompt should openly state that the task is storm/cold recovery; the exact damage and boiler state are revealed through normal observations. False warnings remain possible. Do not hide a rule or create an impossible response deadline to force a gap.

Begin with the **existing actions and event types**. Change the facility and event *data* so a damaged house can materially lose crop value under frost and the surviving energy sources cannot always heat every compartment. Use a smaller, explicitly modeled compartment or a plausible larger pane-loss event; derive the heat loss from exposed glazing area and weather rather than inflating an unexplained multiplier. Preserve public ranges and observation of realized damage. Dutch insurer [Avéro Achmea](https://www.averoachmea.nl/kennis/voorkom-of-beperk-schade-door-storm-in-de-glastuinbouw) documents large pane losses, delayed glaziers, spare glass, emergency repair kits, and screen/vent actions after damage. Its 100-pane reserve guidance for a site up to 3 ha is **stock advice**, not a measured storm-damage distribution.

Only if the data-only version lacks a genuine choice, add one `patch_glass` action: crew-hours and a stocked emergency kit temporarily reduce exposure before the glazier arrives; permanent repair still needs parts and a contractor. Publish its cost, duration and limits. Test it for repeated-use and end-of-horizon exploits. This action has a real-world analogue in the insurer's emergency repair advice; it should not become a free “save crop” button.

Keep the reward as **settled net operating profit** from the trusted ledger, with no bonus for alarms acknowledged, repairs booked or tool calls. Existing market demand may stay, but the episode must have a finite crop inventory and no endlessly profitable resowing loop. A missed firm buyer commitment may be represented as lost revenue first; add a contractual penalty only with a plausible source and explicit public terms. Do not introduce a hidden “recovery score” or judge against knowledge of future weather.

### Reference solution

Replace “repair everything” with a public-information, receding-horizon triage policy:

1. From the briefing, estimate each standing batch's sale value, time to harvest, cold tolerance and quality margin. Read forecast frost and market commitments, using published parameter ranges where exact values are hidden.
2. Estimate heat available from CHP, buffer and boiler after visible faults. Allocate scarce heat to compartments by expected sale value preserved per kWh, accounting for actual damaged-house leakage. Recompute each morning.
3. For each repair, compare expected crop/energy loss until parts and contractor arrive with parts, call-out and labor cost; pre-stock when the public storm warning makes the expected avoided loss worthwhile. Do not inspect future event schedules or hidden simulator state.
4. Book and order in time to meet the crop's remaining sale window. Turn down energy in genuinely empty or unsalvageable compartments. Use exactly the same tool budget and schema as models.

A small documented heuristic plus limited candidate search is preferable to a large new optimizer. A published greenhouse-control study uses an economic planner above a rule-based low-level controller; it supports this architecture, not any claim of optimality: [TU Delft/WUR economic MPC](https://repository.tudelft.nl/record/uuid%3A6657147c-4d98-4252-abbc-49b892d96b1b). The reference must be stronger because it handles the **same observable tradeoffs** more consistently, not because it sees the random seed, future weather, or the judge's ledger.

### Ablation gate before frontier runs

On development seeds, compare the reference with variants that (a) never stock glass, (b) never book repairs, (c) use equal heat priority, and (d) never change the night schedule after damage. Record raw-profit differences, crop grades, heating shortfalls and repair timing. A recovery task is not ready if all four variants nearly tie the full reference. The always-stock/always-repair baseline also must **not** dominate everywhere; otherwise there is no triage decision. Keep seeds 101–108 untouched until the scenario is frozen.

This gate is more important than tweaking the normalized score. If it fails, revise **physical or commercial assumptions**, with sources, before running more expensive models. Never choose seeds because a particular model failed on them.

## Other issues and concrete fixes

| Issue | Change to implement after scenario contract review | Acceptance evidence |
|---|---|---|
| Invalid model attempts counted as zero | In `src/envkit/report.py`, distinguish structured OpenCode provider/config/auth/HTTP errors from agent timeouts and true no-op. A provider failure gets no reward and fails the judge wrapper even if the verifier legitimately grades an empty trace at zero. Apply the same classification in `scripts/benchmark_report.py` and the viewer. | Reproduce the archived `endpoint_not_supported` trial: report says infrastructure failure, not a 0-score model. A genuine no-op still scores zero. |
| Model selection | Pin provider profiles to OpenCode **1.19.5**: native Google against Google; Verda as a distinct OpenAI-compatible provider. Do not route `google/*` through `https://inference.verda.com/v1`; [Verda supports Chat Completions, Responses and model listing](https://docs.verda.com/inference/openai-compatibility/). Give the viewer verified presets plus a custom provider/model field and show the selected endpoint type without exposing keys. | One real tool call for each supported profile on the smoke task; bad ID/key/endpoint is visibly a setup failure. Do not copy current OpenCode V2 config syntax into pinned V1 without checking. |
| Market integrity | Validate demand factors as finite, non-negative and sufficient for the episode. Current code applies a new **calendar-week factor** to a **rolling 168-hour sales history**; decide and document whether this is a rolling capacity or a firm calendar-week order book, then make the formula, public rules and tests agree. | Boundary tests immediately before/after week change, large harvest crossing the cap, and replay-identical revenue. |
| Economic realism | Record revenue, seed, electricity, gas, labor and repair € per m² and per episode, plus sale volumes against public caps. Mark Dutch data, literature ranges, and `[DES]` design assumptions separately. | Profit decomposition and sensitivity table; no unsupported claim that a synthetic demand cap or 240-hour seed delivery is observed Dutch market data. |
| Measurability | Pair every valid model attempt with the same-seed reference; show raw and normalized gaps, model run count, failures, seed-level variance, and decision-linked evidence (heat allocation, bookings, missed sales). Bootstrap by **seed**, not by treating repeated attempts on one seed as independent environments. | A table for each seed and model; infrastructure attempts excluded from means; at least three valid attempts per evaluated seed, subject to the event budget. |
| Reward hacking | Keep scoring from the trusted sidecar trace and verifier. Test no-op, early stop, repeated patch/repair, surplus sales, final-hour orders, abandoned crop, negative electricity prices, illegal actions, and mutated agent files. [AfterQuery's StoreBench](https://www.afterquery.com/blog/storebench) explicitly stresses obligation settlement, exploit baselines and replay. | Audit passes on the frozen scenario; no exploit policy beats honest management by accounting tricks. |
| Craft and provenance | Curate a small reproducible run manifest, summaries and representative traces. Do not mix trajectories from old bundles with current scores; include code SHA, bundle hash, model, backend, Harbor/OpenCode versions and valid/invalid status. Update README and docs only after measured results. | Fresh-checkout judge command reproduces reference/anchors; viewer labels archived runs with their rule set and never calls an invalid zero-call run “finished.” |

## Implementation order and ownership

This branch contains research only. After the team agrees on the recovery contract, open **small isolated worktree PRs** in this order:

1. **Measurement and fairness:** classify invalid model runs; inspect the new 240-hour results; repair short-run feasibility and market-window tests. Claim reporting scripts, harness report and provider config as one file surface.
2. **Scenario and mechanics:** add `winter-recovery` and its facility/event data, with focused climate and economics tests. Reserve scenario/data and simulator files; no simultaneous reference edits to shared contracts.
3. **Reference and ablations:** implement public-information recovery triage, then run the scripted ablation gate. Reserve policy files. Do not tune on holdout seeds.
4. **Frontier evaluation:** three attempts per seed for at least Sonnet and one other frontier model, then representative held-out seeds after freeze. Publish all attempts including failures and the exact command. Use Modal only after the local tool path is valid.
5. **Submission:** revise README, viewer labels, demo narration and curated evidence to match the measured benchmark. Verify official AfterQuery event-kit compatibility; the public Harbor repository alone does not establish it.

If the current 240-hour rules already produce a robust gap, still run the recovery ablation. A supply-chain gap is useful evidence, but it does not by itself demonstrate an autonomous **recovery** benchmark. If the recovery task fails its ablation or model-gap gates, report that honestly and keep the best validated task rather than claiming a win from an invalid run.
