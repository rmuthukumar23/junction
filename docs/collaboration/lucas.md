# Lucas: crops

You own everything about how a plant grows, gets stressed and is harvested. Nothing about any one vegetable is hardcoded: lettuce and basil are two data files read by one generic model. Read [README.md](README.md) first, then spec sections 3.1, 5 and 6.

## Files you own

| File | What |
|---|---|
| `src/greenhouse/config/crop.py` | `CropSpec` (frozen dataclasses) and `parse_crop(raw, source) -> CropSpec`, built with `Table` and `parse_curve` |
| `src/greenhouse/world/crop.py` | The growth model registry (`MODELS = {"leafy_vanhenten": LeafyVanHenten}`, `model_for(spec) -> GrowthModel`) and the models themselves |
| `data/crops/lettuce_butterhead.toml`, `data/crops/basil_genovese.toml` | The values, with a comment giving the source of each |
| `tests/greenhouse/test_crop*.py` | Your tests |

**Don't edit:** `contracts.py` (ask Max), anything under `world/` other than `crop.py`.

## What you provide, and to whom

- `model_for(spec) -> GrowthModel` in `world/crop.py`, one model per crop spec (`GrowthModel` is in `contracts.py`, with a `crop_id` attribute). `sim.py` already calls `new_batch`, `step` every sub-step, `estimate` for `get_batches`, `harvest`, and the planning helpers `labour_hours("plant" | "harvest", area_m2)`, `seedlings_needed(area_m2)` and `min_days_before_end()`.
- `transpiration_kg_h` and `co2_uptake_kg_h`, which Emre's climate balance uses. Agree the units with Emre early.
- `HarvestResult`, including `grade` and `price_factor` from your crop file's grades. Rowan multiplies the market base price by `price_factor`.
- `describe()`: the crop's published rules for `get_rules`, as plain JSON.
- `tests/greenhouse/fakes.py` (`FakeCrop`) shows the expected shape with toy numbers. Copy the shape, not the numbers.

What you consume: a `ClimateSample` each sub-step. Write tests with hand-made samples; you don't need Emre's code.

## Tasks, in order

1. **Schema.** `parse_crop` for the file layout in spec 3.1. Every key is read through `Table`; `t.done()` at the end. Test: lettuce loads; a missing key, a stray key, a negative density and an unknown `growth_model` each fail, naming the key.
2. **Lettuce model (`leafy_vanhenten`).** Use the Van Henten (1994) lettuce model: dry weight from canopy photosynthesis (light, CO2, temperature) minus maintenance respiration, with canopy closure. Put every coefficient in the data file. Sources: van Straten et al. 2010, chapter 6; Boersma and van Mourik (WUR, edepot.wur.nl/693301); context doc section 6. Convert dry to fresh weight with a data-file ratio.
3. **Behaviour tests (these matter most).**
   - Under target climate (20 °C day, 900 ppm, DLI around 15), a batch reaches harvest weight in about `nominal_days` (±15%).
   - At 5 °C with low light it barely grows. At 0 ppm extra CO2 it grows slower than at 900 ppm.
   - Stepping 12 × 5 min gives the same result as stepping 1 hour, within 1%. This catches sub-step bugs.
   - Same inputs give the same output, bit for bit.
4. **Stress and quality.** Counters named in the crop file (`tipburn`, `bolting`, `cold`), each a curve on a signal (`dli_excess`, `temp_day_mean`, `temp_min`). Quality = 1 minus the combined stress, clipped to 0..1. Below `frost_kill_c` the batch is lost. A ready batch that waits loses quality at a data-file rate per day.
5. **Harvest.** Below `min_sellable` it is sellable = False (the anti-exploit for harvesting early). `single` crops become harvested. `repeated` crops (basil) keep `regrow_fraction` of their weight, regrow, and allow at most `max_cuts`.
6. **Basil file.** Same model, warmer targets, `harvest_mode = "repeated"`, `unit = "kg"`. If the leafy model can't represent basil reasonably, add a second registered model rather than a special case.
7. **Pluggability proof.** Add a test fixture `tests/greenhouse/fixtures/spinach.toml` with different values. It must load and grow with zero code changes.
8. **Estimates.** `estimate()` adds noise from the stream it is given, with σ from the crop file. Calling it twice for the same hour gives the same answer.

**Done when:** all of the above have tests, `pytest tests -q` passes, and the two data files cite their sources.

## Next steps (round 2, after `lucas/crops`)

Your branch has tasks 1–8 (schema, `leafy_vanhenten`, lettuce, basil, spinach fixture, estimates). It merged `main` before the full `GrowthModel` interface landed, so it is not merged yet.

1. **Rebase onto `origin/main`** and open the PR.
2. **Add the four methods `sim.py` calls that `LeafyVanHenten` lacks:** `labour_hours("plant" | "harvest", area_m2)`, `seedlings_needed(area_m2)`, `min_days_before_end()` and `describe()` (the crop's published rules as JSON for `get_rules`). Their values (worker-hours per m², planting density, days needed) go in the crop files with sources.
3. **Fill `grade` and `price_factor` on every `HarvestResult`.** The business sells at market price × `price_factor`; 0 when not sellable.
4. **Play it in the game:** a test that runs your model in place of `FakeCrop` on the fake fixture for 10 days (copy the builder pattern in `tests/greenhouse/test_business.py`). Check speed: about 1,000 hours × 12 sub-steps × 8 batches must stay well under a few seconds.
5. **D5 research (spec 7):** how fast a ready but unharvested batch loses quality and when it becomes unsellable; with that, doing nothing loses its crop.
6. **D8 research (open, don't build yet):** nutrient (fertiliser) uptake per m² per day for lettuce and basil, so nutrients can become a consumable after v1.

## Next steps (round 3: lettuce timing, frost, weather signals)

Round 2 is on `main`. Read context section 0 (especially 0.8 and 0.9) and spec sections 14.3 and 14.4. This round you also hold Emre's weather files (`world/weather.py`, `data/climates/`, `data/energy_prices/`); #15 already put the recorded series in, with separate development and evaluation windows.

1. **Lettuce timing.** About 24 days from transplant to harvest at DLI 17 (Cornell), scaling roughly with light (half the light, about twice as long). 24/19 °C day/night are targets, not maxima. Retune `leafy_vanhenten` and the lettuce file, and test the 24-day and the half-light cases.
2. **The 5 °C baseline (D5 revised).** Under 5 °C for 42 days, crops survive but stall below sellable weight. Frost damage hits only near-ready batches. Test both.
3. **Start-batch ages** for the 24-day cycle and the 42-day horizon: propose new ages to Max (they sit in the facility file, which Max holds this round), so a replanting choice still matters before the end.
4. **Plugs research:** propagator lead time (2–3 weeks, longer in winter) and plug price per plant, with sources. Give the numbers to Rowan for the market file.
5. **Weather-based signals:** from the recorded weather, the hours that count as a storm (wind threshold) and a frost night (temperature threshold), as data values. Rowan's storm event and news feed read them. Forecasts must stay a pure function of (seed, issue hour).
6. **Sanity check** against the Wageningen 2022 Autonomous Greenhouse Challenge lettuce data (4TU.ResearchData, CC BY 4.0): weight over time under a similar climate. Record what you compared and the result in DECISIONS.
7. **Later, don't build yet:** pests (context 0.8) and in-house sowing. If you have time, write their crop-file fields as a proposal.

### Measured on the real game (Max, 14 Nov, for task 1)

- Under the standing settings, compartment A gets on average **14.7 °C, 513 ppm CO2 and DLI 10.1** over 14 days, against the 19 °C, 900 ppm and DLI 14.5 at which `nominal_days` holds. So the crops grow slower than their files say: a 24-day-old lettuce batch was ready at hour 395 (about 40 days in total instead of 32), and a 20-day-old basil batch at hour 539 (about 42 days instead of 28). That is the model responding to less light, CO2 and heat, not a bug. But the agent reads `nominal_days` from `get_rules`, so publish how the cycle scales with DLI and temperature, or it will plan with the wrong length.
- New for test scenarios: overrides can address an array item by id, for example `"facility.compartments.A.start_batches" = [...]` (used in `scenarios/smoke.toml`).

### Max changed your tests on `lucas/judge-ready` (quick suite vs benchmarks)

- `tests/greenhouse/test_scenario.py` plays whole 42-day episodes, so it is now skipped unless `ENVKIT_TEST_SCENARIO=normal-winter` (module-level `SkipTest`). Its money check allows float rounding (`< 1e-6` instead of `== 0.0`; it failed with 5.7e-10).
- A merge leftover in `tests/envkit/test_schema.py` (a stray `p["note"]` line, `NameError`) is removed.
- `normal-winter.toml` is marked `benchmark = true`: its `tasks/` and calibration are built only at benchmark time (`envkit build normal-winter`), no longer committed day to day. The quick check is `bash scripts/quick.sh` (about 30 s); your old one-attempt `quick.sh` is now `scripts/model-smoke.sh` on the smoke task. See AGENTS.md, "Checks and handoff".

## Watch out

- An exploit judges will try is harvesting everything early. Your minimum sellable weight blocks it. Test it.
- Growth must not reward extreme settings: no CO2 benefit beyond saturation, a temperature optimum, high light raising tipburn.
- Keep `step` fast: about 1,000 hours × 12 sub-steps × 8 batches, and the reference planner simulates ahead too. Avoid allocations in the hot loop.

## Prompt for your coding agent

> Read `AGENTS.md`, `docs/collaboration/README.md`, `docs/collaboration/lucas.md`, sections 3.1, 5 and 6 of `docs/GREENHOUSE_SPEC.md`, and `src/greenhouse/contracts.py`, `src/greenhouse/config/base.py`, `src/greenhouse/config/curves.py`. I own only the files listed in lucas.md. Do the tasks in lucas.md in order, test first, using `unittest`. Every crop value goes in `data/crops/*.toml` with a source comment, read through `Table`. No numbers in Python. Don't edit files I don't own. If you need a change to `contracts.py`, stop and tell me. Run `uv run --no-sync python -m pytest tests -q` before saying a task is done.
