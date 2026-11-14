# Agent instructions

Read `README.md`, `docs/WORKFLOW.md`, and the issue you claim before editing.

## Goal and status

Build a reproducible interactive environment for Junction 2026's AfterQuery challenge. Shift Planner has a working core and is served and graded as a candidate Harbor task by the `envkit` backend (`docs/BACKEND.md`). Official event-kit compatibility, frontier-agent results, a measured performance gap, and Modal execution remain unverified. See `docs/SCENARIO.md`, `docs/HARNESS.md`, and `docs/EXPERIMENTS.md` for the contract and evidence.

## Working together

- Any teammate, including the coordinator, can claim any issue. Record one current point of contact and temporarily reserved files for each active issue.
- Give every agent session its own branch and worktree. Do not let agents edit the same checkout or another issue's reserved files.
- Agree on changes to `src/junction_env/contracts.py`, public actions or observations, scoring, and shared configuration before dependent work diverges.
- Keep PRs small and `main` runnable. Review the diff and CI before merging; rotate integration duty when possible. Record durable decisions in `docs/DECISIONS.md` and handoffs in the issue or PR.

## AfterQuery correctness

- Keep instances, transitions, and scoring deterministic for a fixed seed. Observations must not reveal the construction witness or judge-only data.
- Reward only genuine completed work. Test invalid actions, incomplete work, do-nothing, early stops, replay, and scoring exploits.
- Use the official AfterQuery starter kit and Harbor/OpenCode MCP harness for the final adapter. Do not claim official compatibility or a frontier gap without runs through that kit.
- Keep development seeds separate from held-out seeds 100–102. For benchmark claims, record the code SHA, exact command, seed, model and harness versions, limits, score, duration, and failures. Do not count infrastructure failures as agent failures.
- Keep secrets and credentials out of commits, prompts, and shared transcripts. Store generated runs under ignored `artifacts/`; commit concise evidence and reproduction commands.

## Checks and handoff

- Run `bash scripts/check.sh` before a PR. For the pinned full test environment, follow the setup in `README.md`.
- `tasks/` and `calibration.json` are generated. After changing anything under `src/` or `scenarios/`, run `uv run --no-sync envkit build` and commit the result; the full check fails if they are stale.
- The candidate judge command is `bash scripts/judge.sh --model "$AFTERQUERY_MODEL" --output artifacts/judge`; it still needs event-kit and frontier validation.
- Update the relevant project docs when an interface, command, decision, or benchmark result changes. End a PR handoff with the current state, verification command and result, and remaining risk.
