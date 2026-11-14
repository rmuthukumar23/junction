# Greenhouse Bench: v1 build spec

Status: draft for team agreement, 14 Nov 2026. Branch `docs/greenhouse-bench-spec`.
Background and reasoning: [GREENHOUSE_BENCH_CONTEXT.md](GREENHOUSE_BENCH_CONTEXT.md). This file fixes the interfaces so work can split up. Anything marked **DECIDE** needs a yes/no from the team before the workstream that depends on it starts.

This environment replaces Root Cause, which has been removed (`src/rootcause/`, its scenario, task, tests and docs). When v1 is built, the mechanism sections of this spec move to `docs/GREENHOUSE.md`.

---

## 1. Scope of v1

**Round 3 (pinned decisions, [context section 0](GREENHOUSE_BENCH_CONTEXT.md)) adds the day shift with a night schedule, persistent damage with contractors and parts, news signals and propagator plugs. Their interfaces are in section 14, and the v1 scope table is in context 0.10. Where this file disagrees with section 14, section 14 wins.**

| In v1 | Later |
|---|---|
| One scenario: **normal winter** (Netherlands, January), 3 dev seeds, 3 eval seeds | Cold snap, storm, disease, supply crunch, price shock |
| Two crops from data files: **lettuce** (single cut) and **basil** (repeated cuts) | Spinach, any other crop: a new data file only |
| One facility file: 2 compartments (A lettuce, B basil) on one shared energy centre | 3 compartments: a facility-file change only |
| Energy centre: CHP, boiler, heat buffer, CO2 (flue gas + external), grid import/export | Backup heater per compartment |
| Compartment climate: heating, vents, CO2, energy screen, lamps | Dehumidifier, shade screen, root zone (EC/pH) |
| Operations: CO2 stock and orders, seedlings, a fixed crew with hiring | Sales contracts and fines |
| 2 event types: late delivery, boiler trip | Sensor drift, CHP failure, broken pane, power outage |
| Ladder: do-nothing, absentee, stop-early, naive, rule-based, reference, exploiter | Smart rules as its own rung, hindsight oracle |
| First model comparison: do-nothing vs one fast model (Gemini Flash) vs one strong model (Gemini Pro or Hydrogen), section 12 | More models, more seeds, scenario variants |

**No crop, facility, price or event value lives in Python.** Code holds mechanisms only: how heat flows, how a response curve is evaluated, how an order is delivered. Values come from data files (section 3). A new vegetable means a new data file plus one line in a scenario; changing basil's optimum temperature means editing one number.

---

## 2. Packages and where things go

Owner initials in brackets: Max (M), Lucas (L), Emre (E), Rowan (R). See `docs/collaboration/`.

```
src/greenhouse/                  # new top-level package (bundled into the Harbor task)
  contracts.py                   # [M] the shared types between modules; changes need all owners' OK
  config/        base.py         # [M] Range, validation errors, strict TOML table reader
                 curves.py       # [M] library of response curves, chosen by name in data files
                 loader.py       # [M] resolve a scenario's data references and overrides, draw hidden params
                 crop.py         # [L] CropSpec dataclass + validation for data/crops/*.toml
                 facility.py     # [E] FacilitySpec, ClimateProfile for data/facilities, data/climates
                 market.py       # [R] MarketSpec, EventSpec for data/markets, data/events
  world/         crop.py         # [L] growth models, chosen by name (registry)
                 weather.py      # [E] seeded weather and price series from profile files
                 climate.py      # [E] one compartment, one sub-step: energy, CO2, humidity balance
                 controller.py   # [E] built-in climate computer: setpoints -> actuator positions
                 energy.py       # [E] CHP, boiler, buffer, grid, CO2 supply; allocation between compartments
                 operations.py   # [R] stock, orders, deliveries, staff, tasks that need worker-hours
                 events.py       # [R] event schedule (seeded from rates) and effects
                 ledger.py       # [R] money in and out by category, conservation check
                 sim.py          # [M] Greenhouse: composes the modules, runs ticks, applies actions, raises RuleError
  views.py                       # [M] what the agent may see (sensor readings, forecasts, ledger)
  outcome.py                     # [R] profit, ledger for the scorer, failure modes
  env.py                         # [M] the envkit binding: tools only
  policies/                      # [R] naive, rule_based, exploiter; [M+R] reference (play through tools only)
data/                            # all values; nothing here is code. Each owner fills their own folder
  crops/lettuce_butterhead.toml
  crops/basil_genovese.toml
  facilities/nl_two_compartment.toml
  climates/nl_january.toml
  markets/nl_winter.toml
  energy_prices/nl_winter.toml
  events/late_delivery.toml
  events/boiler_trip.toml
scenarios/normal-winter.toml     # picks one facility, climate, market, crops, events; sets seeds and scoring
```

Dependency direction: `config` <- `world` <- `views`/`outcome` <- `env` <- `policies`. `world` never imports `env`. Policies import nothing from `world` except, for the reference only, the public model (section 9).

### 2.1 Changes to `envkit` (small, shared, do first)

1. **Multi-hour advance (used by `submit_day`, which closes a whole day in one call).** A tool can ask the engine to close more windows after it returns, e.g. `self.advance_windows(n, interrupt=callable)`. The engine closes up to `n` windows and stops early when `interrupt()` returns a reason (a new alarm). It costs one operation and is one trace record, so replay stays exact. Test: `advance(5)` matches five separate `advance(1)` calls when no alarm fires.
2. **Data files in the bundle.** `[task].data = ["data/crops/lettuce_butterhead.toml", ...]`, or the loader's resolved list, is copied into the bundle and covered by the bundle hash, so a changed crop file makes the calibration stale.

Everything else in envkit (trace, replay verifier, calibration, audit, Harbor build) is reused as is.

---

## 3. Data files

All data files are TOML. TOML matches the scenario files, allows comments with sources, diffs cleanly in PRs, and needs no service at judge time. Every file has `schema = "<kind>/1"` and an `id`, and the loader rejects unknown keys, missing keys and out-of-range values with a message that names the file and key.

A value written `{min = a, max = b}` is a **hidden per-seed parameter**. It is drawn once per seed from a named RNG stream. The range is published to the agent and the drawn value is not.

### 3.1 Crop (`data/crops/*.toml`)

```toml
schema = "crop/1"
id = "lettuce_butterhead"
name = "Butterhead lettuce"
growth_model = "leafy_vanhenten"   # registered model in world/crop.py; parameters below are its inputs

[cycle]
harvest_mode = "single"            # "single" | "repeated"
nominal_days = 32                  # transplant -> harvest under target climate (published)
min_days_before_end = 30           # planting is refused if fewer days remain
# repeated crops only: regrow_fraction, regrow_days, max_cuts

[planting]
density_per_m2 = 20
seedling_cost_eur = 0.08           # per plant
plant_worker_hours_per_1000 = 1.5
harvest_worker_hours_per_1000 = 3.0

[growth]                           # leafy_vanhenten parameters, published in the opening rules
light_use_efficiency = 0.0         # TODO fill from Van Henten 1994 / van Straten 2010 table
co2_compensation_ppm = 0.0
canopy_closure_coeff = 0.0
respiration_q10 = 2.0
respiration_coeff = 0.0
temperature = { curve = "cardinal", t_min = 2.0, t_opt = 20.0, t_max = 30.0 }
light       = { curve = "saturating", half_sat = 0.0 }

[climate_targets]                  # advice published to the agent; not enforced
day_temp_c = [16, 22]
night_temp_c = [12, 18]
co2_ppm = [800, 1000]
dli_mol_m2_d = [12, 17]

[stress]                           # counters that lower quality; each is a curve on a climate signal
tipburn = { signal = "dli_excess", curve = "linear_above", threshold = 17.0, rate = 0.0 }
bolting = { signal = "temp_day_mean", curve = "linear_above", threshold = 24.0, rate = 0.0 }
cold    = { signal = "temp_min", curve = "linear_below", threshold = 4.0, rate = 0.0 }
frost_kill_c = -1.0                # batch lost below this

[market]
unit = "head"                      # "head" | "kg"
min_sellable = { fresh_weight_g = 150 }
grades = [ { name = "A", min_quality = 0.85, price_factor = 1.0 },
           { name = "B", min_quality = 0.60, price_factor = 0.6 },
           { name = "waste", min_quality = 0.0, price_factor = 0.0 } ]
```

Basil uses the same schema with `harvest_mode = "repeated"`, warmer targets, its own curves and `unit = "kg"`. Base prices sit in the market file (3.4), so a price shock is a market change, not a crop change.

**Two levels of plug-in.** Swapping in a crop with the same kind of growth (spinach, rocket) is data only. A crop that needs different mechanics (fruit set for tomato) adds one registered `growth_model` class with its own parameter schema. No other code changes, because the simulator calls models through one interface:

```python
class GrowthModel(Protocol):
    def step(self, batch: BatchState, climate: ClimateSample, dt_h: float) -> BatchState: ...
    def estimate(self, batch: BatchState) -> BatchEstimate: ...   # what the agent may see
    def harvest(self, batch: BatchState) -> HarvestResult: ...
```

Curves (`config/curves.py`) are a closed, tested set: `cardinal`, `saturating`, `linear_above`, `linear_below`, `piecewise` (list of points). A data file chooses one by name.

### 3.2 Facility (`data/facilities/*.toml`)

```toml
schema = "facility/1"
id = "nl_two_compartment"

[energy_centre]
chp = { electric_kw = {min = 300, max = 500}, heat_per_electric = 1.2, co2_kg_per_m3_gas = 1.8,
        gas_m3_per_kwh_e = 0.25, min_load = 0.5 }
boiler = { heat_kw = {min = 600, max = 900}, gas_m3_per_kwh_heat = 0.105, co2_usable = true }
buffer = { capacity_kwh = {min = 2000, max = 4000}, loss_per_h = 0.005, start_fraction = 0.5 }
co2_store = { capacity_kg = 8000, start_kg = 3000 }
external_co2 = { max_kg_per_h = {min = 20, max = 40} }
grid = { import_kw = {min = 400, max = 700}, export_kw = {min = 300, max = 500} }

[[compartments]]
id = "A"
crop = "lettuce_butterhead"
floor_m2 = {min = 2500, max = 3500}
height_m = {min = 4.5, max = 6.0}
cover_u_w_m2_k = {min = 4.5, max = 6.5}      # heat-loss coefficient
cover_transmission = {min = 0.65, max = 0.78}
leakage_ach = {min = 0.3, max = 0.8}         # air changes per hour, vents closed
screen = { insulation = {min = 0.3, max = 0.5} }
lamps = { w_per_m2 = {min = 80, max = 140}, umol_per_j = 2.7, heat_fraction = 0.7 }
start_batches = [ {age_days = 24, area_fraction = 0.25}, {age_days = 16, area_fraction = 0.25},
                  {age_days = 8,  area_fraction = 0.25}, {age_days = 0,  area_fraction = 0.25} ]

[[compartments]]
id = "B"
crop = "basil_genovese"
# ...

[fallback]                     # the anti-freeze baseline at hour 0 (D5, revised)
heat_c = 5.0                   # frost protection: crops survive but stall
co2_ppm = 0
lamps = "off"
```

`[fallback]` is the do-nothing baseline (D5, revised): from hour 0 it is both the day settings and the night schedule, and it stays until the agent changes it. An agent that never acts keeps 5 °C for 42 days, which is the heavy punishment for doing nothing.

Staff (`start_workers`, `hours_per_worker_day`), start cash and starting seedling stock are in the market file (3.4), because the business owns them. Which crop grows where, and how many compartments there are, is facility data. Going to three compartments is a third `[[compartments]]` table.

### 3.3 Climate (`data/climates/*.toml`)

**Decided (D3): researched historical data, fixed in data files.** Weather (outdoor temperature, global radiation, wind, humidity) and energy prices (gas, hourly electricity import, export) are real recorded hourly series, researched once and committed under `data/` with their source. Nothing is fetched live. Every agent on the same seed gets exactly the same series, so a run's profit or loss is fully explained by the decided prices. Forecasts are the true series plus error that grows with lead time, drawn from a named stream per seed (error sizes are in this file), so they too are identical for every agent on a seed.

Each seed picks one recorded window (for example one January week range from a given year) from a list in the file. Dev seeds 1–6 and eval seeds 101–108 use different windows, so nothing is tuned on the evaluation weather. Candidate sources: KNMI hourly station data (De Bilt), EPEX/ENTSO-E day-ahead prices for the Netherlands, TTF gas. The prompt does not name the year or the dates.

### 3.4 Market (`data/markets/*.toml`)

Base price per crop and unit, CO2 price, seedling and repair prices, wage per hour, hiring fee, notice days, order lead times and minimum quantities per item.

Energy prices are their own file, `data/energy_prices/*.toml` (owned with the weather code): recorded hourly gas and electricity prices and the export price, per seed window (D3).

### 3.5 Events (`data/events/*.toml`)

```toml
schema = "event/1"
id = "boiler_trip"
rate_per_day = 0.04                 # published
duration_h = {min = 6, max = 30}    # published as a range
signal = "alarm"                    # what the agent sees: alarm text in the morning briefing
effect = { target = "boiler", capacity_factor = 0.0 }
repair = { cost_eur = 1200, worker_hours = 4, shortens_to_h = 3 }
```

The event schedule is drawn per seed from the rates when the episode starts, on its own RNG stream, so the agent's actions cannot change it. A scenario can also pin an event to a time for a demo seed.

### 3.6 Scenario (`scenarios/normal-winter.toml`)

Same format as today (`[task]`, `[shift]`, `[scoring]`, `[harbor]`), with `[env]` naming the data:

```toml
[env]
facility = "data/facilities/nl_two_compartment.toml"
climate  = "data/climates/nl_january.toml"
market   = "data/markets/nl_winter.toml"
energy_prices = "data/energy_prices/nl_winter.toml"
crops    = ["data/crops/lettuce_butterhead.toml", "data/crops/basil_genovese.toml"]
events   = ["data/events/late_delivery.toml", "data/events/boiler_trip.toml"]
horizon_days = 42
overrides = { "market.crops.basil_genovese.price_eur_per_kg" = 9.0 }   # optional, for variants
```

`overrides` lets a scenario variant change one value without copying a whole file.

---

## 4. Time

- **One window is one simulated hour.** With `horizon_days = 42` that is 1,008 windows, `ops_per_window = 1`.
- Inside an hour the simulator runs **12 sub-steps of 5 minutes**. The climate controller and the physics run on sub-steps; the agent never sees them.
- **The agent acts once a day, at 06:00 (round 3, section 14.1).** `submit_day(actions)` is the only tool: it applies the actions, then runs the day (06:00-18:00) and the night (18:00-06:00) with nobody acting and nothing stopping it, and returns the next morning's briefing. One call is one day, so a run is about 42 calls. There are no read tools and nothing stops early on an alarm; alarms are reported in the briefing.

**Episode length (D1, decided: try 42 days, shorten if evals take too long).** With lettuce at a 32-day cycle and starting ages 0/8/16/24, 35 days lets no new lettuce planting finish, so seedling orders would never matter. **42 days** lets the first freed space (day 8) be replanted and harvested, and leaves the day-16 freed space as a real choice: plant and push climate hard to finish, or leave it empty. Basil's repeated cuts carry on throughout.

### 4.1 Fair budgets: no model is cut off

Every model gets the same simulated world and the same decision budget. Thinking time never changes what a model can do.

- **Simulated time moves only with `submit_day`.** A model that thinks for 10 minutes before one call faces exactly the same world as one that answers in 2 seconds.
- **The call budget is the same for everyone and generous:** `max_calls = 400` (D4), at least 2.5x what the reference uses. It exists only so that a looping agent ends. Reaching it is a legitimate agent outcome (`end_reason = "call_limit"`) and is reported as such.
- **The agent works the day shift only (round 3, section 14.1).** It can act from 06:00 to 18:00. The day and night run inside the one `submit_day` call on the settings and hourly night schedule it committed. That gives 42 calls, well inside 400. The earlier "always-on agent" rationale is replaced: night events are answered by planning ahead (redundancy, a charged buffer, spare parts), not by reacting, and context 0.5 sets the guardrails that keep this fair.
- **The wall-clock timeout is a safety net, not a rule.** `agent_timeout_sec` is set to several times the slowest model's measured full run (start: 3 hours; tune after the first Pro/Hydrogen run). A run that hits it is labelled `interrupted` in the report, kept out of model-comparison means, and rerun. It still gets the stop-early score in the judges' protocol, because reward integrity requires that.
- **Provider failures are not agent results.** Rate limits, auth errors and API outages are infrastructure failures (no reward), as envkit does today. Concurrent attempts per model are capped so that rate limits do not slow one model more than another.
- **The report states, per run:** calls used, simulated hours reached, wall time, end reason. So "ran out of time" and "chose to stop" can never be confused.

### 4.2 Order of one sub-step

1. Events whose start time has passed take effect.
2. The controller reads the **true** climate and the setpoints, and sets vents, screen, lamps, heat request and CO2 request per compartment.
3. The energy centre serves requests: the buffer and CHP first, the boiler next, then allocation when supply is short (4.3). CO2 comes from flue gas, then the store, then the external supply.
4. Compartment balances update: heat, CO2 and vapour (inputs from step 3 and the weather; losses through cover, leakage and vents).
5. Batches grow and stress counters update from the compartment climate.
6. Energy and CO2 flows are metered into the ledger at that hour's prices.

At the end of each hour: deliveries arrive, staff tasks progress, sensor readings are taken (with noise), and alarms are raised.

### 4.3 Allocation when supply is short

**Decided (D2): the agent decides the trade-off.** When heat or CO2 cannot cover every compartment, who gets what is the agent's call, and it can sacrifice a crop to save another. Through `set_energy` it sets, per compartment, a `priority` (integer, default 1) and an exact allocation `heat_cap_kw` and `co2_cap_kg_h`: a compartment never gets more than its cap. Supply goes to the highest priority first; within a level it is shared in proportion to demand, up to each cap. Setting caps that add up to the supply gives an exact split. An agent that sets nothing gets plain proportional sharing, which is the do-nothing behaviour, not a smart default. **At night** the same priority and caps come from the night schedule, per hour, as fixed values (section 14.1).

---

## 5. Tools (the agent's control surface)

Every tool's docstring is what the agent reads; the names below are the contract. Reads are free and never move time. Setpoints **stand until changed**.

| Tool | Cost | Arguments | Effect |
|---|---|---|---|
| `submit_day` | 1 | `actions` (list, at most `actions_per_day` = 5) | The only tool (section 14.1). Applies the actions in order (a refused action changes nothing and the rest still apply; more than 5 refuses the whole call), then runs the day and the night. Returns per-action results and the next morning's briefing. |

Each action is `{"tool": <name>, ...arguments}`; there are no separate tools. Every rule is in the task instruction (`Environment.opening()`), which also holds day 1's briefing. Action names and arguments:

| Action | Arguments | Effect |
|---|---|---|
| `set_climate` | `compartment`, any of: `heat_day_c`, `heat_night_c`, `vent_min_pct`, `vent_max_pct`, `co2_ppm`, `screen` (`auto`/`open`/`closed`), `lamp_hours` (list of hours), `lamp_intensity_pct` | Change standing day setpoints. Values are checked against equipment limits. |
| `set_energy` | any of: `chp_load` (0 or `min_load` to 1), `boiler_max_fraction`, `buffer` (`charge`/`hold`/`discharge`/`auto`), `buffer_draw_max_kw`, `external_co2_kg_h`, `priority` (map), `caps` (map) | Change standing day energy-centre settings. |
| `set_night_schedule` | `from_hour` and one entry's fields (section 14.1) | Sets one night entry; the schedule repeats every night until changed. |
| `place_orders` | `items` (`co2_kg`, `seedlings:<crop>`, `part:<id>`), `quantity`, `express` | Charged on delivery; shows the expected arrival. Minimum quantities apply. |
| `cancel_order` | `order_id` | Only before dispatch (fee). |
| `hire` / `release` | `workers` | Arrive or leave after notice days; fee and wages from the market file. |
| `plant` | `compartment`, `area_m2` | Queues planting; uses seedlings and worker-hours. Refused if too few days remain. |
| `harvest` | `batch_id` | Queues harvest; uses worker-hours. Underweight produce sells for 0. |
| `book_contractor` | `trade`, `target` | Section 14.2. Repairs need a contractor, a part and a day-shift hour. |

**Removed:** `get_rules`, `get_status`, `get_batches`, `get_forecast`, `get_history`, `get_night_report`, `get_news`, `advance`, `end_shift`, `repair`, `finish_episode`. There is no tool to stop: an agent that stops calling tools has stopped; the rest runs with the last day settings and night schedule, and nobody acting (D5).

`plant` and `harvest` are tasks (and repair jobs use contractor hours): they use worker-hours from the day's pool in queue order. A task that does not get enough hours waits. A ready batch loses quality each day it waits (a crop parameter).

---

## 6. What the agent sees

- Sensor readings with noise σ per sensor type (facility file), taken hourly: air temperature, RH, VPD, CO2, PAR and DLI so far.
- Exact: actuator positions, energy-centre output, buffer level, CO2 stock, orders, staff, money, alarms.
- Estimates from the growth model's `estimate()`: batch weight ± error, days to ready, quality.
- Never: true hidden parameters, the event schedule, future weather and prices beyond the forecast. The agent can infer hidden parameters from how the facility responds (for example, heat used per degree of indoor-outdoor difference gives the cover heat loss).

`snapshot()` (verifier timeline only) holds true state for failure-mode analysis.

---

## 7. Money and reward

Profit over the episode, in EUR:

```
+ harvest revenue   Σ sellable units × base price × grade price factor
+ electricity sold  CHP export × export price, hour by hour
- gas               CHP + boiler
- electricity       grid import × hourly price
- CO2               external CO2 + deliveries
- staff             wages + hiring fees
- repairs
- seedlings and other orders
```

Standing crop at the end is worth 0. The fixed crew's wages are charged from hour 0 whether or not anyone acts.

**Score:** an `anchored` envkit component on `profit_eur` with `zero_anchors = ["do-nothing", "absentee"]`, `top_anchors = ["reference"]`, `target = 0.8`. That gives `score = clip(0.8 × (P − P_zero) / (P_ref − P_zero), 0, 1)`, as in the context doc.

**Do-nothing and stopping (D5, revised in round 3).** The facility starts on the `[fallback]` anti-freeze baseline (5 °C, no CO2, lamps off), as day settings and night schedule. Doing nothing keeps it for 42 days: crops survive but stall below sellable weight, nothing is harvested or sold, nothing is replanted or repaired, and wages and gas keep being paid. That is the heavy punishment for doing nothing. Stopping for any reason (finish, call limit, timeout) is the same as doing nothing from then on: the last day settings and night schedule stay and nobody acts. Stopping early is therefore identical to advancing without acting, so it can never score more (tested). Consumption and degradation rates (CO2 use, how fast an unharvested crop loses value) are researched and live in the data files.

---

## 8. Integrity rules and tests

Mechanisms that must hold, each with a test in `tests/greenhouse/`:

- **Conservation:** heat produced = heat delivered + buffer change + losses; CO2 and money likewise. Checked every hour in tests and once at the end in `ledger()`.
- **Sanity:** January, no heating → indoor near outdoor, near-zero growth. Doubling floor area doubles heat demand and yield. Lamps at night raise DLI and the electricity bill.
- **Determinism:** same seed + same trace → identical ledger across processes. An extra read call never changes anything.
- **Data validation:** each data file loads; a file with a missing key, a stray key or an out-of-range value fails with the file and key named; a new crop file with different values runs without code changes (test: run with a third `spinach` fixture crop).
- **Exploits (exploiter policy, must score ≈ 0):** harvest everything early; cut heat in the last days; CHP flat out to sell power; extreme CO2 or temperature; spam repairs or orders; plant in the last days; never harvest.
- **Audit:** `envkit audit normal-winter` passes (do-nothing ≤ 0.05, absentee ≤ 0.15, stop-early monotone, spam and random below the bar).

---

## 9. Policy ladder (all play through tools only)

| Policy | Behaviour | Expected position |
|---|---|---|
| do-nothing | No calls | 0 by construction |
| absentee | Reads every day, never changes anything | ≈ 0 |
| stop-early | Reference for the first 7 days, then stops | Clearly below reference |
| naive | Crop-file target setpoints, CHP on when cold, orders CO2 only when the store is empty, harvests when ready | Shows that lead times and energy timing matter |
| rule-based | Practitioner rules: CO2 off when vents open, lamps in cheap hours, screen at night, reorder at a fixed level, harvest when ready | The gap test: if this is close to the reference, we have no room |
| **reference** | Rule-based plus a 48-hour look-ahead each simulated day. Hidden parameters are estimated from the first day's readings. It plans with the public model (the published equations from `get_rules` and its own estimates), using forecasts only. Thresholds are tuned on dev seeds 1–6 | The bar; 0.8 by construction |
| exploiter | Each exploit in section 8 | ≈ 0 |

The reference may import the same equations as the simulator, because they are published, but it must take every number from tool results: forecasts, readings, the opening rules and its own estimates.

---

## 10. Work split

Merge order and owners. Each workstream gets its own branch and worktree and merges to `main` through a small PR with CI green, per `AGENTS.md`. Nobody pushes straight to `main`.

| # | Workstream | Owner | Files reserved |
|---|---|---|---|
| 0 | envkit changes (2.1), `contracts.py`, `config/base.py`, `curves.py`, `loader.py` | Max | `src/envkit/`, `src/greenhouse/contracts.py`, `src/greenhouse/config/{base,curves,loader}.py` |
| 1 | Crop schema, growth models, crop data (lettuce, basil) | Lucas | `config/crop.py`, `world/crop.py`, `data/crops/`, `tests/greenhouse/test_crop*.py` |
| 2 | Facility and climate schema, climate, controller, energy centre, weather, energy prices | Emre | `config/facility.py`, `world/{climate,controller,energy,weather}.py`, `data/{facilities,climates,energy_prices}/`, `tests/greenhouse/test_{climate,energy,weather}*.py` |
| 3 | Market and event schema, operations, events, ledger, outcome, naive/rule-based/exploiter policies | Rowan | `config/market.py`, `world/{operations,events,ledger,business}.py`, `outcome.py`, `policies/{naive,rule_based,exploiter}.py`, `data/{markets,events}/`, `tests/greenhouse/test_{ops,events,ledger,policies}*.py` |
| 4 | `sim.py`, `views.py`, `env.py`, scenario, reference planner, integration | Max (+ Rowan for the reference) | `world/sim.py`, `views.py`, `env.py`, `policies/reference.py`, `scenarios/` |

Workstream 0 is short and everything depends on `contracts.py`, which is already on `main`. Workstreams 1, 2 and 3 start at once against it. Workstream 4 wires stubs first and swaps in the real modules as they land. Day-to-day instructions per person: `docs/collaboration/`.

---

## 11. Decisions needed before building

| ID | Question | Proposal |
|---|---|---|
| D1 | Episode length | **Decided:** try 42 days (1,008 hourly windows); shorten if evals take too long |
| D2 | Allocation when short (4.3) | **Decided:** the agent decides; priority plus exact per-compartment caps; nothing set = proportional |
| D3 | Weather and prices | **Decided:** researched historical hourly series in data files, one window per seed, identical for every agent; no live data |
| D4 | Call and time budget | `max_calls = 400` for every model, agent may act any hour (4.1); agent timeout 3 h as a safety net; confirm with organisers |
| D5 | Do-nothing start state | **Decided (revised in round 3):** 5 °C anti-freeze baseline as day settings and night schedule; crops stall, nothing is harvested; stopping = doing nothing from then on |
| D9 | Agent working hours | **Decided (round 3):** day shift 06:00–18:00; the night runs on an hourly schedule of fixed values (section 14.1) |
| D10 | Night equipment behaviour | **Decided (round 3):** thermostat draws from scheduled-available sources in a fixed order; nothing unscheduled starts; priority and caps per hour allowed |
| D11 | Repairs | **Decided (round 3):** persistent damage; a repair needs contractor + part + day slot; storm surge on lead times (section 14.2) |
| D8 | Nutrients (fertiliser) as a consumable | Open: research uptake per crop and stock/order rules; add after v1 runs end to end |
| D6 | Compartments in v1 | **Decided:** 2 (A lettuce, B basil); it is facility data, so 1 or 3 is a config change |
| D7 | Package name | **Decided:** `src/greenhouse`; Root Cause already removed |

---

## 12. First model comparison

One small comparison before anything bigger: is there a gap at all, and does a stronger model close it?

| Run | Count | Purpose |
|---|---|---|
| do-nothing | 1 per seed | Zero anchor (scripted, Harbor `nop` agent) |
| reference | 1 per seed | 0.8 anchor; must reproduce calibration exactly |
| Gemini Flash | 3 per seed | Fast, cheap model |
| Gemini Pro or Hydrogen | 3 per seed | Strongest Gemini model |
| Claude (Anthropic) | 3 per seed | A second provider, so the gap is not one vendor's quirk |
| OpenAI (optional) | 3 per seed | Only if an `OPENAI_API_KEY` is available |

Start with dev seed 1 only. Add seeds once the rows separate.

```bash
bash scripts/judge.sh --model google/<flash-id>  --runs 3 --seeds 1 --output artifacts/cmp-flash
bash scripts/judge.sh --model google/<pro-id>    --runs 3 --seeds 1 --agent-only --output artifacts/cmp-pro
bash scripts/judge.sh --model anthropic/<id>     --runs 3 --seeds 1 --agent-only --output artifacts/cmp-claude
bash scripts/judge.sh --model openai/<id>        --runs 3 --seeds 1 --agent-only --output artifacts/cmp-openai
```

The later commands skip the scripted runs, since the first already checked them. The key is picked from the model's provider prefix (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` in `.env`) and forwarded to OpenCode by Harbor; its value never appears on a command line. Add `--backend modal` to any of these during development. A small `envkit report` change will put both directories in one table (model, reward, profit, calls, advance calls, wall time, end reason). Record the code SHA, command, model ids, seeds and results in `docs/DECISIONS.md` (AGENTS.md benchmark rules).

What we want to see: do-nothing 0 < Flash < Pro < reference 0.8, the same order on repeated runs, and failure modes in the logs that trace back to task decisions (section 9 and the context doc, 15.4).

---

## 13. Docker and Modal

Both run the same generated Harbor task. The only difference is the `--backend` flag. This already works today (scripted runs on Modal reproduced their Docker scores, `docs/MODAL.md`).

| | Local Docker/Podman | Modal |
|---|---|---|
| Who uses it | Judges; final evidence runs | Us, for fast parallel development runs |
| Command | `bash scripts/judge.sh ...` | `bash scripts/judge.sh --backend modal ...` |
| Needs | Docker or Podman running | `modal setup` or a token; no local Docker |
| Task, images, scoring | Identical: `tasks/<id>/` built by `envkit build` | Identical |

Rules that keep it zero-friction:

- **Nothing in `src/` or `tasks/` knows about Modal.** Modal stays a Harbor provider, chosen at run time. The environment never imports `modal` and never reads a Modal variable.
- **Every benchmark claim is confirmed on local Docker** before it goes in the README or the pitch, because that is what judges run. Modal results are for iteration.
- **CI runs the Docker smoke** (as now), so a Modal-only shortcut cannot break the judge path without CI failing.
- **Same seed, same score on both.** `judge.sh` already fails if a scripted run does not reproduce its calibrated reward, whichever backend ran it.

---

## 14. Round 3: day shift, night schedule, damage and repairs, news

Implements [context section 0](GREENHOUSE_BENCH_CONTEXT.md). Scope for v1 is context 0.10. Contract types named here land in `contracts.py` first (Max), and everyone builds against them.

### 14.1 The daily turn and the night schedule

**Revised 14 Nov 2026 (built).** The day shift with `advance(hours)` described in the first version of this section was replaced, before it was used, by a daily turn: one decision point a day at 06:00, a cap on actions, and no read tools. Context 0.2's rule that the agent cannot act at night still holds; it now cannot act during the day either, except at 06:00. DECISIONS, "Round 3 built", has the reasons.

**Clock.** Episode hour `h` has clock time `h % 24`. Hours 00:00-06:00 of day 1 run on the baseline before the agent's first call (the handover night, envkit `prelude_windows`), so the agent starts at 06:00 with a morning briefing, like every other day. The episode still ends at hour 1,008.

**What the agent is shown.** There are no read tools. Before its first call the agent is shown every rule (what `get_rules` used to return, plus `turn`) and the first morning's briefing, written into the task instruction (envkit `Environment.opening`, a pure function of the seed). Every later briefing comes back in the result of the call that ends the day. The briefing (`views.briefing`) holds the clock, the actions left, the status (readings, day settings, night schedule, faults and damage, contractor bookings, stock, orders, staff, task queue, money, alarms of the last 24 hours, batches), last night's summary (every alarm and event with its hour, min/max climate per compartment, per batch the change in estimated weight and quality, money over the night), news of the last 3 days, and a 72-hour forecast in columns.

**One call per day (final).** The whole turn is one call, `submit_day(actions)`, the only tool: up to `actions_per_day` actions, each `{"tool": <action>, ...its arguments}`, applied in order, then the day and night run. The paragraph below describes the actions; read "the day ends" as the end of that call.

**The turn.** At 06:00 the agent makes one `submit_day` call (cost 1) with at most `actions_per_day` actions (scenario `[env]`, 5): `set_climate`, `set_energy`, `set_night_schedule` (one entry), `place_orders` (several items, optional `express`), `cancel_order`, `hire`, `release`, `plant` (several compartments), `harvest` (several batches), `book_contractor`. A list is one action and reports what was accepted and what was refused. Actions apply in order; a refused one changes nothing and the rest still apply; more than the limit refuses the whole call. The day (06:00-18:00 on the day settings, crew at work) and the night (18:00-06:00 on the night schedule) then run inside that call with nobody acting, and the result carries the next briefing. One call is one day, so 42 days fit well inside `max_calls = 400`.

**Night schedule.** `set_night_schedule(from_hour, ...)` sets one entry; the schedule repeats every night until changed. Each entry is a `NightHour`:

```python
@dataclass(frozen=True)
class NightHour:
    hour: int                                  # clock hour 18..23 or 0..5
    climate: dict[str, ClimateSetpoints]       # every compartment, resolved when the entry is set
    energy: EnergySettings                     # chp_load, boiler, buffer, external CO2, priority, caps, levels
```

An entry applies from its hour until the next entry, so the 18:00 entry (which always exists and cannot be removed) sets the whole night unless later entries follow. A new entry starts from what is in force at that hour, or from the day settings with `copy_day`; the fields given change it (`heat_c`, vents, CO2, screen, `lamps_on`, lamp intensity, CHP load, `boiler_max_fraction`, buffer mode and `buffer_draw_max_kw`, external CO2, priority and caps). Values are checked like day settings. The schedule only holds fixed values: there is no condition or trigger field.

**Equipment behaviour (D10).** Day and night use the same rule. `EnergySettings` has `boiler_max_fraction` (0 = off, 1 = full) and `buffer_draw_max_kw` (None = no cap). The thermostat serves each compartment's setpoint from the available sources in a fixed order: CHP at its set load, then buffer draw up to its maximum, then boiler up to its maximum. Nothing starts that the settings did not make available, and a failed source delivers nothing. Shortfall is shared by priority and caps (4.3).

**Staff.** Shift hours must lie inside 06:00-18:00 (the market loader rejects anything else). Tasks only progress in shift hours.

**Baseline and stop (D5).** At hour 0 the day settings and the night schedule are both the facility's `[fallback]` (5 °C, no CO2, lamps off). After a stop, the last day settings and night schedule keep running and nobody acts.

### 14.2 Persistent damage, contractors and parts

**Damage.** `EquipmentEffect.until_hour = None` means "until repaired". New equipment ids per compartment for glass (`A.glass`, `B.glass`), next to `boiler`. Broken glass is an effect with `leakage_factor > 1` (more air leakage and heat loss) whose size comes from the number of panes broken, drawn per occurrence and seed from a documented range (0 panes is possible).

**Storms.** A storm event (Rowan's event files) fires when the recorded wind (D3) passes a data threshold, and draws its damage on its own stream. It is **regional**: for a documented number of days after it, parts ordered get the surge lead time and contractors the surge response time. To read the wind, `BusinessModel.start_hour(hour, weather)` gets the hour's recorded weather (contract change, Max).

**Parts** are market items like CO2 (`part:glass_pane`, `part:boiler_kit`), each with a price, a normal lead time, a surge lead time, an express price and an express lead time (a fraction of whichever lead time applies). The lead time is fixed when the order is placed: before a storm, normal; after, surge. Unused parts are worth nothing at the end.

**Contractors** are a market table (`[contractors.glazier]`, `[contractors.heating_installer]` in v1): which equipment they fix, the parts each job needs, call-out fee, hourly rate, job hours, normal and surge response time. Per-seed values come from documented ranges.

**`book_contractor(trade, target)`** (free) books a visit. The visit happens in the first day-shift slot at or after the response time **when the needed parts are on site**. Until then it waits. On the visit, the call-out and hours are charged, the parts are used, and when the job hours are done the effect is cleared. Refusals: unknown trade, a trade that does not fix that target, nothing broken there, a visit already booked. Urgent bookings come later.

**Ledger categories** added to `LedgerCategory`: `contractors` (call-out and labour), `parts`, `express`. `repairs` is kept only for old traces.

### 14.3 News signals

A news table per signal type (Rowan's data, `data/news/*.toml`): which event type or input it relates to, how far ahead it appears, the chance it appears before a real event, the false-alarm rate per day, and the headline texts. Storm and frost signals follow the recorded weather (D3); gas-price signals follow the recorded prices. The whole news feed is drawn at episode start from a named stream, so it is the same for every agent on a seed and no action can change it. New free tool `get_news(days)` returns the headlines published so far (never future ones). No signal names a piece of equipment or an hour.

### 14.4 Plugs and lettuce timing

Seedling items become plugs from a propagator with a 2–3 week lead time (market data, numbers researched by Lucas, put in the file by Rowan). Lettuce: about 24 days from transplant at DLI 17, scaling with light; 24/19 °C are targets. The start-batch ages and the 42-day argument in section 4 are redone with these numbers (Lucas and Max).

### 14.5 Required tests (in addition to section 8)

1. A planned frost night (charged buffer, boiler and CHP available, screens closed) loses clearly less than a naive one when the boiler fails that night (context 0.5).
2. Context 0.7 tests 1–4 (pre-ordered glass, no-damage storm, the three conditions of a repair, storm surge).
3. The daily turn: day 1 starts at 06:00; the last allowed action ends the day; a refused action changes nothing and does not count; there are no read tools and the opening shows the rules and the briefing (`tests/greenhouse/test_sim_env.py`).
4. Same seed, same night: identical night report across processes; the news feed is identical whatever the agent does.
5. The reference and every scripted policy play under the shift rules.

### 14.6 Who builds it (round 3)

| Area | Owner | Files |
|---|---|---|
| Contract types, daily turn, `submit_day`, `set_night_schedule`, morning briefing, news wiring, scenario | Max | `contracts.py`, `sim.py`, `env.py`, `views.py`, envkit if needed |
| Day and night dispatch with boiler level and buffer draw caps, glass effect on leakage, `[fallback]` = 5 °C | Max (Emre's files, handed over for this round) | `world/{energy,controller,climate}.py`, `config/facility.py`, `data/facilities/` |
| Storm event, persistent damage, contractors, parts with surge and express, `book_contractor`, news feed, new ledger categories, CO2 cleanup, policies under shift rules | Rowan | `config/market.py`, `world/{operations,events,ledger,business}.py`, `outcome.py`, `data/{markets,events,news}/`, `policies/` |
| Lettuce at 24 days and light scaling, frost damage on near-ready batches, plug lead times (research), storm and frost news inputs from the recorded weather (D3 itself landed in #15) | Lucas | `config/crop.py`, `world/crop.py`, `data/crops/`, plus `world/weather.py`, `data/{climates,energy_prices}/` (Emre's, handed over for this round) |
| Reference planner under shift rules | Max with Rowan | `policies/reference.py` |
