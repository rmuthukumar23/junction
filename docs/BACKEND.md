# envkit: evaluation backend for "Break the Agent"

A backend for building an agent environment and grading it the way the AfterQuery judges will: as a [Harbor](https://github.com/laude-institute/harbor) task that an OpenCode agent plays over MCP, scored between 0 and 1 by a verifier.

The backend is independent of the environment. It ships with a small placeholder world, **Depot**, so that everything runs today. Swap Depot for the real environment and nothing else has to change.

The design follows AfterQuery's own [StoreBench](https://github.com/AfterQuery/storebench): time metered in tool operations, a hidden world behind an MCP tool surface, scripted events on three information channels, and a composite score calibrated against scripted anchor policies. StoreBench's public repository contains only its task format and scorer, not its engine, so the engine here is written from scratch to match that published design.

## Quick start

Needs Python 3.11+, [uv](https://docs.astral.sh/uv/), and Docker or Podman.

```bash
make setup      # virtualenv + Harbor
make test       # 53 tests, about 3 seconds
make audit      # reward-integrity checks, in-process
make eval       # the judging protocol through Harbor (no API key needed without MODEL)
```

With Podman instead of Docker, also run `uv tool install podman-compose`.

## Running the evaluation

One command runs what the judges rerun: the reference run, a do-nothing baseline, a stop-early baseline, and three agent runs.

```bash
make eval MODEL=<provider/model>      # any model OpenCode accepts; set its API key in the environment
```

Without `MODEL`, only the three scripted runs execute. Each line is a plain Harbor command and can be run by hand:

```bash
harbor run -p tasks/depot-basic-s7 -a oracle                                  # reference
harbor run -p tasks/depot-basic-s7 -a nop                                     # do-nothing
harbor run -p tasks/depot-basic-s7 -a oracle --ae ENVKIT_POLICY=stop-early    # stop-early
harbor run -p tasks/depot-basic-s7 -a opencode -m <provider/model> -k 3       # agent, three runs
```

Add `-e podman` on a machine without Docker. Results land in `jobs/`; `uv run envkit report jobs/<name>` prints the table again.

Expected results for the placeholder task `depot-basic-s7`:

| Run | Reward | business | reliability | continuity |
| --- | --- | --- | --- | --- |
| reference (oracle) | 0.8451 | 0.7801 | 0.9951 | 1.0000 |
| rule-based anchor | 0.7900 | 0.7000 | 1.0000 | 1.0000 |
| stop-early (30% of windows) | 0.2042 | 0.1750 | 0.2587 | 0.3000 |
| do-nothing (nop) | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

The scripted runs are deterministic, so these numbers reproduce exactly. No agent run with a model has been made yet.

## How it works

```
 main container            sim container (sidecar)         verifier container
 +---------------+   MCP   +-------------------------+     +--------------------+
 | OpenCode agent| ------> | MCP server              |     | replays the trace  |
 | or the oracle | <------ | Episode engine + world  |     | in a fresh process |
 +---------------+ results | scenario, seed, hidden  |     | scores the ledger  |
   no task data            | state, trace.jsonl -----+---> | writes reward.txt  |
                           +-------------------------+     +--------------------+
```

- **The agent's container holds no task data.** The scenario, the seed, the engine and the hidden state live in the `sim` sidecar, which the agent can reach only on its MCP port. There is no reset tool and no admin endpoint.
- **Time is metered in operations.** Each accepted tool call spends one operation from the current window's budget. Spending the last one, or calling `end_window`, advances the world. Time depends only on the sequence of actions, never on model or network speed.
- **Stopping never freezes the world.** When the agent stops, every remaining window still runs with nobody acting, and the score is computed after the final window.
- **The score is recomputed from the action log.** The sidecar appends every call to `trace.jsonl`. Harbor hands only that file to a separate verifier container, which replays it in a fresh process and scores the result against the committed calibration. Recorded responses are ignored except to check that replay reproduces them.
- **Everything is deterministic.** Same scenario, seed and actions give the same result, across processes and Python versions. No model and no text matching is involved in scoring.

### Scoring

`reward = 0.7 * business + 0.2 * reliability + 0.1 * continuity`, each component in [0, 1]. Weights, metrics and component names are set per scenario in `[scoring]`.

- **business** is a raw outcome from the ledger, normalized as `clip01((raw - zero) / scale)`. `zero` is the better raw result of the do-nothing and absentee anchors, so what a non-player achieves maps to 0. `scale` maps the best scripted judgment anchor to 0.70, leaving headroom for a stronger reference and for agents.
- **reliability** is the mean of service rates from the ledger. A rate with an empty denominator counts as undefined, and if all are undefined the component is 0.
- **continuity** is the fraction of windows in which the agent acted.

`calibration.json` holds the constants for every scenario and seed, with the score of each anchor policy. It is regenerated by `make build` and must be committed; tests fail if it is stale.

One property to be aware of, inherited from StoreBench: an agent that calls `end_window` every window and does nothing else earns the continuity weight, 0.10. To remove that, set the continuity weight to 0 in the scenario.

### What the audit checks

`make audit` plays strategies that avoid the task and fails if any of them scores well:

1. do-nothing scores at most 0.05, and showing up without acting at most 0.15;
2. stopping earlier never scores more than stopping later, and every stop-early run is below the reference;
3. random calls and spamming any single tool stay below the pass threshold;
4. the reference clears the pass threshold;
5. no tool raised an internal error, and the reference run is identical when repeated and when replayed.

## Adding your environment

1. **Write the world.** Create `envs/<name>/world.py` with a subclass of `envkit.core.Environment`. `envs/depot/world.py` is a complete example in about 200 lines.

   ```python
   class Plant(Environment):
       def setup(self): ...                      # build initial state from self.config
       @tool
       def set_valve(self, valve: str, opening: float) -> dict:
           """What the agent reads as the tool description."""
           ...
       def apply_event(self, event): ...         # scripted events; return the announcement text
       def on_window_end(self, window): ...      # advance the world one window
       def on_finish(self): ...                  # settle anything in flight
       def ledger(self): ...                     # terminal metrics the scorer reads
   ```

   Tool arguments and their JSON schemas come from the type hints. Raise `ToolError` for failures the agent should see.

2. **Write scripted policies** in `envs/<name>/policies.py` and register them in `Environment.policies()`. You need at least one judgment anchor (`rule-based`) and a stronger `reference`. Policies receive only a client with `tools()` and `call()`, so they cannot see anything the agent cannot.

3. **Write a scenario** by copying `scenarios/depot-basic.toml`: the prompt, the clock, the world's configuration, the scripted events, and the scoring.

4. **Build and check.**

   ```bash
   make build     # calibrates and generates tasks/<id>-s<seed>/
   make audit
   make test
   ```

Rules that keep an environment gradeable:

- Draw all randomness from `self.rng`, using a named stream per process (`self.rng.stream("demand")`), so an extra tool call cannot change the world the agent faces. No wall-clock time.
- Ledger values are numbers where higher is better.
- Every rate in the ledger must be 0 when the agent does nothing, and its denominator must not be something the agent can shrink.
- Tools reveal only what an operator could legitimately see. Put hidden values in `snapshot()`, which goes to the verifier's timeline and never to the agent.

## A human reference run

A person can play through the same tools and budget, and the recorded session becomes a reference run that replays exactly.

```bash
uv run envkit play depot-basic --record traces/alice.jsonl
```

Then set `reference = "replay:traces/alice.jsonl"` in the scenario and run `make build`. The Harbor oracle will replay that session through MCP.

The console drives the same client interface as the policies, so a browser front end only needs `tools()` and `call()`. `uv run envkit serve <scenario>` exposes a scenario over MCP on localhost for that.

## Analysing a run

Each Harbor trial directory contains:

- `verifier/reward.txt`: the score.
- `verifier/score.json`: components, the full ledger, the replay check, and a per-window timeline for comparing an agent's trajectory with the reference.
- `artifacts/var/lib/envkit/trace.jsonl`: every call the agent made with its arguments and the response it received. This is also the raw material for training a smaller model on experience.

`uv run envkit replay <scenario> <trace.jsonl>` regrades a trace without containers.

## Layout

```
envkit/            the backend
  core.py            Environment, @tool, the Episode engine
  scenario.py        scenario TOML format
  scoring.py         the composite scorer
  calibrate.py       anchor calibration
  policies.py        built-in policies (do-nothing, absentee, stop-early, random, replay)
  audit.py           reward-integrity checks
  server.py          MCP server (runs in the sidecar)
  verify.py          verifier entry point (trace -> reward.txt)
  harbor.py          Harbor task generator
  repl.py            terminal console
  cli.py             the `envkit` command
envs/depot/        the placeholder world and its policies
scenarios/         one TOML file per task
calibration.json   committed calibration constants and anchor scores
tasks/             generated Harbor tasks, committed (do not edit by hand)
tests/
```

`tasks/` is generated. Each task carries three copies of the code it needs (sidecar, verifier, oracle) because a Harbor task must stand alone. After changing anything under `envkit/`, `envs/` or `scenarios/`, run `make build` and commit the result.

## Before submitting

AfterQuery's requirements, and where this repository stands:

- **Harbor task format**: done. `tasks/<name>/` has `instruction.md`, `task.toml`, `environment/Dockerfile`, `tests/` and `solution/`.
- **Verifier writes one score in [0, 1] to `/logs/verifier/reward.txt`**: done.
- **At least one Harbor run log of a model playing the environment**: not done. Run `make eval MODEL=...`. `jobs/` is git-ignored, so copy the run you want to submit into a tracked directory such as `runs/`.
- **A short README on what the agent has to do, why it is hard, and how it is scored**: to be written once the real environment exists. This file documents the backend.

Limits to know about:

- The sidecar design needs a Compose-capable Harbor provider (local Docker or Podman). It does not run on Harbor's cloud sandboxes. Confirm with the mentors that judges run locally.
- No run with OpenCode and a model has been made yet. Harbor installs OpenCode into the agent image without errors, and the oracle reaches the MCP server from that same container, but OpenCode itself connecting to the server and playing is untested.
