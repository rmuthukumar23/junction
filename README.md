# Junction 2026 · AfterQuery Break the Agent

Shared repository for a four-person team building a reproducible interactive agent environment. **This is an initialized development scaffold, not the final challenge submission.** The actual scenario, official MCP adapter, frontier runs, and evidence still need to be built and verified.

## Start here

Requires Python 3.11+ and no third-party packages for the local core check.

```bash
git clone https://github.com/rmuthukumar23/junction.git
cd junction
bash scripts/check.sh
```

The command compiles the code, runs deterministic contract tests, and checks a toy example. The toy example proves only that the plumbing works; it is **not** a frontier-agent benchmark. The final judge command must be added after integrating AfterQuery's actual starter kit and Harbor/OpenCode harness.

## Repository map

| Path | Purpose |
| --- | --- |
| `src/junction_env/contracts.py` | Shared local environment interface |
| `src/junction_env/` | Real scenario state and transitions |
| `examples/` | Toy contract smoke test; remove from demo claims |
| `tests/` | Determinism, fairness, reward integrity |
| `docs/HARNESS.md` | Official MCP/Harbor adapter plan |
| `docs/EXPERIMENTS.md` | Reproduction commands and result summaries |
| `.github/` | CI and PR handoff |

The first real scenario should be selected after a quick feasibility review: a clear objective, a plausible strong reference, a frontier failure worth explaining, and a reward that cannot be won by stopping or exploiting bookkeeping.

## First work queue

- [Freeze the scenario contract](https://github.com/rmuthukumar23/junction/issues/1).
- [Implement deterministic environment and reward](https://github.com/rmuthukumar23/junction/issues/2).
- [Integrate the official MCP/Harbor adapter](https://github.com/rmuthukumar23/junction/issues/3).
- [Build reference, baselines, and gap evidence](https://github.com/rmuthukumar23/junction/issues/4).
- [Integrate sponsor technologies where they help](https://github.com/rmuthukumar23/junction/issues/5).

Any teammate can claim any issue, including the coordinator. This machine can run implementation agents as well as integration work. Claims reserve a task and its files only while that work is active; they are not permanent roles. The harness and evaluation tasks can start on the toy stub while the real scenario contract is drafted.

## Acceptance gates, in order

1. **Scenario contract:** action/observation schema, terminal conditions, seed handling, scoring rule, and invalid-action behavior are written down.
2. **Reference:** a legal, reproducible policy solves it over a fixed seed set.
3. **Integrity:** do-nothing, stop-early, random, invalid-action, and obvious exploit policies score well below the reference.
4. **Official harness:** the same scenario runs through AfterQuery's MCP integration; record the exact command and configuration.
5. **Gap:** run the frontier agent repeatedly on held-out seeds; record scores, trajectories, and failure analysis.
6. **Submission:** a fresh clone can run the official judge path with one documented command and without team-specific cloud state.

See [the team workflow](docs/WORKFLOW.md), [stack decision](docs/STACK.md), [Entire setup](docs/ENTIRE.md), [harness checklist](docs/HARNESS.md), [experiment log](docs/EXPERIMENTS.md), and [sponsor plan](docs/SPONSORS.md).
