# Evaluation backend (`envkit`)

`src/envkit/` is the one backend that serves, records and grades an environment as a Harbor task. It knows nothing about a particular environment. Shift Planner runs on it through `src/junction_env/scheduling/envkit_binding.py`; `src/envs/depot/` is a second, self-contained example that exercises the features Shift Planner does not use (windows, scripted events, calibrated composite score).

The design follows AfterQuery's [StoreBench](https://github.com/AfterQuery/storebench): time metered in tool operations, a world behind an MCP tool surface, and scores calibrated against scripted anchor policies. StoreBench publishes its task format and scorer but not its engine, so the engine here is written from scratch.

## Trust boundary

```
 main container            sim container (sidecar)         verifier container
 +---------------+   MCP   +-------------------------+     +--------------------+
 | OpenCode agent| ------> | MCP server              |     | replays the trace  |
 | or the oracle | <------ | Episode engine + world  |     | in a fresh process |
 +---------------+ results | scenario, seed, state,  |     | scores the ledger  |
   no task data            | trace.jsonl ------------+---> | writes reward.txt  |
                           +-------------------------+     +--------------------+
```

- The agent's container holds tooling only. The scenario, seed, engine and state live in the `sim` sidecar, reachable only on its MCP port. There is no reset, state, score or file route.
- The sidecar appends every call to `trace.jsonl` and syncs it before replying. Harbor collects that file from the sidecar after stopping the agent and hands only it to a separate verifier container.
- The verifier replays the trace in a fresh process, finishes the episode, scores the ledger and writes `/logs/verifier/reward.txt`. Recorded responses are used only to check that replay reproduces them.
- A trace with no calls is graded as an episode in which nobody acted. A missing or ungradeable trace writes no reward: Harbor records an infrastructure failure, not a zero for the agent.
- Same scenario, seed and actions give the same result across processes and Python versions. No model and no text matching is involved in scoring.

## Commands

All commands run in the locked environment (`uv sync --locked --extra eval --extra mcp --extra harbor`, then `uv run --no-sync ...`).

| Command | Purpose |
|---|---|
| `envkit anchors [SCENARIO]` | Play every scripted policy in-process and print the score table |
| `envkit audit [SCENARIO]` | Reward-integrity checks (below) |
| `envkit build` | Recalibrate and regenerate `tasks/` and `calibration.json` |
| `envkit check` | Fail if `tasks/` or `calibration.json` are stale |
| `envkit run SCENARIO --policy P [--trace FILE]` | Play one policy in-process |
| `envkit play SCENARIO --record FILE` | Play by hand in the terminal; the session is a replayable trace |
| `envkit replay SCENARIO TRACE` | Regrade a trace without containers |
| `envkit serve SCENARIO` | Run the MCP server on localhost |
| `envkit eval --scenario S --output DIR [--model M] [--smoke]` | Judging protocol through Harbor; `scripts/judge.sh` wraps this for Shift Planner |
| `envkit report DIR` | Summarize Harbor trials under a directory |

`tasks/` is generated and committed so that `harbor run -p tasks/<name>` works from a clean clone. Each task carries three copies of the code it needs (sidecar, verifier, oracle) because a Harbor task must stand alone. **After changing anything under `src/` or `scenarios/`, run `envkit build` and commit the result;** `scripts/check.sh` fails in the locked environment if it is stale. Do not run `envkit build` while a Harbor run on a committed task is in flight.

## Engine rules

- **Operations.** Each accepted tool call spends its cost (one by default) from the current window's budget. Spending the last operation, or calling `end_window`, closes the window and advances the world. Time depends only on the action sequence.
- **Stopping.** When the agent stops for any reason, every remaining window runs with nobody acting, and the environment's `on_finish` settles what is in flight. The score is taken after that.
- **Termination.** `Environment.terminated()` is checked after every operation and at every window close.
- **Rejected calls.** A call the engine rejects before it reaches a tool (unknown tool, malformed arguments) is free by default. An environment whose contract charges invalid requests overrides `on_invalid_call`; Shift Planner does.
- **Arguments.** Tool schemas come from type hints. Loose number encodings (`"5"`, `5.0`) are accepted unless the environment sets `strict_arguments = True`; Shift Planner does.
- **Built-in tools.** `end_window` and `read_alerts` are offered unless the environment sets `builtin_tools = ()`; Shift Planner exposes exactly its four contract tools.
- **Events.** A scenario's `[[events]]` reach the agent by channel: announced (an alert states the change), rumored (only the rumor text), or silent (no alert).

## Scoring

`reward = sum(weight × component)`, each component in [0, 1], configured per scenario in `[scoring]`.

- `mean`: the mean of ledger rates already in [0, 1]. An undefined rate is ignored, and if all are undefined the component is 0. Shift Planner uses one such component with weight 1: the contract's on-time value fraction.
- `anchored`: `clip01((raw - zero) / scale)`. `zero` is the best raw result among the do-nothing-style anchors; `scale` maps the best scripted judgment anchor to 0.70, leaving headroom above it. Depot uses 0.7 anchored business + 0.2 reliability + 0.1 continuity, StoreBench's weights.

`calibration.json` holds the constants and each anchor policy's score per scenario and seed. `envkit eval` requires every scripted Harbor run to reproduce its calibrated score exactly.

## What the audit checks

`envkit audit` plays strategies that avoid the task and fails if any scores well:

1. do-nothing scores at most 0.05, and showing up without acting at most 0.15;
2. cutting the reference run off after a fraction of its calls never scores more than cutting it off later, and every such prefix is below the full reference;
3. random calls and spamming any single tool stay below the pass threshold (or below the reference, when the scenario has no anchored component);
4. no tool raised an internal error, and the reference run is identical when repeated and when replayed.

## Adding or changing an environment

1. Subclass `envkit.core.Environment`: `setup`, tools marked with `@tool` (the docstring is the description the agent reads), `on_window_end`, `on_finish`, `ledger`, and `apply_event` if the scenario scripts events. `src/envs/depot/world.py` is a complete example.
2. Register scripted policies in `Environment.policies()`. A policy receives only a client with `tools()` and `call()`, so it cannot see anything the agent cannot. An environment written against `junction_env.contracts` can wrap its observation-to-action policies with `ContractPolicy`, as Shift Planner does.
3. Write `scenarios/<id>.toml`: prompt, clock, environment configuration, events and scoring. The format is documented in `src/envkit/scenario.py`.
4. Run `envkit build`, `envkit audit` and `bash scripts/check.sh`.

Rules that keep an environment gradeable:

- Draw randomness from `self.rng`, with a named stream per process (`self.rng.stream("demand")`), so an extra tool call cannot change the world the agent faces. No wall-clock time.
- Ledger values are numbers where higher is better. Every rate must be 0 when the agent does nothing, and its denominator must not be something the agent can shrink.
- Tools reveal only what an operator could legitimately see. `snapshot()` goes to the verifier's timeline and never to the agent.
- Raise `ToolError` before mutating state, so a failed call changes nothing.

## Recorded human play

```bash
uv run --no-sync envkit play shift-planner --record traces/alice.jsonl
```

A person at the console has the same tools, budget and information as an agent. Setting `reference = "replay:traces/alice.jsonl"` in a scenario and rebuilding makes the Harbor oracle replay that session through MCP. The console drives the same client interface as the policies, so a browser front end needs only `tools()` and `call()`.

## Reading a run

Each Harbor trial directory contains `verifier/reward.txt`, `verifier/score.json` (components, ledger, replay check, per-window timeline; for Shift Planner the timeline carries the per-job outcome table), and `artifacts/var/lib/envkit/trace.jsonl` (every call with its arguments and the response the agent received).

## Limits

- The sidecar needs a Compose-capable Harbor provider. Local Docker and Podman work; Harbor's documentation says multi-container tasks are not supported on its cloud sandboxes, so the Modal path is unverified.
- No run with OpenCode and a model has been made. Harbor installs OpenCode 1.19.5 into the agent image without errors and the oracle reaches the MCP server from that container, but OpenCode connecting and playing is untested.
- On Podman, `podman-compose` 1.x has no `cp`; Harbor logs `compose cp failed; retrying upload with tar stream` and then succeeds.
