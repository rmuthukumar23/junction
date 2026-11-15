# Overnight research log (Rowan's Claude session, 2026-11-15)

Not merged to main. Findings and sources that could strengthen the submission (gap, difficulty,
reward integrity, craft). Newest at the bottom. Main reviewed: e5f87b9 (release check 6/6).

## 1. Does repairing storm damage pay? (checks the "17/17 runs left damage standing" claim)

Method: play the current reference on main e5f87b9, then the same reference with every
`book_contractor` action and every `part:*` order removed (all else identical, same seed).

| Seed | Reference | No repairs | Repairing earns |
|---|---:|---:|---:|
| 1 | 876,586 | 865,554 | +11,032 |
| 2 | 893,506 | 815,484 | +78,022 |
| 3 | 907,765 | 906,443 | +1,322 |
| 101 (held out) | 834,036 | 835,148 | -1,112 |

Reading: on 3 of 4 seeds, leaving the damage standing costs 0-1.3 % of profit (at most ~0.01 of
score). Only seed 2 shows a real cost (~EUR 78 k, ~0.07 of score). So "damage left standing in
17/17 runs" is mostly a rational choice under the current prices, not a planning failure.
Recommendation: do not pitch it as a failure mode across the board; at most cite seed 2, or make
damage costlier (leakage per pane, frost risk) so that ignoring it is a real mistake.

## 2. The ceiling: the capped market leaves little room for a gap (estimate)

From `data/markets/nl_winter.toml` (main e5f87b9): broccoli 4,000 kg/week x week factors summing
to 6.0 x EUR 30 = EUR 720 k; radish 2,500 kg/week x 6.0 x EUR 22 = EUR 330 k; total EUR 1.05 M at
list price. Selling above demand (price falls linearly to 0 at 1.25x) adds at most 12.5 % of each
week's value, so revenue is capped near EUR 1.18 M. Subtract what nobody can avoid (no sales on days
9-17 because of the 10-day seed lead time plus growth; minimum wages, energy and seed, roughly
EUR 70-100 k): a realistic maximum profit near **EUR 1.0 M** (an estimate, not a solved optimum).

Measured: reference 877-908 k (seeds 1-3), Gemini 823-963 k, Sonnet up to 883 k. Everyone competent
is within ~10-15 % of the cap; the best possible score on the 0-0.8 scale is roughly 0.88-0.9.
**Implication: on mean profit a large gap is structurally impossible; the market cap saturates.**
The differences that remain are timing (rolling window) and spend, which the models already do well.

Options (design decisions for the team, not done here):
- Make planning errors costly rather than capping upside: e.g. damage that really hurts if left
  (research item 1 shows it barely matters now), frost nights with a failed boiler, seed shortages
  that last, so a bad plan loses a lot instead of a little.
- Report reliability, not just the mean (see 3): spread, worst run, share of runs below a threshold.
- Add a computed upper bound / oracle line to the README (like Vending-Bench 2's "good strategy")
  so judges see headroom honestly.

## 3. Related work: Vending-Bench (Andon Labs) frames long-horizon failure as inconsistency

- Vending-Bench (arXiv 2502.15840): a simulated vending business, ~2,000 steps and ~25 M tokens per run.
  Conclusion: some runs of top models manage the business very well, but all models struggle with
  *consistent* long-horizon coherence; top performers still hit critical failures (misread orders,
  disruptive loops), and the breakdowns are not explained by context limits.
- Vending-Bench 2 (andonlabs.com/evals/vending-bench-2; epoch.ai/benchmarks/vending-bench-2): one
  simulated year, five runs per model averaged, adds adversarial suppliers, delayed or failed
  deliveries, refunds; a computed "good strategy" reaches about $63 k/yr, far above top models.
- Relevance to us: our measured spread (Sonnet 0.18-0.87 incl. a run that stopped on day 9; Haiku
  selling 2 t into a full window for EUR 2) is the same phenomenon. A pitch built on "frontier models
  match a planner on average but are unreliable run to run, with these concrete failure modes" is
  consistent with the leading benchmark in this genre, and honest about our means.

## 4. Reliability (pass^k, from tau-bench) on our 17 runs

tau-bench (arXiv 2406.12045) defines pass^k as the chance that *all* k i.i.d. trials of a task succeed,
averaged over tasks (unbiased estimate C(c,k)/C(n,k) per task); it showed agents with ~60 % pass^1
dropping to ~25 % at pass^8. ReliabilityBench (arXiv 2601.06112) reports pass@1 overestimating
reliability by 20-40 %.

Applied to `runs/ANALYSIS.md` on main e5f87b9 (task = seed; 2-3 runs per seed; reference is
deterministic, 0.80 every time):

| Success means | Gemini 4 Hydrogen | Claude Sonnet 5.5 | Claude Haiku 5.5 |
|---|---|---|---|
| score >= 0.80 (matches the reference) | pass^1 0.28, pass^2 0.00 | pass^1 0.39, pass^2 0.11 | pass^1 0.00 |
| score >= 0.75 | pass^1 0.89, pass^2 0.78 | pass^1 0.72, pass^2 0.44 | pass^1 0.00 |
| worst / best run | 0.724 / 0.861 | 0.176 / 0.816 | 0.539 / 0.668 |

Reading: a frontier model matches the reference planner on a given seed about a third of the time,
and essentially never twice in a row on the same seed, while the planner does it every time. That is
an honest, measurable "gap" in reliability even though the means are close (0.78 / 0.70 vs 0.80).
Caveats to state with it: 2-3 runs per seed is small; the result depends on the threshold (at 0.75
Gemini is mostly reliable); the reference was tuned partly on seeds 1-3 (held-out 101-108 check
recommended before claiming).

Suggested README line (honest): "The reference planner reaches 0.80 on every seed, every time. Gemini
and Sonnet match it in about a third of runs and never twice on the same seed (pass^2 at 0.80 of
0.00 and 0.11 over 2-3 runs per seed); their worst runs fall to 0.72 and 0.18."

## 5. What AfterQuery values (for the pitch)

- Third-party analyst notes (Sacra) describe AfterQuery as selling behaviour change inside real work:
  simulated workplaces where the model uses terminals, browsers, MCP servers and APIs, with the reward
  coming from whether the job actually gets done; it sells training data, RL environments and evals.
- Pitch implication: emphasise that Greenhouse Bench is an *RL environment* as much as an eval:
  deterministic per seed, MCP tool, reward = profit replayed by a separate verifier, and per-run
  failure-mode labels (glut selling, seed stock-outs, malformed actions, early session end) that say
  *which behaviour* to correct, plus the reliability gap (item 4). Avoid claiming a large mean gap.
- No public page with the "Break the Agent" rubric was found; the rubric in
  docs/GREENHOUSE_BENCH_CONTEXT.md (gap 30, difficulty 30, reward integrity 25, craft 15; 10-min demo,
  rerun reference + 3 agent runs + do-nothing + stop-early, 15-min exploit hunt) remains the source.
