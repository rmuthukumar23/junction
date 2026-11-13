# Four-person workflow

## Roles and first parallel wave

The coordinator owns `main`, issue assignment, interface decisions, CI, integration, and demo readiness. Delegate one bounded issue to each of the other three humans:

1. **Environment:** implement the real scenario's state, transitions, observation filtering, and determinism in `src/junction_env/`; add focused core tests.
2. **Harness:** obtain the official AfterQuery kit, implement the MCP adapter at the boundary, and prove a real Harbor/OpenCode run. Own `docs/HARNESS.md` and adapter files.
3. **Evaluation:** build legal reference and trivial/exploit baselines, fixed/held-out seed suites, and compact result reports. Own evaluation files and `docs/EXPERIMENTS.md`.

The coordinator writes a one-page scenario contract before these three branches diverge. Harness and evaluation developers can use the toy environment as a stub while the real scenario is built. Assign each issue explicit file ownership and an acceptance command. If two issues need the same file, split or sequence that part before agents start.

## Daily loop during the hackathon

1. Create/claim a GitHub issue. Post goal, owned files, inputs, outputs, acceptance test, and dependency.
2. Create `feat/<issue-number>-short-name` from current `main`. Each human uses a separate local clone or `git worktree`; each agent uses its own worktree/branch. Never share a live checkout between agents.
3. Agent commits only its issue scope. Human runs `bash scripts/check.sh`, inspects the diff and score claims, and opens a small PR linked to the issue.
4. Coordinator integrates in dependency order, reruns CI and the end-to-end path, and records any interface decision in `docs/DECISIONS.md`.
5. After each merge, every owner updates from `main` before another substantial task. Put a short handoff in the PR: current state, exact command, seed, result, remaining risk.

Use draft PRs early to expose work without merging incomplete code. Avoid direct pushes to `main` after this initialization. Use squash merges for a clear history. Keep one integration window at least every 2–3 hours; do not let four branches drift until the final hour.

## Conflict and context rules

- One owner per task and file surface. The coordinator resolves shared interface changes first.
- GitHub issues/PRs and `docs/DECISIONS.md` are durable team state. Chat is for quick coordination, not the only record of decisions.
- Entire Sessions should checkpoint important agent context; Graph should be used to locate related code; Brain should retain reviewed architectural decisions. Connect/sync Brain explicitly and test teammate retrieval before relying on it. Trails can assist review if they work with this GitHub workflow, but PRs remain the integration gate.
- Codex (and any other coding agents) work as peers on isolated branches; the coordinator's machine integrates code, not agent compute or shared writable state.
- Any scoring or benchmark change gets a before/after run on the same fixed seed suite and at least one held-out suite.

## GitHub settings for the coordinator

After the first CI run, configure a `main` ruleset in GitHub Settings: require a PR, require the `check` status, block force pushes and branch deletion, and require one reviewer if your team can sustain it. Do not enable a required check until its exact name appears on a real PR. Keep admin bypass for emergency use only. Grant each teammate repository access using their own account; do not share credentials.

Issue format: **Goal / owner / owned files / contract / acceptance command / dependency / deadline**.
