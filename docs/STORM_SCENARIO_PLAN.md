# Storm-season scenario: requirements and implementation plan

**Status:** proposal for review, not implemented.  
**Point of contact:** Max.  
**Reserved files for the first implementation slice:** this plan, a new storm scenario,
its new facility and storm/news data files, plus the generated task/calibration output. Schema,
event/news engine, and policy changes need separate agreement with Rowan before editing.

## Goal

Add a reproducible 42-day `storm-season` benchmark where the agent must balance inventory
cost against the risk and cost of being unprepared for damaging storms. The scenario must make
planning under uncertainty meaningful: forecasts can be correct or false, and they must not
reveal a hidden storm hour, exact damage, affected equipment, or the seed's construction
witness.

It also raises the operating workload to four compartments on one shared energy centre:

| Compartment | Crop | Initial state | Intended planning pressure |
|---|---|---|---|
| A | Radish microgreens | early-stage crop | reserve seed and schedule a later replacement |
| B | Radish microgreens | late-stage crop | harvest and replant soon, without flooding its rolling weekly market |
| C | Broccoli microgreens | mid-stage crop | coordinate a slower cycle with the demand calendar |
| D | Butterhead lettuce | mid-stage crop | manage the longest crop cycle and plug lead time |

Each compartment starts with a defined occupied area, rather than unused land. Exact ages,
areas, facility capacity, demand, and forecast rates remain data values to calibrate; they will
not be hard-coded in Python. The four areas should initially redistribute the current facility's
total growing area, so difficulty comes from coordination rather than an accidental fourfold
energy load.

## What is already reusable

- `normal-winter` already has deterministic per-seed weather, storms triggered by recorded wind,
  persistent broken-glass damage, a regional post-storm supplier/contractor surge, contractor
  bookings, glass inventory, and replayable scoring.
- A glass-pane order before a storm keeps its normal lead time; an order after it gets the surge
  lead time. Existing tests establish that buying and booking earlier repairs much sooner.
- Storm news already has a 24–72 hour lead window, an 80% hit rate, and false alarms. The agent
  receives only its briefing, not the event schedule.
- The facility format already supports any number of uniquely named compartments and staged start
  batches. Crop planting and the current reference already support repeat sowing/replanting.

## Gaps to close

Current storm headlines are generic. They do not say whether the forecast is mild or severe, and
the event's 0–12 broken panes are independent of a headline. The current reference orders panes
and books a glazier only after it sees damage. The existing facility has only three compartments
and no lettuce production compartment.

Terms such as *heavy rain* and *thunder* must not be cosmetic. In version one, a forecast label is
allowed only when it changes the probability or expected glass damage. Hail is a suitable glass
damage signal. Rain or thunder requires a separately modelled operational consequence before it is
advertised; otherwise it would create fake complexity.

## Forecast contract

The agent sees named, public forecast classes in the daily briefing, for example:

| Class | Meaning to publish | Permitted outcome |
|---|---|---|
| Wind watch | elevated probability of a damaging wind event in the coming days | no storm, minor storm, or severe storm |
| Severe wind / hail warning | materially higher probability and larger expected pane loss | false alarm, or a damaging storm |
| Ordinary weather bulletin | no storm-specific claim | may still be followed by an unannounced storm |

Each class will publish a coarse probability and damage band in the rules, not a precise time,
pane count, compartment outcome, or certainty. A false warning uses the same language as a true
one. An unannounced storm remains possible at the published miss rate. The agent can rationally
choose whether to carry spare panes and perhaps book a conditional repair only after damage; it
cannot solve the task by treating every bulletin as truth.

Severity must be coupled at the data boundary: a severe warning and the realised storm draw from
the same public severity model, while retaining per-compartment random damage. This replaces the
present independent headline/damage draw. All randomness remains in named `Rng` streams, fixed by
scenario and seed.

## Reference-policy requirement

The reference must make the same decision from the same briefing as an agent. It must not inspect
the recorded wind series, storm schedule, event occurrence, or hidden severity draw.

Before implementation, define and test two policies:

1. **Reactive baseline:** current behaviour, ordering panes after observed damage.
2. **Forecast-aware reference:** computes the public expected cost of holding panes against the
   expected avoided outage/surge cost, keeps a capped safety stock when the published forecast
   justifies it, and still orders/rebooks repairs after actual damage.

The second policy must outperform the reactive baseline on development seeds by a material,
reported margin, but not dominate every false-alarm seed. It must also continue the normal crop
cycle: order seed/plugs with their lead times, plant after each harvest, and allocate its five
daily actions across crops, energy, inventory, and repairs.

## Implementation sequence

1. **Freeze the scenario contract.** Agree forecast classes, public probabilities, damage bands,
   maximum glass stock rationale, seed suite, and what weather phenomena have mechanics. Record
   the contract and Rowan's ownership of news/event/schema changes before dependent edits.
2. **Add data-driven severity.** Extend the news and storm schemas and their tests so true and
   false forecasts have classed messages, with no witness leakage. Keep `normal-winter` behaviour
   unchanged through its existing data files.
3. **Create the storm data.** Add a storm event configuration with controlled severity settings,
   a matching news configuration with false alarms and misses, and recorded-weather selection or
   scenario-specific deterministic pins sufficient to exercise the decision across development
   seeds. Do not use a single guaranteed storm as the only test.
4. **Create a four-compartment facility.** Define A/B radish at distinct starting stages, C
   broccoli, D lettuce; distribute floor area and validate start batches. Use the existing crop,
   market, energy, and climate formats unless calibration shows a justified new data file is
   needed.
5. **Add `scenarios/storm-season.toml`.** Reuse the daily `submit_day` interface, 42-day horizon,
   anchored profit scoring, and separate development/evaluation seeds. Its prompt documents the
   four compartments, forecast reliability, stock/repair economics, and no-hidden-information
   guarantee.
6. **Make the reference forecast-aware.** Add focused unit tests proving it reacts only to
   displayed news, carries stock when warranted, avoids indiscriminate buying on weak/false
   signals, and keeps planting after harvest.
7. **Integrity and calibration.** Add deterministic tests for forecast truth/false alarms/misses,
   severity correlation, pre- versus post-storm ordering, repeated crop cycles, invalid actions,
   no-op, early stop, replay, and information leakage. Rebuild `storm-season` tasks and
   calibration; compare reference, reactive, and exploit baselines on development seeds.
8. **Review before benchmark claims.** Run the quick check after each change. Only after explicit
   approval run 42-day builds, audit, model smoke, or model benchmarks. Record SHA, commands,
   seeds, harness/model versions, duration, and failures; do not claim a frontier gap without
   official-kit runs.

## Acceptance criteria

- Same seed and action trace reproduce the same forecast feed, storm outcomes, ledger, and score.
- The briefing contains useful uncertainty but no construction witness or exact outcome.
- Both true severe warnings and false severe warnings occur in the development suite; at least one
  damaging storm is unannounced at the published miss rate.
- Pre-positioned panes can beat post-storm ordering when a storm occurs, while unused panes have a
  real opportunity cost at episode end.
- The reference's forecast-sensitive inventory decision is explainable from public rules and
  briefings only.
- Four compartments require repeat planting to sustain output; a harvest-once policy is clearly
  worse than the reference without relying on a hidden score component.
- `normal-winter` remains byte-for-byte behaviourally compatible unless intentionally changed and
  re-calibrated as a separately reviewed decision.

## Validation commands

During planning, no benchmark episode is run. For implementation, run only the required quick
check after each change:

```bash
bash scripts/quick.sh
```

The 42-day `storm-season` build, audit, reference comparisons, and any model run require explicit
approval because they are benchmark checks.
