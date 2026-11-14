# Where Gemini 3.1 Flash-Lite lost €1.24M against the reference (normal-winter, seed 1)

**Run:** `artifacts/r3-nw-gemini-2010` (google/gemini-3.1-flash-lite, OpenCode 1.19.5 on Modal, task bundle
`4af2179867124baa`, 2026-11-14 19:05–19:10 UTC). Reward 0.002, profit −€19,771, 42 `submit_day` calls,
0 rejected calls, end reason `horizon`. The replay matches every recorded response (`replay_verified`).

**Compared with:** the `reference`, `rule-based` and `naive` policies, replayed on the same scenario and seed
through the real tools. The policy profits match the run's bundled calibration exactly.

**Evidence used:** the envkit trace (actions and the error text the tools returned), the hourly replay frames,
and `agent/trajectory.json`. The trajectory does store reasoning: 16 of the 43 agent steps carry a
`reasoning_content` summary, up to day 15. Quotes below come from those summaries. After day 15 no reasoning
was recorded. Nothing is inferred about turns that have none.

## Summary

| Run | Profit (€) | Harvest revenue (€) | Harvests | Planted m² | Orders placed | Failed actions | Lamp energy |
|---|---:|---:|---:|---:|---:|---:|---:|
| reference | 1,221,345 | 1,342,370 | 35 | 14,349 | 18 | 0 of 140 | 454 MWh |
| **gemini-3.1-flash-lite** | **−19,771** | **24,253** | 6 (5 worth €0) | **0** | 1 (CO2) | **13 of 28** | **0** |
| naive | −27,311 | 0 | 8 | 0 | 1 | 0 of 9 | 0 |
| rule-based | −50,080 | 0 | 7 | 2,141 | 12 | 8 of 121 | 0 |

Of the €1,241,117 gap, harvest revenue accounts for −€1,318,117. Every other ledger line together moves it
by less than €80k. Gemini spent less than the reference on seedlings (−€49.6k), electricity (−€26.5k),
gas, contractors and parts. Wages cost it €12.3k more.

**When it diverged.** On day 1 Gemini was €24.8k ahead: it harvested batch B5 a day before the reference.
From day 2 it was behind by more than €5,000 and never came back (`first_diverged_day` = `settled_diverged_day` = 2).
The real point of no return was days 0–8. By day 8 every standing batch had degraded to quality < 0.1,
so nothing it harvested afterwards could be sold. It had also planted nothing to replace them.

## What went wrong, largest cost first

### 1. The lamps were never switched on, so the crop degraded to waste (most of the gap)

The facility starts with "lamps off" (the instructions say so, and the briefing shows `lamp_intensity_pct: 0`).
The crop rules publish a light target of 12–17 mol/m²/day. Below 6 mol a "stretch" stress costs 0.03 quality
per day for each mol missing. Grades A and B need quality ≥ 0.85 and ≥ 0.60; below that, the crop is waste at
€0 (`data/crops/broccoli_micro.toml`).

Gemini's only climate action (day 0) set heating 20/17 °C and CO2 900 ppm. It never set lamp hours or an
intensity, and none of its recorded reasoning mentions lamps or light. Compartment A, every other day:

| Day | Gemini light (mol/m²) | Gemini mean °C | Gemini batch quality (A1, A2, A3) | Reference light | Reference mean °C |
|---:|---:|---:|---|---:|---:|
| 0 | 2.1 | 14.7 | 1.00, 0.97, 0.97 | 21.9 | 16.5 |
| 2 | 1.7 | 16.2 | 0.68, 0.76, 0.73 | 28.4 | 19.6 |
| 4 | 0.7 | 15.5 | 0.51, 0.48, 0.42 | 27.5 | 18.7 |
| 6 | 4.8 | 15.1 | 0.17, 0.16, 0.13 | 31.5 | 18.3 |
| 8 | 7.1 | 15.0 | 0.06, 0.07, 0.00 | 33.9 | 18.0 |

The reference runs the lamps 24 h at 100 % from day 0. The lamps also heat the compartments: the reference
held 18–20 °C while requesting less heat, while Gemini never reached its own 20 °C setpoint.

The result: Gemini's only paid harvest was B5 on day 1 (quality 0.95, €24,253). Its other five harvests
(C9 on day 13, A1 on day 17, B6 on day 21, C10 on day 26, C11 on day 33) were 800–1,000 kg each and sold for
€0.00. Rule-based and naive also leave the lamps dark on this seed, and they too sold nothing (see "Flags").
That is independent evidence that the missing light alone removes almost all harvest revenue, even for a
player whose orders and planting work.

### 2. No seed was ever ordered, so nothing was replanted (0 m² against 14,349 m²)

The reference orders seedlings on day 0 and replants from day 4 onward. Gemini started with no seedlings in
stock, and its seedling and parts orders failed on 10 days between day 1 and day 12. Every one of those failures
has the same cause: the item key was cut at the colon.

| Days | Sent | Error text from the tool |
|---|---|---|
| 1 | `{"seedlings": 150000}` | `seedlings: unknown item 'seedlings'; items are ['co2_kg', 'seedlings:lettuce_butterhead', 'seedlings:broccoli_micro', 'seedlings:radish_micro', 'part:glass_pane', 'part:boiler_kit']. Nothing was ordered.` |
| 2, 3, 5, 6, 7 | `{"seedlings": 150000, "part": 19}` | the same, once for each key |
| 4, 10, 11 | `{"part": 19}` | `part: unknown item 'part'; items are [...]` |
| 12 | `{"glass_pane": 19}` | `glass_pane: unknown item 'glass_pane'; items are [...]` |
| 9, 15 | `{}` | `give at least one item` |
| 8 | `{"co2_kg": 2000}` | accepted (the only order placed) |

That accounts for 12 of the 13 failed actions. The 13th was a second harvest of C10 on day 30 (`batch C10 is harvested`).

From day 3 the reasoning names the right keys repeatedly, for example (step 7, day 5): *"The key should
have been `"part:glass_pane"` … `place_orders(orders={"part:glass_pane": 19, "seedlings:broccoli_micro": 150000})`.
I'm going to run this now."* The emitted call, in that turn and in every other, was `{"seedlings": 150000, "part": 19}`.
OpenCode's raw log (`agent/opencode.txt`) shows the same truncated arguments, so envkit received what the
harness was given.

**Not yet attributable.** Every key containing a colon arrived truncated: on all 10 order attempts, keeping
the prefix 9 times and the suffix once. Meanwhile the reasoning text in the same steps spells the full key,
and the only key without a colon (`co2_kg`) went through. That pattern fits a schema or transport problem as
well as a model error. `orders` is declared as `dict[str, float]`, which becomes a free-form
`additionalProperties` object, and Gemini's function-calling schema supports that poorly. No earlier artifact
shows a Gemini model sending a colon key successfully, because older runs used a different order format.
**Until one direct probe settles it**, for example one Gemini function call with a `{"part:glass_pane": 1}`
argument through the same OpenCode setup, do not count these 11 failures as agent failures in any benchmark
claim (AGENTS.md: infrastructure failures are not agent failures). Changing the order format (for example a
list of `{item, quantity}`) would remove the question, but that is a tool change, to be agreed first.

Even if the orders had gone through, the replanted crop would have had the same light problem as in section 1.

### 3. Ready batches were left standing while each turn went to one failed order

Gemini used 5 action slots on day 0, then 1 or 2 a day. From day 3 to day 12 every turn was a single
`place_orders` attempt. Batch C9 (radish, grade A for under 2 days) was estimated ready on day 1.8 at quality
0.86, and Gemini harvested it on day 13, worth €0. The reference harvested its C9 on day 2 for €24,418.
Because of section 1 this cost less than it seems, but the order loop did displace the rest of the turn.

### 4. Repairs were booked but could never happen (small effect on profit)

On day 2 Gemini booked a glazier for A, B and C. Each booking answered `"status": "waiting_for_parts",
"parts_needed": {"part:glass_pane": 8}` (9 and 2 for B and C), naming the exact key the orders later missed.
The panes never arrived, so no visit was ever made (`fm_contractor_visits` 0). Broken panes went from 19 (day 1)
to 65 (day 36). The boiler tripped on day 22. A heating installer was booked the same day, but the job also
waited for parts (`part:boiler_kit`), so the boiler stayed off for the remaining 19 days. The reference also
had glass broken for long stretches during the storm surges, at 19 panes until day 20. Its repairs cost
€4.9k in contractors and parts. Damage is therefore a real but small part of the gap.

### 5. Staff, energy and effort

- **Staff:** Gemini hired 2 workers on day 0 (crew 5 from day 3) and had almost no work for them. The reference
  stays at 3 until day 35. Gemini's wages were €35,816 against €23,496.
- **Energy:** Gemini ran the CHP at 0.5 all episode and sold €5.8k of electricity. The reference bought €26.5k
  for its lamps. Gemini's lower energy bill is the reason it lost "only" €19.8k.
- **Effort:** Gemini made one climate setting and one energy setting in 42 days, while the reference adjusted
  its lamps and night schedule 76 times. 22 of Gemini's 42 turns were empty (most days from 14 on), and it used
  42 of its 400 calls. It did not stop early: it played every day.

## Flags (not fixed here)

- **Committed `calibration.json` is stale.** For normal-winter seed 1 it holds zero −€42,496, scale €1,740,359,
  reference €1,349,791 and rule-based €525,826. The run's bundled calibration holds zero −€22,806, scale
  €1,555,189, reference €1,221,345 and rule-based −€50,080. The pixel site reads the committed file, so its
  baseline profit and its recomputed policy scores are wrong for normal-winter: the reference shows 0.726, not
  about 0.8. It was last regenerated before `1d0db76` (the `submit_day` change).
- **The rule-based policy never lights the lamps.** It sets `lamp_hours` but never `lamp_intensity_pct`, and
  the facility default is 0 % (`data/facilities/nl_three_compartment.toml`). So its "lamps in cheap hours" rule
  does nothing. On this seed it loses €50k, below do-nothing, which makes it a weak anchor.
- **Gemini 4 Carbon** (`artifacts/r3-nw-carbon-2027`): at the time of writing the run has started but has no
  trial output yet. Compare it with the same command once it finishes.

## Reproduce

```bash
uv run --no-sync python scripts/pixel/analytics.py compare \
  --trace "gemini-3.1-flash-lite=artifacts/r3-nw-gemini-2010/trials/s1-agent/normal-winter-s1__RdBsSuW/artifacts/var/lib/envkit/trace.jsonl" \
  --out-json artifacts/compare/nw-s1-gemini.json --out-md artifacts/compare/nw-s1-gemini.md
```

The command replays the trace and plays the three policies over the full 42 days, which is a benchmark-length
run (about 10 s in all). The Markdown file has the full 42-day table. Add one more `--trace label=path` for the
Carbon run. Code at `0078e6c` plus the `compare_runs` addition to `scripts/pixel/analytics.py`.
