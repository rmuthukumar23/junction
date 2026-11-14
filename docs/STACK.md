# MVP stack

| Component | Choice | Reason |
|---|---|---|
| Runtime | Python 3.12 | One language; matches Harbor's requirement |
| Simulation and verifier | Standard library | Deterministic, inspectable, no cloud/key dependency |
| Reference | OR-Tools CP-SAT 9.15.6755 (`eval` extra) | Explicit intervals, precedence and cumulative resources |
| Agent interface | MCP SDK 2.3.0 (`mcp` extra) | Small stdio bridge to separate trusted HTTP service |
| Evaluation | Harbor 0.26.0, OpenCode 1.19.5 | Native agent lifecycle, separate verifier and sidecar collection |
| Cloud | Harbor's native Modal backend (`harbor` extra) | Isolated CPU trials; concurrency three after smoke |
| Dependencies | uv 0.13.8 + committed uv.lock | Locked installs; hashed image requirements export |
| Tests | unittest, GitHub Actions | Core runs without packages; transport/reference/container gates add coverage |
| Results | JSON and Markdown in ignored artifacts | Inspectable timelines/metadata; no database/UI dependency |
| Collaboration | GitHub, isolated worktrees, temporary task/file claims | Any developer can own any package; rotating review/integration |

Verda and Entire add no MVP dependencies. Existing Entire docs/config are dormant
optional setup material. No hook/session sync is required to build or test.

## Dependency changes

Update pyproject deliberately, run `uv lock`, then regenerate agent-image pins:

```bash
uv export --extra eval --extra mcp --no-dev --no-emit-project --no-editable --format requirements-txt --output-file harness/requirements.txt
uv sync --locked --extra eval --extra mcp --extra harbor
uv run --no-sync bash scripts/check.sh
```

Do not hand-edit generated lock/requirements files. The trusted sidecar/verifier
use no third-party packages; the agent image receives MCP and OR-Tools planning
libraries. Rebuild image/tasks after changing source, contract or dependency pins.
See [HARNESS](HARNESS.md) for isolation and remaining integration gates.
