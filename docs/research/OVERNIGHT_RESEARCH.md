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
