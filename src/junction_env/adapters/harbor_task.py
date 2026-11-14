"""Generate a Harbor 0.26 task with trusted service artifacts and separate grading."""
import argparse
import json
from pathlib import Path
import shutil

from junction_env.evaluation import code_metadata
from junction_env.scheduling import generate

PYTHON_IMAGE = "python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df"
HARBOR_VERSION = "0.26.0"

INSTRUCTION = """# Shift Planner
Complete as much workshop job value as possible before each deadline. Call
observe first to see all jobs and rules. All data is public; no discoveries are
required. There are two technicians, one lathe and one bench.

Use MCP tools observe(), start_job(job_id), advance(to_time), finish().
Starting consumes no virtual time, so you can start independent jobs together.
All prerequisites must have completed before a job starts. Resources are held
until completion. Jobs cannot be cancelled. advance must move strictly forward
and no further than shift_end; it processes all intervening completions.

You have 64 mutating actions, including invalid requests. observe is free.
Invalid requests leave jobs and time unchanged and return a clear error.
Termination occurs at finish, shift end, all jobs completed, action exhaustion,
or harness interruption. Running, late and unstarted jobs receive no credit.
Completion exactly at a deadline counts. Reward is the sum of on-time completed
job values divided by the fixed sum of ALL job values.

You may use Python, OR-Tools, or other code to plan; OR-Tools is installed.
No local output file affects the score. Only actual actions on the environment
count. Finish after completing the work. Do not attempt to reset the episode.
"""


def build_task(destination: Path, seed: int, jobs: int = 8, policy: str = "reference") -> Path:
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite task: {destination}")
    if policy not in ("reference", "do_nothing", "stop_early"):
        raise ValueError("unsupported oracle policy")
    root = Path(__file__).resolve().parents[3]
    environment, tests, solution = (destination / name for name in ("environment", "tests", "solution"))
    for folder in (environment / "service", tests, solution):
        folder.mkdir(parents=True)
    instance = generate(seed, jobs)
    public_json = json.dumps(instance.public(), indent=2) + "\n"
    for folder in (environment, environment / "service", tests):
        (folder / "instance.json").write_text(public_json)
    for folder in (environment / "service", tests):
        shutil.copytree(root / "src", folder / "src", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
    shutil.copyfile(root / "harness/requirements.txt", environment / "requirements.txt")
    shutil.copyfile(Path(__file__).with_name("mcp_server.py"), environment / "mcp_server.py")
    (destination / "instruction.md").write_text(INSTRUCTION)
    (destination / "build.json").write_text(json.dumps({**code_metadata(), "seed": seed,
        "instance_hash": instance.digest, "generator_version": instance.generator_version,
        "harbor_version": HARBOR_VERSION, "oracle_policy": policy,
        "official_afterquery_compatibility": "unverified"}, indent=2) + "\n")
    (destination / "task.toml").write_text(f'''schema_version = "1.4"
artifacts = [{{source = "/state/episode.json", destination = "trusted/episode.json", service = "environment"}}]

[task]
name = "junction/shift-planner-{seed}-{policy}"
version = "1.0.0"
authors = []
keywords = ["scheduling", "resource-planning"]

[agent]
timeout_sec = 300.0

[environment]
build_timeout_sec = 600.0
cpus = 2
memory_mb = 2048
storage_mb = 4096
gpus = 0

[[environment.mcp_servers]]
name = "shift-planner"
transport = "stdio"
command = "python"
args = ["/opt/mcp_server.py", "--url", "http://environment:8000"]

[verifier]
environment_mode = "separate"
timeout_sec = 60.0

[[verifier.collect]]
service = "environment"
command = "python -m junction_env.adapters.service --collect /state/episode.json"
timeout_sec = 15.0
''')
    (environment / "Dockerfile").write_text(f'''FROM {PYTHON_IMAGE}
RUN apt-get update && apt-get install -y --no-install-recommends curl git bash ca-certificates && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt
COPY mcp_server.py /opt/mcp_server.py
WORKDIR /workspace
COPY instance.json /workspace/instance.json
''')
    (environment / "service/Dockerfile").write_text(f'''FROM {PYTHON_IMAGE}
ENV PYTHONPATH=/opt/src PYTHONDONTWRITEBYTECODE=1
COPY src/ /opt/src/
COPY instance.json /opt/instance.json
CMD ["python", "-m", "junction_env.adapters.service", "--instance", "/opt/instance.json"]
''')
    (environment / "docker-compose.yaml").write_text('''services:
  main:
    depends_on:
      environment:
        condition: service_healthy
  environment:
    build:
      context: ./service
    read_only: true
    tmpfs:
      - /state
    expose:
      - "8000"
    healthcheck:
      test: ["CMD", "python", "-c", "from urllib.request import urlopen; urlopen('http://localhost:8000/health', timeout=2)"]
      interval: 2s
      timeout: 3s
      retries: 15
''')
    (tests / "Dockerfile").write_text(f'''FROM {PYTHON_IMAGE}
ENV PYTHONPATH=/opt/src
COPY src/ /opt/src/
COPY instance.json /tests/instance.json
COPY test.sh /tests/test.sh
''')
    (tests / "test.sh").write_text('''#!/bin/sh
set -eu
mkdir -p /logs/verifier
python - <<'PY'
import json
from pathlib import Path
from junction_env.scheduling import Instance
from junction_env.scheduling.verifier import verify_record
record = json.loads(Path("/state/episode.json").read_text())
instance = Instance.from_public(json.loads(Path("/tests/instance.json").read_text()))
score = verify_record(record, instance)
Path("/logs/verifier/verification.json").write_text(json.dumps({"score": score, "instance_hash": instance.digest}))
Path("/logs/verifier/reward.txt").write_text(str(score))
PY
''')
    # Oracle receives solver code only at solution time, never a witness schedule.
    for module in ("types.py", "reference.py"):
        shutil.copyfile(root / "src/junction_env/scheduling" / module, solution / module)
    (solution / "__init__.py").write_text("")
    (solution / "solve.sh").write_text(f'''#!/bin/sh
set -eu
export PYTHONPATH=/
python - <<'PY'
import json, sys
sys.path.insert(0, "/opt")
from mcp_server import request_action
from solution.reference import ReferencePolicy, do_nothing, stop_early
policy = {{"reference": ReferencePolicy(), "do_nothing": do_nothing, "stop_early": stop_early}}[{policy!r}]
url = "http://environment:8000"
observation = request_action(url, {{"tool": "observe"}})
for _ in range(64):
    action = policy(observation)
    if action is None:
        break
    observation = request_action(url, action)
    if "error" in observation:
        raise RuntimeError(observation["error"])
    if observation["done"]:
        break
PY
''')
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--jobs", type=int, choices=(8, 10, 12), default=8)
    parser.add_argument("--policy", choices=("reference", "do_nothing", "stop_early"), default="reference")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(build_task(args.output, args.seed, args.jobs, args.policy))


if __name__ == "__main__":
    main()
