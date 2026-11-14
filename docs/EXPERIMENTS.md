# Experiment evidence

Earlier versions (Shift Planner; the 14-day tomato version of Root Cause) are
in git history before branch `feat/lettuce-greenhouse`. Their numbers do not
describe the current task.

## Root Cause, lettuce incident: first complete run · 2026-11-14

Measured on branch `feat/lettuce-greenhouse`. The commit is in
[root-cause-evidence.json](root-cause-evidence.json); the source was clean.
Linux, Python 3.13 for the dependency-free checks and 3.12 in the locked
environment, MCP SDK 2.3.0, Harbor 0.26.0, uv. **No model and no model
credentials.**

```bash
bash scripts/check.sh                                   # no packages
uv sync --locked --extra eval --extra mcp --extra harbor
uv run --no-sync bash scripts/check.sh                  # + backend tests, task freshness, audit
PYTHONPATH=src python3 scripts/compare.py 7 --json /tmp/demo.json
PYTHONPATH=src python3 scripts/compare.py 1 2 3 4 5 6 --json /tmp/dev.json
PYTHONPATH=src python3 scripts/compare.py 101 102 103 104 105 106 107 108 --json /tmp/eval.json
```

**Checks that passed**

- Without packages: 59 unit tests (greenhouse model, simulator, tools,
  verifier, tampering, failure modes).
- Locked environment: the same 59 tests and 63 backend pytest tests. The
  committed `tasks/root-cause-s7` and `calibration.json` match the source.
  The reward audit passes on seed 7.
- JavaScript: 15 modules parse and the type check passes. These belong to the
  browser app, which is pending rework.

**Comparators** (reward, with profit for seed 7). The reward scale runs from
0 (the default plan) to 1 (the informed planner).

| Policy | Seed 7 | Dev 1–6 mean | Eval 101–108 mean | Eval range |
|---|---:|---:|---:|---:|
| Do nothing | 0.000 (€563) | 0.000 | 0.000 | 0.000 |
| Stop early | 0.000 (€460) | 0.000 | 0.000 | 0.000 |
| EC rules | 0.000 (€481) | 0.000 | 0.000 | 0.000 |
| Blind planner | 0.000 (€542) | 0.064 | 0.099 | 0.000–0.203 |
| Reference | 0.882 (€711) | 0.899 | 0.908 | 0.818–0.941 |
| Informed (yardstick) | 1.000 (€731) | 1.000 | 1.000 | |

Failure signatures on the evaluation suite, all 8 seeds:

- **EC rules:** fed less while the crop was short on 9–11 bench-days per run;
  flushed 2,700–3,300 L of backup water; never used the reserve. Nutrient
  starvation was the dominant loss on every seed. Profit came out below doing
  nothing on every seed.
- **Blind planner:** never tested and never used the reserve. Salinity was
  the dominant loss, about €235–280 of crop per run.
- **Reference:** ordered the mains water test on the notice day (day 1) and
  used 2,100–2,370 L of the 2,400 L reserve. It lost €20–40 of crop to
  salinity, against about €185–260 for doing nothing.

**Reward audit, seed 7** (`envkit audit root-cause`):
- do-nothing and absentee score 0;
- the 5 random policies and spamming any single tool all score 0;
- cutting the reference short gives 0 / 0 / 0 / 0.418 / 0.772 / 0.882 for
  increasing prefixes. The last prefix omits only the final `advance_day`,
  whose day runs the plan already submitted.

No tool fault. The reference is deterministic, and its trace replays exactly.

**Not run:**
- **Harbor on this branch.** The build workspace cannot pull Docker images.
  Its first `judge.sh` attempt failed at the image pull, which is an
  infrastructure failure and was recorded as such.
- **OpenCode with any model.** There was no credential, and the workspace
  cannot reach the model API.
- The event kit, Modal, and seeds other than 7 through Harbor.

There is therefore **no agent result, no human/agent gap and no agent
failure analysis yet.**

### Next run (needs Docker and a Gemini key)

```bash
cp .env.example .env     # fill in GEMINI_API_KEY and AFTERQUERY_MODEL
bash scripts/judge.sh --output artifacts/judge-1
PYTHONPATH=src python3 scripts/analyze.py artifacts/judge-1
```

Record:
- the commit;
- the model id and OpenCode version (from `results.json`);
- each trial's reward, profit and failure modes (`analysis.md`);
- the duration;
- any infrastructure failures, kept separate from agent failures.
