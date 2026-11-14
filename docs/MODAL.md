# Modal handoff (Windows-friendly)

Status (2026-11-14): Modal connectivity, fan-out and determinism were verified with
standalone scripts (since removed), and the Harbor judge's three scripted policies pass on
`--env modal` including the Compose sidecar (see the Harbor section below). Model-driven
runs and the official event kit are still untested.

## Setup (each teammate, once)

The workspace is out of seats, so teammates without one use the team's shared API token
(token ID `ak-...` plus secret `as-...`), which Max hands out privately. This is for the
hackathon only.

1. `python -m pip install --upgrade modal`. Modal 1.6.1 failed with an image-builder
   `VersionError`; 1.6.4 works.
2. Get the token ID and secret from Max. If you have a seat, accept the invite and run
   `python -m modal setup` instead.
3. `python -m modal token set --token-id ak-... --token-secret as-... --profile hackjunction`
   (writes `~\.modal.toml`). Or set `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` in your
   shell to write nothing to disk. Don't commit the token or paste it into prompts.
4. `python -m modal profile current` must print `hackjunction`; otherwise
   `python -m modal profile activate hackjunction`.

Everyone on the shared token appears as one user, so prefix your app names with your
initials to tell runs apart.

Use `python`, not `python3`, on Windows. The `WindowsSelectorEventLoopPolicy`
DeprecationWarnings are harmless. If output shows odd characters, set `PYTHONIOENCODING=utf-8`.

## Verify

`bash scripts/judge.sh --backend modal --smoke --output artifacts/modal-smoke` runs the
reference once through Harbor on Modal. The earlier standalone load tests under `test/`
were removed after they had served their purpose; their results are below.

For Modal runs, the judge uses the host Python's trusted CA certificates. If that Python
loads no CAs (as can happen with a fresh python.org macOS install), it gives only the
Harbor subprocess the pinned `certifi` bundle through `SSL_CERT_FILE`. It does not alter
the shell or disable TLS verification. An existing `SSL_CERT_FILE` or `SSL_CERT_DIR`
takes precedence; fix or unset an invalid path. If certificate verification still fails,
check whether your network requires a private CA and configure that CA explicitly.

## Visibility

All workspace members see every app and container at <https://modal.com/apps/hackjunction>.
CLI: `python -m modal app list`, `python -m modal container list`,
`python -m modal app stop <app-id>`.

## Measured results (one Windows workstation, EU)

- Sandbox cold start plus one command: about 2 s.
- 12 tasks of 5 s: 12 distinct containers, 10.6 s wall (60 s serial).
- Checkers, 64 deterministic games at minimax depth 6: 62.4 s wall including cold start,
  242 s of summed game time, so about 3.9x. Wall time is not near 64x; we did not
  investigate scaling limits or cold-start cost. For small jobs (depth 4, 24 games) the
  run took 10 s wall for 6.8 s of summed game time, so Modal overhead exceeded the work
  itself; locally the 8-game slice took 5.2 s (about 16 s if extrapolated to 24).
- Determinism: 8/8 and 4/4 seeded games replayed locally gave identical winner and ply
  count on Modal.
- These say nothing about Harbor, the sidecar, or model-driven agents.

## Harbor on Modal: what Harbor's docs say (not yet tested here)

Read from docs.harborframework.com by a subagent; unverified by us.

- `tasks/multi-container` lists `modal` under "DinD Docker Compose" (Docker-in-Docker),
  alongside daytona. `e2b` and `runloop` are not supported. This conflicts with the
  note in `docs/BACKEND.md` and `docs/HARNESS.md` that Compose is unsupported on cloud
  sandboxes, so those statements may be outdated. Confirm against the Harbor version
  we pin (0.26.0) before changing them.
- `tasks/network-policies` says Compose tasks on Modal default to a VM runtime
  (`--ek modal_vm_runtime=true|false` overrides) and that the outer sandbox enforces
  egress policy for all services.
- Run flag: `--env modal`; concurrency `-n/--n-concurrent`. Provider credentials stay in
  the Harbor process environment. The docs gave no Modal-specific auth steps.
- The sidecar collection and separate verification question is answered by the smoke
  tests below: both worked on Modal for the scripted policies.

## Harbor judge on Modal: tested 2026-11-14 (Windows 11, Git Bash, Harbor from `uv.lock`)

Code base: `main` at 2fd57ee plus an uncommitted LF fix in `src/envkit/harbor.py`.

| Command | Result |
|---|---|
| `bash scripts/judge.sh --smoke --output artifacts/docker-smoke` | reference reward 1.0000, 163 s total, after the fix below |
| `bash scripts/judge.sh --backend modal --smoke --output artifacts/modal-smoke` | reference reward 1.0000, 161 s; sidecar `trace.jsonl` (16 lines) collected; separate verifier produced the reward |
| `bash scripts/judge.sh --backend modal --output artifacts/modal-full` | reference 1.0000, do-nothing 0.0000, stop-early 0.0000, 389 s for three sequential runs |

So Modal runs the Compose sidecar task, with sidecar artifact collection and separate
verification, for the three scripted policies. No Modal containers remained afterwards.
Not covered: the official event kit, local-versus-Modal score equality beyond the
scripted rewards, and held-out seeds. Model runs are in the next section.

## Gemini agent runs on Modal (development seed 0 only)

Put `GEMINI_API_KEY=...` in a git-ignored `.env` at the repo root (never commit it or
paste it into a chat). Then, from Git Bash. No Docker needed for `--backend modal`:

```bash
set -a; . ./.env; set +a
bash scripts/judge.sh --backend modal --model google/gemini-4-hydrogen   --runs 3 --seeds 0 --output artifacts/judge-gemini-modal
```

`envkit eval` forwards the key to OpenCode as `GOOGLE_GENERATIVE_AI_API_KEY=${GEMINI_API_KEY}`
(a template Harbor expands, so the value never appears in a command line or log). Use
`--credential-env NAME` if your key lives in another variable. Verified end to end on
2026-11-14: reference 1.0, agent 1.0/1.0/1.0, do-nothing 0.0, stop-early 0.0, 12 min 16 s
for the whole set; no key found in the output folder.

Gotchas found:
- OpenCode's Google provider reads only `GOOGLE_GENERATIVE_AI_API_KEY`; Harbor does not
  map `GEMINI_API_KEY` onto it. Before the forwarding fix, the agent failed with
  `ProviderAuthError` and 0 tool calls. The raw `harbor run` equivalent needs
  `--ae 'GOOGLE_GENERATIVE_AI_API_KEY=${GEMINI_API_KEY}'` (single quotes).
- List models your key can use with a `GET` to `/v1beta/models`; some are refused
  (`gemini-2.5-flash-lite`: "no longer available to new users"). Those zeros are API
  errors, not agent scores.

| Model | Where | Rewards | Wall time |
|---|---|---|---|
| `gemini-4-hydrogen` x3 concurrent | Modal | 1.0, 1.0, 1.0 | 223 s |
| `gemini-4-hydrogen` x3 concurrent | local Docker | 1.0 and two infrastructure failures (agent setup timeout at 360 s) | 486 s |
| `gemini-3.1-flash-lite` x3 concurrent | Modal | 1.0, 1.0, 1.0 | 220 s |

Seed 0 is solved by every working model attempt, even Flash-Lite, so it does not
separate models. No performance gap has been shown.

**Windows bug found and fixed.** The first Docker run failed with
`/tests/test.sh: cannot execute: required file not found`. `_write` in
`src/envkit/harbor.py` used `Path.write_text`, which writes CRLF on Windows, so the
`#!/bin/bash` line broke inside the Linux container. It now writes LF. After this change
run `uv run --no-sync envkit build` and commit the regenerated `tasks/` and
`calibration.json`.

**Known Windows test failures.** `scripts/check.sh` needs `python3`, which does not exist
on Windows. Run its steps with `uv run --no-sync python`. Two tests in
`tests/test_shift_backend.py` (`test_real_mcp_episode_against_the_sidecar_server`,
`test_server_has_no_reset_state_or_score_routes`) fail with a `PermissionError` deleting a
temp `trace.jsonl` still held open; they fail identically without the LF change.
`envkit check` (tasks up to date) and `envkit audit` pass.

## Smoke checks (use these while building)

Local, about 30 s, no keys or Modal needed. Run after every change:

```bash
uv run --no-sync python -m compileall -q src tests && uv run --no-sync python -m pytest tests -q && uv run --no-sync envkit check
```

One real model on the 1-day `scenarios/smoke.toml`, about 3 min per model on Modal, most of it container start-up. Run before merging. Use a new output folder each time; the two commands can run in parallel terminals (load `.env` in each).

```bash
set -a; . ./.env; set +a
uv run --no-sync envkit eval --scenario smoke --model google/gemini-3.1-flash-lite --runs 1 --agent-only --backend modal --output artifacts/smoke-gemini-$(date +%H%M)
uv run --no-sync envkit eval --scenario smoke --model anthropic/claude-haiku-5-5 --runs 1 --agent-only --backend modal --output artifacts/smoke-claude-$(date +%H%M)
```

It works when the report shows a reward above 0 (the agent acted), and `score.json` shows `faults` 0 and `replay.consistent` true. A reward of 0 with 0 calls is an infrastructure failure: read `agent/opencode.txt` in the trial folder. Measured 2026-11-14: Gemini 159 s, Claude 192 s, both 6 calls and 0 faults.
