# Collaboration board

Start here. Each person has one file in this folder with their tasks, the files they own, and a prompt to paste into their coding agent. Point your agent at **your file plus this README**, not at the whole repo.

| Person | File | Owns | First deliverable |
|---|---|---|---|
| Max | [max.md](max.md) | envkit changes, loader, `sim.py`, `env.py`, views, scenario, integration, merges, model runs | `advance(hours)` in envkit; loader |
| Lucas | [lucas.md](lucas.md) | Crops: schema, growth models, lettuce and basil data | Lettuce growing in a unit test |
| Emre | [emre.md](emre.md) | Facility: schema, weather, energy prices, climate, controller, energy centre | One compartment heating in a unit test |
| Rowan | [rowan.md](rowan.md) | Operations: market and event schema, orders, staff, events, ledger, outcome, scripted policies | CO2 order arriving after its lead time |

Spec: [GREENHOUSE_SPEC.md](../GREENHOUSE_SPEC.md). Background: [GREENHOUSE_BENCH_CONTEXT.md](../GREENHOUSE_BENCH_CONTEXT.md).

## Already on `main` (use it, don't rewrite it)

- `src/greenhouse/contracts.py`: every type that crosses between two people's modules (`ClimateSample`, `BatchState`, `GrowthModel`, `HarvestResult`, `LedgerEntry`, `Metered`, `EquipmentEffect`, `Alarm`).
- `src/greenhouse/config/base.py`: `Table` (strict TOML reader: missing, stray and out-of-range keys fail with file and key), `Range` (hidden per-seed parameter), `resolve`, `ranges`, `ConfigError`.
- `src/greenhouse/config/curves.py`: `parse_curve` and the curve kinds `cardinal`, `saturating`, `linear_above`, `linear_below`, `piecewise`.
- `envkit`, unchanged: engine, MCP server, verifier, Harbor build, audit.

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
| Max | | | |
| Lucas | | | |
| Emre | | | |
| Rowan | `rowan/operations` | Operations, events, ledger, outcome | Tasks 1–6 done with tests; policies wait for `env.py` tool stubs |
