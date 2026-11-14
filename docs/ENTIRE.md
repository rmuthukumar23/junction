# Entire setup and handoff proof

Entire is a context layer for the GitHub workflow in `WORKFLOW.md`. The repository has Codex hooks and Graph/Brain agent guidance. Each developer installs the CLI and enables capture for the coding agent they actually use. Any two teammates should perform a retrieval test before relying on shared handoffs.

## Setup in a real clone

On macOS, install the stable CLI with `brew install --cask entireio/tap/entire`, or use [Entire's installation guide](https://docs.entire.com/installation) for another installation method. Git 2.36+ is required for Graph. Check that your coding agent loads `AGENTS.md` before starting. From the repository root:

```bash
entire version
entire enable -y --agent codex --local --skip-push-sessions --telemetry=false
# Replace codex with the supported agent identifier used on that machine.
entire status
entire plugin install graph
entire plugin install brain
entire brain setup --no-backfill --no-daemon --no-agent-hooks
entire brain status
```

The committed `.entire/settings.json` disables automatic checkpoint pushing for **every clone**. [Entire's default checkpoint storage](https://docs.entire.com/guides/checkpoints/checkpoint-storage) would otherwise push prompts and transcripts to this public GitHub repository on `git push`. Do not remove `push_sessions: false` without first configuring a private checkpoint destination and reviewing the captured material. Never put secrets in prompts or logs. In each new worktree, run `entire status` to check recording and push status. Local-only checkpoints cannot be retrieved by teammates; use reviewed issue/PR handoffs until a private shared destination is ready.

Graph and Brain setup have already generated `.entire/agent-guide.md` and a managed block in `AGENTS.md`. Do not rerun project setup in each clone or hand-edit the generated guide or managed block. Restart coding-agent sessions after pulling them. Codex may require approval of the project hooks at `/hooks` before session capture works; `entire status` reports this. The `--no-backfill --no-daemon` choice avoids background model calls during the initial setup; enable deeper extraction later if useful.

## Prove shared context

1. One teammate starts an agent session on an issue, makes a small scoped change, and commits it. Accept Entire's prompt to link the session; verify with `entire checkpoint list`.
2. That teammate writes the reviewed architectural choice in `docs/DECISIONS.md` and, if Brain is set up, records a concise memory with `entire brain remember "<decision>" --path decisions.<name>`.
3. Connect Brain to a hosted Entire repository with `entire brain connect` if the team wants memory sync. Local memories are local until connected. Verify a second developer can retrieve the decision with `entire brain recall "<topic>"` and can find related code with Graph. Record the two-person proof in the PR.
4. Keep the issue/PR handoff and decision file as the durable fallback. A session checkpoint is evidence and context, not a substitute for a runnable test or clear acceptance criteria.

For hosted Sessions/Trails, follow Entire's current [mirror setup](https://docs.entire.com/quickstart): `entire login`, authorize its GitHub App, `entire repo mirror add /gh/rmuthukumar23/junction`, and `entire repo remote add entire`. Keep GitHub as the upstream and PR integration gate. A mirror alone does not change the checkpoint privacy setting. Try one Trail on a non-critical branch if its review flow fits the team; do not migrate the whole integration process during the hackathon. Current Brain documentation uses its CLI for agents; it does not offer the earlier `entire brain mcp` command.
