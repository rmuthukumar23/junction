# Agent instructions

Read `README.md`, `docs/WORKFLOW.md`, and the issue you claim before editing. On the greenhouse build, start from `docs/collaboration/README.md` and your own file there: it lists the files you own and must not leave.

## Goal and status

Build a reproducible interactive environment for Junction 2026's AfterQuery challenge. The submission is Greenhouse Bench: an agent runs a multi-compartment winter greenhouse facility with a shared energy centre for 42 simulated days, scored on net profit (`docs/GREENHOUSE_BENCH_CONTEXT.md`, build spec `docs/GREENHOUSE_SPEC.md`). It is served and graded as a Harbor task by the `envkit` backend (`docs/BACKEND.md`). The earlier Root Cause and tomato environments were removed; their history is in git and `docs/DECISIONS.md`. The greenhouse is not built yet, and no model has played it. Official event-kit compatibility, frontier-agent results and a measured performance gap remain unverified. See `docs/HARNESS.md` for the harness.

## Working together

- Any teammate, including the coordinator, can claim any issue. Record one current point of contact and temporarily reserved files for each active issue.
- Give every agent session its own branch and worktree. Do not let agents edit the same checkout or another issue's reserved files.
- Agree on changes to the tools, observations, scoring, and shared configuration before dependent work diverges.
- Keep PRs small and `main` runnable. Review the diff and CI before merging; rotate integration duty when possible. Record durable decisions in `docs/DECISIONS.md` and handoffs in the issue or PR.

## AfterQuery correctness

- Keep instances, transitions, and scoring deterministic for a fixed seed. Observations must not reveal the construction witness or judge-only data.
- Reward only genuine completed work. Test invalid actions, incomplete work, do-nothing, early stops, replay, and scoring exploits.
- Use the official AfterQuery starter kit and Harbor/OpenCode MCP harness for the final adapter. Do not claim official compatibility or a frontier gap without runs through that kit.
- Keep development seeds 1–6 separate from evaluation seeds 101–108. For benchmark claims, record the code SHA, exact command, seed, model and harness versions, limits, score, duration, and failures. Do not count infrastructure failures as agent failures.
- Keep secrets and credentials out of commits, prompts, and shared transcripts. Store generated runs under ignored `artifacts/`; commit concise evidence and reproduction commands.

## Checks and handoff

- Run `bash scripts/check.sh` before a PR. For the pinned full test environment, follow the setup in `README.md`.
- No crop, facility, price or event value is hardcoded in Python: values live in `data/` files and are validated on load (`docs/GREENHOUSE_SPEC.md` section 3). Only the environment's top-level package (`src/greenhouse`) and the data files the scenario names are bundled into the task.
- `tasks/` and `calibration.json` are generated. After changing anything under `src/` or `scenarios/`, run `uv run --no-sync envkit build` and commit the result; the full check fails if they are stale.
- The judge command is `bash scripts/judge.sh --output artifacts/judge`; it reads `GEMINI_API_KEY` and `AFTERQUERY_MODEL` from `.env` (never commit it). It still needs event-kit validation.
- Update the relevant project docs when an interface, command, decision, or benchmark result changes. End a PR handoff with the current state, verification command and result, and remaining risk.

<!-- entire-agent:begin -->
Read .entire/agent-guide.md for this repository's workflow, source inspection, and verification guidance.
@.entire/agent-guide.md
<!-- entire-agent:end -->
