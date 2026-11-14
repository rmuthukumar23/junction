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

## Watch out

- An exploit judges will try is harvesting everything early. Your minimum sellable weight blocks it. Test it.
- Growth must not reward extreme settings: no CO2 benefit beyond saturation, a temperature optimum, high light raising tipburn.
- Keep `step` fast: about 1,000 hours × 12 sub-steps × 8 batches, and the reference planner simulates ahead too. Avoid allocations in the hot loop.

## Prompt for your coding agent

> Read `AGENTS.md`, `docs/collaboration/README.md`, `docs/collaboration/lucas.md`, sections 3.1, 5 and 6 of `docs/GREENHOUSE_SPEC.md`, and `src/greenhouse/contracts.py`, `src/greenhouse/config/base.py`, `src/greenhouse/config/curves.py`. I own only the files listed in lucas.md. Do the tasks in lucas.md in order, test first, using `unittest`. Every crop value goes in `data/crops/*.toml` with a source comment, read through `Table`. No numbers in Python. Don't edit files I don't own. If you need a change to `contracts.py`, stop and tell me. Run `uv run --no-sync python -m pytest tests -q` before saying a task is done.
