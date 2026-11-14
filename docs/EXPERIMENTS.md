# Experiment evidence

## Root Cause: first complete run · 2026-11-14

Measured on branch `feat/root-cause-greenhouse`, base commit `b1c6f9fed11948c8db9dc933b8c7683326c76930`
with an **uncommitted working tree**; bundle `5553a702e8fa8198`. macOS (Darwin 24),
Python 3.13.3 for the dependency-free checks and 3.12.16 in the locked
environment, MCP SDK 2.3.0, Harbor 0.26.0, uv 0.13.8, Docker Desktop 29.6.2,
Chrome 157. **No model and no model credentials.**
Machine-readable record: [root-cause-evidence.json](root-cause-evidence.json).

```bash
bash scripts/check.sh                                   # Python 3.13.3, no packages
uv sync --locked --extra eval --extra mcp --extra harbor
uv run --no-sync bash scripts/check.sh
uv run --no-sync python scripts/browser_smoke.py
PYTHONPATH=src python3 -m rootcause_app.evaluate --suite all --evidence docs/root-cause-evidence.json
ENVKIT_SCENARIO=root-cause bash scripts/judge.sh --output artifacts/rootcause/harbor-final   # run here as `python -m envkit.cli eval --scenario root-cause`
bash scripts/harbor_boundary_probe.sh artifacts/rootcause/boundary-probe
```

**Checks that passed**

- Without packages: 118 unit tests, 3 skipped (the three that need the MCP SDK or OR-Tools). 85 of them are Root Cause tests in `tests/test_rootcause_*.py`.
- Locked environment: the same 118 with none skipped, 59 backend pytest tests, committed `tasks/` and `calibration.json` match the source for all three scenarios, and the reward audit passes for `root-cause` seed 7, `shift-planner` seed 0 and `depot-basic` seed 7.
- Browser: a full 14-day season in headless Chrome, covering start, plan validation, a triple click on Advance (one day played), a test arriving one day later, the end screen, what-if, replay, and a second run next to the first. No JavaScript error and no failed request.
- JavaScript: 13 modules parse. **The type check did not run** (no TypeScript compiler installed).

**Comparators, in-process.** Reward (net profit). Hidden zone types are shown here for analysis; no player sees them.

Development suite (seeds 1-12 were looked at while tuning; 1-6 reported):

| Seed | Hidden zone types A/B/C/D | Water L | Peak °C (day) | Do nothing | Stop early | Rule-based | Reference |
|---|---|---:|---|---:|---:|---:|---:|
| 1 | rich / saline / salty hungry / balanced | 15,600 | 34 (9) | 0.000 (€2,127) | 0.389 (€2,465) | 0.057 (€2,176) | 0.580 (€2,631) |
| 2 | rich / saline / lean / salty hungry | 13,900 | 32 (8) | 0.000 (€1,999) | 0.579 (€2,611) | 0.128 (€2,134) | 0.651 (€2,686) |
| 3 | saline / balanced / rich / lean | 13,700 | 35 (5) | 0.000 (€2,309) | 0.425 (€2,637) | 0.435 (€2,645) | 0.626 (€2,791) |
| 4 | balanced / lean / saline / rich | 15,400 | 34 (6) | 0.000 (€1,979) | 0.226 (€2,220) | 0.507 (€2,519) | 0.696 (€2,720) |
| 5 | saline / salty hungry / rich / lean | 13,800 | 32 (9) | 0.000 (€1,789) | 0.540 (€2,453) | 0.258 (€2,106) | 0.682 (€2,629) |
| 6 | balanced / lean / salty hungry / rich | 16,900 | 32 (6) | 0.000 (€1,806) | 0.310 (€2,119) | 0.279 (€2,088) | 0.695 (€2,507) |
| **mean** | | | | **0.000** | **0.412** | **0.277** | **0.655** |

Evaluation suite (first run after the mechanics were fixed):

| Seed | Hidden zone types A/B/C/D | Water L | Peak °C (day) | Do nothing | Stop early | Rule-based | Reference |
|---|---|---:|---|---:|---:|---:|---:|
| 101 | salty hungry / rich / saline / lean | 13,400 | 34 (10) | 0.000 (€2,031) | 0.493 (€2,533) | 0.212 (€2,247) | 0.651 (€2,693) |
| 102 | saline / rich / balanced / lean | 15,400 | 31 (9) | 0.000 (€2,202) | 0.558 (€2,682) | 0.622 (€2,736) | 0.676 (€2,782) |
| 103 | rich / salty hungry / saline / balanced | 15,900 | 33 (7) | 0.000 (€2,313) | 0.409 (€2,676) | 0.051 (€2,359) | 0.573 (€2,821) |
| 104 | rich / balanced / salty hungry / lean | 14,700 | 33 (5) | 0.000 (€2,137) | 0.373 (€2,422) | 0.187 (€2,280) | 0.618 (€2,609) |
| 105 | salty hungry / lean / saline / balanced | 14,900 | 31 (4) | 0.000 (€1,729) | 0.600 (€2,496) | 0.160 (€1,934) | 0.683 (€2,603) |
| 106 | balanced / saline / rich / salty hungry | 16,500 | 31 (9) | 0.000 (€2,321) | 0.347 (€2,603) | 0.000 (€2,197) | 0.518 (€2,742) |
| 107 | rich / saline / salty hungry / lean | 15,800 | 32 (7) | 0.000 (€1,863) | 0.518 (€2,470) | 0.104 (€1,986) | 0.670 (€2,649) |
| 108 | balanced / lean / salty hungry / saline | 16,200 | 36 (5) | 0.000 (€1,993) | 0.136 (€2,134) | 0.186 (€2,187) | 0.640 (€2,658) |
| **mean** | | | | **0.000** | **0.429** | **0.191** | **0.629** |

Demo seed 7: do-nothing 0.000, stop-early 0.308, rule-based 0.154, reference 0.607 (€2,467.78, 4 tests).
All 60 runs finished with no internal error and with water, nutrient and salt balances closed.

- The rule-based policy scores 0.43-0.62 on the three seeds with no "salty hungry" zone (3, 4, 102) and 0.00-0.28 on the other eleven.
- Stop-early is weakest where a strong hot spell follows its last decision (4: 34 °C on day 6; 108: 36 °C on day 5).
- On seed 106 the rule-based policy earns less than doing nothing (€2,197 against €2,321); its reward clips to 0.

**What-if on a real trace** (rule-based, seed 7; method and limits in `rootcause_app/analysis.py`). The three days with the most growth lost were days 0, 1 and 2. Replacing one day's plan and replaying the rest of the recorded requests:

| Day | 300 g more fertilizer in zone C | Flush 300 L more in zone B | Default plan instead |
|---|---:|---:|---:|
| 0 | +€156 | −€28 | +€55 |
| 1 | +€140 | −€31 | −€24 |
| 2 | +€123 | −€28 | −€6 |

Zone C is the salty, nutrient-short zone whose EC (3.29) looked unremarkable; zone B has the highest EC and is nutrient-rich. One alternative on day 0 (150 L more irrigation everywhere) was infeasible under the daily cap and is recorded as not evaluated. No later recorded plan became infeasible. These are local, one-day substitutions: evidence that the rule's plan could be improved on those days, not a best plan.

**Harbor on Docker**, `root-cause` seed 7, MCP sidecar and separate verifier:

| Run | Harbor agent | Reward | Calls | Seconds | Status |
|---|---|---:|---:|---:|---|
| reference | oracle | 0.6066 | 48 | 47.2 | completed |
| do-nothing | nop | 0.0000 | 0 | 42.1 | interrupted |
| stop-early | oracle, `ENVKIT_POLICY=stop-early` | 0.3083 | 18 | 43.4 | interrupted |

Each reproduced its calibrated score; batch 133 s with images cached. An earlier run on the previous bundle (before a comment-only scenario edit) gave the same three rewards.

**Boundary probe through Harbor.** `scripts/boundary_probe_agent.sh` ran as root in the agent's container in place of an agent and played nothing. Observed:

- No scenario, manifest, calibration, trace or engine file anywhere in the container; no Docker socket; no task or verifier mounts.
- It wrote `/logs/verifier/reward.txt` = 1.0, a forged `/var/lib/envkit/trace.jsonl` and a `/tests/test.sh` inside its own container. None reached the verifier.
- On the simulator, only port 8000 was open (13 common ports tried). `/healthz` answered 200; ten other paths 404; `DELETE`, `PUT`, `PATCH` on `/mcp` 405.
- `set_state`, `reset` and `get_analysis` were rejected as unknown tools, a negative amount and an extra `profit_eur` argument were rejected, `resources/list` returned "Method not found", and `get_status` contained none of the hidden-state field names.
- Verifier: reward 0.0000, profit equal to the floor, six calls replayed, no notes.

This is a scripted probe of specific attacks. It is not an adversarial session by a model, and it does not cover a Harbor provider other than local Docker.

**Not run:** OpenCode with any model, on any seed; the event kit; Modal; Podman; Harbor on seeds other than 7; GitHub CI on this branch; the JavaScript type check. There is therefore no agent result, no human/agent gap and no failure analysis for Root Cause.

## Backend merge check · 2026-11-14

Measured code: `b5bdf44033127d2bf7696cda3120da35cde07f9f`, clean working tree,
fresh clone. Python 3.12.16, OR-Tools 9.15.6755, MCP SDK 2.3.0, Harbor 0.26.0,
uv 0.13.8 for the locked install, Podman 5.8.9 with podman-compose 1.6.0.
No model or model credentials.

```bash
bash scripts/check.sh                                   # Python 3.12, no packages
uv sync --locked --extra eval --extra mcp --extra harbor
uv run --no-sync bash scripts/check.sh
uv run --no-sync python -m junction_env.evaluation --verify-count 100 --output artifacts/reference-100
bash scripts/judge.sh --output artifacts/judge          # no --model: scripted runs only
```

- Without packages: 33 tests, 3 skipped, toy example passed.
- Locked environment: 33 unittest tests and 59 backend pytest tests passed;
  committed `tasks/` and `calibration.json` matched the source; reward audit
  passed for `shift-planner` seed 0 and `depot-basic` seed 7.
- Reference seeds 0–99 on the local runner: **100/100 at reward 1.0**, at most
  **16/64 actions**, 1.928 seconds on this workstation.
- Backend scores equal the local runner for the earliest-deadline and
  stop-early policies on seeds 0–4 at 8, 10 and 12 jobs (test).
- Harbor on Podman, Shift Planner seed 0, through the `envkit` sidecar and
  separate verifier:

| Run | Harbor agent | Reward | Calls | Trial seconds | Status |
|---|---|---:|---:|---:|---|
| reference | oracle | 1.0 | 15 (14 actions + one free observe) | 93.8 | completed |
| do-nothing | nop | 0.0 | 0 | 82.3 | interrupted |
| stop-early | oracle, `ENVKIT_POLICY=stop-early` | 0.0 | 3 | 75.6 | completed |

  Each run reproduced its calibrated score; sidecar trace collection and
  replay verification completed for all three. Batch 274.0 seconds.
- Before commit, on the same code with a dirty tree: `judge.sh --smoke` passed,
  and `depot-basic` seed 7 scored reference 0.8451, do-nothing 0.0, stop-early 0.2042.

**Not run on this path:** Docker (this workstation has Podman only), GitHub CI,
OpenCode with any model, Modal, seeds other than 0 through Harbor, held-out
seeds. The difficulty risk below is unchanged: the earliest-deadline heuristic
still matches the reference on development seeds.

## Local implementation check · 2026-11-14

Measured code: `ede974d5389090a3c65b3ae1fc57cb28a029ad7b`, clean working tree.
[Machine-readable compact evidence](local-evidence.json). Python 3.12.4, OR-Tools
9.15.6755, local runner v1, generator shift-v1; no model or model credentials.

```bash
uv sync --locked --extra eval --extra mcp --extra harbor
uv run --no-sync bash scripts/check.sh
uv run --no-sync shift-planner --verify-count 100 --output artifacts/reference-committed
uv run --no-sync shift-planner --output artifacts/development-committed
```

- 25 tests passed, including a real MCP stdio → bridge → trusted HTTP service episode.
- Reference seeds 0–99: **100/100 at reward 1.0**, at most **16/64 actions**.
- Reference batch: 2.048 seconds on this workstation, including solver import. This
  is a local observation, not a cloud-throughput or portable speed claim.
- Independent verifier checked replay, resources, prerequisites and completion credit.
- Held-out seeds **100–102 have not been evaluated**.

| Development seed | CP-SAT reference | Do nothing | Stop early | Earliest deadline heuristic |
|---|---:|---:|---:|---:|
| 0 | 1.0 | 0.0 | 0.0 | 1.0 |
| 1 | 1.0 | 0.0 | 0.0 | 1.0 |
| 2 | 1.0 | 0.0 | 0.0 | 1.0 |
| 3 | 1.0 | 0.0 | 0.0 | 1.0 |
| 4 | 1.0 | 0.0 | 0.0 | 1.0 |

**Difficulty risk:** a simple heuristic matches the reference on all development
seeds. These results prove basic solvability and baseline scoring, not meaningful
frontier difficulty. The first official frontier pilot is the highest-priority
next experiment. Preserve access to planning code/optimization tools; calibrate
job count only after measuring performance, then freeze before held-out runs.

## Integrity evidence

Tests cover exact/late deadlines, technician/equipment conflicts, dependencies,
duplicate starts, malformed types and IDs, backwards time, action exhaustion,
post-termination actions, every early-stop prefix in a representative trajectory,
mutable observations/actions, forged trace/reward rejection, parallel independent
episodes, service file isolation, timeout credit and infrastructure-error labels.

The construction witness is feasible across 60 tested 8/10/12-job instances; the
CP-SAT policy separately executes 15 development instances across these sizes.
The 100-run claim above is eight jobs. No construction witness is read by CP-SAT.

## Harness and frontier status

- Harbor 0.26 task schema validates against the installed package.
- Local MCP transport tested with MCP SDK 2.3.0.
- The Docker and CI results in this list were measured on the previous adapter (HTTP service and stdio bridge), before the backend merge.
- **Docker reference smoke passed** in [CI run 43537261501](https://github.com/rmuthukumar23/junction/actions/runs/43537261501): seed 0, reward 1.0, 14 actions; separate verification and trusted sidecar collection both completed.
- CI tested PR merge SHA `a85d0fafc2a59b88c29507e62413e212404c3edd` for source head `b69719510066ba5ce327bfc1a98676911ab47415`. Docker trial 73.143 s; entire Harbor invocation 80.705 s including setup. This is not a Modal timing.
- Downloaded the CI sidecar artifact and independently replayed it locally: 1.0, matching instance `eb85920cd8fffb6e504179970b350967d48f966b40f91ec9c19aec848a3e94f2`.
- Earlier CI runs [43536868023](https://github.com/rmuthukumar23/junction/actions/runs/43536868023) and [43536872234](https://github.com/rmuthukumar23/junction/actions/runs/43536872234) failed trusted artifact collection with `RewardFileNotFoundError`. The sidecar record on tmpfs could not be retrieved by Docker's copy path. Moving it to the sidecar's private filesystem fixed collection. Both failures were reported as infrastructure failures with no agent score; no failed attempt is omitted from this handoff.
- This workstation has no Docker, Modal configuration or frontier credentials.
- **No official frontier evaluation, repeated gap, cloud timing, local/cloud equality
  or frontier failure analysis has been recorded.** No sponsor runtime claim is made.

## Required final evidence

Freeze scenario/version/limits after development pilots. Run three attempts on each
of seeds 100–102 under the event-approved model budget. Retain every attempt,
including rate limits, with code SHA, instance/hash, seed, model, harness and agent
version, limits, score, duration and full trace. Never count infrastructure failures
as evidence of agent weakness. Report per-instance variability and analyze actual
start/advance choices, blocked resources, lost prerequisite opportunities and
missed deadlines. If there is no repeated reference advantage, mark the benchmark
incomplete. Do not replace missing frontier evidence with the heuristic results.
