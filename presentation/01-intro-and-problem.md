# Part 1: Intro and the problem (draft)

Status: web-checked 15 Nov 2026 with search excerpts. Two PDFs (WUR monitor, GTNL key figures) could not be read in full, so figures marked "excerpt" should get a 30-second check before the slide is final.

## (a) Slides

### Slide 1. "A greenhouse is a power plant that grows lettuce"
- The Netherlands has about 9,000-10,000 ha of glasshouse.
- It uses about 9% of all Dutch natural gas; about three quarters of that gas feeds CHP units.
- More than 1,000 CHP units, 2,400 MW electric, 10.5 TWh/yr: more than the sector's own 6.6 TWh demand. Growers sell power to the grid.
- Visual: one pixel greenhouse with three arrows: gas in, heat + CO2 to crops, power out to grid.
- **Big number: ~9% of Dutch natural gas.**

### Slide 2. "2022 showed what that means"
- Gas and power prices spiked; growers idled lamps and left houses partly or fully empty.
- Yet fewer than 0.5% of companies went bankrupt (2021 to Q1 2023): growers with CHP and fixed contracts survived. Energy planning decided who did well.
- Today the grid itself is a constraint: growers rank grid congestion as their most pressing issue.
- Visual: price line (from our own scenario data, or a labelled public chart) with "lamps off, houses empty" annotation.
- **Big number: +65% (2021) and +62% (2022) energy costs for the sector (excerpt, verify basis).**

### Slide 3. "The climate computer follows setpoints. Who sets them?"
- Priva/Hoogendoorn-style computers move vents, screens, pipes to a setpoint. They do not decide the plan.
- Someone must weigh: gas vs power price, CO2 vs heat from the CHP, lamp hours vs grid cap, which batch to plant, how many staff, which order to fill.
- Labour is short (sector relies on migrant workers, supply falling) so that someone is scarce.
- Visual: two-layer diagram. Bottom: "climate computer (executes)". Top, highlighted: "planner (energy, CO2, crop timing, staff, orders)".
- **Big number: 1 plan, 5 coupled decisions.** (No stat; keep as the framing line.)

### Slide 4. "Who sells AI here, and what is open"
- Blue Radix: autonomous climate/irrigation/energy control; Revol Greens uses it across US sites. Koidra: won the Wageningen Autonomous Greenhouse Challenge (lettuce, 2022: EUR 5.93/m2 net profit vs EUR 3.39 for second).
- These systems are tested on one compartment's climate and crop, scored on net profit.
- Open: the whole facility. Shared energy centre, staffing, orders, weekly contracts, damage and repairs, all in one profit number, and nobody publishes how frontier LLM agents do at it.
- Visual: three columns "Climate control (solved-ish)", "Crop challenge (AGC)", "Whole-facility planning (Greenhouse Bench)".
- **Big number: EUR 5.93/m2 (AGC 2022 winner net profit).**

### Optional slide 5 (transition). "So we built the facility as a benchmark"
- 42 days, one tool call per day, scored in euros of net profit, deterministic by seed.
- Next: how it works (Part 2).
- Visual: the Greenhouse Bench pixel site title screen.

## (b) Speaker notes

**Slide 1 (~45 s).** "Picture a lettuce greenhouse in Westland. It looks like farming, but economically it is a small power station. About nine percent of all Dutch natural gas goes into greenhouses, and three quarters of that runs combined heat and power engines. There are over a thousand of them, 2.4 gigawatts, producing more electricity than the whole sector uses. So the grower is selling power, buying power, buying gas, and using the exhaust CO2 on the crop, all at hourly prices."

**Slide 2 (~40 s).** "In 2022 that exposure became real. Energy costs for the sector rose by around two thirds two years running, growers switched off lights and left greenhouses empty. Wageningen found few went bankrupt, partly because many had fixed contracts and CHP. The lesson: how you plan energy decides the outcome. And now the grid is full: growers name congestion as their top problem, so even when power is cheap you may not be able to use or sell it."

**Slide 3 (~50 s).** "Here is the gap. The climate computer is excellent at holding 24 degrees. It does not decide whether to run the CHP tonight, whether lamps are worth the grid peak, which batch to plant given a seed delivery that takes ten days, or whether to hire. That planning sits with a head grower, and that person is hard to find: the sector depends on migrant labour and labour supply is falling. Planning across energy, CO2, crop timing, staff and orders is the job nobody has automated."

**Slide 4 (~50 s).** "There is real AI here. Blue Radix runs climate, irrigation and energy at commercial sites including Revol Greens in the US. Koidra won Wageningen's Autonomous Greenhouse Challenge, scored on net profit, with 5.93 euros per square meter on lettuce. That is the crop and climate layer. What is open is the whole facility under one profit number, with shared energy, staff, orders and damage, and a way to measure whether language-model agents can do it. That is what we built."

## (c) Sources

| Claim (exact, as supported) | URL |
|---|---|
| Greenhouse horticulture "ruim 9.000 hectare" in 2024 (CBS Landbouwtelling) | https://communicatietoolkitgezondheidengeluk.glastuinbouwnederland.nl/content/glastuinbouwnederland/docs/Verantwoorde_Glastuinbouw/Visiedocumenten_2025/Visiedocument_Ruimte_2025.pdf |
| Total greenhouse area "10 duizend hectare" (CBS, 2024 data) | https://www.cbs.nl/nl-nl/nieuws/2026/07/biologische-bestrijders-op-94-procent-van-glastuinbouwareaal |
| CBS topographic measure gives 13,000 ha (different measure; do not use as the headline) | https://www.cbs.nl/nl-nl/longread/aanvullende-statistische-diensten/2023/aardgasverbruik-glastuinbouw-in-nederland/3-deelonderzoek-areaal |
| Greenhouses = 9% of Dutch natural gas; three quarters of it fuels CHP; CHP covers 11% of national electricity (older article) | https://subsites.wur.nl/en/article/greenhouses-cant-do-without-gas-yet.htm |
| >1,000 CHPs, 2,400 MW, 10.5 TWh/yr production vs 6.6 TWh/yr horticulture demand (undated factsheet, Feb 2024 filename) | https://kasalsenergiebron.nl/content/docs/WKK/20240229_factsheet_CHP_ENGLISH.pdf |
| ~62% of glasshouse area heated with CHP in 2017 | https://edepot.wur.nl/526773 |
| Energy use +8% to +14% and CO2 +5% in 2023 vs 2022; electricity purchases +60% (excerpt; article internally inconsistent on energy use) | https://www.hortidaily.com/article/9680843/nl-glasshouse-horticulture-energy-use-rebounds-in-2023-sector-does-become-more-economical |
| Gas use 2022-2024 on average 27% below 2019-2021; agricultural gas use +5% in 2024 driven by greenhouse CHP | https://abnamro.com/research/en/our-research/esg-economist-gas-consumption-structurally-lower-since-energy-crisis |
| <0.5% of greenhouse companies bankrupt 2021 to Q1 2023; 11 bankruptcies; ~4% stopped; a quarter saw no negative effect; ornamentals hit hardest; 75% had fixed some energy price pre-2022 | https://research.wur.nl/en/publications/onderzoek-naar-de-gevolgen-van-hoge-energieprijzen-in-de-glastuin/ and https://www.hortidaily.com/article/9573080/11-bankruptcies-more-stoppers-and-mostly-ornamental-horticulture |
| Energy costs of greenhouse horticulture +65% in 2021 and +62% in 2022 (table-of-contents excerpt, basis unconfirmed) | https://research.wur.nl/en/publications/onderzoek-naar-de-gevolgen-van-hoge-energieprijzen-in-de-glastuin/ |
| Growers left greenhouses partly or entirely empty; government compensation for voluntary reduction | https://www.mfat.govt.nz/en/trade/mfat-market-reports/the-dutch-horticulture-sector-an-innovative-sector-facing-an-energy-crisis-and-rising-costs-september-2022 and https://www.bnnbloomberg.ca/energy-crisis-empties-greenhouses-in-world-s-top-flower-producer-1.1813888 |
| Grid congestion named the most pressing issue and main reason for not investing in energy saving (Rabobank-based, 2024) | https://www.hortidaily.com/article/9629438/rabobank-energy-transition-in-horticulture-not-finished |
| Horticulture exports EUR 11.5 bn in 2023 (CBS; flat vs 2022; total Dutch agri exports EUR 123.8 bn) | https://www.cbs.nl/en-gb/news/2024/10/dutch-agricultural-exports-worth-nearly-124-billion-euros-in-2023 |
| Sector relies heavily on migrant workers; labour supply fallen; labour- and energy-intensive greenhouse horticulture relocating (MFAT, Aug 2023) | https://www.mfat.govt.nz/br/trade/mfat-market-reports/innovations-in-dutch-agritech-august-2023 |
| Labour scheduling model could change labour costs for cut roses by up to EUR 7.1/m2/yr (roses; the digest's "EUR 4" is not confirmed) | https://wur.nl/en/research-results/research-institutes/plant-research/greenhouse-horticulture/show-greenhouse/update-quantitative-information-kwin-shows-major-price-changes-in-greenhouse-horticulture.htm |
| Blue Radix: AI services for all Revol Greens US greenhouses; climate, irrigation, energy; recomputes optimal climate every 5 min; no quantified results published; rollout MN, CA, GA, TX | https://www.greenhousegrower.com/production/revol-greens-invests-in-ai-platform-to-boost-yields-and-reduce-energy-costs/ |
| Blue Radix grew out of the first Autonomous Greenhouse Challenge team; GreenTech Innovation Award 2024 | https://aiph.org/floraculture/news/blue-radix-wins-the-greentech-innovation-award-2024 |
| Koidra founded 2020 by Kenneth Tran after the challenge; Team Koala (Koidra + Cornell) won the 2022 lettuce edition | https://cea.cals.cornell.edu/2022/07/06/dutch-american-team-captures-autonomous-greenhouse-challenge |
| AGC 2022 results: Koala EUR 5.93/m2 net profit, Digital Cucumbers EUR 3.39, CVA 1.47, Monday Lettuce negative; five teams; cultivar Lugano | https://www.ledsmagazine.com/company-newsfeed/article/14280580/team-koala-wins-the-autonomous-greenhouse-challenge-for-a-second-time and https://www.hortidaily.com/article/9441502/focus-on-crop-temperature-brings-victory-to-koala-in-autonomous-greenhouse-challenge |
| AGC lettuce-edition data set (4TU, CC BY 4.0) | per repo docs/GREENHOUSE_BENCH_CONTEXT.md (not re-verified today) |

## (d) Do not claim

- Energy as a percentage of production cost: no source found. Skip it; use the +65%/+62% cost-rise only with "excerpt" caution, or drop it.
- "Labour above 30% of production cost (WUR)": in the research digest but not reproduced in any source today. Do not put on a slide until confirmed.
- "EUR 4/m2/yr saved by labour scheduling": digest figure; the source says "up to EUR 7.1/m2/yr" for roses. Quote the source, name the crop, or omit.
- "Prices ~10x in 2022": not confirmed today. Say "spiked" or cite a concrete gas price from the sourced articles.
- Dutch greenhouse area as a single exact number: sources give 9,000+ (Landbouwtelling), 10,000 (CBS 2026), 13,000 (topographic). Say "about 9,000-10,000 ha".
- Exports as "EUR 11.3 bn": year unclear. Use EUR 11.5 bn horticulture exports in 2023 (CBS), and note it covers all horticulture, not only greenhouses.
- "Blue Radix at 100+ sites / up to 80% less manual work": not seen in today's sources. Do not quote; say "used at commercial sites such as Revol Greens".
- Any claim that Koidra or Blue Radix cannot plan across the facility. We found no source on their scope; phrase as "published results focus on climate and crop; whole-facility LLM-agent results are not published, to our knowledge".
- "Ed. 2 all 5 AI teams beat growers" and "AI teams beat growers" in general: not re-verified. Omit.
- A frontier-agent gap, official kit compatibility, or any model score from our benchmark (README Known limits).
- Percentage of greenhouses with night staff (see GREENHOUSE_BENCH_CONTEXT 0.4).
- Number of growers hit by grid congestion or labour shortage: only qualitative statements found.
