# MVP stack

| Component | Choice | Reason |
|---|---|---|
| Runtime | Python 3.12 | One language; matches Harbor's requirement |
| Simulation and verifier | Standard library | Deterministic, inspectable, no cloud/key dependency |
| Reference | OR-Tools CP-SAT 9.15.6755 (`eval` extra) | Explicit intervals, precedence and cumulative resources |
| Agent interface | MCP SDK 2.3.0 (`mcp` extra) | Streamable-HTTP MCP server inside the trusted sidecar; no bridge in the agent container |
| Backend | `src/envkit`, standard library except the MCP server | One engine, verifier, task generator and judge for every environment; see [BACKEND](BACKEND.md) |
| Evaluation | Harbor 0.26.0, OpenCode 1.19.5 | Native agent lifecycle, separate verifier and sidecar collection |
| Cloud | Harbor's native Modal backend (`harbor` extra) | Isolated CPU trials; concurrency three after smoke |
| Dependencies | uv 0.13.8 + committed uv.lock | Locked installs; hashed image requirements export |
| Tests | unittest; pytest 9.0.3 for `tests/envkit`; GitHub Actions | Core runs without packages; transport/reference/backend/container gates add coverage |
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

Do not hand-edit generated lock/requirements files. The verifier uses no
third-party packages. The agent image and the sidecar install the same hashed
requirements: the agent gets MCP and OR-Tools planning libraries, the sidecar
needs the MCP SDK to serve. After changing source, contract, scenario or
dependency pins, run `uv run --no-sync envkit build` and commit `tasks/` and
`calibration.json`.
See [HARNESS](HARNESS.md) for isolation and remaining integration gates.
