# Part 4: What makes it realistic, and what the agent must juggle and plan ahead

Drafted 15 Nov 2026. Every mechanic below was checked against the CURRENT repo (`docs/GREENHOUSE_SPEC.md` incl. section 14, `docs/DECISIONS.md`, `docs/CROPS.md`, `data/`, `scenarios/normal-winter.toml`, README). Where `presentation/00-uploaded-research-digest.md` is outdated I used the repo (lettuce is NOT grown in `normal-winter`: it is 2 broccoli-microgreen compartments + 1 radish-microgreen compartment; there is no read tool; the agent has one tool, `submit_day`). Web sources are in section D. Numbers marked "my arithmetic" are back-of-envelope from the data files, not simulator output.

---

## A. Slide-by-slide draft (7 slides)

### Slide 1: "A real Dutch winter greenhouse, as a rulebook"
- Real weather (KNMI De Bilt, hourly), real day-ahead power prices (ENTSO-E via Energy-Charts), real gas (TTF): recorded, never generated.
- Real equipment stack: CHP + peak boiler + heat buffer + CO2 + grid cap, on one energy centre.
- Real operations: seed on a lead time, weekly buyers, a crew, storms, a boiler that trips.
- Honest labels: every value is tagged sourced / calibrated / design assumption.
- **Big number:** `3 + 3`: 3 compartments on 1 energy centre, 3 kinds of recorded data (weather, power, gas). Visual: facility diagram with a source tag on each box (green = sourced, amber = design assumption).

Speaker notes: Open with "this is not a toy farm; the equipment is the standard Dutch set-up." About 62 % of Dutch glasshouse area was heated with CHP in 2017 (WUR memo), and the sector runs more than 1,000 CHP units of about 2.4 GW electric. The numbers in our facility file are engineering assumptions in that real range, not one farm's data. Say that plainly; it earns trust. Everything the agent needs is in its instructions; nothing is hidden that a careful planner would need.

### Slide 2: "Real inputs, real equipment, one shared energy centre"
- Weather: 2 x 50-day KNMI windows per year, 2024 and 2025. Dev seeds 1-6 and eval seeds 101-108 use different windows.
- Prices: hourly Dutch day-ahead, including the near-zero and negative hours and the evening peaks.
- Energy centre: CHP 300-500 kW electric, boiler 600-900 kW heat, buffer 2-4 MWh, grid import 400-700 kW and export 300-500 kW (ranges published, drawn value hidden per seed).
- Control layer: the agent sets setpoints; a built-in climate computer moves vents, screens, lamps and valves, as Priva/Hoogendoorn computers do.
- **Big number:** `0.0 -> 110 EUR/MWh` swing inside one recorded day (1 Jan 2024: about 0 in the morning, 60-110 in the evening). Visual: the real price curve of one day with the CHP run window shaded.

Speaker notes: The grid cap is real: Noord-Holland growers were asked to run CHP like "one big power plant" because the grid is full (NL Times, May 2025). Prices are recorded, so any profit or loss is explained by decided prices. Be upfront about the two tariff assumptions: import markup EUR 0.03/kWh and export at 50 % of day-ahead.

### Slide 3: "One engine, three products: heat, power, CO2"
- A CHP burns gas and makes heat, electricity and CO2 together; the crop wants CO2 when it is sunny, not when heat is needed.
- Our numbers: 0.25 m3 gas per kWh electric, 1.2 kWh heat and 0.45 kg CO2 per kWh electric. The boiler's flue gas is not usable for CO2 at this site.
- Worked example (my arithmetic, gas at EUR 0.29/m3): running the CHP costs about EUR 0.036 per kWh electric after the heat is credited. At 50 % export it only pays on power above about EUR 72/MWh day-ahead. But its CO2 (0.45 kg/kWh, EUR 0.25-0.32/kg if bought) is worth more than that margin, so CHP-for-CO2 is tempting and then the heat must go to the buffer (fills in roughly 3-11 h).
- **Big number:** `EUR 72/MWh` breakeven for exporting CHP power. Visual: a three-arrow sankey (gas -> heat / power / CO2) with the breakeven line on the price curve.

Speaker notes: This is the real Dutch dilemma. Growers fired CHPs just for CO2 in summer and wasted heat; in the 2022 crisis CHP owners offset expensive gas by selling power. A naive agent runs the CHP "because it is cold" or "because CO2 is cheap" and overfills the buffer, or leaves it off and buys CO2 at EUR 0.25-0.32/kg. Say clearly that the breakeven is a hand calculation from the data files; the reference planner does this per hour.

### Slide 4: "Plan ahead: 10 + 12 + 2.5 days against a weekly order book"
- Seed takes 10 days to arrive. Broccoli microgreens take about 12 days to ready, then keep top grade only about 2.5 days (waste after about 7).
- Buyers publish a weekly order book (broccoli x 4,000 kg: 2.4 / 6.0 / 2.0 / 5.6 / 2.8 / 5.2 t over six weeks). Sales above the rolling 7-day demand fall to EUR 0 at 1.25 x demand.
- Worked example: for the 5.6 t week (days 21-27) the seed must be ordered on about day 1. The next-week dip is 2.0 t, and a surplus batch cannot wait there because it loses grade in days.
- **Big number:** `22 days` from decision to money (10 + 12). Visual: a Gantt: order -> seed lands -> sow -> ready -> sell, laid over the weekly demand bars.

Speaker notes: The order book is published, so nothing is hidden; the difficulty is back-planning a market you can see against supply you can only change 3 weeks ahead. This is the failure we saw in model runs: Haiku sold 2.2 t of broccoli for EUR 0 into a full week; 10 of 17 runs planted before the seed had landed. Illustrative arithmetic: 6,000 kg harvested into a 4,000 kg week earns EUR 120k for the first 4,000 kg, about EUR 15k for the next 1,000 kg and EUR 0 for the last 1,000 kg. Those 1,000 kg only cost labour.

### Slide 5: "Nights and storms: insurance is paid in advance"
- The agent acts once a day at 06:00. The night runs on an hourly schedule of fixed values; nobody comes in at night.
- The boiler trips (about 1 in 25 days) and stays out until a contractor with a part and a day-shift slot fixes it.
- Storms follow the recorded wind (10 m/s at De Bilt): 0-12 panes per compartment, leakage x (1 + 0.08 per pane), up to about double. After a storm glass lead time jumps from 3-5 days to 18-23 days for 10 days, and the glazier takes 4-7 days.
- A EUR 45 glass pane ordered before the storm headline is a gamble: pay for nothing if no damage, or save about 3 weeks if there is.
- **Big number:** `3-5 days -> 18-23 days` glass lead time after a storm. Visual: two timelines, "ordered before" vs "ordered after".

Speaker notes: Real Dutch growers have an on-call grower; we deliberately model the day operator, so planning ahead (a charged buffer, spare parts, CHP and boiler both available on a frost night) is the only insurance. The news feed gives real-grower-style headlines with false alarms, never an equipment name or an hour. In runs, 8 of 17 left the boiler broken for over a week even though the alarm was in every briefing.

### Slide 6: "What we simplified, honestly"
- Sourced and close: recorded weather and power prices, CHP/boiler/buffer topology, Van Henten crop model, microgreen yield and cycle from trial data, wage floor.
- Simplified: heat/CO2/vapour balances, CO2 supply as a tank plus a capped contract (real OCAP is a pipeline), no disease model, hourly day-ahead only.
- Pure design assumptions: seed lead time, event rates, storm damage, part prices, demand levels and factors, crew rules.
- All in data files with a tag; changing one is a one-line edit.
- **Big number:** `3 tags`: sourced / calibrated / design. Visual: the realism map table as a heat strip (see section C).

Speaker notes: Judges check "rules make sense for the setting". Showing the tags and what we did not model (disease, sensor drift, pests) is better than overclaiming. Mention that "price shock" and "disease" scenarios are listed as later work, not built.

### Slide 7: "Why it is built this way"
- One daily turn through one tool: a run is about 42 calls, so difficulty is planning, not call-budget bookkeeping; every model sees identical information.
- Day operator only: floor work is day-shift; nights unstaffed; planning ahead becomes the core skill (and scheduling ahead is where agents are weakest, SimuHome).
- Setpoints, not valves: the agent is the allocator above the climate computer, like a real grower.
- Deterministic and sealed: same seed, same trace, same score; no LLM in the simulator; hidden per-seed parameters with published ranges.
- **Big number:** `~42 calls` per run (limit 400). Visual: one day's loop: 06:00 briefing -> 5 actions -> day -> night -> briefing.

Speaker notes: Use the recorded reasons in section C3. Be clear which reasons are recorded and which are proposed.

---

## B. The juggling list (interacting decisions across days)

1. **Seed lead time vs weekly demand vs crop shelf life.** Order about 22 days ahead of the sale; the product holds top grade about 2.5 days; surplus above the rolling 7-day demand sells down to EUR 0. (Worked example 1.)
2. **CHP for heat vs power vs CO2.** Gas margin, export price (50 % of day-ahead), CO2 value, buffer capacity 2-4 MWh with 0.5 %/h loss, min CHP load 0.5. (Worked example 2.)
3. **Lamps vs hourly price vs grid import cap.** Lamps are 80-140 W/m2 on 1,450-1,950 m2 per compartment: about 350-820 kW if all three compartments run flat out, against a 400-700 kW import cap (ranges, per seed). The lamp heat (70 %) offsets boiler heat; light buys cycle time (microgreen growth rises with light), but electricity at the evening peak can cost more than the crop gains. Recorded negative hours make importing pay.
4. **Heat sharing across compartments.** A, B and C draw on one boiler/CHP/buffer; when short, the agent sets priority and caps, or gets plain proportional sharing (the naive default).
5. **Staffing.** Crew of 3 (8 worker-hours each, EUR 22/h) up to 10; hiring takes 3 days and EUR 400, release is paid for 7 days. Sowing and harvest use worker-hours; a ready batch waiting for hands loses grade (0.06/day broccoli, 0.08/day radish). Hire before the harvest peak, not on it.
6. **Night plan vs day plan.** Charge the buffer by day, close screens, keep CHP and boiler both available on a frost night; the night schedule repeats until changed.
7. **Repair chain.** Contractor booking + part on site + day slot; parts have normal and storm-surge lead times; unused parts are worth nothing at the end. (Worked example 3.)
8. **CO2 stock.** Tank min order 2,000 kg, 72 h lead time, 150 EUR cancel fee, late deliveries (0.08/day, 12-60 h): running dry stops dosing everywhere.
9. **End-of-episode.** Planting is refused if too few days remain; crop standing at the end is worth 0, so wind-down timing matters.

### Worked example 1: the seed clock (broccoli)
Rules: seed arrives 240 h (10 days) after the order; the crop is ready after about 12 days under target climate (longer if the house runs cold; Haiku saw 10-14); ready loss 0.06/day means grade A for about 2.5 days, waste after about 7; weekly demand 4,000 kg x [0.6, 1.5, 0.5, 1.4, 0.7, 1.3]; price falls linearly from EUR 30/kg at demand to 0 at 1.25 x demand.
- Week 3 (days 21-27) wants 5.6 t. Ready by day 21-23 means sowing about day 9-11, so the seed must be ordered on day 1. An agent that "orders when it sees the demand is coming" is 3 weeks late.
- Week 2 (days 14-20) wants only 2.0 t, and price is 0 beyond 2.5 t. A batch that ripens there cannot wait for week 3, because it drops from grade A after about 2.5 days.
- A naive "plant everything, harvest when ready" fills the glut weeks and earns EUR 0 on the surplus (my arithmetic: 6,000 kg into a 4,000 kg week = EUR 135k, the same as selling 5,000 kg, with 1,000 kg of pure labour cost).
- Evidence from real runs: README, "What we noticed" (Haiku 2.2 t for EUR 0; 10 of 17 runs planted before the seed landed).

### Worked example 2: CHP economics (my arithmetic from `data/`)
Gas EUR 0.29/m3 (first recorded window). CHP: 0.25 m3 per kWh electric = EUR 0.0725; its 1.2 kWh heat replaces 1.2 x 0.105 m3 of boiler gas = EUR 0.0365; net EUR 0.036 per kWh electric. Export pays 0.5 x day-ahead, so breakeven is a day-ahead price of about EUR 72/MWh. On 1 Jan 2024 only a few evening hours clear that; the morning hours at about 0 or below do not.
CO2 changes the picture: 0.25 x 1.8 = 0.45 kg CO2 per kWh electric, worth EUR 0.11-0.14 if you would otherwise buy it. So the CHP is worth running for CO2 on a dosing day, but then 360-600 kW of heat must be used or stored; the 2-4 MWh buffer fills in roughly 3-11 hours and then the heat is wasted. The right plan depends on tomorrow's heat demand (forecast), the evening price and the CO2 stock at the same time. A rule-of-thumb agent gets at least one of the three wrong.

### Worked example 3: the storm gamble and the boiler
- Boiler trips about 1 in 25 days and stays out. A repair needs `part:boiler_kit` (EUR 350, 24-48 h, express EUR 560), a heating installer (12-24 h response, EUR 94 call-out) and a day slot. Holding no part turns a next-morning fix into 2-4 days.
- Storm headline appears; a storm may do 0-12 panes of damage per compartment. Glass (EUR 45) ordered before arrives in 3-5 days; ordered after, 18-23 days, glazier 4-7 days. At 12 broken panes leakage is about double, so heat demand rises sharply for weeks.
- Pre-ordering is cheap if it hits (3 weeks saved) and a waste if the storm does nothing. That is the trade-off, with false alarms in the news feed at a stated rate.
- Evidence: 8 of 17 model runs left the boiler broken for over a week (README).

---

## C. Full realism map

Tags: **EXACT** = recorded or published data used as is; **SIMPLIFIED** = a real mechanism reduced to a model; **ASSUMPTION** = design value, no source for the number itself.

| Element | What it models | Real-world evidence (source) | How close |
|---|---|---|---|
| CHP | Gas engine: electricity, heat and CO2 together. 300-500 kW electric, 1.2 heat/electric, 0.25 m3 gas/kWh e, 1.8 kg CO2/m3 gas, min load 0.5. Flue gas assumed to pass a clean capture line | CHP is the standard Dutch set-up: about 62 % of area (WUR memo edepot.wur.nl/526773); more than 1,000 units, about 2.4 GW, 10.5 TWh/yr (HortiDaily/Kas als Energiebron); CO2 mostly from CHP or OCAP (HortiDaily 9863075) | SIMPLIFIED; sizes are ranges, ASSUMPTION for the exact values (implies roughly 40-45 % electrical efficiency, my arithmetic) |
| Peak boiler | Heat only, 600-900 kW, 0.105 m3 gas/kWh heat. Flue CO2 not usable at this site | CHP + peak boiler + buffer is the standard stack; Cornell CEA warns heater flue gas may carry growth-inhibiting contaminants | SIMPLIFIED; the "no usable CO2" rule is an ASSUMPTION stated in the file |
| Heat buffer | 2-4 MWh, 0.5 %/h loss, starts half full; charge/hold/discharge/auto | Buffers decouple CHP running from heat demand; CHP and buffer matter much for profit (Seginer et al. 2018, from digest; WUR 583595 on boiler/CHP/buffer optimisation) | SIMPLIFIED; size and loss ASSUMPTION |
| Grid import/export caps | Import 400-700 kW, export 300-500 kW | Dutch grid congestion; Noord-Holland growers run CHP to help the grid (NL Times 2025) | ASSUMPTION for the numbers; the cap mechanism is real |
| Hourly prices and spikes | Recorded Dutch day-ahead hourly prices incl. negative hours; recorded daily TTF gas; import markup EUR 0.03/kWh; export 50 % of day-ahead | ENTSO-E via Fraunhofer ISE Energy-Charts (CC BY 4.0); Gasradar/EnergyZero TTF (CC BY 4.0) | EXACT for the series; the markup and the export fraction are ASSUMPTIONS. Gas is a daily price (simplified). No price-shock scenario is built, only whatever the recorded windows contain |
| Weather | Hourly KNMI De Bilt temperature, radiation, wind, RH; forecasts = truth + error growing with lead time (1.4 C at 24 h) | KNMI hourly data | EXACT series; forecast-error sizes ASSUMPTION |
| CO2 supply | Tank: EUR 0.25/kg, min 2,000 kg, 72 h lead, EUR 150 cancel; contract dosing up to 20-40 kg/h at EUR 0.32/kg; store 8,000 kg | OCAP pipeline: about 580 growers, about 1,900 ha, 400-500 kt/yr (OCAP factsheet); real shortages happen mostly in summer; merchant CO2 price from a market report cited in the market file | SIMPLIFIED (pipeline abstracted to a capped contract plus tank); prices and lead time ASSUMPTION |
| Lamps and DLI | 80-140 W/m2, 2.7 umol/J, 70 % of power becomes heat; DLI tracked per day; stress when DLI < 6 (stretch) | Growth proportional to light (Cornell CEA); microgreens DLI 9-16 (Virginia Tech), 12 and 18 tested (Gerovac 2016); yield rises with light (Jones-Baumgardt 2019) | SIMPLIFIED; fixture efficiency and heat fraction are ASSUMPTIONS |
| Crop growth | Van Henten 1994 leafy-crop model (light, CO2, temperature, respiration); microgreen canopy closure calibrated so 12 d broccoli (2.5 kg/m2) and 8 d radish (2.2 kg/m2) at target climate | Van Henten 1994; Johnny's yield trial (12.5 d, 326 g/tray); Ortiz 2024 (best harvest day 13 / day 10) | SIMPLIFIED: leaf coefficients are lettuce's, reused for microgreens; only canopy closure is calibrated |
| Humidity and disease | Humidity balance (transpiration, venting, condensation recorded); controller vents toward 75 % RH; RH targets published per crop. **No disease counter in v1** | Botrytis needs long leaf wetness (8-12 h) and high humidity (UC ANR; UConn; GreenhouseGrower) | Humidity physics SIMPLIFIED; disease NOT modelled (listed as later work) |
| Setpoint control layer | Agent sets heat, vents, CO2, screen, lamps; a built-in controller moves actuators every 5 simulated minutes (12 sub-steps per hour); thermostat draws CHP, then buffer, then boiler | Priva/Hoogendoorn-style climate computers: grower sets setpoints, computer drives actuators (Priva product pages) | SIMPLIFIED; controller gains ASSUMPTION/calibration |
| Staff | Crew 3, up to 10; 8 h shifts inside 06:00-18:00; EUR 22/h employer cost; hire notice 3 d + EUR 400 fee; release paid 7 d | Dutch minimum wage EUR 14.71/h and greenhouse pay EUR 14.71-18 (NLnest, quoted in the market file); labour a large cost share (WUR, from digest, not re-verified) | ASSUMPTION for notice periods, fees and crew size; wage SIMPLIFIED from sources |
| Seed and plug orders with lead time | Microgreen seed 240 h, min order, EUR 50 cancel; lettuce plugs 336-504 h (lettuce not grown in the benchmark scenario) | Dutch propagators grow to order (Beekenkamp); propagation 2-3 weeks (Teagasc) | Plug lead time grounded; the 10-day microgreen seed lead time is an ASSUMPTION |
| Weekly demand and glut | Published weekly order book per crop (broccoli 4 t, radish 2.5 t x weekly factors); price linear to 0 at 1.25 x demand | Buyers take limited volumes (small HoReCa/wholesale market); minimum-volume contracts common (USDA ERS, from digest, not re-verified) | ASSUMPTION: levels, factors and the glut rule are design values, tuned so supply must be planned |
| Event: boiler trip | Persistent boiler outage, 0.04/day | Equipment failures are normal; a failed heater on a cold night can kill a crop | ASSUMPTION for the rate; repair chain SIMPLIFIED |
| Event: storm | Fires when recorded wind reaches 10 m/s; 0-12 panes per compartment; leakage 1 + 0.08 x panes; 10-day regional surge | After the 2025-26 Dutch windstorm glass lead times were about three weeks (context doc, not re-verified here) | Trigger on real wind is EXACT-to-data; damage sizes, thresholds and surge length are ASSUMPTIONS |
| Event: late delivery | CO2 order late by 12-60 h, 0.08/day | Pipeline and tank suppliers fail to deliver at times (OCAP and Air Liquide shortages, digest) | ASSUMPTION for rate and delay |
| News signals | Storm, frost and gas-price headlines, with hit rates and false alarms, following the recorded weather and prices; never name equipment or an hour | Growers read weather and market news | Follows recorded data; rates are ASSUMPTIONS |
| Contractors and parts | Glazier, heating installer; call-out, hourly rate, response times with surge; parts with normal, surge and express lead times | Service engineer about EUR 94/h with similar call-out (Wilo list); installers EUR 55-85/h (Dutch price guides, quoted in the market file); pane price EUR 45 not found | Ranges anchored on sources, point values ASSUMPTIONS |
| Hidden per-seed parameters | Drawn once per seed from published ranges: floor area, height, cover U, transmission, leakage, screen, lamp power, CHP, boiler and buffer size, CO2 cap, grid caps, thermal mass; event durations and lead times | Real farms differ and a grower learns the facility by watching it | Design choice; ranges are ASSUMPTIONS |
| Sensors | Noise: T 0.2 C, RH 2 %, CO2 15 ppm, PAR 5; batch weight estimates have error | Real sensors are noisy | ASSUMPTION |
| Daily-turn interface | 06:00 only, one `submit_day` call with at most 5 actions, no read tools, morning briefing | See C3 | Design choice, not a claim about practice |

---

## C3. Design rationale

**Why one daily turn through one tool, and why the agent sees the morning, not every night hour.**
Recorded reasons:
- Context 0.2/0.4 (pinned, round 3): the agent is the day operator. Greenhouse floor work is day-shift and nights are unstaffed; a real site often has an on-call grower, and we "leave that out on purpose, to make planning ahead the core skill." Scheduling ahead was the hardest category in SimuHome (agents cannot verify a scheduled action when they set it).
- Rubric guardrail (context 0.5): a well-planned night must lose clearly less than a naive one; every night event leaves a visible trace in the morning report; nothing the agent needs is withheld. The test is `test_a_planned_frost_night_loses_less_when_the_boiler_fails`.
- DECISIONS, "Round 3 built" (decided by Max): one turn a day at 06:00, at most 5 actions, no read tools, because "a run is at most 42 x 6 calls, so it is short and cheap; the difficulty is planning a day and a night ahead, not spending a call budget on reads; every model sees exactly the same information." Cost accepted: nothing reacts to a daytime alarm until the next morning. It became a single tool `submit_day` because the server sees tool calls, not model responses, so "one submission a day" could not be enforced otherwise.
- The briefing carries last night's summary (every alarm and event with its hour, min/max climate per compartment, change in batch weight and quality, money over the night) plus status, 3 days of news and a 72 h forecast (spec 14.1).
Not stated in the repo (so PROPOSED, label as such on the slide): why the briefing is a summary and not all 12 night hours of readings per compartment. A defensible reason: it is what a real grower reads in the morning, and 42 x 12 x 3 hourly rows would flood the context window and reward log-scanning over planning. Say "we think", not "we decided".

**Why per-day turns, not hourly.**
Recorded: context 7 left cadence open ("every 1 to 4 hours keeps episodes at a few hundred decisions; daily is cheaper but hides fast events"). DECISIONS (lettuce redesign): Gemini needed about 18 s per call and 15-26 min per season, so the call became one per day. DECISIONS (earlier, since reversed): a 10-hour agent day was rejected because night events would be unanswerable by construction; the round-3 answer was to make the night plan a first-class decision instead. The physics still runs hourly with 12 five-minute sub-steps, so only the decision cadence is daily. Spec 4.1: simulated time moves only with `submit_day`, so thinking time never changes the world a model faces; budget `max_calls = 400` is a safety net.

**Why setpoints, not raw actuators.**
Recorded: context 4.2 and spec 4.2: "a built-in climate controller turns the agent's setpoints into actuator moves every few simulated minutes, like a real greenhouse climate computer"; the agent is "the allocator". D10: real computers sequence heat sources automatically, and a strict no-switching version "was considered and rejected: real equipment does not work like that, and judges would call the losses artificial." Not stated: a separate token or latency reason. Proposed: raw valve control would turn the benchmark into a control-loop task a PID solves, hiding the planning problem.

**Why deterministic seeds and hidden parameters; why no LLM in the sim.**
Recorded: hard requirements (context 1): one deterministic reward from simulator state, no LLM inside the simulation, same seed + same actions = same result. StoreBench lesson: LLM counterparties can be manipulated (context 16). Hidden per-seed parameters exist because a public simulator (GreenLight / GL-Gym) could be downloaded and optimised offline (context 2); we write our own model with our own prices, events and operations, and publish only ranges, so the agent learns the facility by observing it. Dev seeds 1-6 and evaluation seeds 101-108 use separate recorded weather and price windows, so nothing is tuned on the evaluation weather. Verification: determinism, conservation, replay and exploit tests (spec 8).

---

## D. Sources

Repo (read in full): `docs/GREENHOUSE_SPEC.md`, `docs/GREENHOUSE_BENCH_CONTEXT.md`, `docs/DECISIONS.md`, `docs/CROPS.md`, `data/facilities/nl_three_compartment.toml`, `data/markets/nl_winter.toml`, `data/crops/broccoli_micro.toml`, `data/events/*.toml`, `data/news/gas_price.toml`, `data/energy_prices/nl_winter.toml` (header and first window), `data/climates/nl_january.toml` (header), `scenarios/normal-winter.toml`, README.

Web, retrieved 15 Nov 2026 by search (snippets, not full read unless noted):
- CHP memo, Dutch horticulture (WUR): https://edepot.wur.nl/526773
- Optimal control of greenhouse energy systems (WUR): https://edepot.wur.nl/583595
- Greenhouse industry CO2 (CO2 from CHP or OCAP; flue gas cleaner): https://www.hortidaily.com/article/9863075/greenhouse-industry-has-the-potential-to-solve-its-own-co2-issue/
- CHP remains important as costs rise (HortiDaily): https://www.hortidaily.com/article/9787124/nl-chp-remains-important-as-energy-costs-rise-sharply-due-to-new-policy
- Kas als Energiebron CHP factsheet: https://kasalsenergiebron.nl/content/docs/WKK/20240229_factsheet_CHP_ENGLISH.pdf
- Growers as power plants to ease Noord-Holland grid strain (NL Times, 29 May 2025): https://nltimes.nl/2025/05/29/growers-turn-greenhouses-power-plants-ease-noord-holland-grid-strain
- TU Delft, Dutch horticulture energy operations 2030 (CHP load-following): https://repository.tudelft.nl/record/uuid:4e127dc4-69a2-4730-a4d4-735ee962bbc0
- OCAP factsheet (about 580 growers, about 1,900 ha): https://www.tomatoworld.nl/media/1857/ocap_factsheet_english_tcm978-561158.pdf
- 2022 crisis: growers cut heat and light; CHP owners sold power: https://www.resource-online.nl/index.php/2022/09/16/innovation-in-greenhouses-stalled-by-energy-crisis/?lang=en and https://www.hortidaily.com/article/9577950/nl-energy-use-and-co2-emissions-horticulture-sharply-down-in-2022
- Lettuce light: DLI 17, growth proportional to light, half light doubles time (Cornell CEA): https://cea.cals.cornell.edu/files/2019/06/GPNOctober2016_LeafyGreens.pdf
- Microgreen DLI 9-16 (Virginia Tech): https://pubs.ext.vt.edu/SPES/spes-756.html
- Continuous LED and microgreen yield (Shibaeva 2022): https://www.mdpi.com/2223-7747/11/2/176
- Broccoli day 13 / radish day 10 best harvest (Ortiz 2024): https://www.maxapress.com/data/article/tihort/preview/pdf/tihort-0023-0031.pdf
- Botrytis and leaf wetness (UC ANR): https://ucanr.edu/node/100836 ; Botrytis prevention (Greenhouse Grower): https://www.greenhousegrower.com/?p=180920 ; humidity (UConn): https://ipm.cahnr.uconn.edu/reduce-greenhouse-humidity/
- Priva climate computers (grower sets setpoints): https://www.priva.com/horticulture/solutions/climate-and-process-computers
- Data: Energy-Charts https://api.energy-charts.info/ ; KNMI https://www.daggegevens.knmi.nl/klimatologie/uurgegevens ; Gasradar https://gasradar.nl/data
- Microgreen yield and cycle, seed prices, lettuce sources: see the tag table in `docs/CROPS.md` (Johnny's trial, Gerovac 2016, Jones-Baumgardt 2019, Beekenkamp, Teagasc, FreshPlaza).

Search found no source for: labour share of Dutch glasshouse cost (the digest's ">30 % (WUR)" is unverified here), per-pane glass price, microgreen seed lead time, the 2025-26 windstorm glass lead time.

---

## E. Honesty box: assumptions that are NOT sourced

Say these out loud rather than letting a judge find them.
1. **Design values (tag [DES] in the data files):** the 10-day microgreen seed lead time; boiler-trip rate 0.04/day; storm wind threshold, 0-12 panes and surge length; contractor and part prices and response times; late-delivery rate and delay; news hit and false-alarm rates; weekly demand levels (4 t / 2.5 t), the weekly factors and the glut-at-1.25x rule; hiring fee, notice periods and crew size; ready-loss per day and grade cut-offs; stress rates.
2. **Equipment sizes and efficiencies** are plausible ranges (CHP, boiler, buffer, lamps, grid caps), not one real farm's data. The facility file says so in its header.
3. **Tariff:** import markup EUR 0.03/kWh and export at 50 % of day-ahead are scenario assumptions, not exchange quotes. Gas is a daily recorded price, not hourly.
4. **CO2 supply** is a tank plus a capped contract, not an OCAP pipeline; the CO2 prices come from a general market report, not Dutch pipeline tariffs.
5. **Crop model:** microgreen leaf coefficients are Van Henten's lettuce values; only canopy closure is calibrated to the trial yields. Temperature is a weak driver in Van Henten's model (digest caution). Microgreen sale prices (EUR 30 and 22/kg) are design values within a range of price lists. Thousand-seed weights are assumed.
6. **Not modelled:** disease (Botrytis), pests, sensor drift, CHP failure, power outage, fertigation, contracts with fines, an on-call grower, a price-shock or cold-snap scenario. Humidity exists as physics and an RH setpoint but has no disease consequence.
7. **No frontier gap is claimed yet** on the current rules; the committed model runs are on earlier round-3 rule sets or are the README's 17 runs; official event-kit compatibility is unverified (AGENTS.md).
8. **Figures from the research digest not re-verified in this pass:** 62 % CHP area (2017 WUR memo, cited in repo), labour above 30 % of cost, USDA ERS 29 % retail contracts, Blue Radix, Koidra, SimuHome. Do not put these on a slide without a check.
9. **My worked examples** (CHP breakeven EUR 72/MWh, EUR 0.036/kWh margin, buffer fill 3-11 h, 6,000 kg into 4,000 kg = EUR 135k, lamp load 350-820 kW) are hand arithmetic from the data files, not simulator output.
