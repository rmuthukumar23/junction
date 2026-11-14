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

## Watch out

- Doing nothing and stopping early must earn about 0. You own the costs that make that true (wages from hour 0) and the rule that standing crop counts for nothing.
- Spamming orders or repairs must cost money and worker-hours. Test that 50 repairs in a row are clearly worse than none.
- Every ledger number must be explainable from the trace: no hidden bonuses.

## Prompt for your coding agent

> Read `AGENTS.md`, `docs/collaboration/README.md`, `docs/collaboration/rowan.md`, sections 3.4, 3.5, 5, 7, 8 and 9 of `docs/GREENHOUSE_SPEC.md`, and `src/greenhouse/contracts.py`, `src/greenhouse/config/base.py`. I own only the files listed in rowan.md. Do the tasks in rowan.md in order, test first, using `unittest`. Every price, lead time, wage and event rate goes in `data/` TOML files with a source comment, read through `Table`. No numbers in Python. Randomness only from named `Rng` streams. Policies use only the tool client, never simulator internals. Don't edit files I don't own. If you need a change to `contracts.py`, stop and tell me. Run `uv run --no-sync python -m pytest tests -q` before saying a task is done.
