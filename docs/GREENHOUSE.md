# Root Cause: model, rules and scoring

Root Cause is a greenhouse operations simulator: four tomato zones, fourteen days, limited fresh water. A person plays it in the browser and an agent plays it through MCP tools; both drive the same engine through the same calls.

**This is a transparent, simplified research simulator. It is not a validated agronomic model and makes no prediction about a real farm.** Parameter values are illustrative and were chosen to make the trade-offs visible within fourteen decisions, not fitted to data.

Results are in [EXPERIMENTS](EXPERIMENTS.md); commands are in the [README](../README.md).

## Where the code is

| Path | What it holds |
|---|---|
| `src/rootcause/model.py` | Every parameter and response curve, and `step_zone`: one zone, one day |
| `src/rootcause/generator.py` | Seeded instances: zones, weather, forecasts, sensor noise |
| `src/rootcause/sim.py` | `Greenhouse`: plans, tests, the daily update, accounting |
| `src/rootcause/views.py` | What a player may see during play |
| `src/rootcause/outcome.py` | Profit, the reward bounds, conservation checks, the post-episode report |
| `src/rootcause/env.py` | The `envkit` binding: the tools |
| `src/rootcause/policies.py`, `planner.py` | Rule-based policy and the reference planner |
| `src/rootcause_app/` | Browser app, comparator runs, what-if analysis, suite evaluation |
| `scenarios/root-cause.toml` | The scenario: agent instructions, clock, scoring |
| `tasks/root-cause-s7/` | The generated Harbor task (do not edit by hand) |

The browser app is outside the `rootcause` package on purpose. Only `envkit` and `rootcause` go into the Harbor bundle, so a change to the dashboard cannot change a bundle hash or a score.

## The mechanism

Each zone is a closed recirculating loop, modelled as one well-mixed volume (substrate slabs plus drain tank, counted once). Two masses are dissolved in it and stored separately:

- **Nutrients** are taken up by the crop in proportion to growth, at a rate per kg that rises through the season on a published schedule. A fixed feeding plan that suits day 1 starves the crop by the second week.
- **Salts** arrive with every litre of fresh water and with fertilizer, are never taken up, and leave only when solution is flushed or overflows.

Electrical conductivity is derived, never stored: `EC = 1.5 dS/m per g/L × (nutrients + salts) / volume`. Both count equally, so EC cannot say which is present. Two zones at EC 3.6 can hold 2.0 g/L nutrients with 0.4 g/L salts, or 0.5 with 1.9: one has more nutrient than it needs, the other is starving in salty water.

The three daily actions interact:

- **Irrigation** replaces transpired water and dilutes. Transpiration removes water only, so it concentrates everything dissolved. Heat raises demand.
- **Fertilizer** cures nutrient shortage and raises EC.
- **Flushing** bleeds solution to waste (nutrients and salts alike, in proportion to concentration) and refills with fresh water. It is the only way to remove salt, and it spends scarce water and the nutrients already paid for.

Fresh water is shared by all zones and limited twice: a season allocation and a daily delivery cap.

## Order of one day

The same for every caller (`Greenhouse.advance`, `model.step_zone`):

1. The plan in effect is fixed: the plan submitted for today, or the default plan if none was submitted. If fresh water cannot cover the default plan, every zone's default irrigation is cut by the same factor.
2. Fresh water for irrigation and flushing is drawn from the shared allocation, for all zones at once.
3. Flush: `flush_l` litres leave with `flush_l / volume` of each dissolved mass; the same volume of fresh water replaces them.
4. Irrigation: fresh water is added. Volume above capacity overflows to waste at the mixed concentration. Every litre of fresh water brings 0.15 g of salt.
5. Fertilizer dissolves: 92% nutrient, 8% salt. It adds no water.
6. Plants transpire, grow and take up nutrients.
7. Crop condition for tomorrow is set from today's stress.
8. Water, fertilizer and discharge are charged. Test fees were charged when ordered.
9. Next morning: due tests are delivered, sensors are read, a new forecast is issued.

Zones do not interact within a day, so the order in which they are computed cannot favor one.

## Formulas

With `v` the volume after irrigation, `T` the day's transpiration and `v_mid = v − T/2`:

| Quantity | Rule |
|---|---|
| Water demand | `base × temp_factor × (0.4 + 0.6 × condition)`; `temp_factor = 1 + 0.06 per °C above 24`, `−0.02 per °C` below, floor 0.7 |
| Transpired | `min(demand × supply, v − 300)`, `supply = clamp((v − 300) / (750 − 300))` |
| Water factor | `T / demand` |
| Nutrient factor | `1 − (1 − min(1, c_N / 1.2))²`, `c_N` in g/L at `v_mid` |
| Salinity factor | `clamp(1 − 0.12 × max(0, EC − 3.5))`, EC at `v_mid` |
| Heat factor | `clamp(1 − 0.04 × max(0, temp − 30), 0.5, 1)` |
| Growth (kg) | `min(growth_max × condition × heat × water × nutrient × salinity, nutrient_g / uptake_rate)` |
| Nutrient uptake | `uptake_rate × growth_kg`, `uptake_rate = 5 + 1.1 × day` g/kg (fruit filling needs more nutrient per kg as the season goes on; day 13 needs 19.3 g/kg) |
| Stress | `1 − water × nutrient × salinity` (heat is excluded: no action changes it) |
| Condition tomorrow | stress > 0.10: `condition − 0.25 × (stress − 0.10)`, floor 0.2; otherwise `min(1, condition + 0.03)` |

The curves are continuous and piecewise smooth; there are no hidden cliffs. Every parameter is in `Params` and published by `get_rules`.

**Timing of damage and recovery.** Today's growth uses this morning's condition, so stress costs growth immediately through the factors above and again from tomorrow through lower condition. Condition recovers by 0.03 per calm day and never faster: a crop that drops from 1.0 to 0.7 needs ten stress-free days to recover, which is most of the season. Harvest only accumulates; a day's growth is added once.

## What the player sees

Every morning, per zone: EC (sensor error σ = 0.06 dS/m), solution volume, crop condition and harvest so far (all exact), plus yesterday's plan and outcome. A seven-day temperature forecast whose error grows with lead time; the temperature that occurred appears in the history once the day has passed.

Not shown: each zone's split between nutrients and salts, and future weather. A **composition test** (€25) samples the solution at the moment it is ordered, before that day's plan, and delivers nutrients and salts in g/L with the sample volume the next morning. The result is stamped with its sample day. Because the rules are public it can be rolled forward exactly: convert to masses, then apply the day's plan and uptake (`test_a_result_can_be_rolled_forward_with_the_public_rules`).

Nothing about the model is secret. The dashboard and the agent get the same observations and the same actions. Hidden state appears only in the post-episode analysis, which the engine refuses to produce before the last day has been played.

All weather, forecasts and sensor errors are drawn before the first decision from named random streams, so an extra read, test or plan cannot change them.

## Requests

| Tool | Effect |
|---|---|
| `get_rules`, `get_status`, `get_history`, `get_forecast`, `get_pending_tests`, `get_events` | Reads. Free, repeatable, change nothing, never move time |
| `order_test(zone_id)` | Samples now, charges €25 once. One sample per zone per day |
| `submit_day_plan(zone_plans)` | Sets today's plan for all four zones at once. Replaces an earlier plan for today. Nothing is applied or charged yet |
| `advance_day()` | Applies the plan in effect, runs the day. The only call that moves time |
| `finish_episode()` | Stops deciding; the remaining days still run |

A plan is accepted or rejected whole. Rejection changes nothing, charges nothing and lists every problem with the amounts needed to fix it. A plan that would draw more than the daily cap or the allocation is rejected; water is never created and no zone is served first. A plan lasts one day.

## Scoring

Raw objective: `profit = €2.00 × harvest − water − fertilizer − discharge − tests`. Unused water and fertilizer are worth nothing.

Reward: `clamp((profit − floor) / (ceiling − floor), 0, 1)`.

- **Floor** is the profit of the default plan on the same instance, computed by running the simulator with no requests. Doing nothing scores exactly 0.
- **Ceiling** is an upper bound on any plan's profit: sales from stress-free growth on every day, minus the cheapest water and fertilizer that such growth must consume beyond what the zones hold at the start. The derivation is in `outcome.ceiling`; it holds because growth takes up a fixed mass of nutrient per kg and needs transpiration in proportion. It ignores the day needed to learn a zone's composition, all flushing, all tests and forecast error, so no plan reaches 1.0.

Both bounds depend on the instance only, never on who plays or on any evaluation result. The conversion is monotonic. Profit below the floor clips to 0, which is why raw profit is always reported next to the reward.

**Every run is scored at the end of day 13.** Doing nothing is the default plan for fourteen days. Stopping early, calling `finish_episode`, closing the browser or a dead agent process all end the same way: the remaining days run under the default plan, and tests already ordered stay charged. An unfinished browser run has no result and none is projected, because projecting one would read hidden state. The number of calls, tests or plans is not rewarded, and nothing a player writes is graded.

## Integrity

- One engine. The browser server and the MCP sidecar both hold an `envkit` episode and pass requests to `Episode.call`; scripted policies use the same call through a client.
- The result is recomputed, not trusted. The sidecar appends every request to `trace.jsonl`. The verifier, in a separate container holding its own copy of the code, replays that trace, plays any unplayed days, checks that the water, nutrient and salt balances close, and writes the reward. It never reads a number the trace claims.
- A run whose balances do not close is not scored: `env.ledger` raises and the verifier reports an infrastructure failure instead of a reward.
- The agent's container holds no scenario, seed or engine code. It reaches the simulator only on its MCP port, which has no reset, state or file route.

What this does and does not establish is stated under limitations.

## Comparators

All four play through the tools only (`test_scripted_policies_touch_only_the_public_tools`).

1. **Do nothing**: no requests; the default plan runs every day.
2. **Stop early**: the reference plays the first four days, then stops.
3. **Rule-based**: tops each zone up to a fixed level and feeds or flushes by EC band. It never tests, so it reads EC as a nutrient gauge.
4. **Reference**: tests every zone on day 0, then keeps its own estimate of each zone's nutrient and salt mass, rolled forward each morning with the published rules. Every morning it scores a grid of candidates per zone (flush today × nutrient level × volume level) by simulating its estimate to the end of the season under the forecast, and picks one per zone under both water limits by raising an internal price on water. Only today's part is submitted.

The reference is a strong comparator and is **not** claimed to be optimal. Known weaknesses: it tests all four zones although one day of growth data can identify a nutrient-short zone for free; it acts on a guess on day 0; its grid is coarse; it plans against a point forecast.

## Simplifications and limitations

- One lumped nutrient and one lumped salt. No pH, no individual ions, no specific-ion toxicity, no disease, no light or humidity.
- EC is linear in total dissolved mass. Real EC depends on ion species and temperature.
- Each loop is perfectly mixed and treated as one volume; real slabs and drain tanks lag each other.
- One decision and one update per day; within-day dynamics are reduced to a mid-day volume.
- Temperature is the only weather variable.
- The salinity curve has the threshold-and-slope form of Maas and Hoffman (1977, "Crop salt tolerance: current assessment", *J. Irrig. Drain. Div. ASCE* 103). The threshold and slope here are not their tomato values, which were derived for soil saturation extract, not a recirculating solution. The idea of removing salt by applying water beyond crop demand follows the leaching-fraction concept in Ayers and Westcot (1985, FAO Irrigation and Drainage Paper 29). These sources were cited from memory during the build and were not re-read; treat them as pointers to the mechanism, not as support for any number here.
- Prices are stylized so that water, fertilizer and tests each matter within fourteen days.
- After the first test, a careful player can track a zone's composition exactly, because uptake is a known function of observed growth. Repeated testing therefore has little value in this version. Hidden per-zone variation in uptake or source-water salinity would change that and is not implemented.
- The trust boundary is tested at the level of traces and replay, by one scripted Harbor run per policy, and by a scripted probe run inside the agent's container (`scripts/harbor_boundary_probe.sh`; results in EXPERIMENTS). It has not been attacked by a model with a shell, and only local Docker was tried.
