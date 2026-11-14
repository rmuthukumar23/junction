# Crops: the locked set

Locked on 14 Nov 2026 for the hackathon. Every scenario uses only these three crops:

| Id | Crop | Grown as | Days in the compartment | Harvest | Sold |
|---|---|---|---|---|---|
| `lettuce_butterhead` | Butterhead lettuce | Bought-in plug, transplanted | 21 (plus 11 in propagation) | Single cut | Per head |
| `broccoli_micro` | Broccoli microgreens | Sown in trays in the compartment | 12 | Single cut | Per kg |
| `radish_micro` | Radish microgreens | Sown in trays in the compartment | 8 | Single cut | Per kg |

Basil (`data/crops/basil_genovese.toml`) leaves the locked set. Its file can stay as a test fixture for the repeated-cut code path, but no scenario uses it.

**Why these three.** They cover three cycle lengths (8, 12 and 21 days), so a 42-day episode has many harvest and resowing decisions, and they give two supply routes: lettuce depends on a plug order with a lead time, while microgreens are sown directly from seed held in stock. All three are cool-season brassicas or lettuce, so they share one climate band, and a mixed compartment remains a real but manageable compromise.

**How to read the values.** Every value carries a tag. A sourced value cites the source (list at the end). `[DES]` marks a design value: no usable published number was found, so the value was chosen to be plausible, and changing it is a data change only. `[CAL]` marks a value set by a calibration test so the model hits a sourced target. Base prices belong in the market file (`data/markets/*.toml`, spec 3.4), not in the crop file; they are listed here so one page holds everything a scenario needs.

---

## What a crop needs to plug in

A crop is plugged into a scenario by three things. No Python changes, except the one model change marked below for microgreens.

1. **Crop file** `data/crops/<id>.toml` (schema `crop/1`, spec 3.1): `[cycle]`, `[planting]`, `[growth]`, `[climate_targets]`, `[stress]`, `ready_loss_per_day`, `[market]` (unit, minimum sellable size, grades), `[estimate]`.
2. **Market entries** in the scenario's market file: `[crops.<id>]` with the sale price, and `[items."seedlings:<id>"]` (lettuce plugs) or `[items."seed:<id>"]` (microgreen seed), each with price, lead time, minimum quantity, dispatch window and cancel fee.
3. **The scenario** lists the crop file under `[env] crops` and sets any starting batches.

**Model change needed for microgreens (one change, owned by Lucas).** `leafy_vanhenten` starts a batch from a transplanted plug and grows it on light from hour 0. Microgreens start from seed and spend their first days germinating in the dark (blackout), living on the seed's reserves. That needs either one optional field in `[cycle]`, `germination_days` (no light-driven growth and no light demand during those days; the batch starts from `transplant_dry_weight_g` = seed dry weight afterwards), or a registered `microgreen` growth model. The optional field is the smaller change and keeps one model for all three crops. Everything else below fits the current schema.

---

## 1. Butterhead lettuce (`lettuce_butterhead`)

The file exists and its growth parameters are from Van Henten (1994). It needs the cycle values below, then a recalibration.

### Cycle and supply

| Field | Value | Tag and note |
|---|---|---|
| `harvest_mode` | `single` | |
| Propagation (seed to plug) | 11 days at good light; 22 at half light | [CEA] Cornell. Happens at the propagator, not in the episode |
| `nominal_days` (transplant to harvest) | **21** | Pinned design value at DLI 17 with CO2 enrichment. The best sourced commercial figure is 24 days at DLI 17 [CEA]; grower guides give 21 to 28; Kentucky gives about 30. **Currently 32 in the file: change it** |
| Growth scaling | Roughly proportional to light: half the light, about twice as long | [CEA] Already a property of the light-driven model |
| `min_days_before_end` | 21 | [DES] Same as the cycle, so a batch planted on time can still be sold. **Currently 30 in the file** |
| `ready_fresh_weight_g` | 250 | [DES] Typical marketable butterhead, 250 to 300 g |
| `canopy_closure_m2_kg` | Recalibrate | [CAL] Currently 9.5, which gives 32.2 days. Retune `test_crop_growth.py` so the target climate gives 21 days |
| Plug supply | Market item `seedlings:lettuce_butterhead`: EUR 0.08 per plant, 168 h lead time, minimum 5,000, 24 h dispatch, EUR 200 cancel fee | Existing market file. Propagators grow to order [BKK]; 2 to 3 weeks from sowing [TEA]; one week assumes a pre-booked schedule [DES]. The plug price is [DES]: no published Dutch per-plug price was found |

### Planting, labour, climate, stress, market

| Field | Value | Tag |
|---|---|---|
| `density_per_m2` | 20 | [DES] Common butterhead spacing |
| `transplant_dry_weight_g` | 0.175 (about 4 g fresh) | [VH94] |
| `plant_worker_hours_per_1000` / `harvest_worker_hours_per_1000` | 1.5 / 3.0 | [DES] |
| Day / night temperature | 16–22 / 12–18 °C (24 / 19 °C are upper targets, not maxima) | [DES] |
| CO2 | 800–1,000 ppm, no gain above 1,200 | [DES] |
| DLI | 12–17 mol m⁻² d⁻¹, photoperiod 16 h | [CEA] Tipburn rises above 17 |
| RH | 70–85 % | [DES] |
| Stress: tipburn | DLI above 17, 0.01 per mol per day | [CEA] threshold, [DES] rate |
| Stress: bolting | Day mean above 24 °C, 0.01 per °C per day | [DES] |
| Stress: cold / frost | Below 4 °C, 0.05 per °C per day; batch lost below −1 °C | [DES] |
| `ready_loss_per_day` | 0.03 (grade A 5 days, then B, waste after about 13) | [DES] Late harvest lowers butterhead quality [RED] |
| Unit, minimum sellable | Per head, 150 g | [DES] |
| Grades | A ≥ 0.85 × 1.0; B ≥ 0.60 × 0.6; waste | [DES] |
| Sale price | EUR 0.45 per head | [FP1][FP2] EUR 0.30 in weak markets, 0.50 in good ones; winter is the upper half |

**Revenue check.** 20 heads/m² × EUR 0.45 = **EUR 9 per m² per 21-day cycle**, less EUR 1.60/m² of plugs.

---

## 2. Broccoli microgreens (`broccoli_micro`)

New crop. Grown in trays on benches in a compartment, sown from seed, harvested whole at the first true leaf.

### Cycle and supply

| Field | Value | Tag and note |
|---|---|---|
| `harvest_mode` | `single` | Microgreens are cut once and the tray is cleared |
| `germination_days` (new field) | 3 | [DES] Blackout of 3 to 4 days is typical grower practice [BSF]; no peer-reviewed figure |
| `nominal_days` (sow to harvest) | **12** | Johnny's trial: 12.5 days average to the first true leaf [JSS]. Highest yield on day 13 [ORT]. Seed suppliers give 10 to 15 [SUP]. Shortest realistic value, rounded down |
| `min_days_before_end` | 12 | [DES] Same as the cycle |
| Yield at harvest | **2.5 kg/m²** | [JSS] 11.5 oz (326 g) per 10×20-inch tray (0.129 m²). Calibration target for the model at the target climate |
| Yield range | 1.6 to 2.5 kg/m² | Fresh weight rises with light, by 36 to 82 % from PPFD 100 to 600 in four Brassicaceae microgreens [JB19] |
| `canopy_closure_m2_kg` and growth parameters | Lettuce's Van Henten values; retune `canopy_closure_m2_kg` only | [CAL] So the target climate gives 2.5 kg/m² on day 12 |
| `dry_matter_fraction` | 0.093 | [SR24] Moisture 90.72 g/100 g fresh weight |
| Seed supply | Market item `seed:broccoli_micro`, held in stock and drawn per sowing | Sowing rate below. Seed price, lead time and minimum quantity are [DES]: no EU wholesale seed price was found. Suggested: EUR 40/kg, 72 h lead time, minimum 5 kg |

### Planting, labour, climate, stress, market

| Field | Value | Tag |
|---|---|---|
| Sowing rate | 100 g seed per m² (13 g per tray) | [JSS] Johnny's yield-trial rate. Other growers sow 15 to 20 g per tray [BSF] |
| `density_per_m2` | 29,000 seeds | [DES] From the sowing rate and an assumed thousand-seed weight of about 3.5 g (not sourced) |
| `transplant_dry_weight_g` (seed dry weight) | 0.0033 | [DES] Same assumption |
| `ready_fresh_weight_g` (per plant) | 0.086 | Derived: 2.5 kg/m² ÷ 29,000 |
| Sowing / harvest labour | 2 / 10 worker-hours per 1,000 m² | [DES] Trays are sown by machine and cut by hand. Microgreens are labour-heavy per m² |
| Day / night temperature | 18–22 / 16–18 °C | [GC16] grown at 21 / 17 °C |
| CO2 | 800–1,000 ppm | [DES] Same as lettuce; no microgreen-specific source |
| DLI | 12–17 mol m⁻² d⁻¹, photoperiod 16 h | [GC16] tested 6, 12 and 18; higher DLI gave shorter stems and more dry matter. [SHB22] 16 h at DLI 15.6 is the usual baseline |
| RH | 60–75 % | [DES] Dense trays are prone to damping-off at high humidity |
| Stress: stretch (low light) | DLI below 6, 0.03 per mol per day | [DES] Low light gives long, weak stems [GC16] |
| Stress: heat | Day mean above 24 °C, 0.02 per °C per day | [DES] |
| Stress: cold / frost | Below 6 °C, 0.05 per °C per day; batch lost below −1 °C | [DES] |
| `ready_loss_per_day` | 0.06 (grade A for 2.5 days, waste after about 7) | [DES] Past the first true leaf, stems toughen and yield-quality falls; harvest timing changes quality [ORT] |
| Unit, minimum sellable | Per kg, 1.2 kg/m² (0.04 g per plant) | [DES] Half the target yield |
| Grades | A ≥ 0.85 × 1.0; B ≥ 0.60 × 0.6; waste | [DES] Same as lettuce |
| Sale price | **EUR 30 per kg** | [DES] Within the range found: EU HoReCa blend EUR 36/kg [UFE]; Canadian bulk C$30/kg [OTG]; US restaurant wholesale USD 2.50–4.00/oz, about EUR 80–130/kg [MGM]; German retail about EUR 60/kg [OGR]. Set at the low end because a Dutch glasshouse sells into wholesale |

**Revenue check.** 2.5 kg/m² × EUR 30 = **EUR 75 per m² per 12-day cycle**, less about EUR 4/m² of seed. See the balance note below.

---

## 3. Radish microgreens (`radish_micro`)

New crop. Same production system as broccoli microgreens: faster, cheaper seed, a lower price.

### Cycle and supply

| Field | Value | Tag and note |
|---|---|---|
| `harvest_mode` | `single` | |
| `germination_days` (new field) | 2 | [DES] Radish germinates fast; blackout 2 to 3 days in grower practice [BSF] |
| `nominal_days` (sow to harvest) | **8** | Johnny's trial: 8 days average to the first true leaf for Red Arrow and Daikon, 9.5 for Hong Vit [JSS]. Seed suppliers give 6 to 10 [TLM]. Highest yield on day 10 [ORT]. Shortest realistic value |
| `min_days_before_end` | 8 | [DES] |
| Yield at harvest | **2.2 kg/m²** | [JSS] 10 oz (283 g) per tray for Red Arrow; 8 to 11.5 oz across three cultivars. Penn State measured 4.3 oz in a greenhouse [UHL], so the low end is about 0.9 kg/m² |
| `canopy_closure_m2_kg` and growth parameters | Lettuce's Van Henten values; retune `canopy_closure_m2_kg` only | [CAL] So the target climate gives 2.2 kg/m² on day 8 |
| `dry_matter_fraction` | 0.07 | [FPS23] 4.75 to 7.65 % at day 10; [PRC24] 8.5 to 8.8 % for daikon and red radish freeze-dried |
| Seed supply | Market item `seed:radish_micro` | Seed price etc. [DES]: suggested EUR 15/kg, 72 h lead time, minimum 5 kg |

### Planting, labour, climate, stress, market

| Field | Value | Tag |
|---|---|---|
| Sowing rate | 190 g seed per m² (24.5 g per tray) | [JSS] Red Arrow / Red Rambo rate; Daikon 22.5 g. Others sow 1 oz (28 g) per tray [TLM] |
| `density_per_m2` | 19,000 seeds | [DES] From the sowing rate and an assumed thousand-seed weight of about 10 g (not sourced) |
| `transplant_dry_weight_g` (seed dry weight) | 0.0095 | [DES] Same assumption |
| `ready_fresh_weight_g` (per plant) | 0.116 | Derived: 2.2 kg/m² ÷ 19,000 |
| Sowing / harvest labour | 2 / 10 worker-hours per 1,000 m² | [DES] As broccoli |
| Day / night temperature | 18–22 / 16–18 °C | [GC16] As broccoli |
| CO2 | 800–1,000 ppm | [DES] |
| DLI | 12–17 mol m⁻² d⁻¹, photoperiod 16 h | [SHB22] Radish among the four microgreens tested; continuous light at DLI 23.3 raised fresh and dry weight over 16 h at 15.6 |
| RH | 60–75 % | [DES] |
| Stress: stretch, heat, cold / frost | As broccoli | [DES] |
| `ready_loss_per_day` | 0.08 (grade A for under 2 days, waste after about 5) | [DES] Radish is the fastest and goes over fastest |
| Unit, minimum sellable | Per kg, 1.1 kg/m² (0.058 g per plant) | [DES] Half the target yield |
| Grades | A ≥ 0.85 × 1.0; B ≥ 0.60 × 0.6; waste | [DES] |
| Sale price | **EUR 22 per kg** | [DES] Radish is the cheapest common microgreen in every price list found [MGM][UFE]; set below broccoli |

**Revenue check.** 2.2 kg/m² × EUR 22 = **EUR 48 per m² per 8-day cycle**, less about EUR 3/m² of seed.

---

## Balance note (must be solved in the market file before a scenario uses microgreens)

Per m² per day, at these prices: lettuce about EUR 0.35, broccoli microgreens about EUR 5.9, radish microgreens about EUR 5.7 (revenue less seed, before labour and energy). Unchecked, the best strategy is "fill every square metre with microgreens", and lettuce becomes irrelevant. In reality the microgreen market is small: buyers are restaurants and retailers taking a few kilograms a day, so extra kilograms do not sell at the list price.

Recommended (market file, no crop change): a **daily demand cap per microgreen**, beyond which the price drops to a low surplus price. For example, 40 kg a day at the list price, then EUR 3/kg. With caps set so that microgreens fill roughly one compartment, the decision becomes how much area to give each crop and when to sow so harvests land on separate days, rather than a single dominant crop. The cap values are [DES] and must be tuned with the scripted policies before the first model run.

## Sources

| Tag | Source |
|---|---|
| [VH94] | Van Henten, E.J. (1994). *Greenhouse climate management: an optimal control approach*. PhD thesis, Wageningen University (with van Straten et al. 2010, and Boersma and van Mourik, edepot.wur.nl/693301) |
| [CEA] | Brechner, M. and Both, A.J. Cornell CEA *Hydroponic Lettuce Handbook* (DLI 17, about 24 days at DLI 17, 11 days propagation) |
| [RED] | Hydroponic butterhead harvest-stage study, redalyc.org/pdf/908/90842183011.pdf |
| [BKK] | [Beekenkamp Plants, leaf-vegetable and brassica young plants](https://www.beekenkamp.nl/plants/app/uploads/2023/11/Vollegrondsgewassen-2022-EN.pdf) |
| [TEA] | Teagasc, *Iceberg Lettuce* technical note (2020): propagation 2 to 3 weeks |
| [FP1] | [FreshPlaza, "Greenhouse lettuce demand and prices fluctuate"](https://www.freshplaza.com/europe/article/9427572/greenhouse-lettuce-demand-and-prices-fluctuate/) |
| [FP2] | [FreshPlaza, "Scandinavia and the Middle East in the market for Dutch greenhouse lettuce"](https://www.freshplaza.com/article/9063899/scandinavia-and-the-middle-east-in-the-market-for-dutch-greenhouse-lettuce/) |
| [JSS] | [Johnny's Selected Seeds, *Micro Greens Yield Trial* tech sheet (2017)](https://www.johnnyseeds.com/on/demandware.static/-/Library-Sites-JSSSharedLibrary/default/dw320cb0ff/assets/information/micro-greens-yield-trial-results-tech-sheet.pdf); [broccoli product page](https://www.johnnyseeds.com/vegetables/microgreens/microgreen-vegetables/broccoli-microgreen-seed-2290M.html); [Red Rambo radish page](https://www.johnnyseeds.com/vegetables/microgreens/microgreen-vegetables/radish-red-rambo-microgreen-seed-2539M.html) |
| [ORT] | Ortiz et al. (2024), *Technology in Horticulture*: broccoli best harvested on day 13, radish on day 10 ([PDF](https://maxapress.com/data/article/tihort/preview/pdf/tihort-0023-0031.pdf)) |
| [SUP] | [Superseeds, broccoli microgreens](https://www.superseeds.com/products/broccoli): 10 to 15 days |
| [TLM] | [True Leaf Market, Rambo radish microgreens](https://trueleafmarket.com/products/radish-rambo-seeds?variant=39483221192): 6 to 10 days, 1 oz per tray |
| [BSF] | [Bootstrap Farmer, microgreen cheat sheet](https://bootstrapfarmer.com/blogs/microgreens/the-ultimate-microgreen-cheat-sheet) and [top ten microgreens](https://www.bootstrapfarmer.com/blogs/microgreens/top-ten-microgreens): blackout times, broccoli 15–20 g per tray |
| [UHL] | [Urban Harvest Lab, yield per tray](https://urbanharvestlab.com/blog/microgreens/microgreens-tray-sizes-yield/), citing a Penn State greenhouse trial (radish 4.3 oz) |
| [JB19] | Jones-Baumgardt, C., Llewellyn, D., Ying, Q., Zheng, Y. (2019). Intensity of sole-source LEDs affects growth, yield and quality of Brassicaceae microgreens. *HortScience* 54(7): 1168–1174 ([link](https://journals.ashs.org/view/journals/hortsci/54/7/article-p1168.xml)) |
| [GC16] | Gerovac, J.R., Craver, J.K., Boldt, J.K., Lopez, R.G. (2016). Light intensity and quality from sole-source LEDs impact growth of Brassica microgreens. *HortScience* 51(5): 497–503 ([summary](https://ars.usda.gov/ARSUserFiles/50820500/GPRG/2016PublicationsandSummaries/2016_Light%20intensity%20and%20quality%20from%20sole%20source%20%20light%20emitting%20diodes.pdf)) |
| [SHB22] | Shibaeva et al. (2022). Continuous LED lighting enhances yield and nutritional value of four genotypes of Brassicaceae microgreens. *Plants* ([record](https://agris.fao.org/search/ru/records/65dfae854c5aef494fe444ac)) |
| [SR24] | Microgreen nutrient composition table, broccoli moisture 90.72 g/100 g FW ([PMC5362588, table 1](https://pmc.ncbi.nlm.nih.gov/articles/PMC5362588/table/T1)) |
| [FPS23] | [Frontiers in Plant Science (2023), 10.3389/fpls.2023.1236055](https://www.frontiersin.org/journals/plant-science/articles/10.3389/fpls.2023.1236055/full): radish dry matter 4.75–7.65 % |
| [PRC24] | [Stajčić et al., *Processes* 12: 1743](https://mdpi-res.com/d_attachment/processes/processes-12-01743/article_deploy/processes-12-01743.pdf): daikon and red radish dry matter 8.48 and 8.81 % |
| [MGM] | [Microgreen Manager, pricing guide](https://microgreenmanager.com/blog/microgreens-pricing-guide): radish and broccoli USD 2.50–4.00/oz wholesale |
| [UFE] | [Urban Farm Estonia, HoReCa price list](https://urbanfarm.ee/horeca/cut-plants-price): sunflower, radish and pea blend EUR 36/kg |
| [OTG] | [On The Grow, microgreens for restaurants](https://onthegrow.net/pages/best-microgreens-for-restaurants): bulk from C$30/kg |
| [OGR] | [Our Greenery, Raumgarten Pro](https://ourgreenery.com/en/products/raumgarten-pro-indoor-farm-gastronomie): about EUR 6 per 100 g in shops (a vendor figure) |

**Not found, so marked [DES]:** Dutch per-plug price for lettuce; EU wholesale prices for microgreen seed; thousand-seed weights; per-day quality loss after the harvest window; labour per m² for microgreens; microgreen demand caps.
