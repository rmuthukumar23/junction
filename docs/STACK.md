# Stack decision for the 48-hour build

## Recommendation

Use **Python 3.11** (recorded in `.python-version`) for the deterministic environment, reference policies, evaluation, and MCP adapter. Keep the core dependency-free. Add the official MCP Python SDK only when the AfterQuery starter kit confirms its expected version and transport. Use **GitHub + Actions** for code and integration, **separate worktrees** for people and agents, and **Entire** for session/context handoff. Use **Modal** for optional parallel episode evaluation and a public demo URL. Use **Verda** only for a genuine large rollout or GPU fine-tuning experiment after the core benchmark is valid.

The first command is `bash scripts/check.sh`; it works without cloud accounts, packages, Docker, or a database. When the adapter introduces external Python dependencies, add them to `pyproject.toml`, generate and commit `uv.lock`, and use `uv sync --locked` in CI and setup. Do not hand-edit the lockfile. The final judge command must match the official starter kit and be demonstrated from a clean clone.

## Why this stack

| Option | Decision | Hackathon tradeoff |
| --- | --- | --- |
| Python core | Choose | Fastest path to simulation, reference policies, numeric evaluation, and the official MCP Python SDK; one language across core and cloud adapters. |
| TypeScript core | Skip unless the official kit requires it | Better browser UI ecosystem, but adds another runtime and language boundary for this challenge. |
| Standard-library local check | Choose now | Works immediately and keeps CI/judge setup small; add `pytest`/`ruff` only if their value exceeds setup and lockfile work. |
| `uv` + committed lockfile | Adopt when dependencies arrive | Fast, repeatable installs; unnecessary while the core has zero external dependencies. |
| SQLite | Optional for local experiment metadata | Useful only if result volume makes files hard to manage. Do not make it a judge prerequisite. |
| Postgres/Redis/Kubernetes | Skip | Adds services, credentials, and integration failure modes without helping the core scoring problem. |
| Docker | Use only if the official harness requires it | Good for identical runtime images, but image build time and architecture differences can slow this team. |
| Web UI | Optional after benchmark evidence | Judges score the environment and reproducible gap; a compact trace viewer may help demo, but should not gate it. |

## Boundary diagram

```text
AfterQuery Harbor/OpenCode --MCP--> adapter --calls--> deterministic Python environment
                                                |                  |
                                                |                  +--> objective score
                                                +--> local runner/reference/baselines

Same pure episode code --optional--> Modal parallel evaluation / demo endpoint
Saved trajectories --optional--> Verda GPU rollouts or small-model training
GitHub PR + CI <-- human/agent worktrees; Entire records cross-agent context
```

The MCP adapter must follow the official kit's schema. Current MCP Python SDK documentation describes Python 3.11+ and stdio/HTTP transports, but that does **not** establish which SDK version or transport AfterQuery's harness expects. Verify with the starter kit before pinning dependencies.

## Sponsor workload split

- **Modal:** `Function.map`/`spawn_map` is a good fit for many independent seeded episodes; use a public endpoint only if it helps judges inspect the result. Measure local versus Modal throughput on the same seeds.
- **Verda:** choose a GPU instance for iterative fine-tuning, or batch jobs when there is a containerized long-running workload. Log the GPU/model, training recipe, data split, cost/credits, and held-out before/after scores. Verda's inference API is useful only if an open model is part of the experiment; calling it once is not a credible compute story.
- **Entire:** initialize Sessions and Graph after the repository has meaningful code. Checkpoint handoffs and explicitly test Brain sharing. Trails may add review evidence, but GitHub PRs remain the merge gate so the team keeps one canonical history.
- **Codex:** use issue-scoped coding and review tasks with isolated worktrees on any team machine. Rotate PR review/integration; no central computer dispatches every agent or holds shared mutable working files.

## Sources checked on 2026-11-14

- [Official MCP Python SDK](https://py.sdk.modelcontextprotocol.io/)
- [uv locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/)
- [Modal batch processing](https://modal.com/docs/guide/batch-processing)
- [Verda GPU instances](https://docs.verda.com/cpu-and-gpu-instances/set-up-a-gpu-instance/) and [batch jobs](https://docs.verda.com/containers/batch-jobs/)
- [Entire Graph setup](https://docs.entire.com/guides/graph/set-up-graph), [Brain](https://docs.entire.com/guides/brain/overview), and [Trails](https://docs.entire.com/guides/trails/overview)
