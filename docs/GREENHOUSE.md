# Root Cause: model, incident, rules and scoring

Three NFT benches of butterhead lettuce over the last six days before
harvest. An agent plays through MCP tools. The scripted comparators and the
verifier drive the same engine through the same calls.

**This is a transparent, simplified research simulator, not a validated
agronomic model.** Parameter values are illustrative. They were chosen so
that the incident and its remedy matter within six decisions. They were not
fitted to data.

## Where the code is

| Path | What it holds |
|---|---|
| `src/rootcause/model.py` | Every parameter and response curve; `step_bench` is one bench, one day |
| `src/rootcause/generator.py` | Seeded instances: benches, weather, forecasts, sensor noise, the incident |
| `src/rootcause/sim.py` | `Greenhouse`: plans, tests, the daily update, the notice, accounting |
| `src/rootcause/views.py` | What a player may see during play |
| `src/rootcause/outcome.py` | Profit, the reward bounds, conservation checks, failure modes, the post-episode report |
| `src/rootcause/env.py` | The `envkit` binding: the tools |
| `src/rootcause/planner.py` | Reference, blind and informed planners (one planning core) |
| `src/rootcause/policies.py` | Absentee and EC-rules comparators |
| `scenarios/root-cause.toml` | The scenario: prompt, clock, call limit, scoring, Harbor limits |

## Why this setup

- **NFT, not deep-water rafts.** Commercial greenhouse lettuce is grown
  mostly in NFT channels or on floating rafts (DWC). A raft pond holds so much
  water that a change in the supply barely shows within a week. An NFT
  bench's small recirculating tank turns over about a quarter of its volume
  a day, so a change in the source water reaches the roots within days. Each
  bench is one gully bench with its own tank, treated as one well-mixed
  volume.
- **Lettuce targets.** Hydroponic lettuce is usually run at an EC of about
  0.8–1.4 mS/cm, and it is salt-sensitive. Here nutrition saturates at
  0.75 g/L (≈1.1 dS/m), and salinity stress starts above 1.8 dS/m and cuts
  growth by 25% per dS/m.
- **One incident.** On the morning of day 1 the utility moves the mains to a
  backup source carrying 1.2–1.5 g/L of salt, against the usual 0.10 g/L. The
  notice ("switched to a backup source") is real-world vague: it names the
  change, not its consequence. Day 0 is normal, so every player sees what
  "before" looks like.
- **A real remedy that costs something.** A clean reverse-osmosis reserve
  tank (2,400 L, shared, never refilled) costs four times as much as mains
  water. In normal operation nobody should use it. After the switch, it is
  the only way to top up without adding salt, and it does not cover every
  bench for every day, so it has to be allocated.

## The mechanism

Two masses are dissolved in each bench and stored separately:

- **Nutrients** are taken up in proportion to growth, at a rate per kg that
  rises slowly (older heads need more per kg).
- **Salts** arrive with mains water, a little with fertilizer, and none with
  reserve water. They are never taken up, and they leave only by flushing or
  overflow.

EC is derived, never stored: `EC = 1.5 dS/m per g/L × (nutrients + salts) / volume`.
After the switch, EC rises on every bench. That rise is salt, and nothing in
the readings says so. Transpiration removes water only, so whatever the
top-up brings in is concentrated further.

Daily actions per bench interact:

| Action | Effect | Trap after the switch |
|---|---|---|
| `mains_l` | Replaces transpired water; brings that day's mains salt | Each litre now brings 12–15× the usual salt |
| `reserve_l` | Clean top-up; costs 4× mains; shared and limited | Must be shared across benches and days |
| `fertilizer_g` | Cures nutrient shortage; raises EC | Cutting it because EC rose starves the crop |
| `flush_l` | Bleeds solution to waste and refills with **mains** water | Refilling with the backup water removes nutrients and buys back little salt |

## Order of one day

1. The plan in effect is fixed: the plan submitted for today, or the default plan.
2. Flush, refilled with mains water at that day's mains salt.
3. Top-up with mains and reserve water; volume above capacity overflows at the mixed concentration.
4. Fertilizer dissolves: 95% nutrient, 5% salt.
5. Plants transpire, grow and take up nutrients.
6. Crop condition for tomorrow is set from today's stress.
7. Mains water, reserve water, fertilizer and discharge are charged. Test fees were charged at order time.
8. Next morning: due tests are delivered, sensors are read, a forecast is issued, and any notice is posted.

## Formulas

With `v` the volume after the top-up, `T` the day's transpiration, and `v_mid = v − T/2`:

| Quantity | Rule |
|---|---|
| Water demand | `base × temp_factor × (0.4 + 0.6 × condition)`; `temp_factor = 1 + 0.05/°C` above 22 °C, `−0.02/°C` below, floor 0.7 |
| Transpired | `min(demand × supply, v − 250)`, `supply = clamp((v − 250) / (600 − 250))` |
| Water factor | `T / demand` |
| Nutrient factor | `1 − (1 − min(1, c_N / 0.75))²`, `c_N` in g/L at `v_mid` |
| Salinity factor | `clamp(1 − 0.25 × max(0, EC − 1.8))`, EC at `v_mid` |
| Heat factor | `clamp(1 − 0.05 × max(0, temp − 26), 0.5, 1)` |
| Growth (kg) | `min(growth_max × condition × heat × water × nutrient × salinity, nutrient_g / uptake_rate)` |
| Uptake | `uptake_rate × growth`, `uptake_rate = 4.0 + 0.2 × day` g/kg |
| Stress | `1 − water × nutrient × salinity` |
| Condition tomorrow | stress > 0.10: `condition − 0.30 × (stress − 0.10)`, floor 0.2; else `min(1, condition + 0.03)` |

Every parameter is in `Params` and published by `get_rules`.

## What the player sees

- **Every morning, per bench:** EC (σ = 0.04 dS/m), volume, crop condition
  and crop gained (exact), plus yesterday's plan and outcome.
- **Also:** a day-0 lab report for every bench (exact), notices, a 3-day
  temperature forecast, the reserve left, and costs.
- **Not shown:** each bench's nutrient/salt split after day 0, and the backup
  water's salt.
- **Tests:** a composition test (€15) reports a bench's split. A mains water
  test (€15) reports the salt in the supply. Both are sampled when ordered,
  and the result arrives the next morning.
- **Diagnosing without a test:** because the rules are public, the
  unexplained part of the EC rise can also be turned into an estimate of the
  new salinity. That is how the reference cross-checks.

## Scoring

- **Raw:** `profit = €2.50 × crop gain − mains − reserve − fertilizer − discharge − tests`.
- **Reward:** `clamp((profit − floor) / (informed − floor), 0, 1)`.
  - `floor` is the default plan's profit on the same instance.
  - `informed` is the planner's profit when it knows the backup salinity
    from the notice on and sees the true bench state every morning.
- **Context only:** a proven upper bound on profit (stress-free growth at
  the cheapest water and fertilizer) is reported as `profit_upper_bound_eur`.
  No plan reaches it.
- **Every run is scored at the end of day 5.** Stopping early,
  `finish_episode`, the 120-call limit, a timeout or a dead agent all run
  the remaining days on the default plan. Tests already ordered stay charged.

## Failure modes

`outcome.failure_modes` reads hidden state after the last day and reports
how a run lost value. Crop lost on a bench-day is split into four causes:

- **carried damage:** condition below the best reachable condition, caused
  by earlier stress;
- **water, nutrient and salinity:** the rest of the gap, shared in
  proportion to `−ln(factor)`, so the shares add up exactly.

Counters:
- bench-days short of nutrient;
- bench-days under salt stress;
- bench-days fed below the default while short of nutrient (the misread-EC
  signature);
- days from the notice to the first test, and the day of the mains test;
- litres flushed after the switch;
- reserve used and left;
- days on the default plan.

Each comparator has its own recognizable signature (tests in
`tests/test_rootcause_sim.py::FailureModeTests`):

| Comparator | Signature |
|---|---|
| Do nothing | dominant loss salinity; never tested; 6 default days |
| EC rules | 9–11 bench-days fed less while short; 2,700–3,300 L flushed with backup water; reserve unused; nutrient loss above €50 |
| Blind planner | dominant loss salinity; reserve unused; never tested |
| Reference | tests the water on the notice day; uses most of the reserve; loses less than half of what doing nothing loses |

## Comparators

All of these play through the tools only.

1. **Do nothing:** the default plan every day.
2. **Stop early:** the reference for the first two days, then the default plan.
3. **EC rules:** top up to a level with mains water; feed by EC band; flush
   when EC is far above the threshold. It never tests and never uses the
   reserve.
4. **Blind planner:** the reference planner without diagnosis. It assumes
   the water is unchanged and trusts its own model.
5. **Reference:** diagnoses, tracks state, and plans by grid search to the
   last day (see the README). It is a strong comparator, **not** a proven
   optimum. Known weaknesses: a coarse grid, planning against a point
   forecast, and one day of acting on a precautionary guess before the
   water test arrives.

## Simplifications

- One lumped nutrient and one lumped salt. No pH, no individual ions (no
  sodium or chloride toxicity, no calcium-driven tipburn), no disease, no
  light or humidity.
- EC is linear in total dissolved mass.
- Perfect mixing; one decision and one update per day.
- Temperature is the only weather variable, and it is mild here (21–23 °C);
  the incident is the only shock.
- Revenue counts the head weight added during the six days. The weight at
  the start is a constant and is left out.
- The salinity curve has the threshold-and-slope form of Maas and Hoffman
  (1977). Its numbers are not their lettuce values, which were derived for
  soil saturation extract.
