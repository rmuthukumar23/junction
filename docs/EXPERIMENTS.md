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

- Without packages: 60 unit tests (after the one-call-per-day change) (greenhouse model, simulator, tools,
  verifier, tampering, failure modes).
- Locked environment: the same 60 tests and 63 backend pytest tests. The
  committed `tasks/root-cause-s7` and `calibration.json` match the source.
  The reward audit passes on seed 7.
- JavaScript: 15 modules parse and the type check passes. These belong to the
  browser app, which is pending rework.

The comparator numbers below are unchanged by the one-call-per-day change, which re-measured seeds 7, 1 and 2 with the same rewards; the reference now uses 9 calls.

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
bash scripts/quick.sh                       # one attempt + analysis.md
bash scripts/judge.sh --output artifacts/judge-1   # full protocol
```

Record:
- the commit;
- the model id and OpenCode version (from `results.json`);
- each trial's reward, profit and failure modes (`analysis.md`);
- the duration;
- any infrastructure failures, kept separate from agent failures.

## Earlier tomato version: first model runs, Gemini 4 Hydrogen · 2026-11-14

*Recorded on `main` (commit `5c48e2f`) for the 14-day tomato version, before the lettuce redesign. Kept because it is why the task was redesigned: the reference was too weak, and a 14-day season took 15–26 minutes at about 18 s per tool call.*

**Result: no gap. Every Hydrogen attempt that played a full season scored above the
reference (4 of 4, on 2 seeds).** The reference is not the stronger player on this task.

Code `4c8a16e` with uncommitted changes to docs, `.env.example` and `scripts/judge.sh` only;
bundle `6bd5004b21948f40` for both seeds (no task code changed). Fedora, Podman 5.8.9,
podman-compose 1.6.0, Harbor 0.26.0, OpenCode 1.19.5, model `google/gemini-4-hydrogen`
(Google AI Studio key). Development seeds 7 and 2; held-out seeds not used.

```bash
ENVKIT_SCENARIO=root-cause bash scripts/judge.sh --model google/gemini-4-hydrogen \
    --runs 1 --seeds 7 --backend podman --output artifacts/rootcause/gap/pilot-s7
# then, in parallel, with an 18-minute agent limit to fit a 30-minute session:
harbor run --path tasks/root-cause-s7 --env podman --agent opencode --model google/gemini-4-hydrogen \
    --agent-kwarg version=1.19.5 --agent-timeout-multiplier 0.30 \
    --ae 'GOOGLE_GENERATIVE_AI_API_KEY=${GEMINI_API_KEY}' --n-attempts 4 --n-concurrent 4 ...
# same for seed 2 (task built with envkit.harbor.build_task, 2 attempts), plus
# oracle / nop / oracle ENVKIT_POLICY=stop-early on both seeds
uv run --no-sync envkit replay root-cause <trace.jsonl> --seed <s>   # re-score any trace
```

| Seed | Run | Reward | Days | Tests | Calls | Agent limit | Wall time |
|---|---|---|---|---|---|---|---|
| 7 | reference (Harbor) | 0.6662 | 14 | 4 | 48 | – | 3.4 min |
| 7 | do-nothing / stop-early | 0.0000 / 0.0902 | – | – | 0 / 18 | – | 1 min |
| 7 | Hydrogen `XzFN2np` | **0.8263** | 14 | 0 | 99 | 60 min | 26.4 min |
| 7 | Hydrogen `UEaxrqa` | **0.7071** | 14 | 4 | 53 | 18 min | 14.8 min |
| 7 | Hydrogen `hX4qjRr` | **0.7122** | 14 | 4 | 50 | 18 min | 16.6 min |
| 2 | reference (Harbor) | 0.7612 | 14 | 4 | 48 | – | 1.1 min |
| 2 | do-nothing / stop-early | 0.0000 / 0.1958 | – | – | 0 / 18 | – | 1 min |
| 2 | Hydrogen `2aKiKQW` | **0.7979** | 14 | 4 | 50 | 18 min | 14.9 min |

- Every scripted run matched its calibration exactly. Each Hydrogen reward above was written
  by the Harbor verifier and reproduced exactly by `envkit replay` of the sidecar trace
  ("replay consistent: True"); no plan was rejected.
- Seed 7: Hydrogen mean 0.749 over 3 full seasons (range 0.707–0.826) against a reference of
  0.666. The attempt that never ordered a test scored highest.
- Three more attempts were stopped by the operator at 12:38 (not by the agent or the
  harness) and are **not** agent results: seed 2 at 13/14 days (0.7327 so far), seed 7 at
  12/14 (0.5900) and 8/14 (0.3659). They are listed only so that no run is hidden.
- Limitations: 4 complete attempts on 2 seeds, one model, Podman only, not the event kit.
  Three of the four ran under an 18-minute agent limit; finishing in 15–17 min, they were
  not cut off. The stopped attempts were slower, so the completed sample may favor fast
  runs.

What it means for the task: as built, the reference planner (one-step grid search on
a point forecast) is weaker than this model. Claiming a gap needs a stronger reference
(or a harder instance) first; see GREENHOUSE "Comparators" for its known weaknesses.
