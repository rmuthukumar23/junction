# Four-person workflow

## Current MVP integration window (6–8 hours)

Claimable packages, never permanent developer roles:

| Window | Acceptance |
|---|---|
| 0–30 min | Event kit/example, model access and submission shape confirmed; contract read |
| 30 min–2 h | Environment, reference, harness and reporting slices integrated with reserved file surfaces |
| By hour 2–3 | One complete legal reference and first official frontier pilot |
| Hours 3–5 | Development-seed calibration, exploit tests, 45-minute Modal gate; freeze scenario |
| Hours 5–6 | Three attempts per held-out seed, deterministic replay, results and decision-based analysis |
| Hours 6–8 | Fresh-clone judge rehearsal, adversarial tests and ten-minute demo |

If no meaningful gap exists by hour four, prioritize calibration over cloud/UI
work. The current implementation does not assign fixed developer roles. Any
teammate or this machine can claim the next package. Entire is available for
local context; Verda training is deferred. Do not block core work on either.

## Original 48-hour reference timeline

- Hours 0 to 2: decide and set up
- Hours 2 to 36: parallel build
- Hours 36 to 40: integration
- Hour 40: feature freeze
- Hours 40 to 46: hardening and demo prep
- Hours 46 to 48: buffer

Adjust the milestone times if the official submission deadline differs. The coordinator tracks dependency and demo readiness, and remains free to claim development work.

## Dynamic work queue and first parallel wave

All four programmers can design, implement, evaluate, integrate, and review. The coordinator tracks dependencies and demo readiness, and also takes development issues. This machine is another development workstation. At a given moment, each active issue has one human point of contact and a defined file surface; that claim expires when the issue is merged or handed off. Choose tasks from the work queue by availability and dependency, not by a permanent role:

1. **Scenario contract:** agree on the real objective, action/observation schema, scoring, and seeds. Any teammate can lead; get quick team review because the other tasks depend on it.
2. **Environment:** implement state, transitions, observation filtering, determinism, and focused tests.
3. **Harness:** obtain the official AfterQuery kit, implement the MCP adapter, and prove a real Harbor/OpenCode run.
4. **Evaluation:** build reference and exploit baselines, seed suites, and result reports.

Freeze the one-page scenario contract with team review before incompatible implementations diverge. The harness and evaluation tasks can use the toy environment as a stub while the real scenario is built. Give each active issue temporary file ownership and an acceptance command. If two issues need the same file, split or sequence that edit before agents start.

## Daily loop during the hackathon

1. Create/claim a GitHub issue. Post goal, temporarily reserved files, inputs, outputs, acceptance test, and dependency. Anyone, including the coordinator, can claim the next suitable issue or hand one off.
2. Create `feat/<issue-number>-short-name` from current `main`. Each human uses a separate local clone or `git worktree`; each agent uses its own worktree/branch. Never share a live checkout between agents.
3. Agent commits only its issue scope. Human runs `bash scripts/check.sh`, inspects the diff and score claims, and opens a small PR linked to the issue.
4. One designated integrator for that PR reviews and merges in dependency order, reruns CI and the end-to-end path, and records any interface decision in `docs/DECISIONS.md`. This duty can rotate; an implementer can integrate another person's PR.
5. After each merge, every owner updates from `main` before another substantial task. Put a short handoff in the PR: current state, exact command, seed, result, remaining risk.

Use draft PRs early to expose work without merging incomplete code. Avoid direct pushes to `main` after this initialization. Use squash merges for a clear history. Merge small ready PRs every 30–60 minutes when practical, and keep an integration window at least every 2–3 hours; do not let four branches drift until the final hour.

For a second agent on the same computer, create an isolated worktree from an up-to-date `main`:

```bash
git fetch origin
git switch main
git pull --ff-only
git worktree add ../junction-2-environment -b feat/2-environment main
```

Run that agent only inside `../junction-2-environment`. Use a different directory and branch for each additional agent. Before opening a PR, push the branch with `git push -u origin feat/2-environment`.

## Conflict and context rules

- One active point of contact per issue and reserved file surface. Agree on shared interface changes in the issue/PR before concurrent branches depend on them.
- Only the agent in the claimed branch edits its reserved files. Need a change in another active issue's files? Coordinate with that issue's point of contact rather than editing the other checkout.
- Keep dependency changes coordinated and announced in the PR. Avoid drive-by refactors and keep `main` runnable.
- GitHub issues/PRs and `docs/DECISIONS.md` are durable team state. Chat is for quick coordination, not the only record of decisions.
- Entire records local checkpoints and provides Graph/Brain context. Automatic session pushing is disabled because this repository is public. Use issue/PR handoffs until a private checkpoint destination and a two-person retrieval test are ready; keep GitHub PRs as the integration gate. See `docs/ENTIRE.md`.
- Codex (and any other coding agents) work as peers on isolated branches. Any team machine, including the coordinator's, can run development agents. GitHub coordinates integration; no machine owns all agent compute or a shared writable checkout.
- Any scoring or benchmark change gets before/after development-seed runs. Keep seeds 100–102 unseen until scenario freeze, then use them only for final held-out evaluation.

## GitHub settings

An admin should configure a `main` ruleset in GitHub Settings: require a PR, require the `check` status, block force pushes and branch deletion, and require one reviewer if the team can sustain it. Do not enable a required check until its exact name appears on a real PR. Keep admin bypass for emergency use only. Grant each teammate repository access using their own account; do not share credentials.

Issue format: **Goal / current point of contact / reserved files / contract / acceptance command / dependency / deadline**.
