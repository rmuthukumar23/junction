# Worklog: opening a real planning gap (branch `emre/planning-gap`)

Goal: frontier models (Gemini 4 Hydrogen, Claude Sonnet 5.5) should score consistently below the
reference (0.80), because the task demands planning they get wrong, not because anything is
hidden or broken. Pushed every ~30 min; newest entries at the bottom.

## Starting point (main @ 1424712)
- Rules: weekly demand per crop with a firm week-by-week order book (price falls to 0 at 2x demand),
  seed lead time 240 h, order ids that survive tool layers.
- 15 model runs under the previous rules (weekly order book, 72 h seed; `runs/archive/schedule-3day-seed`):
  Gemini mean 0.791, Sonnet 0.776, Haiku 0.543, reference 0.800. Top models tie the reference.

## Analysis of the 15 runs (replayed under the rules they were played on)
- Total demand is about 24 t broccoli + 15 t radish = EUR 1.05 M at list price; the benches can grow
  about twice that. Overshooting was cheap (1.2x demand still fetched ~80 % of the price), so "grow
  plenty" was nearly free and the only way to lose was to undersupply.
- Reference: revenue EUR 1.05-1.14 M, lost EUR 223-265 k (17-18 %) to oversupply; still tied the best models.
- Good model runs (EUR 950 k-1.0 M) sold 25-30 t broccoli; weak ones (Haiku, the 0.71-0.75 Sonnet/Gemini
  runs) sold 10-30 % less, with whole weeks missed (e.g. Sonnet 0.708: EUR 90 k in week 5).
- Conclusion: the decision that separates runs (how much to sow, when) was forgiving in one direction.

## Change 1: steep glut (`glut_at`, market file)
- The price now reaches 0 at 1.25x the week's demand (was 2x). Surplus fresh microgreens find no buyer.
- Check: replaying the 15 old runs with this rule and the old reference re-tuned -> reference EUR 745 k,
  models' old play scored HIGHER (Gemini 0.88, Sonnet 0.86): the reference's "top up the bench" sowing
  was lumpy and the steep glut punished lumps. So the reference had to become precise.

## Change 2: the reference is a production planner (`policies/reference.py`)
- `daily_area`: each morning sow the area whose harvest, about one cycle later, supplies that future
  week's demand / 7 per day (yield per m2 = ready weight x density x `yield_factor`).
- Seed ordered for the sowing plan over the lead time plus cover.
- Tried and dropped: a daily seed pipeline (no gain: bench space, not seed, binds in peak weeks).
- `hold_for_market` turned on (`hold_frac = 1.0`): hold a ready batch while this week's sales already
  meet demand and it keeps top grade 1.5 days more. Matters now because the 12 starting batches ripen in
  week 1 (broccoli demand x0.6) and week 2 is the peak (x1.5).
- Tuned on seeds 4-6 only (models are scored on 1-3): EUR 672 k -> 711 k with holding.
- Finding: days 9-17 have no sales for anyone (10-day seed + growth); unavoidable, same for every player.

## Result of the first run on the current rules (2026-11-15)
- Gemini 4 Hydrogen, seed 1: **0.99**, profit EUR 823 k vs reference EUR 710 k. The gap did NOT open;
  Gemini beat the reference.
- Ledger vs reference: revenue 913 k vs 839 k, seedlings 34 k vs 51 k, electricity 17 k vs 33 k,
  23 harvests vs 52. Gemini sowed few large plantings (days 13, 20, 26, 28, 34) and cut whole batches late.
- So the reference is not near optimal: it spends more seed and power for less revenue. Next: find
  where its revenue is lost (weight at cut vs price/glut) and fix the reference, then re-check.
- Sonnet 5.5, seed 1: **1.00**, profit EUR 883 k (revenue 969 k). Both models beat the reference.

## Why the models won (sales logged per harvest, `artifacts/an/sales.py`)
- The demand is counted over a rolling 168 h window. After a big week, the reference kept selling a
  steady stream into the next (small) week while the window still held the big week's sales: glut
  prices (e.g. 2.5 t radish for EUR 8 k in week 3).
- Sonnet and Gemini sold in **bursts**: one big cut per crop per week, sized to that week's demand,
  timed after the window cleared, and nothing in between (Sonnet sold no radish at all in weeks 1 and 3).
- They also spent less: electricity EUR 17 k vs 30-33 k (lamps 16 h, not 24 h), wages 17-18 k vs 23.5 k
  (released a worker; harvest labour is small), seed 34 k vs 51 k.

## Change 3: the reference sells in bursts (`policies/market_plan.py`, new)
- Cut timing: each morning the ready batches (most urgent first) are priced at every hour they could
  still sell (today or a later morning while they keep a grade) against its own sales log and the
  published rule; cut today only if today is best. Quality from the ready alarm, not the noisy estimate.
- Sowing: a small dynamic programme picks the burst hours (one window apart, within the planting
  deadline) that sell the most at full price; each burst is sown so it is ready just before its hour.
  Grow time is measured from its own sowings (default 0.65 x nominal days at full light).
- No hire for the last harvests (labour is small).
- Result: reference EUR 807 / 792 / 730 k on seeds 1-3 (was 710-ish), mean 780 k on seeds 1-6.
- Rescored model runs (seed 1): Gemini 0.815, Sonnet 0.873. **Still above the reference.**
- Known weak spots of the reference: the starting batches ripen into a glut in weeks 0-1 (models
  ran fewer lamp hours, which slows them); a burst that finishes an hour earlier than last week's
  is blocked by the window and slips a day (knife edge of the rolling window); lamp hours.
