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
- Sonnet seed 1 still running.
