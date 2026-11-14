# Modal handoff (Windows-friendly)

Status (2026-11-14): Modal connectivity, fan-out and determinism are verified with
standalone scripts in `test/`. **Harbor `--env modal` with the envkit Compose sidecar is
still unrun.** Modal is not wired into envkit or `scripts/judge.sh`.

## Setup (each teammate, once)

1. Accept the invite to the `hackjunction` Modal workspace.
2. `python -m pip install --upgrade modal`. Modal 1.6.1 failed with an image-builder
   `VersionError`; 1.6.4 works.
3. `python -m modal setup` and sign in with your own account (writes `~\.modal.toml`).
   **Never share or commit that token.** Do not give it to teammates; each person
   authenticates separately.
4. `python -m modal profile current` must print `hackjunction`; otherwise
   `python -m modal profile activate hackjunction`.

Use `python`, not `python3`, on Windows. The `WindowsSelectorEventLoopPolicy`
DeprecationWarnings are harmless. If output shows odd characters, set `PYTHONIOENCODING=utf-8`.

## Verify

```bash
python -m modal run test/modal_check.py --n 12 --work-seconds 5
python -m modal run test/checkers_sim.py --games 16 --depth 6 --local-games 1
```

Cost is a few cents of CPU. Both scripts are throwaway load tests, independent of envkit.
`checkers_sim.py` plays scripted checkers agents (random, greedy, minimax). It calls no
AI model, because no model credentials or Modal secrets exist yet.

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
- Open question: DinD may not provide the trusted sidecar artifact collection and
  separate verification our judge requires. That is the thing to test.

## Next gate (not done)

`bash scripts/judge.sh --backend modal --smoke --output artifacts/modal-smoke`
(Git Bash or WSL, plus Harbor). Pass only if sidecar collection and separate
verification both work; otherwise keep the Docker judge path.
