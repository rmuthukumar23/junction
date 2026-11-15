# Small viewer fixes

Original branch base: `86b82f0deb77f75fc6c81c523020e4cc94ac76ed`. The viewer fix was applied onto `83af485` (remote `main`, 2026-11-15) for integration. This branch changes no simulator, reference, scoring, or benchmark data.

## Fixed

- The viewer's 14-day run option now points to `dev-winter`, the existing scenario. `quick-winter` was removed, so selecting it failed before launch. The label states that the 14-day run checks plumbing, as the README explains.
- A viewer-launched judge process with a nonzero exit is now reported as failed even if it left a trace file. Previously it appeared finished and the browser auto-loaded a potentially empty or partial run as if evaluation succeeded. The job log remains visible.

## Checked

- A committed Sonnet run trace contains 42 `submit_day` calls and 52 inner actions. The viewer's replay returned 42 turns, 52 actions, and 42/42 matching response digests. There is no general replay loss of model decisions in the current code.
- The status fix is checked with a nonzero/zero/running process stub and a trace file. The scenario option is checked against the files in `scenarios/`.
- `bash scripts/quick.sh` passed in the clean integration worktree with the README's pinned `eval`, `mcp`, and `harbor` extras. The viewer smoke replay (`--scenario smoke --seeds 1 --players reference`) and the focused running/finished/failed job-status cases passed. CI remains a separate merge gate.

## Deferred

The narrow performance gap requires reference or scenario work with measured frontier runs. This viewer patch does not claim to improve that gap. Input validation changes were investigated but removed from this branch because changing packaged environment code requires rebuilding the 42-day benchmark bundles.
