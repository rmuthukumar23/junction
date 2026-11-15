<!--
THE DECK TEXT. Edit this file, reload present.html. Nothing else needs touching.

Slides are separated by a line with three dashes.
Each slide: `key: value` lines, then `- item` lines, then optional `notes:` (everything after it is speaker notes, press N).

keys
  layout  hero | stats | cards | flow | bars | image | big
  title   the slide title (keep it short and plain)
  steps   on = each item appears on its own click (use only where order matters)
  image   file in deck/ (png/svg) or img/ (README figures) for hero and image layouts
  tag     small line at the bottom of a hero slide
  mascot  yes = centred picture with the title below (hero only)

items   - main text | small text | colour
  colours: green blue orange purple red grey
  bars:   - Name | 0.62 | colour      (value 0 to 1)
  stats:  - 10,000 | hectares | green  (big number, label)
  big:    first item is the big line, second the small line
-->

layout: hero
title: LettuceBench
image: deck/greenhouse.png
tag: 42 days. Maximize net profit.
notes: Open on the picture. Six growers, same weather, same prices, same breakdowns, one simulator. Nothing to explain yet.

---

layout: stats
title: Dutch glasshouses
steps: on
- ~10,000 | hectares under glass | green
- ~9% | of all Dutch natural gas | orange
- 1,000+ | combined heat and power engines | blue
notes: A glasshouse is economically a small power station. About 9,000 to 10,000 ha depending on the measure (CBS). About 9% of Dutch natural gas, three quarters of it feeds CHP. More than 1,000 CHP units, about 2.4 GW electric, which is more than the sector itself uses, so growers sell power to the grid. Sources and caveats are in presentation/01-intro-and-problem.md. Two PDFs were only read as excerpts, so say "about".

---

layout: cards
title: 2022 showed the risk
steps: on
- Energy prices spiked | Gas and power costs rose by about two thirds, two years running | orange
- Houses stood empty | Growers switched off lamps and left glass unplanted | red
- Planning decided who survived | Fixed contracts and CHP carried many through | green
notes: Energy costs for the sector rose roughly 65% in 2021 and 62% in 2022 (WUR; only read as an excerpt, say "about two thirds" and do not quote the exact numbers if pressed). Fewer than 0.5% of firms went bankrupt, partly thanks to fixed contracts and CHP. Do not say prices went up ten times; that is not confirmed.

---

layout: cards
title: Why it matters now
steps: on
- The grid is full | Congestion is the top concern of growers; cheap power cannot always be used or sold | blue
- Labour is short | The sector depends on migrant workers and supply is falling | orange
- The plan is the margin | Every day has linked choices on energy, crew, orders and repairs | green
notes: Grid congestion named the most pressing issue (Rabobank 2024). Noord-Holland growers were asked to run CHP like one big power plant because the grid is full. Labour: MFAT reports on Dutch horticulture. Only qualitative statements are available, no counts.

---

layout: flow
title: The planning job
steps: on
- Climate computer | Holds setpoints: vents, screens, lamps, valves | grey
- Grower | Decides the plan: energy, crew, orders, repairs, what to plant | green
notes: Priva and Hoogendoorn style computers execute setpoints. They do not decide whether to run the CHP tonight, whether lamps are worth the grid peak, what to plant given a ten-day seed delivery, or whether to hire. Blue Radix and Koidra (winner of the 2022 Autonomous Greenhouse Challenge) work on climate and crop. Whole-facility results for language-model agents are not published, to our knowledge. Do not claim those systems cannot plan.

---

layout: big
title: The open question
- Can an AI plan the whole facility?
- Nobody has measured it. So we built the test.
notes: This is the gap. Long horizon, linked decisions, scored in euros.

---

layout: image
title: LettuceBench
image: deck/greenhouse.png
notes: The 3D viewer scene. Three compartments (two broccoli microgreens, one radish) and one shared energy centre, 42 simulated days, score is net profit.

---

layout: flow
title: The environment
steps: on
- Data files | Recorded weather, power and gas prices. Crops, equipment, costs. | green
- Scenario | Picks the data: a 42-day winter, which crops, how many houses. | blue
- Seed | One number. Same seed, same weather, prices and breakdowns. | orange
- Simulator | Plain code, no AI. Runs the farm hour by hour. Deterministic. | blue
- Agent | The model. One tool, submit_day: up to 5 actions a day. | purple
notes: This is the architecture, not one scenario. Crops, houses and lead times are knobs. Data lives in data/ and is validated on load. The agent container holds no scenario, seed or engine: the world runs in a sidecar over MCP (Harbor 0.26 with OpenCode 1.19.5). Held-out evaluation seeds are 101 to 108, dev seeds 1 to 6. If asked: official AfterQuery event-kit compatibility is not verified.

---

layout: flow
title: A day
steps: on
- 06:00 Briefing | The agent sees the farm, prices, orders and alarms | orange
- submit_day | Up to 5 actions: climate, lamps, orders, crew, planting, harvest, repairs | green
- 24 hours | The day runs. Nobody acts. Weather and prices play out. | blue
notes: One call per day, 42 days. The simulator runs 24 one-hour windows inside the call. The agent cannot react mid-day, like a grower who sets the plan in the morning and lives with it. A missing or ungradeable trace is an infrastructure failure, not a zero for the agent.

---

layout: flow
title: Verifier
steps: on
- Replay | A separate process replays every recorded action | purple
- Recalculate | Same season, same world, from scratch | blue
- Net profit | Sales minus costs, in euros | green
notes: Score = clip(0.8 x (profit - profit_nobody) / (profit_reference - profit_nobody), 0, 1). Zero is a farm where nobody acts, 0.8 is the scripted reference planner, so there is headroom above it. The replay is checked against recorded digests, so the score cannot be faked.

---

layout: cards
title: Realism
steps: on
- Recorded | KNMI hourly weather, Dutch day-ahead power prices, TTF gas | green
- Assumed | Equipment sizes, crew and wages, buyers and weekly demand | orange
notes: Weather: two 50-day KNMI De Bilt windows (2024 and 2025). Prices: hourly ENTSO-E day-ahead incl. negative hours. Equipment values are engineering assumptions in the real Dutch range (CHP, peak boiler, buffer, CO2, grid cap is the standard set-up), not one farm's data. Tariffs: import markup EUR 0.03 per kWh, export at 50% of day-ahead. Say so plainly if asked.

---

layout: bars
title: 17 runs. 3 seeds.
steps: on
- Nobody acts | 0.00 | grey
- Stop early | 0.24 | grey
- Claude Haiku | 0.62 | orange
- Claude Sonnet | 0.70 | purple
- Gemini | 0.78 | blue
- Reference solution | 0.80 | green
notes: From runs/ANALYSIS.md, 15 Nov 2026, Harbor 0.26 with OpenCode 1.19.5. Gemini 0.781 (95% CI 0.751 to 0.814, 7 runs), Sonnet 0.695 (0.518 to 0.799, 7 runs; 0.781 without the run that ended on day 9), Haiku 0.622 (0.539 to 0.668, 3 runs). If asked: few runs per cell, wide intervals, no frontier gap is claimed, official kit not run.

---

layout: image
title: Where it failed
image: img/market-window.svg
notes: The planner keeps sales (blue) under the demand line. Haiku sold 6.2 t in week 3, then cut 2.2 t more in week 4 while that was still inside the rolling window: EUR 0. Models know the rules and lose the plan.

---

layout: stats
title: The same mistakes, again
steps: on
- 8 of 17 | left the boiler broken over a week | red
- 10 of 17 | planted before the seed arrived | orange
- 6 of 7 | Gemini runs sent malformed actions | purple
notes: Boiler: tripped on day 22 and in every briefing after, no repair for 20 days (Sonnet seed 1, runs/normal-winter/claude-sonnet-5-5-s1-lbtq2lu/DAYS.md). Seed: ordered with a ten-day lead, planted a few hours before it landed. Malformed: ordered "part" instead of "part:glass_pane" so the whole order was refused. Good play exists: Gemini seed 2 beat the planner by staggering partial sales.

---

layout: big
title: Training
- Qwen 3-4B
- Result goes here
notes: PLACEHOLDER. There are no fine-tuning docs, scripts or results in the repo. Need: method, base score, tuned score, seeds. If the result is good, move this before "Where it failed" and make it the climax.

---

layout: hero
title: Beat the AI
image: deck/lettuce.png
mascot: yes
tag: Play two mornings. Get ranked against 7 AI runs.
notes: Live demo. bash scripts/phone.sh, play two mornings of seed 1 on a phone, ranked against the 7 AI runs and the planner (docs/PHONE_GAME.md). Fallback: open the replay viewer, index.html.
