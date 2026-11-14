# Max: backend, integration and evaluation

You own the glue: the envkit changes, the loader, the simulator that composes everyone's modules, the MCP tools, the scenario, merging, and the model runs. You also keep the shared files (`contracts.py`, `config/base.py`, `config/curves.py`, `docs/collaboration/README.md`). Read [README.md](README.md) first, then spec sections 2, 4, 5, 6, 12 and 13.

## Files you own

| File | What |
|---|---|
| `src/envkit/core.py`, `src/envkit/bundle.py`, `src/envkit/scenario.py` | Multi-hour advance; data files in the bundle (spec 2.1) |
| `src/greenhouse/contracts.py`, `config/base.py`, `config/curves.py` | Shared; already on `main` |
| `src/greenhouse/config/loader.py` | Scenario `[env]` to resolved specs: reads each file through its owner's `parse_*`, applies `overrides`, draws hidden parameters per seed with `resolve` |
| `src/greenhouse/world/sim.py` | `Greenhouse`: composes crop, facility, operations, events and ledger; runs hours and sub-steps in the order of spec 4.2; applies actions; raises `RuleError` before mutating |
| `src/greenhouse/views.py`, `src/greenhouse/env.py` | What the agent sees; the tools of spec 5 |
| `src/greenhouse/policies/reference.py` | The reference planner (with Rowan) |
| `scenarios/normal-winter.toml`, `tasks/`, `calibration.json` | Scenario and generated output |
| `scripts/`, `.github/`, `README.md`, `AGENTS.md` | Tooling and top-level docs |

## Tasks, in order

1. **Merge this branch** (`docs/greenhouse-bench-spec`) once CI is green, so everyone starts from the same `main`. Send everyone their file.
2. **envkit: `advance(hours)`.** A tool asks the engine to close up to n windows, and `interrupt()` can stop it early. One operation, one trace record. Tests: `advance(5)` equals five `advance(1)` calls with no alarm; replay is identical; the call limit still works. Run the depot and strict fixture tests to make sure nothing else changed.
3. **envkit: data files in the bundle.** Data files the scenario references are copied into the bundle and covered by the hash. Test: editing a crop file makes `envkit check` report stale tasks.
4. **Loader.** `load(env_config, seed) -> Config`, calling `parse_crop` (Lucas), `parse_facility`/`parse_climate`/`parse_energy_prices` (Emre) and `parse_market`/`parse_event` (Rowan). Until theirs land, use stubs that return fixed test specs.
5. **`sim.py` skeleton with stubs**, then `env.py` with every tool from spec 5 returning stub data. That unblocks Rowan's policies. Swap in real modules as their PRs merge.
6. **Scenario `normal-winter.toml`.** 42 days, `window_hours = 1`, `max_calls = 400`, `agent_timeout_sec = 10800`, anchored scoring on `profit_eur` (target 0.8), dev seeds 1–3 committed. Then `envkit build`, `envkit audit`, and `bash scripts/judge.sh --smoke` on Docker.
7. **Reference planner** with Rowan, then calibrate. Check the ladder order: do-nothing < naive < rule-based < reference.
8. **First model comparison** (spec 12): Gemini Flash vs Gemini Pro/Hydrogen, 3 runs each, seed 1, on Modal; confirm on Docker. Record it in `DECISIONS.md` with SHA, command, models and results.
9. **Entire:** enable capture for Claude Code too, so these sessions are recorded (see below).

## Integration duty

- Review and merge everyone's PRs in dependency order. CI must be green; read the diff for hardcoded values and edits outside the owner's files.
- After merging anything under `src/` or `data/`, run `uv run --no-sync envkit build` and commit `tasks/` and `calibration.json` once the scenario exists.
- Keep the status table in `README.md` current.

## Entire

Entire currently records Codex sessions only (`entire status`: "Agents · Codex"; 7 Codex hooks waiting for approval). Claude Code sessions, including the one that wrote this spec, are not captured. To add Claude Code locally: `entire enable -y --agent claude-code --local --skip-push-sessions --telemetry=false --import-history`, then `entire status`. `--import-history` brings in the last 30 days of sessions, including the one that wrote this spec. Keep `push_sessions: false`: this repository is public (docs/ENTIRE.md). Brain is not installed (`entire plugin install brain`). Until it is, `DECISIONS.md` and the PR descriptions are the shared memory.

## Prompt for your coding agent

> Read `AGENTS.md`, `docs/collaboration/README.md`, `docs/collaboration/max.md`, `docs/GREENHOUSE_SPEC.md` and `docs/BACKEND.md`. I own the files listed in max.md. Do the tasks in max.md in order, test first. envkit changes must keep every existing test in `tests/envkit` passing and keep replay exact. In `sim.py`, use stubs for modules owned by Lucas, Emre and Rowan until their PRs land, and don't edit their files. Run `uv run --no-sync python -m pytest tests -q` before saying a task is done.
