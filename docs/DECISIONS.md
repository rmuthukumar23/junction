# Decisions and handoffs

Record changes here with date, decision, reason, and affected interface. Keep entries short enough that an incoming teammate or agent can read them in minutes.

## Initial decisions · 2026-11-14

- `rmuthukumar23/junction` is the single code source of truth. No second writable mirror or custom master-node scheduler.
- Python 3.11+ with a dependency-free deterministic core. Cloud services stay behind adapters; the judge path must run from a fresh clone.
- `contracts.py` is the local seam between environment, evaluation, and MCP adapter. Freeze its semantics before parallel implementation; adjust it when the official AfterQuery starter kit reveals requirements.
- GitHub issues/PRs/CI handle integration. Entire adds session memory, graph search, and review context if it works with the repo; it does not replace Git history.
- Modal is the planned parallel evaluation/sandbox and public demo surface. Verda is reserved for a genuine compute-heavy training/rollout experiment, conditional on a working benchmark. Sponsor claims require measured evidence.

## Shift Planner implementation · 2026-11-14

- User-approved contract: eight jobs, two technicians, one lathe/bench, visible DAG/deadlines/values; 64 mutating actions and fixed completion-value denominator. See SCENARIO.md.
- Core is standard library. Evaluation defaults to Python 3.12. CP-SAT solves public data with fixed settings; it never reads the construction witness.
- Deep-copy runner boundaries; interruption preserves completed score. Infrastructure errors have no agent score.
- Harbor 0.26.0 has trusted sidecar artifact collection and separate verification. Use these native facilities, not agent-written score files or a custom Modal scheduler.
- CPU-only Modal is optional after Docker smoke; three concurrent frontier attempts and no automatic provider retries. Verda/Entire deferred.
- Locked packages and generated hashed agent-image requirements committed. Static image digest; OpenCode version explicit.
- Reference feasibility uses seeds 0–99. Development calibration 0–4; 100–102 remain reserved until freeze. No frontier gap has been measured.

## Backend merge · 2026-11-14

- `src/envkit` is the single evaluation backend. It replaces `src/junction_env/adapters/` (HTTP service, stdio MCP bridge, task builder, judge, results). Reason: one implementation per concern, and one path to audit. Affected interface: transport and result envelope below; rules and scoring of Shift Planner are unchanged.
- `contracts.py`, the scheduling core, the local runner and `evaluation.py` are unchanged. `scheduling/envkit_binding.py` is the only place Shift Planner meets the backend. Every request, valid or not, still goes through `ShiftPlanner.step`, so action accounting and termination follow SCENARIO.md.
- Transport: the agent connects by streamable HTTP to an MCP server inside the sidecar. The agent container no longer holds a bridge or `instance.json`; `observe` returns the instance.
- Evidence for grading: the sidecar's append-only `trace.jsonl`, collected as a Harbor artifact. The verifier replays it and repeats the independent interval check. A missing or ungradeable trace writes no reward (infrastructure failure), as before. No collect hook is needed, because the verifier finalizes the episode itself.
- Tool results are wrapped as `{ok, result | error, header}`. `result` is the observation defined in SCENARIO.md.
- Harbor tasks are generated from `scenarios/*.toml` and committed under `tasks/`, with `calibration.json`. `scripts/check.sh` fails in the locked environment when they are stale. `scripts/judge.sh` builds fresh tasks per seed and requires each scripted run to reproduce its calibrated score.
- Kept from the previous adapter: image digests, hashed image requirements, explicit OpenCode version, no automatic retries, failure categories (completed / interrupted / infrastructure failure), rate limits reported separately.
- Dropped: `judge.sh --jobs` (use a scenario file per job count) and the `shift-planner-mcp` script.
- Podman is accepted as a local backend next to Docker.
- `src/envs/depot` and `scenarios/depot-basic.toml` stay as the worked example for windows, scripted events and calibrated composite scoring. They are not part of the submission.

## Root Cause greenhouse benchmark · 2026-11-14

- Root Cause is a second environment on `envkit`, in its own top-level package `src/rootcause`. `envkit` itself is unchanged, so the Shift Planner and Depot tasks and their bundle hashes are unchanged. Model, rules and scoring: [GREENHOUSE](GREENHOUSE.md).
- One window is one day. `advance_day` costs the day's single operation and every other tool costs 0, so reads never move time. `builtin_tools = ()`: `advance_day` replaces `end_window`.
- A plan lasts one day; a day with no submitted plan runs the default plan. That makes "do nothing" and "stop early" the same documented thing: the default plan for the remaining days. `finish_episode`, a closed browser and a dead agent all end on day 13 with the same result (`test_every_way_of_stopping_early_gives_the_same_final_day_result`).
- Reward is `clamp((profit - floor) / (ceiling - floor))` computed inside the engine, as a `mean` component on the ledger value `normalized_profit`, not as an `anchored` component. Reason: the bounds are properties of the instance (default-plan profit; a proven upper bound) rather than of any scripted policy's score.
- The browser app is a standard-library HTTP server with a no-build static frontend in `src/rootcause_app`, outside the bundle. It keeps one `envkit` episode per run and writes the same trace as the sidecar; results are recomputed by replay. Reason: one engine and one scoring path, and a judge can start it with plain Python.
- No result is projected for an unfinished browser run. An earlier draft showed "profit if abandoned now"; that reads hidden state and future weather and would let a player price a plan before committing to it. A test now forbids it.
- Seeds: 7 is the committed task and the demo. Seeds 1-12 were looked at while tuning the mechanics (1-6 are reported as the development suite). Seeds 101-108 are the evaluation suite and were first run after the mechanics were fixed.
- `scripts/judge.sh` takes `ENVKIT_SCENARIO` (default `shift-planner`), so the same wrapper runs either scenario.
- Not done, by decision: no second (non-Harbor) model runner was written. The only model path is Harbor with OpenCode, as the challenge requires, and no credential was available to test another one.

## Windows and OpenCode findings (2026-11-14)

- Generated task files are always written with LF (`_write` in `src/envkit/harbor.py`),
  and `.gitattributes` forces LF for scripts, Dockerfiles, compose files and `tasks/`.
  Why: CRLF makes `#!/bin/bash` fail in the Linux container with
  `cannot execute: required file not found`, which looked like an agent/infrastructure failure.
- OpenCode's Google provider reads only `GOOGLE_GENERATIVE_AI_API_KEY`. `envkit eval` now
  forwards the host variable (`GEMINI_API_KEY` by default for `google/` and `gemini/` models)
  with `--ae GOOGLE_GENERATIVE_AI_API_KEY=${GEMINI_API_KEY}`, a template Harbor expands, so
  the key value never appears on a command line. `--credential-env` selects a different host variable.
- Modal does not need local Docker or Podman; only the Docker/Podman backends do.
- Provider-side errors (for example a retired model) are not agent scores; exclude them.

## Lettuce incident-response redesign · 2026-11-14 (branch feat/lettuce-greenhouse)

- **One environment.** Shift Planner is removed: it was fully observable and a deadline-first heuristic matched its solver, so there was no gap to show. Depot stays only as a backend test fixture (`tests/envkit/fixtures/`), next to a new strict-contract fixture (`src/envs/strict.py`). Integrity tests now run on the committed greenhouse task.
- **Scope: a single incident.** There are 3 NFT lettuce benches over 6 days. On day 1 the mains moves to a brackish backup source, announced by a vague notice. The day-0 bench composition is published, so the only unknown is the incident. This replaces the 14-day tomato version, whose known weakness was that one test made the state exactly trackable.
- **Why NFT.** A small recirculating tank shows a change in the source water within days; a deep-water raft pond would buffer it away.
- **The remedy has a price.** The clean reserve costs 4× mains (€0.04/L), so a planner that ignores the notice has no reason to use it. A free reserve made the blind planner match the reference (measured, then changed).
- **Reward = clamp((profit − default) / (informed − default)).** `informed` is the same planner told the backup salinity at the notice. Reasons: 1.0 is explainable ("knew the root cause at once"), the bound is instance-only and computed in the verifier, and the reference's gap to 1.0 measures the cost of diagnosing. The proven upper bound is still reported as `profit_upper_bound_eur`.
- **Outcome-only reward; diagnosis is evidence.** Failure modes (`fm_*` in the ledger) are computed from hidden state after the run and never rewarded, so testing or explaining cannot be gamed.
- **Runtime.** The design keeps runs far from the limits. Safety nets: `[shift] max_calls` (now 60) (a new optional envkit feature; reaching it equals stopping), agent timeout 420 s, verifier timeout 120 s.
- **Audit change.** A cut-short reference may tie the full reference only if every omitted call is listed in `[audit] clock_tools` (`advance_day`), because that day runs the already-submitted plan anyway.
- **Credentials.** `scripts/judge.sh` loads `GEMINI_API_KEY` and `AFTERQUERY_MODEL` from a gitignored `.env` (template `.env.example`).
- **One call per day (after merging main's Hydrogen runs).** Gemini took about 18 s per call and 15–26 min per 14-day season on the tomato version. `advance_day` now takes the day's plan inline, so a season is about 10 calls and 3–4 minutes. A rejected inline plan raises `ToolError(spend=False)`, a new envkit option that refunds the operation, so the day does not move. `max_calls` was lowered to 60.
- **Fast feedback.** `scripts/quick.sh` runs one model attempt (`envkit eval --agent-only`) and writes `analysis.md`. The scripted comparators' scores are already fixed in `calibration.json`. It creates `.env` from the template on first use; the default model is `google/gemini-4-hydrogen`.
- **Pass line 0.5** in the analysis: the run recovered half the value of knowing the root cause at once. It is explanatory only; the reward is unchanged.
- **Not done, by decision.** The browser app (`src/rootcause_app`) is not ported yet, and its tests are removed until the UI is reworked for the demo.

## Remaining event decisions

- AfterQuery starter-kit/scoring-skeleton version and any differences from candidate Harbor task.
- Approved frontier model identifier and credentials mapping.
- Scenario freeze after the first official development pilot.

## Greenhouse Bench replaces Root Cause · 2026-11-14

- The submission becomes Greenhouse Bench ([context](GREENHOUSE_BENCH_CONTEXT.md), [spec](GREENHOUSE_SPEC.md)): a 42-day winter facility with a shared energy centre and several compartments, scored on net profit, calibrated against a planning reference.
- Root Cause is removed in place: `src/rootcause`, `src/rootcause_app`, its tests, scenario, generated task, `docs/GREENHOUSE.md`, `docs/EXPERIMENTS.md`, `docs/root-cause-evidence.json`, and the scripts that only served it (`compare.py`, `analyze.py`, `browser_smoke.py`, `check_frontend.sh`, `play.sh`, `test/modal_check.py`). Reason: verified and superseded; git history keeps them. Evidence kept from them: the tomato version showed no gap (Gemini 4 Hydrogen beat its reference 4 of 4), and Gemini Flash-Lite and Hydrogen both solved Root Cause seed 0 at 1.0. Both results argue for a task where planning ahead, not one diagnosis, decides the score.
- `envkit` and its depot and strict fixtures stay unchanged. Until the new scenario exists, `tests/envkit/test_integrity.py` skips and `scripts/check.sh` skips task freshness and the audit. `calibration.json` is empty. `judge.sh` defaults to scenario `normal-winter`.
- No crop, facility, price or event value is hardcoded: they are TOML data files validated on load (spec section 3).
- Fairness: simulated time moves only with `advance`; every model gets the same call budget; the wall-clock timeout is a safety net, and runs that hit it are labelled interrupted and rerun for model comparisons (spec 4.1).
- Docker and Modal run the same generated task through `--backend`. Benchmark claims are confirmed on local Docker (spec 13).

## Workstream 0: engine, loader, simulator and tools · 2026-11-14

- envkit: `Environment.close_windows(n)` lets one call close several windows (one window = one simulated hour; `advance(hours)` costs one operation). `Environment.data_files(config)` puts data files into the bundle and its hash. Fixture and tests: `src/envs/clock.py`, `tests/envkit/test_clock.py`. The project root is now found by `pyproject.toml` as well as `scenarios/`, which fixes the root resolving to `src/` while `scenarios/` is empty.
- `contracts.py` gained the subsystem interfaces `sim.py` calls: `FacilityModel` (Emre, `world/energy.py:build_facility`), `BusinessModel` (Rowan, `world/operations.py:build_business`), extra `GrowthModel` methods (Lucas, `world/crop.py:model_for`), settings types, `RuleError`, `Task`, `Delivery`, `HourEnd`, `StartBatch`, and energy prices on `Metered` and grades on `HarvestResult`. Owners replaced "propose an entry point" with these.
- Staff, start cash and seedling stock move to the market file (Rowan). The CO2 store stays with the facility (Emre); sim routes CO2 deliveries to it.
- Any hour nobody ran (a stop, the call limit, a timeout) switches the settings to the facility's `[fallback]` for the rest of the episode. (Superseded the same day by D5 below: settings stand after a stop.)
- Subsystems are chosen by `[env] modules = "package.module:function"`. The default builds the real modules from data files. Tests use `fakes:build` (`tests/greenhouse/fakes.py`, never bundled).

## Design decisions D2, D3, D5 and the business adapter · 2026-11-14

- **D2, decided: the agent decides who gets heat and CO2 when supply is short.** Per compartment it sets a `priority` and exact caps (`heat_cap_kw`, `co2_cap_kg_h`) through `set_energy`, and may sacrifice a crop. Nothing set means plain proportional sharing (spec 4.3). Affects Emre's `world/energy.py` allocation; the settings already exist in `EnergySettings`.
- **D3, decided: weather and energy prices are researched historical hourly series** committed under `data/` with sources. Nothing is fetched live. Every agent on a seed gets the identical series; forecasts are the true series plus seeded error. Each seed picks a recorded window; dev and eval seeds use different windows (spec 3.3). Replaces the generated-profile proposal. Affects Emre's `world/weather.py` and the climate and energy-price data files.
- **D5, decided: do-nothing means the facility's handover baseline is never adjusted** (`[fallback]` is now a typical running setting, not frost protection). Consumables run out, nothing is reordered, harvested, replanted or repaired, and wages and energy keep being paid (spec 7). Stopping for any reason means the same from then on: `sim.go_unattended()` no longer switches settings, so stopping early equals advancing without acting (test `test_stopping_equals_advancing_without_acting`). Consumption rates are to be researched, not guessed.
- **Decision budget kept: 400 calls for 1,008 hours, the agent may act any hour.** Daytime realism lives in the staff shift (tasks progress only in shift hours), not in the agent. A 10-hour agent day was rejected because it would make night events unanswerable by construction (spec 4.1).
- **D8, open: nutrients (fertiliser) as a consumable.** Research uptake per crop and order rules; add after v1 runs end to end.
- **Business adapter.** `world/business.py:build_business` implements `BusinessModel` over Rowan's `Operations`, `Events` and `Ledger` (written by Max; Rowan owns it from here). CO2 deliveries pass straight to the facility's store, so the market's `start_stock.co2_kg` is unused. The sale price is the market crop price times the crop model's `price_factor`. `world/modules.py` now imports it from `business.py` instead of `operations.py`. Tests: `tests/greenhouse/test_business.py` (real market and event files, alone and inside the simulator with the fake facility and crops).
- **`HourEnd.effects` (new optional field).** A finished repair can end an outage `shortens_to_h` later instead of at once; `sim.py` applies the updated effect, and clears it when it expires.
- **Model credentials by provider.** `envkit eval` picks the key from the model prefix: `google/` or `gemini/` uses `GEMINI_API_KEY` (forwarded as `GOOGLE_GENERATIVE_AI_API_KEY`), `anthropic/` uses `ANTHROPIC_API_KEY`, `openai/` uses `OPENAI_API_KEY`, each forwarded to OpenCode by Harbor without the value on a command line. Before this, an `anthropic/` model failed preflight looking for `OPENAI_API_KEY`. Modal needs `modal setup` (`~/.modal.toml`) or `MODAL_TOKEN_ID` plus `MODAL_TOKEN_SECRET`; `.env.example` lists all of them. An Anthropic model is added to the first comparison (spec 12); OpenAI is optional.

## Rowan round 2: business cleanup, policies, D5 values · 2026-11-14

- **CO2 never enters the business's stock.** Operations hands every CO2 delivery to the facility's store (via `HourEnd.deliveries`); the market file refuses `start_stock.co2_kg`, and the business has no CO2 warning or shortage counters. Hours with an empty store are facility evidence (Emre), to be reported through `sim.failure_evidence()`.
- **Peak-price evidence without a threshold.** `Metered` carries prices but no peak flag, so the old `fm_peak_import_kwh` was always 0. Replaced by `fm_import_price_paid_eur_per_kwh` (cost / kWh imported) next to `fm_import_price_mean_eur_per_kwh` (mean hourly price): paying above the mean means buying at peaks.
- **A refused repair changes nothing.** `Events.repair_quote` is pure; `record_repair` runs only after the work is queued. Repairing working equipment is refused for free by `sim.py`; a repair requested during a fault and found unnecessary at completion still costs.
- **Seedling lead time 7 days (was 5).** Dutch propagators raise plants to order and lettuce propagation takes 2–3 weeks; we assume plants on a pre-booked propagation schedule released a week after the call-off, because a full sow-to-order lead time leaves no replanting window in 42 days (D1).
- **Scripted policies** (`src/greenhouse/policies/`): `naive`, `rule-based` and eight `exploit:*` sub-policies, tools only. On the fakes, the money-losing exploits lose and a boiler trip is repaired once. Two checks wait for the real crops and facility: naive < rule-based on seeds 1–3, and every exploit scoring ≤ 0.05.
- **Open, for the team: price per head regardless of weight.** Lettuce sells per head at any sellable weight, so harvesting at the minimum sellable weight earns as much per head as waiting. Unless the crop model's `price_factor` falls for light heads (weight grades), `exploit:harvest-early` may pay. Lucas (crop grades) and Rowan (market) to settle.
- **Recommendation to Max: draw event durations per occurrence.** The loader draws each `{min, max}` once per seed, so every boiler trip in a run lasts the same; `events.py` already draws one per occurrence from `events/<id>/<n>`, so the loader should leave event ranges unresolved.
