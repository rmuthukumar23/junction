"""envkit: a small, environment-agnostic backend for agent evaluation.

The pieces, in dependency order:

  rng       deterministic, named random streams
  schema    tool-argument schemas and validation derived from type hints
  core      Environment base class, the @tool decorator, and the Episode engine
  scenario  scenario TOML loading
  trace     the append-only action log, and deterministic replay
  scoring   the composite scorer (pure function of a terminal ledger)
  policies  scripted policies that play through the same tools as an agent
  calibrate anchor-policy calibration
  audit     a battery of degenerate strategies that must not score well
  verify    the verifier entry point (trace -> reward.txt)
  server    the MCP server (the only module that needs third-party packages)
  harbor    the Harbor task generator

Everything except `server` and `clients.McpClient` is standard library only,
so the verifier image needs nothing but Python.
"""

__version__ = "0.1.0"
