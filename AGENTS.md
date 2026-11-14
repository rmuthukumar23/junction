# AGENTS.md

The single instruction file for agents in this repo. Read `README.md`, `docs/WORKFLOW.md`, and the GitHub issue you claimed before editing.

## Project

- Build a reproducible interactive agent environment for Junction 2026's AfterQuery challenge. This repo is an initialized scaffold, not the final submission.
- The demo must show a legitimate reference solution, a measured frontier-agent gap, and a fresh-clone run through the official harness.
- Details: [README.md](README.md) and [docs/HARNESS.md](docs/HARNESS.md).

## Commands

- Local core: Python 3.11+; no third-party packages required.
- Run the toy contract example: `PYTHONPATH=src:. python3 examples/toy_environment.py`. It is not a benchmark or final demo.
- Check and test: `bash scripts/check.sh`.
- Official judge command: pending integration of the AfterQuery starter kit.

## Core principles

### Process
- Clarify before building when data structure, user flow, or edge cases cannot be established from the repo or issue. Ask at most 3 consequential questions per task.
- Work in small runnable increments: one component or function at a time, never a whole feature or page in one shot.
- End every step with how to run it: commands, env var names needed, what is mocked or skipped.

### Code quality
- Meaningful names over comments. Comments only for non-obvious decisions.
- Size limits and splitting: see Anti-sprawl.
- Types live in one dedicated file per feature, not scattered inline. Shared environment types and protocols currently live in `src/junction_env/contracts.py`.
- Consistent formatting, matching the project's existing style.

### Architecture
- External services (database, third-party APIs, SDKs) are called only from a dedicated adapter or service file inside the owning feature, or from a small shared module if truly shared. UI components and hooks never call them directly. This applies to the hackathon too.
- Service functions take and return typed, app-shaped data, not raw rows or raw API responses. Map once, at the boundary.
- Keep the deterministic environment core independent of cloud services and secrets.
- Secrets, keys and tokens never appear in client-side code.

### Design consistency (when a UI exists)
- Define the design system once (colors, spacing, typography, radius, motion) as tokens: CSS variables, a theme file or Tailwind config.
- Use tokens and semantic classes in components. No raw values (`#fff`, `text-white`, `bg-[#CC571F]`) inline.
- No long or repeated class strings. Extract them into a variant system (e.g. `cva`) or a named class.
- Once a pattern exists (button, card, input), reuse it. Do not make a slightly different copy per screen.

### Communication
- No filler or marketing language ("seamless", "robust", "cutting-edge").
- Be direct about complexity and tradeoffs.
- Say "I don't know" when true.
- Push back on requests that are unsafe, overcomplicated or unnecessary.

### Security and privacy
- Flag any risk to data, secrets, logs, tokens or credentials as soon as it comes up, without being asked.
- Store only what is needed. Keep sensitive data server-side.
- Never commit credentials, `.env` files, unreviewed model outputs, or large result dumps. Keep generated artifacts under ignored `artifacts/`; commit small summaries and reproduction commands.

### Budget and practicality
- Prefer simple, working solutions. No overengineering, no premature optimization.
- Prefer cheap, swappable tools. Flag ongoing costs when relevant.

## Anti-sprawl

### Code structure
- Split code by feature as the project grows, not solely by technical layer. A feature owns everything it needs in one folder.
- Keep shared code small and limited to genuinely shared concerns; the current `src/junction_env/contracts.py` is the environment interface.
- A feature uses another feature only through that feature's main entry point, never its internal files.
- Keep entry and routing files thin.

### Limits
- Before creating a file or folder, search for an existing place for it. Prefer extending an existing file.
- Aim for files under about 300 lines and functions under about 100. Split before hitting the limit, while writing, not afterwards.
- No new folder unless a feature needs it, and no deeper than 3 levels inside a feature unless the structure demands it.
- No new helper, wrapper or abstraction unless it is used in at least two places or establishes a needed external-service boundary.
- One implementation per concern.

## AfterQuery correctness

- Keep the environment and score deterministic for a fixed seed. Observations are agent-visible; never include hidden state, answer keys, judge-only diagnostics, or privileged reward data.
- Score genuine completed work. Incomplete, do-nothing, early-stop, and invalid-action paths need explicit tests. Do not optimize a proxy that can be gamed.
- Use the official AfterQuery starter kit and Harbor/OpenCode MCP harness for the final adapter. Do not claim compatibility until it has been run against that harness.
- Before a PR, run `bash scripts/check.sh`. Record the exact command, seed set, model/version, and results for benchmark claims.

## Working together

- Any teammate, including the coordinator, may claim any issue. One active human point of contact per issue and temporarily reserved files; the claim ends when work is merged or handed off.
- One git worktree and branch per agent session. Never let two agents edit the same checkout. Work only in the issue's reserved files; coordinate changes elsewhere through the issue or PR.
- Propose changes to `src/junction_env/contracts.py`, the public action/observation schema, scoring semantics, or shared configuration before dependent work diverges.
- Keep PRs small; merge frequently after rebasing on `main` and passing checks. Announce dependency changes in the PR and coordinate their merge order.
- No drive-by refactors. Never leave `main` broken. Have a different teammate review and merge each PR when available; rotate integration duty.

## Docs routing

- When you start any task, read [README.md](README.md) and [docs/WORKFLOW.md](docs/WORKFLOW.md) first.
- When you plan work or check deadlines, read [docs/WORKFLOW.md](docs/WORKFLOW.md) first.
- When you add a feature, folder or technology, read [docs/STACK.md](docs/STACK.md) and [docs/DECISIONS.md](docs/DECISIONS.md) first.
- When you branch, merge or open a pull request, read [docs/WORKFLOW.md](docs/WORKFLOW.md) first.
- When you install, configure or run the project, read [README.md](README.md) first.
- When you set up or troubleshoot your coding agent or Entire, read [docs/ENTIRE.md](docs/ENTIRE.md) first.
- When you write tests or call something done, read [README.md](README.md) and [docs/HARNESS.md](docs/HARNESS.md) first.
- When you prepare or change the demo, read [README.md](README.md), [docs/HARNESS.md](docs/HARNESS.md), and [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md) first.
- When a choice affects several features, read [docs/DECISIONS.md](docs/DECISIONS.md) first and use [docs/decisions/_template.md](docs/decisions/_template.md) if a separate record helps.
- When you work on a feature, use [docs/features/_template.md](docs/features/_template.md) if a feature doc helps the handoff.
- When you need reference material, read [docs/source/](docs/source/). It is read-only.

## Keep docs current

- When you change a feature, interface, command, or architectural choice, update the relevant doc in the same PR.
- Put durable decisions in `docs/DECISIONS.md` and experiment evidence in `docs/EXPERIMENTS.md`. Entire Sessions/Brain supplement these files; Git history and reviewed docs remain the team handoff.
- End PR handoffs with current state, exact command, result, and remaining risk.
