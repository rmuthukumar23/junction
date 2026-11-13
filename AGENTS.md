# Agent operating rules

Read `README.md`, `docs/WORKFLOW.md`, and the GitHub issue you claimed before editing.

- Any teammate, including the coordinator, may claim any issue. One active human point of contact per issue; one agent per branch and isolated worktree. Never let two agents edit the same checkout.
- Work in the issue's temporarily reserved files. Propose changes to `src/junction_env/contracts.py`, the public action/observation schema, scoring semantics, or shared configuration in the issue or PR so dependent work can adapt before merging.
- Keep the environment and score deterministic for a fixed seed. The core must run without cloud services or secrets.
- Observations are agent-visible; never include hidden state, answer keys, judge-only diagnostics, or privileged reward data.
- Score genuine completed work. Incomplete, do-nothing, early-stop, and invalid-action paths need explicit tests. Do not optimize a proxy that can be gamed.
- Use the official AfterQuery starter kit and Harbor/OpenCode MCP harness for the final adapter. Do not claim compatibility until it has been run against that harness.
- Before a PR, run `bash scripts/check.sh`. Record the exact command, seed set, model/version, and results for benchmark claims.
- Put durable decisions in `docs/DECISIONS.md` and experiment evidence in `docs/EXPERIMENTS.md`. Entire Sessions/Brain can supplement these files; Git history and these documents remain the team handoff.
- Never commit credentials, `.env` files, unreviewed model outputs, or large result dumps. Keep generated artifacts under ignored `artifacts/`; commit small summaries and reproduction commands.
- Keep PRs small. Have a different teammate review and merge each PR when available; rotate integration duty rather than reserving it for one person.
