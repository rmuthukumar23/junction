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
tag: Can an AI run a greenhouse for 42 days?
notes: Open with the question. The next slides: why this job matters, what makes it hard, how we built it, what happened.

---

layout: stats
title: Dutch glasshouses
steps: on
- ~10,000 | hectares under glass | green
- ~9% | of all Dutch natural gas | orange
- 1,000+ | combined heat and power engines | blue
notes: One of the biggest greenhouse industries in the world, and heavily energy-driven. About 9% of Dutch gas, three quarters of it for CHP engines that make heat, power and CO2 together. This is why we chose it as the setting.

---

layout: cards
title: The operator's day
steps: on
- Plants | What to plant and when, when to harvest | green
- Climate | Heat, light and CO2 for each house | orange
- Energy | Gas, power and a heat buffer, shared by all houses | blue
- Business | Crew, orders, repairs, who to sell to | purple
notes: A greenhouse operator does not just buy energy. They grow plants and run a business. Every morning these four jobs compete for the same limited resources.

---

layout: flow
title: Everything is linked
steps: on
- Order seed | Arrives in 10 days | orange
- Plant | Needs heat, light and CO2 | green
- Grow | Climate sets how fast | green
- Harvest | Only a short window of top quality | purple
- Sell | Buyers want a set amount each week | blue
notes: Today's seed order pays off two weeks later. Order late and the cycle is lost. Harvest everything at once and the market is full, so the rest sells for nothing. The agent must plan volume, not just notice a crop is ready.

---

layout: cards
title: Why it is hard
steps: on
- Plan ahead | Seeds, orders and gas take days to arrive | orange
- Share limits | One energy centre, three houses. Every choice is a trade-off. | blue
- Adapt | Storms and breakdowns break the plan | red
notes: Our hypothesis: models plan well for one step and lose the plan over weeks. Three failure patterns, all seen in the real runs: constraints that interact, no change after bad news, work left unfinished. Do not claim AI cannot operate greenhouses; the claim is about this reproducible 42-day task.

---

layout: flow
title: The environment
steps: on
- Data files | Recorded weather, power and gas prices. Crops, equipment, costs. | green
- Scenario | Picks the data: a 42-day winter, which crops, how many houses. | blue
- Seed | One number. Same seed, same weather, prices and breakdowns. | orange
- Simulator | Plain code, no AI. Runs the farm hour by hour. Deterministic. | blue
- Agent | The model. One tool, submit_day: up to 5 actions a day. | purple
notes: This is the architecture, not one scenario. Crops, houses and lead times are knobs. The agent container holds no scenario, seed or engine; the world runs in a sidecar over MCP (Harbor 0.26 with OpenCode 1.19.5). If asked: official AfterQuery event-kit compatibility is not verified.

---

layout: flow
title: A day
steps: on
- Night | Nobody is on site. The farm runs on its own. | grey
- 06:00 | Read the night report and the forecast. Decide. | orange
- submit_day | Up to 5 actions: climate, planting, orders, crew, repairs | green
notes: Research shows most greenhouses have no night shift: staff leave in the evening and arrive around 06:00. So the agent starts each day the same way: it reads what happened overnight, checks the forecast, and makes the judgment calls. It cannot fix a bad plan hourly. This is a modelling choice that creates a planning test, not a claim that nobody is on call.

---

layout: cards
title: Realism
steps: on
- The Netherlands | Real hourly weather, power and gas prices | green
- The biology | Every crop has its own growth model. Light, heat and CO2 set growth, growth sets the kilos to sell. | orange
- The equipment | A standard Dutch set-up with a gas engine, boiler, heat buffer | blue
notes: We researched Dutch greenhouse horticulture and crop growth so the scenario is as realistic as we can make it. Do not go into equations. Honest labels if asked: weather and prices are recorded (KNMI De Bilt, ENTSO-E, TTF); crop models are from published research (Van Henten) and calibrated to published harvest times; equipment sizes and some prices are transparent design choices. It is a research-informed abstraction, not a copy of one farm.

---

layout: flow
title: Scoring
steps: on
- Replay | A separate process replays every recorded action | purple
- Recalculate | Same season, same world, from scratch | blue
- Net profit | Sales minus costs, in euros | green
notes: Score = clip(0.8 x (profit - profit_nobody) / (profit_reference - profit_nobody), 0, 1). Zero is a farm where nobody acts, 0.8 is the scripted reference planner, so there is headroom above it. The replay is checked against recorded digests, so the score cannot be faked.

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
notes: From runs/ANALYSIS.md, 15 Nov 2026. Gemini 0.781 (95% CI 0.751 to 0.814, 7 runs), Sonnet 0.695 (0.518 to 0.799, 7 runs; 0.781 without the run that ended on day 9), Haiku 0.622 (0.539 to 0.668, 3 runs). If asked: few runs per cell, wide intervals, no frontier gap is claimed, official kit not run.

---

layout: image
title: Where it failed
image: img/market-window.svg
notes: The planner keeps sales (blue) under the demand line. Haiku sold 6.2 t in week 3, then cut 2.2 t more in week 4 while still inside the rolling window: EUR 0. Models know the rules and lose the plan.

---

layout: stats
title: The same mistakes, again
steps: on
- 8 of 17 | left the boiler broken over a week | red
- 10 of 17 | planted before the seed arrived | orange
- 6 of 7 | Gemini runs sent malformed actions | purple
notes: Boiler: tripped on day 22, no repair for 20 days (Sonnet seed 1). Seed: ordered with a ten-day lead, planted a few hours before it landed. Malformed: ordered "part" instead of "part:glass_pane", so the whole order was refused. Good play exists: Gemini seed 2 beat the planner by staggering partial sales.

---

layout: hero
title: Beat the AI
tag: Play two mornings. Get ranked against 7 AI runs.
notes: Live demo. bash scripts/phone.sh, play two mornings of seed 1 on a phone, ranked against the 7 AI runs and the planner. Fallback: open the replay viewer, index.html.
