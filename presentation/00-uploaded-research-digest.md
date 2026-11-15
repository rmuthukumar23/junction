# Digest of the uploaded "Realism and Research Verification" report (14 Nov 2026)

Condensed by the coordinator. The report is slightly outdated against the round-3 rules: check every number against `docs/` and `data/` before using it. Sources are in the original report; re-verify with a web search before putting a stat on a slide.

## Verified real-world facts (usable, cite the source)
- ~62% of Dutch glasshouse area heated by CHP (2017, WUR memo edepot.wur.nl/526773); NZ benchmarking says two thirds.
- ~10,000 ha of glasshouse; ~9% of all Dutch natural gas; >1,000 CHP units, ~2,400 MW electric, ~10.5 TWh/yr (more than the sector's own 6.6 TWh demand). TenneT treats them as balancing capacity.
- CHP + peak boiler + heat buffer is the standard setup. One CHP makes heat, power and CO2 at once; ~40% of fuel becomes electricity, so it burns more gas than a boiler for the same heat and makes ~2x the CO2. Crop wants CO2 when it is sunny, i.e. when heat is least needed: that mismatch is the core trade-off.
- WUR "heat demand mode" vs "economic value mode" (run CHP when power revenue exceeds fuel cost). Running CHP just for CO2 wastes heat.
- Seginer et al. 2018: CHP and buffer contribute very significantly to profit; screen and boiler only marginally.
- OCAP: ~580 growers, ~1,900 ha, 97 km transport line. Shortages are real (OCAP and Air Liquide both failed for days) but cluster in SUMMER. A winter CO2 crunch is only realistic paired with a CHP failure or gas spike.
- Dutch grid congestion: caps on import/export; Noord-Holland growers paid to flex CHPs.
- 2022 energy crisis: prices ~10x; growers cut lighting, left houses empty; firms without CHP went bankrupt; CHP owners offset by selling power at high prices. Strongest pitch scenario.
- Priva Connext / Hoogendoorn: grower sets setpoints, climate computer moves actuators. Our agent sets setpoints (the layer above).
- Blue Radix: 100+ commercial sites, up to 80% less manual climate-computer work; Revol Greens (largest US greenhouse lettuce grower) uses it for climate, irrigation, energy. Koidra (won AGC) at Great Lakes Greenhouses.
- Wageningen Autonomous Greenhouse Challenge: ed.1 cucumber 2018 (one AI team beat growers), ed.2 cherry tomato (all 5 AI teams beat growers), ed.3 2022 lettuce, scored on NET PROFIT, 96 m2 compartments. All lettuce teams grew heads too heavy and too slow: a harvest-timing failure.
- Labour >30% of greenhouse production cost (WUR). WUR labour-scheduling model saved ~EUR 4/m2/yr in a rose grower.
- Lettuce: DLI optimum ~17 mol/m2/d, tipburn above; growth ~proportional to light (half DLI doubles time); 35 d seed-to-harvest, 24 d transplant-to-harvest at DLI 17; Dutch winter outdoor DLI ~1-5, so winter cycles need lamps (lamps are the lever that buys cycle time, paid at hourly power prices and capped by grid connection). Targets 24 C day / 19 C night (setpoints, not maxima). Bolting at 27-32 C. Botrytis needs 85%+ RH and 8-12 h leaf wetness. Lettuce tolerates light frost: do-nothing "stalls and never reaches sellable weight" (do not say "freezes").
- Van Henten 1994: 4 states, 4 disturbances, 3 controls, net-return objective; Katzin et al. used it for Dutch winter lettuce. Caution: temperature is a weak driver in his model.
- Retail contracts with minimum volume are the most common produce contract (USDA ERS 29%).
- Failure grounding: StoreBench (AfterQuery, Oct 2026): Fable 5.2 0.835 composite; 26% of runs underbought (178 of 693); 60 runs never placed a PO; premature termination. Vending-Bench (Andon Labs): runs derail on delivery schedules, forgotten orders, meltdown loops. tau-bench: pass^k, GPT-4o 61% pass^1 vs 25% pass^8.

## Corrections the report asked for
1. Lettuce cycle = transplant to harvest, ~24 d at target DLI, assumes supplemental light.
2. Temperature as targets, not maxima.
3. Do-nothing stalls, not freezes.
4. Winter CO2 cut must pair with CHP outage / gas spike.
5. Gas: grid gas with price risk; no stock/lead times.
6. Low-VPD threshold: document range 0.2-0.4 kPa.
7. Check temperature sensitivity in the growth model.
8. UNVERIFIED, do not quote: StoreBench training result (Qwen 0.136 to 0.373); "thermostat off by 5 F"; hiring notice periods and seedling lead times (design assumptions).

## Pitch-safe lines the report proposed
See report section 11; the safe ones: two-thirds CHP heating; 1,000+ CHP units / 2,400 MW; OCAP 580 growers; 2022 tenfold prices; AGC scores AI on lettuce net profit and we extend it to the whole facility; Blue Radix at 100+ sites, open question is the planning layer above it; reward is net profit in euros (Van Henten's objective).
