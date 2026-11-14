# Emre: facility, climate and energy

You own the physics of the building and the energy centre: weather outside, heat, CO2 and humidity inside each compartment, the climate computer, and the shared CHP, boiler, buffer and grid. Read [README.md](README.md) first, then spec sections 3.2, 3.3, 4 and 8.

## Files you own

| File | What |
|---|---|
| `src/greenhouse/config/facility.py` | `FacilitySpec`, `CompartmentSpec`, `EnergyCentreSpec`, `ClimateProfile`, `EnergyPriceSpec`, and their `parse_*` functions |
| `src/greenhouse/world/weather.py` | Seeded hourly weather and energy-price series from the profile files, plus forecasts with error |
| `src/greenhouse/world/climate.py` | One compartment, one 5-minute sub-step: heat, CO2 and vapour balances |
| `src/greenhouse/world/controller.py` | The built-in climate computer: setpoints and true climate to vent, screen, lamp, heat-request and CO2-request positions |
| `src/greenhouse/world/energy.py` | CHP, boiler, buffer, grid, CO2 store and external CO2; serving requests; allocation when short (spec 4.3); produces `Metered` |
| `data/facilities/nl_two_compartment.toml`, `data/climates/nl_january.toml`, `data/energy_prices/nl_winter.toml` | The values, with sources |
| `tests/greenhouse/test_{climate,energy,weather,facility}*.py` | Your tests |

**Don't edit:** `contracts.py` (ask Max), `world/crop.py` (Lucas), operations, events or ledger (Rowan).

## What you provide, and to whom

- A `ClimateSample` per compartment per sub-step, for Lucas's crop model.
- `Metered` per hour, which Rowan's ledger prices using your energy prices.
- Hooks that honour `EquipmentEffect` (capacity factor, leakage factor) for Rowan's events.
- Sensor readings for `get_status`: true value plus noise from a named stream, σ from the facility file.
- The forecast for `get_forecast`.
- **One object implementing `FacilityModel` (in `contracts.py`)**, built by `build_facility(facility, climate, energy_prices, rng)` in `world/energy.py`. `sim.py` already calls it: `substep(hour, dt_h, climate_setpoints, energy_settings, crop_loads) -> {compartment: ClimateSample}` every sub-step, `end_hour(hour) -> (Metered, alarms)` every hour, plus `fallback_climate/energy`, `check_climate/energy` (raise `RuleError`), `apply_effect`, `clear_effect`, `receive_co2`, `crop_id`, `start_batches`, `floor_area_m2`, `equipment_ids`, `view`, `forecast`, `rules`. `tests/greenhouse/fakes.py` (`FakeFacility`) shows the expected shape with toy numbers. Copy the shape, not the numbers.
- `Metered` carries that hour's energy prices (`gas_eur_per_m3`, `import_eur_per_kwh`, `export_eur_per_kwh`) so Rowan can price it without your series.
- Staff moved to the market file (Rowan). The facility file keeps the CO2 store, crops per compartment, `start_batches` and `[fallback]`.

What you consume: setpoints (spec 5, `set_climate` and `set_energy` fields), and transpiration and CO2 uptake from crops (stub them as constants in tests).

## Tasks, in order

1. **Schemas** for the three files (spec 3.2 and 3.3). Hidden parameters use `t.param` (a `{min, max}` range). Test: the files load; bad keys fail; `ranges(spec)` lists every hidden parameter.
2. **Weather and prices.** Generate the series once per seed from named streams (`weather`, `prices`). Forecast error grows with lead time. A forecast is a pure function of (seed, issue hour), so reading it twice gives the same thing. Test: deterministic, and January-plausible (mean around 3 °C, short days).
3. **One compartment's climate.** Energy balance: heating in, cover loss U·A·(T_in − T_out), leakage and ventilation loss, solar gain × transmission, lamp heat. CO2 balance: injection, crop uptake, exchange with outside air through leakage and vents. Vapour balance: transpiration in, ventilation out, condensation on the cover. Base it on the Van Henten state equations, with air volume = floor × height.
4. **Sanity tests (these matter most).**
   - No heating in January: inside ends near outside, a few degrees above it on sun.
   - Doubling floor area at the same height doubles heat demand.
   - A closed screen lowers heat demand at night.
   - Open vents drop CO2 towards the outside level.
   - 12 × 5 min ≈ 1 hour of sub-steps, within 1%.
5. **Controller.** Proportional control per actuator, from setpoints to actuator positions, within vent and lamp limits. Lamps follow the `lamp_hours` schedule. CO2 dosing pauses above a vent threshold (a data value).
6. **Energy centre.** The CHP produces heat, electricity and CO2 together at its load. The boiler covers peaks. The buffer charges and discharges with losses. The grid has import and export caps. When supply is short, allocate by priority, then proportionally (spec 4.3). **Conservation test:** heat produced = delivered + buffer change + losses, every hour.
7. **Equipment effects.** Capacity factor 0 for a boiler trip; leakage factor for a broken pane.

**Done when:** a two-compartment facility runs 42 days from data files under a fixed setpoint, deterministically, with conservation passing every hour, in under 10 s.

## Next steps (round 2, after `emre/facility-climate-energy`)

Your branch has the schemas, weather, climate, controller and energy centre, and the allocation already matches D2. It started before the `FacilityModel` interface existed, so it is the biggest piece of integration left, and the scenario waits on it.

1. **Rebase onto `origin/main`.** Delete your local `EnergySettings` and `ClimateSetpoints` and use the ones in `contracts.py` (field names `heat_cap_kw`, `co2_cap_kg_h`, `lamp_hours`, `lamp_intensity_pct`). If a field is missing, tell Max; don't fork the type.
2. **Implement all of `FacilityModel` and `build_facility(facility, climate, energy_prices, rng)` in `world/energy.py`.** Missing today: `compartment_ids`, `floor_area_m2`, `crop_id`, `start_batches`, `equipment_ids`, `fallback_climate`/`fallback_energy`, `check_climate`/`check_energy` (raise `RuleError`), `clear_effect`, `receive_co2`, `view(hour, rng)`, `forecast(hour, hours)`, `rules()`, and `end_hour(hour)` must return `(Metered, alarms)` with that hour's prices on `Metered`. Copy the shape of `FakeFacility` in `tests/greenhouse/fakes.py`.
3. **Facility file:** remove `[staff]` (it is in the market file). Make `[fallback]` the D5 handover baseline: a typical standing setting per compartment, researched, not frost protection. You own the CO2 store: its start level, capacity, and an alarm when it runs low.
4. **Play it in the game:** a test that runs your facility in place of `FakeFacility` with the fake crops and Rowan's real business for 10 days (the builder pattern is in `tests/greenhouse/test_business.py`). Equipment ids must include Rowan's event targets (`boiler`).
5. **D3, after the facility runs in the game:** replace the generated weather and prices with recorded hourly series in the data files (KNMI De Bilt; EPEX/ENTSO-E NL day-ahead; TTF gas), with sources. Each seed picks a window from a list; dev seeds 1–6 and eval seeds 101–108 use different windows. Forecast = true series + seeded error growing with lead time. Keep the series in data, never fetched at run time.
6. **D5 research:** CO2 dosing use per m² per hour, so the store runs out at a realistic pace when nobody reorders.

## Watch out

- An exploit judges will try is running the CHP flat out to sell power. Export cap and realistic price ratios must make it pay only when it really would. Test that flat-out CHP on a mild day loses money.
- Speed: this is the hot loop (1,008 hours × 12 sub-steps × 2 compartments), and the reference planner runs it ahead. Keep it plain floats; no numpy needed.
- Physics bugs become exploits. Prefer a simple, conserved model to a detailed one.

## Prompt for your coding agent

> Read `AGENTS.md`, `docs/collaboration/README.md`, `docs/collaboration/emre.md`, sections 3.2–3.4, 4 and 8 of `docs/GREENHOUSE_SPEC.md`, and `src/greenhouse/contracts.py`, `src/greenhouse/config/base.py`, `src/greenhouse/config/curves.py`. I own only the files listed in emre.md. Do the tasks in emre.md in order, test first, using `unittest`. Every facility, weather and price value goes in `data/` TOML files with a source comment, read through `Table`. Hidden parameters use `Table.param`. No numbers in Python except physical constants with a source. Randomness only from the named `Rng` streams. Don't edit files I don't own. If you need a change to `contracts.py`, stop and tell me. Run `uv run --no-sync python -m pytest tests -q` before saying a task is done.
