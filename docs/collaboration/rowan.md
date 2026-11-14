# Rowan: operations, events, money and scripted policies

You own everything about running the business: the market, orders that arrive days later, staff and worker-hours, events, the money ledger, the final outcome, and the scripted policies that prove the reward works. Read [README.md](README.md) first, then spec sections 3.4, 3.5, 5, 7, 8 and 9.

## Files you own

| File | What |
|---|---|
| `src/greenhouse/config/market.py` | `MarketSpec`, `EventSpec`, and their `parse_*` functions |
| `src/greenhouse/world/operations.py` | Stock (CO2 kg, seedlings per crop), orders with lead times, minimum quantities and late-delivery events, staff (crew, hiring with notice, release), task queue for plant, harvest and repair using worker-hours |
| `src/greenhouse/world/events.py` | Event schedule drawn per seed from rates (stream `events`); turns events into `EquipmentEffect`s and `Alarm`s |
| `src/greenhouse/world/ledger.py` | Records `LedgerEntry`s, prices `Metered` and `HarvestResult`, totals by category, money conservation check |
| `src/greenhouse/world/business.py` | `build_business` and `Business`: the `BusinessModel` sim.py calls, over your operations, events and ledger (Max wrote the first version; yours now) |
| `src/greenhouse/outcome.py` | `profit_eur`, the ledger dict the scorer reads, failure-mode fields (`fm_*`) |
| `src/greenhouse/policies/{naive,rule_based,exploiter}.py` | Scripted policies (spec 9), playing through tools only |
| `data/markets/nl_winter.toml`, `data/events/*.toml` | The values, with sources |
| `tests/greenhouse/test_{ops,events,ledger,outcome,policies}*.py` | Your tests |

**Don't edit:** `contracts.py` (ask Max), crop or facility modules.

## What you provide, and to whom

- **One object implementing `BusinessModel` (in `contracts.py`)**, built by `build_business(market, events, crop_ids, equipment_ids, horizon_h, rng)` in `world/business.py`. `sim.py` already calls it: `start_hour` (events due), `end_hour(hour, metered)` (price energy, wages, task progress, deliveries), `place_order`, `cancel_order`, `hire`, `release`, `take_seedlings`, `queue_task`, `sell`, `cash_eur`, `profit_eur`, `totals`, `view`, `rules`. Inside it, split operations, events and ledger however you like. `tests/greenhouse/fakes.py` (`FakeBusiness`) shows the expected shape with toy numbers. Copy the shape, not the numbers.
- Staff, start cash and starting seedling stock live in the market file (yours). The CO2 store level is physical and belongs to the facility (Emre): a CO2 `Delivery` you return is passed to `facility.receive_co2` by `sim.py`.
- `outcome.ledger(sim) -> dict[str, float]` with `profit_eur` (the scored metric) plus `fm_*` evidence fields. Max wires it into `env.py`.
- The policies Max registers in `env.policies()`.

What you consume: `HarvestResult` (from Lucas) and `Metered` (from Emre). Write tests with hand-made instances; you don't need their code.

## Now (14 Nov): test and benchmark the base version on `max/locked-crops`

**This comes before everything below.** Max builds the day/night shift in parallel on his own branch; you make the base version (no round 3) solid and measured.

**What changed** (DECISIONS, "Locked crop set"; the notes below list the edits to your files):
- The crops are locked for the whole hackathon: lettuce, broccoli microgreens, radish microgreens (`data/crops/`, values in `docs/CROPS.md`). Basil is deleted. No germination phase; microgreen seed is the `seedlings:<crop>` item, priced per seed.
- The main scenario `normal-winter` runs `data/facilities/nl_three_compartment.toml`: A and B broccoli (12 days), C radish (8 days), start batches at staggered ages. `smoke` uses the same setup for 1 day. A scenario chooses each compartment's crop in its facility file.
- The reference and rule-based policies were fixed for short, by-weight cycles; not run on 42 days yet.

**Your tasks, in order:**
1. `git fetch && git switch max/locked-crops` (or `main` once merged), then `bash scripts/quick.sh`. It last passed on the crops commit; the scenario commit is untested. Fix what breaks.
2. One cheap model on the smoke task on Modal (docs/MODAL.md, "Smoke checks").
3. **Benchmark checks: you are authorised to run these** (the user asked for them for this task, overriding the AGENTS.md default): `ENVKIT_TEST_SCENARIO=normal-winter uv run --no-sync python -m pytest tests -q`, `uv run --no-sync envkit build normal-winter`, `uv run --no-sync envkit audit`. Record seed, command, scores and failures in the PR.
4. Check the ladder: reference > rule-based > naive > do-nothing (0), every policy inside 400 calls (the reference's daily seed orders add about two calls a day), and no exploit above the reference.
5. **Balance (yours):** microgreens earn about 16 times lettuce per m², and any amount sells at list price. Add a daily demand cap per microgreen in `config/market.py` and the market file (list price up to the cap, a surplus price above), or lower the prices, so that the reference does not score by just maximising area and lamps. Microgreens have no upper light limit, so lamps flat out costs only electricity.
6. You may edit `policies/reference.py` for this work (shared with Max). Don't touch the shift clock, `env.py` or `sim.py`: Max is changing them for day/night.

## Tasks, in order

1. **Schemas** for market and event files (spec 3.4, 3.5). Test: the files load; bad keys fail.
2. **Ledger.** Categories exactly as `LedgerCategory` in `contracts.py`. Fixed crew wages are charged every hour from hour 0, whether or not anyone acts (this is what makes do-nothing negative). Money conservation: start cash + sum of entries = cash.
3. **Orders and stock.** `place_order(item, quantity)` checks the minimum quantity and returns the expected arrival. Delivery adds stock and charges on arrival. A late-delivery event pushes the arrival back and raises an `Alarm`. Test: a CO2 order placed at hour 10 with a 72 h lead time arrives at hour 82, not before.
4. **Staff and tasks.** A daily worker-hour pool from crew × hours per day. Tasks consume hours in queue order and wait when the pool is empty. Hiring arrives after notice days with a fee. Test: a harvest queued with no hours left completes the next day.
5. **Events.** Draw the schedule at episode start from `rate_per_day`, on its own stream, so agent actions can't change it. Each event yields an `EquipmentEffect` and an `Alarm`. A repair shortens the outage at a cost in money and worker-hours.
6. **Outcome.** `profit_eur`, and `fm_*` fields read after the run: days CO2 stock was empty, harvests that waited, unsellable harvests, kWh bought at peak price, events handled late.
7. **Policies.** The tools already exist in `src/greenhouse/env.py` and run on fakes: develop against `tests/greenhouse/fixtures/fake-winter.toml` (see `tests/greenhouse/test_sim_env.py` for how to drive an `Episode`). `naive` and `rule_based` as described in spec 9, using only `client.call(tool, args)`. Then `exploiter`: one sub-policy per exploit in spec 8, each of which must score about 0.
8. **Reference planner** (with Max, phase 3): rule-based plus a 48-hour look-ahead.

**Done when:** ledger, ops and events have tests; profit is reproducible bit for bit; naive < rule-based in profit on seeds 1–3; the exploiter scores at most 0.05.

## Next steps (round 2, after PR #12)

Tasks 1–6 are on `main`. Max wired them into the simulator with `world/business.py` (the `BusinessModel` adapter) and `tests/greenhouse/test_business.py`, which runs your real market and event files inside the game with the fake facility and crops. Pull `main` first.

1. **Review `world/business.py`; it is yours now.** Two contract rules it applies: CO2 deliveries go straight to the facility's store (Emre), and the sale price is the market crop price × the crop model's `price_factor` (Lucas grades, you price).
2. **Clean up CO2 in the market file and ops.** The business never holds CO2 any more: drop `start_stock.co2_kg` and the CO2 `warn_below` (the facility raises the low-store alarm), and move `fm_co2_*` evidence out of `Operations` (ask Emre to report store-empty hours from the facility).
3. **Policies (task 7)** against `tests/greenhouse/fixtures/fake-winter.toml`: `naive`, `rule_based`, then `exploiter`. The tools all exist.
4. **D5 research (spec 7):** realistic rates for what goes wrong when nobody acts: how often a greenhouse of this size refills its CO2 tank, seedling lead times, what an unrepaired boiler costs. Put the values with sources in your data files.
5. **Tell Max** if a per-occurrence event range matters to you: the loader currently draws every `{min, max}` once per seed, so all boiler trips in one run have the same duration.
6. **Reference planner** with Max once the real facility lands.

## Round 3: built by Max's session (14 Nov 2026), please review

A Sonnet subagent built your round-3 list in your files: the persistent boiler trip, the storm on the recorded wind, the surge, parts with surge and express, contractors (`world/contractors.py`), `book_contractor`, the news feed (`world/news.py`, `data/news/`), the new ledger categories and `fm_*` evidence. The policies now play a daily turn (DECISIONS, "Round 3 built"). The quick suite passes. Check the values in `data/events/storm.toml`, `data/markets/nl_winter.toml` and `data/news/` (all [DES]).

## Next steps (round 3: damage, contractors, parts, news)

**Deferred (14 Nov):** storms, damage, contractors, parts and news are not in the base version. Don't start them; the day/night shift is Max's.

Round 2 is on `main` (#14). Read context section 0 (especially 0.3, 0.5 and 0.7) and spec sections 14.2, 14.3 and 14.5. Start with the data and schemas now; wire them to the new contract types once Max's contracts PR lands (within the hour).

1. **Storm event.** A new event kind that fires when the recorded wind passes a data threshold (you get the hour's weather in `start_hour(hour, weather)`). Damage per occurrence and seed: panes broken in `A.glass` / `B.glass`, 0 possible. The effect lasts until repaired (`until_hour = None`). A storm is regional: it opens a surge window of documented length.
2. **Parts** as market items (`part:glass_pane`, `part:boiler_kit`): price, normal lead time, surge lead time, express price and express lead fraction. The lead time is fixed when the order is placed. Unused parts are worth nothing at the end.
3. **Contractors** in the market file (`[contractors.glazier]`, `[contractors.heating_installer]`): what they fix, the parts per job, call-out, hourly rate, job hours, normal and surge response. `book_contractor(trade, target)` waits for a day-shift slot after the response time **and** the parts on site; then it charges call-out and hours, uses the parts, and clears the effect when the job is done. The boiler trip now waits for the heating installer too.
4. **Ledger:** the new categories `contractors`, `parts`, `express`. Use the Wilo and Dutch price-guide ranges (context 0.7) as `{min, max}` ranges, with sources.
5. **News feed** (`data/news/*.toml` and a module of yours): signal types for storm, cold snap and gas price. Each has a lead time, a chance it appears before a real event, a false-alarm rate per day and headline texts. Drawn once at the start from a named stream, so it is identical for every agent on a seed. Never name equipment or an hour. Lucas provides the storm and frost inputs from the recorded weather.
6. **Plugs:** set the seedling items' lead times to the propagator values Lucas researches (2–3 weeks).
7. **Tests:** context 0.7 tests 1–4, and that the news feed does not change whatever the agent does.
8. **Policies under shift rules:** naive and rule-based must set a night schedule and call `end_shift`; the exploiter adds hoarding parts and booking contractors for nothing. Then the reference planner with Max.

### Max edited two of your files (merge `9790f32`, please review)

They crashed the first runs on the real game, so Max fixed them directly instead of waiting. Check the diff and keep or rewrite as you like.

- **`world/ledger.py`:** the recorded NL prices go negative in 15 development hours. `price_metered` called `earn` with a negative export income, which raised `LedgerError` and killed the run. Export now goes through `_export`, which books the signed amount in `electricity_sold` (exporting at a negative price costs money). Test: `test_exporting_at_a_negative_price_costs_money_instead_of_crashing`.
- **`policies/rule_based.py` `set_lamps`:** the real facility's forecast is `{"energy_prices": [{"import_eur_kwh", "export_eur_kwh"}, ...]}`, not a list of numbers as on the fakes. Rule-based and six exploits crashed on `sorted`. It now reads `import_eur_kwh`.
- **Also new for you:** bankruptcy ends the episode when cash goes below 0 (`sim.bankrupt_hour`, ledger key `bankrupt`), using your `start_cash_eur` (EUR 50,000). `naive` is registered in `env.policies()`, and `reference` points at naive until the planner exists.
- **Found, not fixed, yours to judge:** on the real game over 42 days, naive ends at about -EUR 16.6k (wages 22k, electricity 15k, revenue 27k), so even honest play loses money. Exploits that already run on it: harvest-early -31.8k (9 of 10 harvests unsellable), extreme-climate -42.7k.

### Max edited your market file and tests (branch `max/locked-crops`, please review)

- `data/markets/nl_winter.toml`: basil out; `[crops.broccoli_micro]` EUR 30/kg and `[crops.radish_micro]` EUR 22/kg; seed as `seedlings:broccoli_micro` / `seedlings:radish_micro`, priced per seed (EUR 0.00014 / 0.00015), 72 h lead time, minimum about 5 kg of seed. No demand cap yet: that is still yours (DECISIONS, "Locked crop set").
- `policies/reference.py` (shared with Max): cuts a single-cut crop sold by kg when ready, and reorders seedlings every day for the space that frees within the lead time (`reorder_seedlings`). `policies/rule_based.py`: seedling orders count plants (area × density), not sale units. Watch the reference's call count on 42 days: the daily orders add about two calls a day.
- **Your next run, on this branch:** `bash scripts/quick.sh`; one model on the smoke task (docs/MODAL.md); then the benchmark checks (`ENVKIT_TEST_SCENARIO=normal-winter uv run --no-sync python -m pytest tests -q`, `envkit build normal-winter`, `envkit audit`). Open for you: a demand cap or lower microgreen prices, and whether the ladder still orders reference > rule-based > naive > 0.
- Crop id `basil_genovese` replaced by `broccoli_micro` in `test_business.py`, `test_ops.py`, `test_ops_business.py`, `test_ops_market.py`, `test_policies.py`.

## Watch out

- Doing nothing and stopping early must earn about 0. You own the costs that make that true (wages from hour 0) and the rule that standing crop counts for nothing.
- Spamming orders or repairs must cost money and worker-hours. Test that 50 repairs in a row are clearly worse than none.
- Every ledger number must be explainable from the trace: no hidden bonuses.

## Prompt for your coding agent

> Read `AGENTS.md`, `docs/collaboration/README.md`, `docs/collaboration/rowan.md` (start with "Now (14 Nov)"), `docs/CROPS.md`, the "Locked crop set" entries in `docs/DECISIONS.md`, `scenarios/normal-winter.toml`, `data/facilities/nl_three_compartment.toml`, and `src/greenhouse/policies/reference.py`. Work on branch `max/locked-crops` (or `main` once merged) in your own worktree. Do the tasks under "Now (14 Nov)" in order. For this task the benchmark checks in step 3 are authorised. Every price and cap goes in `data/` TOML files with a source comment, read through `Table`; no numbers in Python. Policies use only the tool client. Don't edit `env.py`, `sim.py` or `contracts.py` (Max is changing them for day/night). Run `bash scripts/quick.sh` after every change, and end with a PR handoff: state, commands and results, remaining risk.
