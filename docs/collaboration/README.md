# Collaboration board

Start here. Each person has one file in this folder with their tasks, the files they own, and a prompt to paste into their coding agent. Point your agent at **your file plus this README**, not at the whole repo.

| Person | File | Owns | First deliverable |
|---|---|---|---|
| Max | [max.md](max.md) | envkit changes, loader, `sim.py`, `env.py`, views, scenario, integration, merges, model runs | `advance(hours)` in envkit; loader |
| Lucas | [lucas.md](lucas.md) | Crops: schema, growth models, lettuce and basil data | Lettuce growing in a unit test |
| Emre | [emre.md](emre.md) | Facility: schema, weather, energy prices, climate, controller, energy centre | One compartment heating in a unit test |
| Rowan | [rowan.md](rowan.md) | Operations: market and event schema, orders, staff, events, ledger, outcome, scripted policies | CO2 order arriving after its lead time |

Spec: [GREENHOUSE_SPEC.md](../GREENHOUSE_SPEC.md). Background: [GREENHOUSE_BENCH_CONTEXT.md](../GREENHOUSE_BENCH_CONTEXT.md).

> **Round 3 is built** on branch `max/no-finish-episode` (14 Nov 2026), with a change from spec 14.1 as first written: the agent plays a **daily turn**, one decision point at 06:00 with at most 5 actions and no read tools. It sees the rules and each morning's briefing instead. See DECISIONS, "Round 3 built". **Rowan:** your business files (`config/market.py`, `world/{business,events,operations}.py`, `outcome.py`, new `world/contractors.py` and `world/news.py`, `data/{markets,events,news}/`, your tests) were edited by a subagent for storms, contractors, parts and news; please review. **Lucas:** lettuce plug lead time (336-504 h) is set in the market file. Benchmark checks on the new rules are not run yet.

> **Round 3 is on.** Read [context section 0](../GREENHOUSE_BENCH_CONTEXT.md) (pinned decisions: day shift, night schedule, persistent damage, contractors and parts, news, Netherlands) and [spec section 14](../GREENHOUSE_SPEC.md) (interfaces and who builds what). Then your file's "Next steps (round 3)". This round is split across Max, Rowan and Lucas: Emre's facility files are with Max, and his weather files with Lucas, until he is back. Max's contracts PR comes first; build your data and schemas meanwhile.

## Already on `main` (use it, don't rewrite it)

- `src/greenhouse/contracts.py`: every type that crosses between two people's modules (`ClimateSample`, `BatchState`, `GrowthModel`, `HarvestResult`, `LedgerEntry`, `Metered`, `EquipmentEffect`, `Alarm`).
- `src/greenhouse/config/base.py`: `Table` (strict TOML reader: missing, stray and out-of-range keys fail with file and key), `Range` (hidden per-seed parameter), `resolve`, `ranges`, `ConfigError`.
- `src/greenhouse/config/curves.py`: `parse_curve` and the curve kinds `cardinal`, `saturating`, `linear_above`, `linear_below`, `piecewise`.
- `src/greenhouse/config/loader.py`: reads a scenario's data files, applies overrides, calls each owner's `parse_*` and draws hidden parameters per seed.
- `src/greenhouse/world/sim.py`, `views.py`, `env.py`: the simulator and every tool of spec 5, wired against `FacilityModel`, `BusinessModel` and `GrowthModel` in `contracts.py`.
- `tests/greenhouse/fakes.py` + `tests/greenhouse/fixtures/fake-winter.toml`: toy versions of all three subsystems, so the whole game runs end to end today. **Use them to test your module in context, and copy their shape (not their numbers).** Swap a fake for your real module by having `world/modules.py:build` find it. That needs no change to sim or env.
- `envkit`: engine, MCP server, verifier, Harbor build, audit. New: `close_windows(n)` for multi-hour advances and `data_files()` for bundling data.
- Rowan's operations, events, ledger and outcome (PR #12), wired into the simulator by `world/business.py:build_business` (tests: `tests/greenhouse/test_business.py`).
- **Smoke checks** (docs/MODAL.md, "Smoke checks"). Before every push: `uv run --no-sync python -m compileall -q src tests && uv run --no-sync python -m pytest tests -q && uv run --no-sync envkit check` (about 30 s). Before merging a change to tools or the game: one real model on `scenarios/smoke.toml` on Modal (about 3 min). Gemini Flash-Lite and Claude Haiku both play it.
- **Bankruptcy:** cash below EUR 0 ends the episode. **Overrides** can address an array item by id (`facility.compartments.A.start_batches`).
- **Decided (spec 11):** D2 the agent allocates scarce heat and CO2 (priority + exact caps); D3 weather and prices are researched historical series in data files, identical for every agent on a seed; D5 doing nothing keeps the handover baseline forever, and stopping equals doing nothing. Each person's file has a "Next steps (round 2)" section.

## Rules that keep us out of each other's way

1. **Your own worktree and branch.** Never work in someone else's checkout.
   ```bash
   git fetch origin
   git worktree add ../junction-<name> -b <name>/<topic> origin/main
   cd ../junction-<name>
   uv sync --locked --extra eval --extra mcp --extra harbor
   ```
2. **Only edit files you own** (your file lists them). Need a change elsewhere? Ask the owner in the team chat, or open an issue. Don't edit their file.
3. **`contracts.py` is shared.** To change it, open a PR that touches only that file and tag everyone. Merge it before any code that depends on it. Adding an optional field with a default is fine at any time; renaming or removing a field needs everyone's OK.
4. **No values in code.** Every number lives in a data file under `data/` and is read through `Table`. A constant in Python is a review blocker. Physical constants (the specific heat of air, Stefan–Boltzmann) are the only exception, and they need a comment with their source.
5. **Determinism.** Randomness only from `envkit.rng.Rng` streams you are given; noisy readings use a stream named after what they read (see the `contracts.py` docstring). No `random`, `time`, `datetime.now`, or iteration over sets.
6. **Small PRs to `main`, at least every 2 hours.** Merge only when CI is green and one other person has looked at the diff. Max integrates. Never push straight to `main`.
7. **Tests next to your code**, in `tests/greenhouse/test_<your area>*.py`, written with `unittest` (they also run under pytest). Run `uv run --no-sync python -m pytest tests -q` before every push.
8. **Decisions go in [DECISIONS.md](../DECISIONS.md)**, one bullet each, with the date. Handoffs go in the PR description: the current state, the command you ran and its result, and the remaining risk.

## Timeline (about 10 hours)

| Phase | Hours | Max | Lucas | Emre | Rowan |
|---|---|---|---|---|---|
| 1. Pieces | 0–3 | envkit advance + bundle; loader; sim skeleton with stubs | Crop schema; lettuce model + data | Facility schema; weather + prices; one compartment's climate | Market/event schema; ledger; orders + staff |
| 2. Wire | 3–5 | `sim.py` + `env.py` with real modules; scenario file | Basil (repeated cuts); estimates; stress | Controller; energy centre + allocation | Events; outcome; naive + rule-based policies |
| 3. Calibrate | 5–7 | Reference planner (with Rowan); `envkit build`; audit | Tune growth to published behaviour | Sanity + conservation tests; tune heat demand | Exploiter; audit fixes |
| 4. Gap | 7–10 | Model comparison (spec 12); fixes; README; demo | Failure-mode signals from crops | Failure-mode signals from energy | Failure-mode report; exploit hunt |

## Status (update your row when you push)

| Person | Branch | Last PR | State |
|---|---|---|---|
| Max | `max/smoke-scenario` | Smoke scenario; first model runs on the real game; fixes (`9790f32`) | Gemini and Claude play the 1-day smoke task on Modal. Edited Rowan's `ledger.py` and `rule_based.py` (crash fixes; see rowan.md). Next: contracts PR, shift clock, facility dispatch, scenario |
| Lucas | `lucas/crops` | Crop schema, `leafy_vanhenten`, lettuce, basil (tasks 1–8); round 2 | Round 2 done and merged: four planning methods, grades, in-game test, D5 and D8 research. Next: spec 3.1 without `seedling_cost_eur` (Max) |
| Lucas | `lucas/judge-ready` | Integration: scenario, reference planner, registered ladder, Harbor tasks, three fixes (negative prices, plant rounding, hidden event values) | Judge path works on the rules on `main` (not round 3): reference 0.80, rule-based 0.26, naive 0.12, nobody 0 on seeds 1–3; audit passes on seeds 1–3. Touches Max's and Rowan's files: see DECISIONS "Integration". Next: model runs |
| Max | `max/locked-crops` | Locked crops (broccoli and radish files, lettuce at 21 days, basil deleted); main scenario on three compartments, two broccoli and one radish; reference and rule-based fixes for short by-weight cycles | Quick check passed on the crops commit; the scenario commit is not tested yet (smoke task builds). Edited Lucas's crop files and tests, Rowan's market file, tests and policies: see lucas.md, rowan.md. Next: Rowan runs the quick check, a model smoke run, then the benchmark |
| Emre | `emre/facility-climate-energy` | Schemas, weather, climate, controller, energy centre | Merged (#13; recorded data in #15). Round 3: away; files held by Max and Lucas |
| Rowan | `rowan/round-2` | Round 2: business fixes, CO2 cleanup, policies, D5 values | Policies on fakes done; ranking and exploiter bound wait for real crops and facility |
