# Four-person workflow

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

Use draft PRs early to expose work without merging incomplete code. Avoid direct pushes to `main` after this initialization. Use squash merges for a clear history. Keep one integration window at least every 2–3 hours; do not let four branches drift until the final hour.

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
- GitHub issues/PRs and `docs/DECISIONS.md` are durable team state. Chat is for quick coordination, not the only record of decisions.
- Entire Sessions should checkpoint important agent context; Graph should be used to locate related code; Brain should retain reviewed architectural decisions. Connect/sync Brain explicitly and test teammate retrieval before relying on it. Trails can assist review if they work with this GitHub workflow, but PRs remain the integration gate.
- Codex (and any other coding agents) work as peers on isolated branches. Any team machine, including the coordinator's, can run development agents. GitHub coordinates integration; no machine owns all agent compute or a shared writable checkout.
- Any scoring or benchmark change gets a before/after run on the same fixed seed suite and at least one held-out suite.

## GitHub settings

An admin should configure a `main` ruleset in GitHub Settings: require a PR, require the `check` status, block force pushes and branch deletion, and require one reviewer if the team can sustain it. Do not enable a required check until its exact name appears on a real PR. Keep admin bypass for emergency use only. Grant each teammate repository access using their own account; do not share credentials.

Issue format: **Goal / owner / owned files / contract / acceptance command / dependency / deadline**.
