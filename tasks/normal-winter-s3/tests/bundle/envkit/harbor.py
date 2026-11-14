"""Harbor task generator.

Turns (scenario, seed, calibration entry) into a self-contained Harbor task:

    tasks/<id>-s<seed>/
      task.toml              MCP server declared, separate verifier, trace artifact
      instruction.md         the scenario prompt plus the interface notes
      environment/
        Dockerfile           the agent's container: tooling only, no task data
        docker-compose.yaml  adds the `sim` sidecar
        sim/                 the simulation + MCP server image (holds the bundle)
      tests/                 the verifier image: replays the trace and scores it
      solution/              the oracle: plays the reference policy over MCP

Layout of trust:
  * `main` (agent)      can reach `sim` only on its MCP port.
  * `sim`  (world)      owns the scenario, seed, hidden state and the trace.
  * verifier            a fresh container; gets the trace from `sim` as an
                        artifact and nothing from the agent's filesystem.

Generated directories are committed so that `harbor run -p tasks/<name>` works
from a clean clone. `envkit check` fails if they are stale.
"""
from __future__ import annotations

import filecmp
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .bundle import ROOT, write_bundle
from .core import Environment, Episode
from .scenario import Scenario

SIM_SERVICE = "sim"
SIM_PORT = 8000
STATE_DIR = "/var/lib/envkit"
HARBOR_VERSION = "0.26.0"
# Multi-platform image digests, so a rebuild next week gets the same base.
PYTHON_IMAGE = ("docker.io/library/python@sha256:"
                "935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df")  # 3.12-slim-bookworm
NODE_IMAGE = ("docker.io/library/node@sha256:"
              "e9f565d32859f0cbfb52125eafe8be39390f24dac302dc3cdf566e8ba3ab21ee")    # 22-bookworm-slim
# Hash-pinned packages for the agent and simulation images, exported from uv.lock
# (see docs/STACK.md). The verifier image installs nothing.
REQUIREMENTS = "harness/requirements.txt"


def task_name(scenario: Scenario, seed: int) -> str:
    return f"{scenario.id}-s{int(seed)}"


def build_task(scenario: Scenario, seed: int, calibration: dict[str, Any], out_root: Path) -> Path:
    h = scenario.harbor
    name = task_name(scenario, seed)
    task = out_root / name
    if task.exists():
        shutil.rmtree(task)
    mcp_name = str(h.get("mcp_name", "env"))
    url = f"http://{SIM_SERVICE}:{SIM_PORT}/mcp"
    requirements = (ROOT / REQUIREMENTS).read_text()
    env_class = scenario.env_class()
    notes = []
    if env_class.on_invalid_call is Environment.on_invalid_call:
        notes.append("- Each tool call spends one operation, unless the tool's description says otherwise. "
                     "A call rejected for malformed arguments spends nothing.")
    if "end_window" in env_class.builtin_tools:
        notes.append("- `end_window` closes the current window.")
    if "read_alerts" in env_class.builtin_tools:
        notes.append("- `read_alerts` returns announcements and rumors that have arrived.")
    notes.append("- Every result is JSON with `ok`, then `result` or `error`, then a `header` with the "
                 "operations left (`ops_left`) and status. When `header.done` is true the episode is over.")
    if scenario.shift.max_calls is not None:
        notes.append("- `header.calls_left` is the number of tool calls you have left in the whole episode, "
                     "every request counted. `header.ops_left` only counts operations in the current window.")
    notes.append("- There is no reset and no second attempt. Your result is computed from the state of "
                 "the world when the episode ends.")

    bundle_hash = ""
    for sub in ("environment/sim/bundle", "tests/bundle", "solution/bundle"):
        bundle_hash = write_bundle(task / sub, scenario, seed, calibration)

    _write(task / "task.toml", f'''schema_version = "1.4"

# The only evidence the verifier receives: the action log written by the
# simulation sidecar. Nothing is taken from the agent's container.
artifacts = [
    {{ source = "{STATE_DIR}/trace.jsonl", service = "{SIM_SERVICE}" }},
]

[task]
name = "{h.get("org", "junction")}/{name}"
description = {json.dumps(scenario.title)}
keywords = ["envkit", "mcp", "simulation"]

[metadata]
scenario = "{scenario.id}"
seed = {int(seed)}
bundle = "{bundle_hash}"

[agent]
timeout_sec = {float(h.get("agent_timeout_sec", 3600))}

[verifier]
timeout_sec = {float(h.get("verifier_timeout_sec", 300))}
environment_mode = "separate"

[environment]
build_timeout_sec = {float(h.get("build_timeout_sec", 900))}
cpus = {int(h.get("cpus", 1))}
memory_mb = {int(h.get("memory_mb", 2048))}
storage_mb = {int(h.get("storage_mb", 10240))}
gpus = 0

[[environment.mcp_servers]]
name = "{mcp_name}"
transport = "streamable-http"
url = "{url}"
''')

    opening = Episode(scenario, seed).opening
    shown = "" if opening is None else (
        "\n## Before your first call\n\nThis is everything you are shown before your first tool call "
        "(the rules, and the state of the world now), as JSON:\n\n```json\n"
        + json.dumps(opening, sort_keys=True, separators=(",", ":")) + "\n```\n")
    _write(task / "instruction.md", scenario.render_prompt() + shown + f'''
## Interface

Every action goes through the tools of the MCP server `{mcp_name}` (`{url}`), which is already connected. Nothing in this container's filesystem affects your result.

{chr(10).join(notes)}
''')

    _write(task / "environment/Dockerfile", f'''# The agent's container. It holds tooling only: no scenario, no seed, no engine code.
FROM {NODE_IMAGE} AS node

FROM {PYTHON_IMAGE}
RUN apt-get update \\
    && apt-get install -y --no-install-recommends bash ca-certificates coreutils curl git \\
    && rm -rf /var/lib/apt/lists/*
# Node and npm, so the harness can install its agent without an apt round trip.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \\
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
# Planning and MCP client libraries, available to the agent and used by the oracle.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt
WORKDIR /app
''')
    _write(task / "environment/requirements.txt", requirements)
    _write(task / "environment/sim/requirements.txt", requirements)

    _write(task / "environment/docker-compose.yaml", f'''# Merged on top of Harbor's base compose file, which defines `main`.
services:
  main:
    depends_on:
      {SIM_SERVICE}:
        condition: service_healthy

  # The world. It is reachable from `main` only on the MCP port.
  {SIM_SERVICE}:
    build:
      context: ./sim
    expose:
      - "{SIM_PORT}"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:{SIM_PORT}/healthz', timeout=2)"]
      interval: 2s
      timeout: 5s
      retries: 30
      start_period: 3s
''')

    _write(task / "environment/sim/Dockerfile", f'''FROM {PYTHON_IMAGE}
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt
RUN useradd --system --uid 10001 envkit \\
    && mkdir -p {STATE_DIR} && chown envkit {STATE_DIR}
COPY bundle /opt/envkit
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 ENVKIT_STATE_DIR={STATE_DIR}
USER envkit
WORKDIR /opt/envkit
EXPOSE {SIM_PORT}
CMD ["python", "-m", "envkit.server"]
''')

    _write(task / "tests/Dockerfile", f'''# The verifier image. Standard library only: it needs no network to grade.
FROM {PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1
COPY . /tests/
''')

    _write(task / "tests/test.sh", f'''#!/bin/bash
# Replays the collected trace in a fresh process and writes the reward.
mkdir -p /logs/verifier
cd /tests/bundle
# No reward file is written if the trace is missing or cannot be graded: that is
# an infrastructure failure, not a score of zero.
exec python3 -m envkit.verify --bundle /tests/bundle --trace {STATE_DIR}/trace.jsonl --out /logs/verifier
''', executable=True)

    _write(task / "solution/solve.sh", f'''#!/bin/bash
# The oracle. Plays a scripted policy through the same MCP tools the agent has.
#   ENVKIT_POLICY=reference    (default) the scenario's reference run
#   ENVKIT_POLICY=stop-early   the reference for the first 30% of windows, then stop
#   ENVKIT_POLICY=<name>       any other policy; see envkit/policies.py
set -euo pipefail
cd "$(dirname "$0")/bundle"
exec python3 -m envkit.oracle --url {url} --policy "${{ENVKIT_POLICY:-reference}}"
''', executable=True)
    return task


def trees_equal(a: Path, b: Path) -> list[str]:
    """Paths that differ between two directory trees."""
    diffs: list[str] = []

    def walk(cmp: filecmp.dircmp, prefix: str) -> None:
        for n in cmp.left_only:
            diffs.append(f"only in {a.name}: {prefix}{n}")
        for n in cmp.right_only:
            diffs.append(f"only in {b.name}: {prefix}{n}")
        _, mismatch, errors = filecmp.cmpfiles(cmp.left, cmp.right, cmp.common_files, shallow=False)
        diffs.extend(f"differs: {prefix}{n}" for n in [*mismatch, *errors])
        for n, sub in cmp.subdirs.items():
            walk(sub, f"{prefix}{n}/")

    walk(filecmp.dircmp(a, b, ignore=["__pycache__"]), "")
    return diffs


def check_task(scenario: Scenario, seed: int, calibration: dict[str, Any], out_root: Path) -> list[str]:
    """Regenerate a task in a scratch directory and compare with the committed one."""
    committed = out_root / task_name(scenario, seed)
    if not committed.exists():
        return [f"{committed} is missing; run `envkit build`"]
    with tempfile.TemporaryDirectory() as tmp:
        fresh = build_task(scenario, seed, calibration, Path(tmp))
        return trees_equal(committed, fresh)


def _write(path: Path, text: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, newline="\n")  # LF always: CRLF breaks #! scripts inside Linux containers
    path.chmod(0o755 if executable else 0o644)
