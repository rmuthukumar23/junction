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

## Remaining event decisions

- AfterQuery starter-kit/scoring-skeleton version and any differences from candidate Harbor task.
- Approved frontier model identifier and credentials mapping.
- Scenario freeze after the first official development pilot.
