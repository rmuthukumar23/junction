# Greenhouse Bench: Project Context

Status: decisions and research as of 14 Nov 2026 (Junction 2026, AfterQuery "Break the Agent" challenge).
Purpose of this file: give full context on what we are building and why. It describes the environment, the scenario, the scoring and the benchmarking approach. It does not prescribe code structure or implementation.

Related material:
- Design brief (living doc): https://claude.ai/artifact/DuomRUU4RWfggQd6N1rZum
- Facility map (pixel visualisation): https://claude.ai/artifact/BUKL1iNZkuiPxNMHCLJDYt

---

## 0. Pinned decisions (14 Nov 2026, round 3)

**This section overrides anything later in this file that disagrees with it.** Where the team refined a pinned point, the refinement is marked *Agreed refinement*. The build spec ([GREENHOUSE_SPEC.md](GREENHOUSE_SPEC.md), section 14) turns this into interfaces; who builds what is in [collaboration/](collaboration/).

### 0.1 Setting: the Netherlands

- The default facility is a Dutch glasshouse: CHP, peak boiler, heat buffer, OCAP-style CO2 supply, grid buy and sell.
- Reason: far more data and market. Dutch glasshouse area is about 9,000 to 10,000 ha, against a total Finnish greenhouse sector of EUR 410 m. Van Henten, GreenLight and GL-Gym are all calibrated on Dutch greenhouses. Wageningen's open lettuce dataset from the 2022 Autonomous Greenhouse Challenge (4TU.ResearchData, CC BY 4.0) can be used to sanity-check the simulator.
- Finland is not implemented. At most it is one line in the pitch.

### 0.2 The agent works the day shift only (hard stop)

**Rule.** The agent is on duty 06:00 to 18:00 simulated time, every day. At 18:00 it is switched off: it cannot act, read or receive anything until 06:00. The simulator runs the night with no agent involvement. At 06:00 the agent wakes and must find out what happened overnight through the normal tools.

**What the agent may set for the night: only an hourly schedule of fixed values.** For each night hour and compartment: heating setpoint, vent limits, screen position, lamps on/off and intensity, CO2 setpoint. For the facility, per hour: CHP load, boiler on/off and level, buffer charge/draw. If nothing new is set, the last submitted schedule carries over. The schedule must be committed before 18:00; anything not committed is ignored.

**What the agent may not do for the night.** No conditional rules ("if the temperature drops below X ..."), no triggers or thresholds that change behaviour, no on-call callouts, no alarms the agent can respond to, no background scripts. Nobody comes in at night.

*Agreed refinement: how the equipment behaves at night (replaces "no automatic switching").* Real Dutch climate computers (Priva, Hoogendoorn, Ridder) do sequence heat sources automatically, and real sites have an on-call grower. We keep the first, because it is ordinary equipment behaviour, and drop the second on purpose. The rule:
- Each night hour, the schedule says which equipment is **available** and up to what level: boiler (off, or up to a level), buffer draw (off, or up to a kW), CHP (a fixed load), external CO2 (up to a rate).
- The climate computer works like a thermostat: within the hour it draws heat from the available sources in a fixed, published order (CHP at its fixed load, then buffer, then boiler) up to what the setpoints need.
- Equipment that is not available that hour never starts. If an available source fails, the others take up the slack only as far as they were made available. Nothing re-plans: no rule changes the schedule, and nothing unscheduled turns on.
- This keeps the trade-off: insurance has to be paid for in advance. A full buffer must be charged during the day. The CHP runs at its scheduled load whether or not heat is needed (gas burnt, power sold at night prices). The boiler's scheduled level caps it.
- The strict version (only exactly scheduled output, no thermostat) was considered and rejected: real equipment does not work like that, and judges would call the losses artificial.

*Agreed refinement: sharing heat and CO2 when there is not enough.* "Scarce" means the available sources cannot deliver what all compartments ask for at once. Example: the boiler fails, the buffer gives 400 kW, and A and B together want 900 kW. The night schedule may hold **priority and caps per hour as fixed values**: "A has priority" means A is kept at its setpoint as far as possible no matter what, and B gets what is left. Caps set an exact maximum per compartment. These are fixed values, not conditional rules, so they are allowed. If the schedule sets none, supply is shared in proportion to demand. By day the agent can change them at any time (D2).

*Agreed refinement: 06:00.* At 06:00 the day settings the agent had in force at 18:00 the previous day resume. The night schedule repeats every night until the agent changes it.

**What still happens automatically (physics, not decisions).** The thermostat behaviour above. If scheduled equipment fails, it stops, and the shortfall in heat or CO2 is real; the crop experiences it.

**The morning report.** At 06:00 these are readable through MCP tools: an overnight event and alarm log with timestamps (what failed, when), hourly climate per compartment for the night, crop damage and stress changes per batch, deliveries that arrived, stock levels, money spent overnight. The agent has to read them; nothing is pushed.

**Physical work.** Staff exist only during the day shift. Planting, harvesting, repairs and inspections can only be scheduled into 06:00 to 18:00 and consume worker-hours. A repair for something that broke at night starts the next morning at the earliest.

**Baseline and stopping (D5, revised).** At hour 0 the facility runs the anti-freeze baseline: 5 °C heating, no CO2, lamps off, as day settings and as the night schedule. An agent that does nothing keeps it for 42 days: crops survive but stall below sellable weight, nothing is harvested, wages and gas are paid. That is the heavy punishment for doing nothing. When an agent stops for any reason, its last day settings and night schedule run for the rest of the episode and nobody acts.

### 0.3 Forecasts and information policy

**Allowed during the shift.** Weather forecasts several days ahead with error (temperature, sun, wind, cold snaps, storms). Energy price forecasts (gas, hourly electricity, spike risk). General news-style signals written as real headlines, for example "Storm warning for the coast from Thursday night", "Cold spell expected, frost likely overnight", "Gas prices rising on supply fears", "Trade disruption affecting CO2 and fertiliser shipments", "Grid operator warns of congestion this week", "CO2 supplier announces maintenance at its main source". Documented event types and base rates, in the task description.

**Not allowed (would give the answer away).** No warning that a specific piece of equipment will fail, or when. No warning that a sensor is drifting. No exact timing of any event. No hidden facility parameters.

Rule of thumb: a news signal is something a real grower could read in the news or a weather report. It raises the probability of an event type; it never names the exact event or time. *Agreed refinement:* signals also appear when nothing follows (false alarms, at a documented rate), and storm and frost signals follow the recorded weather (D3), so they are honest forecasts, not hints.

### 0.4 Why this is defensible (README and pitch)

- Real Dutch greenhouse floor work is day-shift: Westland jobs typically start around 06:00 with 8-hour shifts. At night the climate computer runs on its settings and nobody is on the floor. Dutch alarm systems even defer low-priority night alarms to the next morning.
- No published percentage of greenhouses with night staff was found. Do **not** claim a number such as "under 5%". Say "greenhouse floor work is day-shift; nights are unstaffed."
- The hard stop is a deliberate modelling choice: we model the day operator, not an on-call technician. Real sites often have an on-call person; we leave that out on purpose, to make planning ahead the core skill.
- It targets a known weakness: in SimuHome (ICLR 2026), scheduling actions ahead was the hardest category, because agents cannot verify a scheduled action when they set it, while over 40% of their successes on direct device control relied on correcting themselves from immediate feedback.
- **Before any of these go into the README, check each source** (Westland shift times, alarm deferral, SimuHome figures, Wilo rates). Nobody on the team has verified them yet.

### 0.5 Guardrails the build must respect (rubric: "meaningful difficulty")

The rubric scores zero if the gap comes from withheld information or impossible timing. A good day plan must **reduce** night losses, even if it cannot prevent them.

1. **Planning must pay off.** A well-planned night (buffer filled before 18:00, screens closed on cold nights, conservative setpoints, CHP and boiler both available on a frost night, repairs done by day) loses clearly less than a naive night when the same event happens. Tested explicitly.
2. **Redundancy is the only insurance**, and it costs money, so it is a real trade-off.
3. **Night events come from documented base rates**, seeded and reproducible. Same seed, same night.
4. **The reference policy plays under exactly the same shift rules.**
5. **Every night event leaves a visible trace** in the morning report.

### 0.6 Episode loop

```
for each simulated day:
    06:00            agent wakes; tools available; the morning report covers the night
    06:00 to 18:00   agent acts (advance moves time and stops at 18:00 at the latest); staff do physical work
    before 18:00     agent commits the night schedule (hourly fixed values only)
    18:00            the only possible action is end_shift; every other tool answers "off duty"
    18:00 to 06:00   end_shift runs the night on the schedule inside that one call; events may fire
```

Because simulated time moves only through tool calls, the night exists only inside `end_shift`: no script can reach the simulator "at night".

### 0.7 Damage, repairs, contractors and spare parts

Replaces the single generic "request a repair" action.

**Damage persists until repaired.** Broken glass, a torn screen, a stuck vent motor, a failed boiler or CHP: the effect stays until a repair is completed. Broken panes raise leakage and heat loss in that compartment every hour until replaced. The amount of damage is drawn per event and seed from documented ranges (a storm can do nothing, a little or a lot).

**A repair needs three things at once:** the right contractor booked and on site, the right parts on site, and day-shift time. If any is missing, the repair waits.

**Contractors.** Each repair type needs a trade, with per-seed values within documented ranges: call-out fee, hourly rate, job duration per repair type, response time (normal booking, e.g. next day, vs urgent same-day at a surcharge), and availability (after a regional storm the glazier is overloaded and response times rise sharply). Full set: glazier / repair crew (panes, gutters, screen frames), screen installer, heating installer (boiler, pipes, valves, buffer), CHP service engineer (service contract, next-day response), electrician (lamps, power, vent motors, controls), fertigation technician, sensor / climate computer technician. Calibration reference, as ranges only: a service engineer around EUR 94 per hour with a similar call-out fee and 150–200% for out-of-hours work (Wilo price list); installers around EUR 55–85 per hour (Dutch price guides).

**Spare parts** (inventory with lead times): glass panes, screen cloth, vent motor, pump, sensors, boiler parts, CHP parts. Each has a unit price, a normal lead time, an express option, and a surge after regional events.

**Order queue rule.** Parts arrive after their lead time, like any delivery. Orders placed **before** a regional event keep the normal lead time. Orders placed **after** it get the surge lead time (glass: about three weeks, after the 2025-26 Dutch windstorm; the normal lead time of a few days is a design assumption). Express shortens the lead time at a higher price, but during a surge it shortens the surge time, not back to normal. Ordering spare glass before a forecast storm is therefore a gamble: repaired in days if the storm does damage, money spent for nothing if not. **Spare parts left at the end have no value**, like standing crop, so hoarding is not free.

**Forecast link.** Storm, cold and supply signals only raise the probability of damage; they never say how much or which part.

**Reward terms:** contractor call-out fees and labour, urgent-booking surcharges, spare parts bought (including unused), express surcharges.

**Tests:** (1) same seed and storm with damage: pre-ordering glass and booking the glazier the next morning loses clearly less than waiting; (2) same storm without damage: pre-ordering only costs money; (3) a repair cannot complete without the part, the contractor and a day slot; (4) after a regional storm, glass lead time and glazier response time rise.

### 0.8 Crops, replanting, seasons and pests

**Lettuce lifecycle.** Propagation (seed to plug) about 11 to 14 days, in a propagator nursery or in-house; production (transplant to harvest) about 24 days at DLI 17, scaling roughly with light (half the light, about twice as long). The episode tracks the production phase per batch; propagation only matters when replanting.

**Replanting, two ways.** Buy plugs from a propagator: dearer per plant, grown to order, so ordered about 2 to 3 weeks ahead (design assumption), longer in winter. Or sow in-house: cheap seed, but propagation space, lamps and worker-hours, 11 to 14 days then transplant. (Real grounding: Dutch propagators such as Beekenkamp grow to order from growers' schedules; one Dutch lettuce grower started propagating in-house under LED because extra winter orders took longer.) Kept: a batch may only be planted if it can reach sellable weight before the episode ends.

**Pluggable crops.** Each crop file has propagation days, production days at reference DLI and temperature, growth response to light, CO2 and temperature, harvest type, climate targets and stress limits, quality effects (tipburn, bolting, disease, pest damage), plant density, minimum sellable weight, price per unit by grade, and seasonal pest susceptibility. Lettuce (butterhead, about 24 days at DLI 17, 24/19 °C day/night targets) is the main crop. Arugula and spinach are optional later; tomato and cucumber are out of scope. *Locked crop set (14 Nov 2026):* lettuce, broccoli microgreens and radish microgreens, nothing else; values and sources in [CROPS.md](CROPS.md). Basil leaves the set (its file stays only as a repeated-cut test fixture).

**Seasons** change inputs, not code. Winter (v1): very low light, lamps decide cycle length, heating is the main cost, CO2 plentiful from the CHP, low bolting risk, lower but non-zero pest pressure, EU nitrate limit 5,000 mg/kg. Summer (later): shade screens, cooling by venting, CO2 scarce with the CHP off, high bolting risk, thrips pressure, nitrate limit 4,000 mg/kg.

**Pests** (later, not v1): hidden pressure per compartment, seasonal base rate (not zero in winter: some aphids thrive at 10–16 °C), visible only by scouting (worker-hours) or late symptoms. Biological control is preventive, ordered with a lead time and slow in winter; pesticide is curative and fast, with a pre-harvest interval (design assumption). Late control on near-ready lettuce saves little. Reward terms: scouting labour, biocontrol and pesticide, value lost.

### 0.9 Corrections from the research (adopted)

- Lettuce: about 24 days transplant to harvest at DLI 17 (Cornell); 35 days is from seed. A winter episode assumes grow lamps.
- 24 °C day / 19 °C night are targets, not maxima.
- Do-nothing: crops mainly stall below sellable weight; frost damage only on near-ready batches.
- Gas comes from the grid: price risk only, no stock or delivery lead time.
- Winter CO2 scarcity is only realistic combined with a CHP outage or a gas price spike.
- No root-zone sensors (EC, pH, solution temperature) and no nutrient or water costs until there is a fertigation model behind them.

### 0.10 v1 scope (agreed refinement)

| v1 (build now) | Later (after the first model comparison) |
|---|---|
| Netherlands, normal winter, 42 days, 2 compartments (crops from the locked set: lettuce, broccoli and radish microgreens) | Summer scenario, other seasons |
| Day shift, hourly night schedule, thermostat with available sources, morning report | Urgent same-day bookings |
| Weather and price forecasts; news signals for storm, cold snap and gas price, with false alarms | CO2/fertiliser supply news, grid congestion |
| Persistent damage; 2 contractors (glazier, heating installer); 2 parts (glass, boiler parts); storm surge; express delivery | The other 5 contractors and parts |
| Plugs from a propagator with a 2–3 week lead time | Sowing in-house (propagation area) |
| Lettuce at 21 days from transplant scaling with light; broccoli (12 days) and radish (8 days) microgreens sown from seed; frost damage on near-ready batches | Spinach, arugula; pests and scouting; sensor drift; fertigation |

---

## 1. The challenge we are answering

AfterQuery's "Break the Agent" challenge asks for a reinforcement learning environment that challenges today's best AI agents, shows real failure modes, and has a reward that reflects real progress.

What the organisers provide:
- Harbor running the OpenCode agent, connecting to our environment over MCP.
- A scoring skeleton and frontier model API credits.
- The agent has a full shell and can write its own scripts or optimisers.

Judging rubric (100 points):

| Criterion | Points | Full points means |
| --- | --- | --- |
| The gap | 30 | The frontier agent consistently scores below a stronger reference run that we demonstrate, reproducibly across repeated runs. |
| Meaningful difficulty | 30 | We can explain the agent's main mistakes and tie them to decisions in the task. The information and tools needed to do better are available to it. Zero if the gap comes from withheld information, trick wording, impossible timing or broken tools. |
| Reward integrity | 25 | The reward measures success, holds up when judges try to exploit it, and doing nothing or stopping early earns little or nothing. |
| Craft | 15 | Rules and behaviour make sense for the setting. Judges can run the evaluation from the README with one command and reproduce our results. |

How judging runs: a 10-minute demo, then judges rerun our reference run, three agent runs, a do-nothing baseline and a stop-early baseline with the standard harness, then spend 15 minutes hunting for reward exploits.

Tiebreaker: a smaller model that improves after training on experience from our environment.

Hard requirements we carry through everything:
- One deterministic reward number from simulator state. No LLM judge, no LLM inside the simulation.
- Same seed and same actions must reproduce the same result exactly.
- Runs from the plain Harbor Docker image with one command. We use Modal only to speed up our own development runs; the environment must not depend on it.
- The simulator lives in a separate container from the agent and is reachable only through MCP tools.

---

## 2. Why a greenhouse, and how we got here

We considered three directions:
1. Grid storm restoration (a distribution control room dispatching repair crews).
2. Commercial greenhouse operations.
3. Emergency dispatch (fire, EMS, flood).

We chose the greenhouse. The concerns raised against it and how we resolved them:

| Concern | Resolution |
| --- | --- |
| The agent could download the public greenhouse simulator (GreenLight / GL-Gym) and optimise offline, closing the gap. | We write our own small simulator, based on a published model but extended with our own prices, events, operations and hidden per-seed parameters. A public copy would be miscalibrated. |
| A passive greenhouse still grows, so doing nothing earns reward (reward leak). | Cold season, crops only count when harvested and sellable, and costs are charged even when idle. |
| Most textbook failures are fixed rules an agent could script (for example, do not dose CO2 with vents open). | The difficulty comes from shared scarce resources, delivery delays, staffing, events revealed over time and hidden facility parameters. These require planning, not rules. |
| Tomato-style fruit crops take months, so a short episode mostly measures decisions made before it started. | Use fast leafy crops (lettuce first) whose full cycle fits inside one episode. |

Hiding the simulator implementation is legitimate and standard (StoreBench does the same). What we must never hide is information the agent needs to decide well: current state, rules, reward terms, event types. Parameters can vary per seed as long as the ranges are documented and the agent can learn the values by observing.

---

## 3. The environment in one paragraph

The agent manages a greenhouse facility for 30 to 40 simulated days in a cold season. The facility has one central energy centre and two or three greenhouse compartments, each growing a crop in staggered batches of different ages. Heat, CO2 and electricity are produced or bought centrally and shared through common pipes and wires, and each compartment has its own climate controls. The agent also runs the operation: staff, consumable stock, orders that arrive days later, and sales contracts. Weather, prices and events (equipment failures, storms, disease, late deliveries) arrive over time. The agent is scored on net profit in EUR, compared against a hand-written reference policy.

---

## 4. The facility

### 4.1 Layout

- **Inputs from outside:** gas, the electricity grid (buy and sell), and an external CO2 supply (pipeline or delivered tanks, capped by contract).
- **Central energy centre (shared):**
  - CHP (combined heat and power): burns gas and produces heat, electricity and CO2 together.
  - Central boiler: heat only, covers peaks.
  - Heat buffer tank: stores hot water for later use.
  - CO2 supply: from CHP flue gas or the external source, with a stock level.
- **Compartments (two or three):** each with its own climate, crop and batches. Example: A = lettuce (4 batches), B = lettuce (3 batches), C = basil.
- **Backup heater per compartment (draft decision):** a small, expensive local heater used when central heat is insufficient or fails.

### 4.2 Who allocates what

Supply is central, controls are local, and the agent is the allocator. It decides how the energy centre runs and what each compartment asks for. A built-in climate controller turns the agent's setpoints into actuator moves every few simulated minutes, like a real greenhouse climate computer. When total demand exceeds supply, someone must decide who gets heat or CO2 first. That decision is the heart of the challenge. (Open: default rule when the agent sets no priority. Leaning towards proportional sharing with agent-set priorities or caps.)

### 4.3 Why compartments instead of one big greenhouse

- Real high-tech facilities split glasshouses into compartments with their own climate control, and smaller farms run separate houses. One large single-crop house also exists, so this is partly a design choice.
- Different crops need different climates (lettuce is a cool crop, basil prefers warmer), so separate compartments are realistic with more than one crop.
- Failures stay local: a broken pane or disease outbreak hits one compartment.
- Mainly: it creates allocation trade-offs. With one compartment there is nothing to share. With several on one energy centre, every choice in one compartment costs another.

### 4.4 Real-world grounding of the layout

- Most Dutch growers run a CHP next to a boiler that covers heat peaks, and use heat buffers to store heat for when they need it. CHP supplies CO2 to the greenhouse as well.
- About 62% of Dutch glasshouse area was heated with CHP systems in 2017.
- The OCAP pipeline delivers industrial CO2 to 500+ greenhouse connections between Rotterdam and Amsterdam, and its suppliers cannot always meet demand.
- A known real dilemma: in summer, CHP units were fired just for CO2 even when no heat was needed, wasting energy. This heat/power/CO2 coupling is one of our core trade-offs.
- Smaller operations often have a dedicated heater per greenhouse (hence the backup heater option).

---

## 5. Crops and batches

### 5.1 Crops are pluggable

A crop is defined by data, not special logic, so new crops can be added without changing the facility. Each crop definition covers:
- Growth response to light, CO2 and temperature.
- Cycle length from transplant to harvest.
- Harvest type: single cut (lettuce) or repeated cuts (basil).
- Climate targets and stress limits.
- Quality effects: tipburn, bolting, disease.
- Plant density and minimum sellable weight.
- Market price per kg or per head, possibly by quality grade.

### 5.2 Candidate crops

| Crop | Cycle | Role |
| --- | --- | --- |
| Lettuce | About 30 to 35 days transplant to harvest; single harvest | First crop. Published model (Van Henten). Clear tipburn and bolting trade-offs. |
| Basil | Repeated cuts | Second crop if time allows. Second most grown hydroponic leafy crop. |
| Spinach | Short, cool crop, bolts in warm air | Optional. |
| Tomato, cucumber | Months; fruit lags weeks | Out of scope for now. |

### 5.3 Lettuce reference values (from extension and grower sources)

- Air temperature: should not exceed about 24 C during the day and 18 C at night.
- Daily light integral (DLI): optimal 12 to 17 mol/m2/day; Cornell targets about 17.
- Relative humidity: about 50 to 70%.
- CO2: around 800 to 1,000 ppm when dosing, less when vents are open.
- Cycle: Cornell's hydroponic model reaches harvest in about 35 days from seeding under optimal light and temperature.
- Tipburn: mainly caused by growing too fast under high light (calcium cannot reach young leaves fast enough). Rises above the DLI target and with poor air flow or low transpiration.
- Bolting: driven mainly by warm temperatures and temperature swings; makes lettuce bitter.

### 5.4 Staggered batches

Commercial leafy-green growers grow several batches of different ages in the same space, so harvests are continuous (for example, a weekly harvest from four batches a week apart). Each compartment starts the episode with batches at different stages. Each batch has: crop, compartment, planting day, area, growth state, stress counters, status (growing, ready, harvested, lost).

---

## 6. The growth and climate model

Basis: the Van Henten (1994) lettuce greenhouse model, a standard benchmark in greenhouse optimal control and RL research. It has 4 states (crop dry weight, indoor CO2 concentration, indoor air temperature, indoor humidity), 4 weather disturbances, and 3 controls (CO2 injection, ventilation, heating). Van Henten's original objective matches ours: net return equals harvest revenue minus climate conditioning costs. Parameter tables are published (for example in Boersma and van Mourik, and Chapter 6 of van Straten et al. 2010).

Our extensions on top of it:
- Supplemental lighting, screens and dehumidification.
- The central energy centre (CHP, boiler, buffer) and shared distribution.
- Multiple compartments and batches.
- Stress counters for tipburn, bolting and disease, which reduce quality.
- Hidden per-seed facility parameters.
- Prices, events, operations and contracts.

Verification matters more than speed of writing: physics bugs create exploits. The model should be checked against published behaviour, and obvious sanity properties should hold (for example, no heating in winter means near-zero growth; energy is conserved).

---

## 7. What the agent can do (controls)

Each control has a realistic delay before its effect is felt.

| Control | Level | Effect delay | Notes |
| --- | --- | --- | --- |
| Heating setpoints (day and night) | Compartment | Hours | Draws on shared heat supply |
| Ventilation limits (min and max opening) | Compartment | Minutes | Cools and dries, but loses heat and CO2 |
| CO2 setpoint | Compartment | Minutes | Draws on shared CO2 stock |
| Screen rules (insulation at night, shade at high light) | Compartment | Minutes | Closing traps humidity |
| Lamp schedule (hours, intensity) | Compartment | Instant | Paid at hourly electricity price; grid import cap |
| Dehumidification | Compartment | Hours | Costs heat |
| Backup heater (draft) | Compartment | Instant | Expensive local heat |
| CHP on, off or load level | Facility | Instant | Makes heat, power and CO2 together |
| Central boiler | Facility | Instant | Heat only |
| Heat buffer charge or draw | Facility | Hours | Size limit, slow losses |
| External CO2 purchase rate | Facility | Instant within contract | Capped, priced |
| Order CO2, gas, nutrients, seedlings | Facility | Days | Lead time and minimum order; suppliers can be late |
| Hire or release staff | Facility | Days | Notice period, daily wage, hiring fee |
| Plant, harvest or discard a batch | Batch | Hours | Needs worker-hours; minimum sellable weight |
| Inspect a sensor, request a repair | Equipment | Hours | Costs money and time |
| Read status and forecasts, advance time | Any | n/a | Status reading should be cheap or free |

Decision cadence is open: every 1 to 4 simulated hours keeps episodes at a few hundred decisions; daily is cheaper but hides fast events.

---

## 8. What comes from outside (inputs)

| Input | Visibility |
| --- | --- |
| Weather: temperature, sun, wind | Forecast a few days ahead, with error |
| Gas and hourly electricity prices | Forecast; spikes possible |
| Crop prices and sales contracts | Known; contracts fix weekly volumes with fines for shortfall |
| Events: failures, storms, disease, late deliveries | Types and rates documented; timing hidden; each gives a visible signal |
| Facility parameters | Drawn per seed within documented ranges; learned from how the facility responds |
| Starting state: batches, stock, staff, money | Known |

### 8.1 Hidden per-seed facility parameters

| Parameter | Level | What it changes |
| --- | --- | --- |
| Floor area and height (air volume) | Compartment | How fast air heats, cools and fills with CO2 |
| Cover heat-loss coefficient (single glass, double glass, polycarbonate) | Compartment | Heating demand |
| Cover light transmission | Compartment | Free light, lamp hours needed |
| Air leakage rate | Compartment | Heat and CO2 lost with vents closed |
| Screen insulation and shading | Compartment | Savings from closing screens |
| Lamp capacity and type | Compartment | Maximum supplemental light, lamp heat |
| CHP size (electric, heat, CO2 output) | Facility | The coupling trade-off |
| Boiler capacity | Facility | Peak heat cover |
| Heat buffer size | Facility | Heat storage |
| External CO2 contract cap and price | Facility | CO2 when CHP is off |
| Grid connection limits (import and export) | Facility | Lamp load cap, sellable CHP power |
| Location, season, weather series | Facility | Heating demand, natural light |
| Energy price series | Facility | When heating, lamps and CHP pay off |
| Crop prices per crop and grade | Market | Value of each batch |

Numeric ranges are still open: set them from the Van Henten parameters and a Dutch reference greenhouse, then tune for the gap.

---

## 9. What the agent can measure (outputs and observations)

The agent sees sensor readings, not true state. Sensors can drift or fail. The ledger (money, stock, orders) is always exact.

| Observation | Level | Type |
| --- | --- | --- |
| Air temperature | Compartment | Sensor |
| Relative humidity and VPD | Compartment | Sensor |
| CO2 concentration (ppm) | Compartment | Sensor |
| Light now and daily light so far (DLI) | Compartment | Sensor |
| Root zone: EC, pH, solution temperature | Compartment | Sensor |
| Vent, screen and lamp state | Compartment | Sensor |
| Batch estimates: weight, days to ready, stress | Batch | Estimate |
| Equipment status and alarms | Facility | Exact |
| Heat buffer level, CO2 stock, open orders and arrival times | Facility | Exact |
| Staff available | Facility | Exact |
| Energy use, costs and money so far | Facility | Exact |
| Weather and price forecasts | Facility | Forecast |

Note on "pressure": air pressure is not a control variable in greenhouses. Growers track vapour pressure deficit (VPD), the drying power of the air relative to the leaf. Low VPD (below about 0.4 kPa) means humid, stagnant air and disease risk (Botrytis); it also slows transpiration, which is linked to tipburn.

---

## 10. Operations: staff, stock, deliveries, contracts

These test planning ahead, which is where StoreBench found agents fail most: 26% of analysed runs underbought stock, and some agents never placed a purchase order.

| Resource | How it works | Planning trap |
| --- | --- | --- |
| Staff (worker-hours) | Planting, harvesting, repairs and inspections need worker-hours each day | Too few: ready batches go unharvested and lose value. Too many: wages wasted. |
| Hiring | New workers arrive after a notice period | Must hire before a harvest peak, not on the day |
| CO2 stock | Drains with dosing; reorders arrive after a lead time with a minimum order | Running dry stops dosing in every compartment |
| Gas (if delivered) | Same lead-time logic | A cold snap empties it faster |
| Nutrients and seedlings | Ordered ahead | Late seedlings leave space empty |
| Sales contracts | A buyer takes a fixed volume per week at a set price; spot market for the rest | Missing a delivery costs a fine |

Every order shows its expected arrival. Suppliers can be late (an event).

---

## 11. Events and failures

Every event has a real-world basis, a visible signal, and a correct response the tools allow. Event types and rates are documented for the agent; their timing is not.

| Event | Real-world basis | Effect | Good response |
| --- | --- | --- | --- |
| Sensor drift or failure | Thermostats can be off by about 5 F, causing heating and cooling to run at once | One sensor reports wrong values | Cross-check other sensors and energy use, inspect, stop trusting it |
| Boiler failure | A heater failing on a cold night can freeze a crop | Boiler capacity drops to zero for hours | Close screens, draw on the buffer, run the CHP harder, use backup heaters, repair |
| CHP failure | CHP supplies heat, power and CO2 at most Dutch growers | No CHP heat, power or CO2 | Boiler for heat, buy external CO2 or lower CO2 targets |
| Power outage | An outage on a hot day stops cooling; growers keep generators for this | Lamps, fans, pumps, vent motors stop | Set vents safe beforehand, decide what backup power runs |
| Vent motor stuck | A vent malfunction cooked a crop three weeks from harvest (New Zealand) | One vent ignores setpoints | Notice the mismatch, compensate, repair |
| Broken pane or torn screen | Vent gaps and screen tears leak heat | Higher leakage and heat loss in one compartment | Detect rising heat demand, cut CO2 there, repair |
| CO2 supply cut or late delivery | Pipeline suppliers cannot always meet demand | External CO2 capped or zero | Re-plan CO2 across compartments, run CHP for CO2, order earlier next time |
| Fertigation pump or dripper jammed | Pumps and irrigation are standard alarm points | Water and nutrient stress, more tipburn | Spot it in root-zone readings, repair |
| Heat wave or cold snap | Forecast days ahead | Weather extreme | Pre-heat, fill the buffer, shift lamp hours |
| Energy price spike or grid curtailment | Utilities curtail with minutes of notice | Electricity expensive or capped | Shift or dim lamps, sell CHP power if it pays |
| Disease pressure | Long humid spells favour Botrytis | Disease counter rises with hours of humid air | Dehumidify early, even at an energy cost |
| Staff absence | Common operational risk | Fewer worker-hours | Re-prioritise harvests, hire temporary help |

Keep the first version to 4 to 6 event types; each one needs a test, a reference response, and a way to check from the log whether the agent handled it.

---

## 12. Scenarios

A scenario is a named bundle of events and conditions. Each runs on several seeds and gets its own score scale, because a hard scenario earns less money for every policy. StoreBench uses the same idea with 11 named tasks of 30 to 45 days (for example a trade war and a black-swan demand drop).

| Scenario | Main pressure | What good play looks like |
| --- | --- | --- |
| Normal winter | Steady cold, normal prices | Efficient energy plan, orders on time |
| Cold snap | Days of frost, forecast ahead | Fill the heat buffer early, close screens, protect the most valuable batches |
| Storm damage | Broken panes, possible power outage | Detect the damaged compartment, reroute heat, repair in order of value |
| Disease pressure | Long humid spell | Dehumidify early at an energy cost |
| Supply crunch | Late CO2 delivery, capped pipeline | Order ahead, split scarce CO2 by crop value |
| Price shock | Electricity or gas spike | Shift lamp hours, run the CHP when selling power pays |

The exact scenario set is not final. Start with 2 or 3 scenarios, each with 3 seeds.

---

## 13. Episode design

- Length: 30 to 40 simulated days, cold season (so a passive greenhouse earns little).
- Start: two or three compartments with batches already at different ages (for lettuce roughly 0, 8, 16 and 24 days into a 32-day cycle). Equipment at defaults, buffer partly full, some stock.
- During: the agent may plant into freed space only if that batch can finish before the episode ends.
- End: when the last starting batch is ready, plus a short harvest window. Anything not harvested earns nothing. This avoids valuing standing crop, which would either reward stopping early or punish good planning.
- Seeds fix facility parameters, weather, prices and event schedules, so every run is reproducible.
- Simulated time advances with the agent's actions, not wall-clock time, so model speed does not matter (StoreBench uses an operation budget per time window with a free status probe).

---

## 14. Reward and scoring

### 14.1 One number: net profit in EUR

Why money and not yield: every trade-off lands in one unit (a lost batch and an overspent gas bill both reduce profit), crops of different value compare fairly, it matches Van Henten's original objective, and it stays linear and deterministic.

Net profit over the episode:

- plus harvest revenue: kg (or heads) × price × quality factor (0 to 1, reduced by tipburn, bolting, disease)
- plus electricity sold by the CHP
- minus gas
- minus electricity bought
- minus CO2 bought
- minus staff wages and hiring fees
- minus repairs and inspections
- minus seedlings, nutrients and water
- minus contract fines

### 14.2 Normalisation

Profit is rescaled per scenario and seed:

score = clip(0.8 × (P_agent − P_do_nothing) / (P_reference − P_do_nothing), 0, 1)

Do-nothing scores 0 and the reference scores 0.8, leaving visible room if an agent beats the reference. (StoreBench calibrates per task and seed against its scripted policies in a similar spirit, with a pass bar between the two strongest honest policies.)

### 14.3 Baselines the judges will run

- **Do-nothing:** no actions. Equipment stays at its start state (heating off, vents closed, no CO2, lamps off) in a cold season, so batches stall or are lost. Profit near the cost of the starting stock.
- **Stop-early:** the agent stops partway. The rest of the episode runs a frost-protection fallback whose energy is charged, and unharvested batches earn nothing.

### 14.4 Exploits we must block

| Exploit | Block |
| --- | --- |
| Harvest everything early | Minimum sellable weight; underweight produce sells at zero |
| Cut all heating near the end | Cold stress lowers quality; only harvested, sellable crops count |
| Run the CHP flat out to sell power | Export cap and realistic price series; it only pays when it really would |
| Extreme CO2 or temperature | Crop damage above crop limits; CO2 costs money |
| Read hidden state or logs | Simulator in a separate container, reachable only through MCP |
| Spam inspections or repairs | Each costs money and time |
| Value standing crop at the end | Not counted |
| Ignore contracts | Fines, as StoreBench escalates ignored returns into fines |

---

## 15. Benchmarking: the reference run

### 15.1 How the "best solution" is defined

We do not compute or prove an optimal solution. Following StoreBench, the reference is the top of a ladder of hand-written policies that play the environment through the same MCP tools as the agent, with no LLM. Each is run on every scenario and seed, and their profits set the scale.

StoreBench's ladder, for comparison:

| Policy | Score | What it does |
| --- | --- | --- |
| smart-triage | 0.764 | Hand-written rules prioritising urgent work; sets the pass bar |
| rule-based | 0.638 | Fixed checklist |
| blast-list | 0.463 | Ships every order, no broader decisions |
| absentee | 0.100 | Attends, takes no actions |
| exploiter | 0.039 | Tries known reward exploits |
| do-nothing | 0.000 | Nothing |

Warning from their results: AfterQuery's blog reports Claude Fable 5.2 at 0.835, above smart-triage (0.764). The paper reports that no frontier model matched the heuristic on average (the two likely cover different model sets). Either way, a rule-only reference may not stay ahead of the best agent, so ours must plan ahead.

### 15.2 Our ladder

| Policy | What it does | Purpose |
| --- | --- | --- |
| Hindsight oracle | Optimises with all future weather, prices and events known | Upper bound only, never the reference |
| Reference (smart planner) | Smart rules plus a look-ahead over the next 2 to 3 days using only forecasts and visible state; thresholds tuned on separate training seeds | The bar the agent should miss |
| Smart rules | Practitioner rules plus playbooks: reorder before stock runs out given lead time, hire before harvest peaks, schedule CHP and buffer on price forecasts, a response per event type | Shows planning beats rules |
| Rule-based | Practitioner rules only: cut CO2 with open vents, lamps in cheap hours, humidity limits | Gap test: if this is close to the reference, there is no room |
| Naive | Crop-file setpoints, reorders only when stock hits zero, harvests when ready | Shows lead times matter |
| Absentee | Frost-protection fallback only | Lower anchor for stop-early |
| Exploiter | Tries every known exploit | Regression test; must score near zero |
| Do-nothing | No actions | Zero anchor |

### 15.3 How we show the reference is strong without proving it optimal

1. It beats every simpler policy on every seed, in the expected order.
2. It sits close to the hindsight oracle, showing how much room is left.
3. Its tuning seeds are separate from evaluation seeds.
4. It uses only information the agent also has.
5. The same seed and actions replay to the same ledger, so judges can verify it.

If a frontier agent beats the reference at the first check, the cheapest fix is to search the reference's thresholds (reorder margins, heating setpoints, buffer rules) on training seeds and keep the best settings.

### 15.4 Agent failure modes we expect and will look for in logs

From StoreBench, Vending-Bench and related work:
- Underbuying or never ordering stock; ignoring lead times.
- Greedy, short-term decisions that lock in early commitments.
- Trusting a drifting sensor instead of cross-checking.
- Losing track of state over a long episode (stock, orders, batch ages).
- Running stale batched scripts based on outdated data.
- Claiming a background process is running things instead of acting.
- Declaring the task done early.
- Inconsistency across repeated runs (tau-bench: about 61% pass once but about 25% across 8 trials).

---

## 16. Lessons from StoreBench we are copying

- No LLM inside the simulator: LLM counterparties can be manipulated.
- Seeded, deterministic, replayable episodes.
- Simulated time tied to actions, not model speed.
- Scores calibrated against scripted policies per task and seed.
- Known exploits kept as regression tests (their exploiter scores about 0.04 against 0.46 to 0.76 for honest baselines).
- Ignored obligations become fines.
- Named scenarios of 30 to 45 days across several seeds.
- Their training result (relevant for the tiebreaker): Qwen3.5-27B trained with GRPO on five training tasks rose from 0.136 to 0.373 mean composite on held-out tasks.

---

## 17. Open decisions

- Default rule when compartments' demand exceeds supply (proportional sharing vs agent-set caps).
- Per-compartment backup heater: keep or drop; or full boiler per compartment.
- Decision cadence: hourly, every 4 hours, or daily.
- Numeric ranges for hidden facility parameters.
- Real or generated weather and price series.
- First crop list: lettuce only, or lettuce plus basil.
- First 4 to 6 event types and first 2 or 3 scenarios.
- Number of compartments (2 or 3).
- Whether the agent container has internet access (ask the mentors).

## 18. Main risks

- **No gap:** if scripted practitioner rules score close to the reference, a frontier agent will too. Test this early.
- **Reference too weak:** the best frontier model beat StoreBench's heuristic; ours must plan.
- **Physics bugs creating exploits:** verify against published behaviour and sanity checks.
- **Scope:** staff, orders, contracts, events and a planning reference on top of the climate model is a lot for about 10 hours with 4 people. Cut order if needed: contracts, then hiring, then the third compartment. Keep CO2 ordering with lead times, since it carries the main planning failure.

---

## 19. Sources

Greenhouse modelling and energy systems:
- Katzin et al., energy saving in optimally controlled greenhouse lettuce (WUR): https://edepot.wur.nl/520084
- Boersma and van Mourik, sensor configurations in a lettuce greenhouse (WUR): https://edepot.wur.nl/693301
- Van Henten 1994, Greenhouse climate management: an optimal control approach: https://agris.fao.org/search/fr/records/6748d3347625988a3721190f
- Optimal control and greenhouse energy systems (WUR): https://edepot.wur.nl/583595
- Memo on CHP in Dutch horticulture (WUR): https://edepot.wur.nl/526773
- Residual heat and CHP at Dutch growers (HortiDaily): https://www.hortidaily.com/article/9454290/mobile-calculation-container-replaces-boiler-for-greenhouse-heating-30-reduction-in-gas-consumption/
- CO2 from biogas and the OCAP pipeline (gasworld): https://www.gasworld.com/feature/an-introduction-to-co2-from-biogas-systems/2079802.article.article/
- OCAP client story (Capgemini): https://alternate.ucwe.capgemini.com/wp-content/uploads/2023/02/OCAP-client-story.pdf

Lettuce and leafy crops:
- Hydroponic lettuce production (University of Kentucky): https://ccd.uky.edu/sites/default/files/2025-10/hydroponic-lettuce-production_0.docx
- Hydroponic lettuce guide (University of Kentucky): https://ccd.uky.edu/sites/default/files/2026-02/ccd-cp-63_hydrolettuce-updated_accessible.pdf
- Greenhouse lettuce fertilization, Mattson/Cornell (Hort Americas): https://hortamericas.com/tag/neil-mattson/
- Lettuce and leafy greens 101 (Produce Grower): https://producegrower.com/article/lettuce-and-leafy-greens-101-a-production-guide
- Light and temperature effects on lettuce (Produce Grower): https://producegrower.com/article/greenhouse-lighting-lettuce-yield
- Hydroponic leafy crops (University of Tennessee): https://uthort.tennessee.edu/wp-content/uploads/sites/228/2023/11/W844-B.pdf
- Aquaponics production manual: staggered cropping (Farmhub): https://learn.farmhub.ag/resources/aquaponics-production-manual/4-grow-out-management/4-5-plants/
- Hydroponics for lettuce and herbs (Ceres Greenhouse Solutions): https://ceresgs.com/hydroponics-for-lettuce-and-herbs-smarter-greenhouse-growing/

Climate, humidity and failures:
- The VPD Blueprint (GrowDirector): https://growdirector.com/the-vpd-blueprint-a-professional-guide-to-climate-steering-and-profitability/
- Reduce greenhouse humidity (UConn): https://ipm.cahnr.uconn.edu/reduce-greenhouse-humidity/
- Managing humidity and Botrytis (HortiDaily): https://www.hortidaily.com/article/9770398/managing-humidity-to-create-healthier-tomato-plants/
- Winter maintenance for greenhouse equipment (MSU): https://www.canr.msu.edu/floriculture/resources/energy/assets/Winter-maintenance.pdf
- Greenhouse alarms (Greenhouse Grower): https://www.greenhousegrower.com/?p=134244
- Remote monitoring systems (Greenhouse Grower): https://www.greenhousegrower.com/?p=145456
- Outage and curtailment plans (Greenhouse Grower): https://www.greenhousegrower.com/?p=181246
- Crop fries and dies (Grower2Grower): https://www.grower2grower.co.nz/?p=2933
- Woods Greenhouses case study, a heater per greenhouse (Sensaphone): https://sensaphone.com/case-studies/woods-greenhouses-prevents-plant-loss-during-harsh-new-jersey-winters

Benchmark design:
- StoreBench design summary (AfterQuery blog): https://www.afterquery.com/blog/storebench
- StoreBench paper (arXiv 2610.10942): https://arxiv.org/abs/2610.10942
- Vending-Bench: https://arxiv.org/pdf/2502.15840
- tau-bench (ICLR 2025): https://proceedings.iclr.cc/paper_files/paper/2025/file/1b126cc38b8638e07bef37e7b2bb72bf-Paper-Conference.pdf

Most greenhouse sources were read through search excerpts rather than in full; check key figures against the source before quoting them in the pitch. The StoreBench blog and paper abstract were read directly.
