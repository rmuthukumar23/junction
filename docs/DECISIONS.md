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

## Remaining event decisions

- AfterQuery starter-kit/scoring-skeleton version and any differences from candidate Harbor task.
- Approved frontier model identifier and credentials mapping.
- Scenario freeze after the first official development pilot.
