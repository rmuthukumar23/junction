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
