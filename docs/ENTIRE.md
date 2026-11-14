# Entire setup and handoff proof

Entire is a context layer for the GitHub workflow in `WORKFLOW.md`. Each developer installs it in their own clone and enables capture for the coding agent they actually use. Any two teammates should perform a retrieval test before relying on it for handoffs.

## Setup in a real clone

On macOS, install the stable CLI with `brew install --cask entireio/tap/entire`. Use [Entire's installation guide](https://docs.entire.com/quickstart) for other systems. Git 2.36+ is required for Graph. Check that your coding agent loads `AGENTS.md` before starting. From the repository root:

```bash
entire version
entire enable -y --agent codex
# Replace codex with the supported agent identifier used on that machine.
entire status
entire plugin install graph
entire graph setup --repo .
entire plugin install brain
entire brain setup --no-backfill --no-daemon
entire brain status
```

In each new worktree, run `entire status` to check that recording is on. [Entire's default checkpoint storage](https://docs.entire.com/guides/checkpoints/checkpoint-storage) pushes session context, including prompts and transcripts, to the same Git repository when code is pushed. In this public repository, review what a session captured before sharing it; never put secrets in prompts or logs. To keep a clone's checkpoints local, run `entire configure --local --skip-push-sessions` before recording sessions. [Local-only checkpoints](https://docs.entire.com/guides/checkpoints/keep-checkpoints-local) cannot be retrieved by teammates, so use reviewed issue/PR handoffs when that setting is active.

Graph and Brain setup generate `.entire/agent-guide.md` and managed blocks in agent instruction files. Review and commit generated project files from one branch; everyone else pulls them. Do not hand-edit the generated guide or managed blocks. Restart coding-agent sessions after pulling them. The `--no-backfill --no-daemon` choice avoids background model calls during the initial setup; enable deeper extraction later if useful.

## Prove shared context

1. One teammate starts an agent session on an issue, makes a small scoped change, and commits it. Accept Entire's prompt to link the session; verify with `entire checkpoint list`.
2. That teammate writes the reviewed architectural choice in `docs/DECISIONS.md` and, if Brain is set up, records a concise memory with `entire brain remember "<decision>" --path decisions.<name>`.
3. Connect Brain to a hosted Entire repository with `entire brain connect` if the team wants memory sync. Local memories are local until connected. Verify a second developer can retrieve the decision with `entire brain recall "<topic>"` and can find related code with Graph. Record the two-person proof in the PR.
4. Keep the issue/PR handoff and decision file as the durable fallback. A session checkpoint is evidence and context, not a substitute for a runnable test or clear acceptance criteria.

For hosted Sessions/Trails, follow Entire's current [mirror setup](https://docs.entire.com/quickstart): `entire login`, authorize its GitHub App, `entire repo mirror add`, and `entire repo remote add entire`. Keep GitHub as the upstream and PR integration gate. Try one Trail on a non-critical branch if its review flow fits the team; do not migrate the whole integration process during the hackathon. Current Brain documentation uses its CLI for agents; it does not offer the earlier `entire brain mcp` command.
