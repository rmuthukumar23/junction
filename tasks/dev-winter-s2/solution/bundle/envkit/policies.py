"""Scripted policies.

A policy sees the world only through a `Client`: it can list tools and call
them, exactly like an agent. It has no handle on the Episode or the
Environment, so a reference policy cannot use information the agent lacks.
The same policy object runs in-process (calibration, tests, audit) and over
MCP (the Harbor oracle run).

Policy names accepted by `make_policy`:

  do-nothing                 never acts
  absentee                   attends every window and immediately ends it
  stop-early[:P[@F]]         plays policy P (default: the scenario's reference)
                             for the first fraction F (default 0.3) of the
                             windows, then stops
  stop-after:P@N             plays policy P for its first N tool calls, then stops
  random[:SEED]              random valid-looking calls
  spam:TOOL                  calls one tool over and over
  replay:PATH                re-issues the calls of a recorded trace
  NAME                       a policy the environment registers in policies()
  reference                  whatever the scenario names as its reference
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .bundle import ROOT
from .rng import Rng
from .scenario import Scenario
from .trace import read_trace



class StopPolicy(Exception):
    """Raised to end a policy run early."""


class Client:
    """What a policy is allowed to touch."""

    last_header: dict[str, Any] | None = None

    def call(self, tool: str, **args: Any) -> dict[str, Any]:
        raise NotImplementedError

    def tools(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def opening(self) -> Any:
        """What the player was shown before its first call (Environment.opening)."""
        return None

    @property
    def done(self) -> bool:
        return bool(self.last_header and self.last_header.get("done"))


class Policy:
    name = "policy"

    def run(self, client: Client) -> None:
        raise NotImplementedError


class DoNothing(Policy):
    name = "do-nothing"

    def run(self, client: Client) -> None:
        return


class Absentee(Policy):
    name = "absentee"

    def run(self, client: Client) -> None:
        for _ in range(100_000):
            if client.call("end_window")["header"]["done"]:
                return


class _Limited(Client):
    def __init__(self, inner: Client, fraction: float):
        self.inner, self.fraction = inner, fraction

    @property
    def last_header(self) -> dict[str, Any] | None:  # type: ignore[override]
        return self.inner.last_header

    def tools(self) -> list[dict[str, Any]]:
        return self.inner.tools()

    def opening(self) -> Any:
        return self.inner.opening()

    def call(self, tool: str, **args: Any) -> dict[str, Any]:
        h = self.inner.last_header
        if h and h["window"] > max(1, int(self.fraction * h["windows_total"])):
            raise StopPolicy
        return self.inner.call(tool, **args)


class _Counted(Client):
    def __init__(self, inner: Client, limit: int):
        self.inner, self.limit, self.count = inner, limit, 0

    @property
    def last_header(self) -> dict[str, Any] | None:  # type: ignore[override]
        return self.inner.last_header

    def tools(self) -> list[dict[str, Any]]:
        return self.inner.tools()

    def opening(self) -> Any:
        return self.inner.opening()

    def call(self, tool: str, **args: Any) -> dict[str, Any]:
        if self.count >= self.limit:
            raise StopPolicy
        self.count += 1
        return self.inner.call(tool, **args)


class StopAfter(Policy):
    def __init__(self, inner: Policy, calls: int):
        self.inner, self.calls = inner, calls
        self.name = f"stop-after:{inner.name}@{calls}"

    def run(self, client: Client) -> None:
        self.inner.run(_Counted(client, self.calls))


class StopEarly(Policy):
    def __init__(self, inner: Policy, fraction: float = 0.3):
        self.inner, self.fraction = inner, fraction
        self.name = f"stop-early:{inner.name}@{fraction:g}"

    def run(self, client: Client) -> None:
        self.inner.run(_Limited(client, self.fraction))


class Random(Policy):
    def __init__(self, env_class: type, seed: int = 0, max_calls: int = 20_000):
        self.env_class, self.seed, self.max_calls = env_class, seed, max_calls
        self.name = f"random:{seed}"

    def run(self, client: Client) -> None:
        rng = Rng(self.seed, "policy/random")
        tools = client.tools()
        for _ in range(self.max_calls):
            spec = rng.choice(tools)
            args = self.env_class.fuzz_args(spec["name"], rng)
            if args is None:
                args = sample_args(spec["input_schema"], rng)
            if client.call(spec["name"], **args)["header"]["done"]:
                return


class Spam(Policy):
    def __init__(self, env_class: type, tool: str, max_calls: int = 20_000):
        self.env_class, self.tool, self.max_calls = env_class, tool, max_calls
        self.name = f"spam:{tool}"

    def run(self, client: Client) -> None:
        rng = Rng(0, f"policy/spam/{self.tool}")
        spec = next(t for t in client.tools() if t["name"] == self.tool)
        free = 0
        for _ in range(self.max_calls):
            args = self.env_class.fuzz_args(self.tool, rng)
            if args is None:
                args = sample_args(spec["input_schema"], rng)
            before = client.last_header
            r = client.call(self.tool, **args)
            if r["header"]["done"]:
                return
            same_budget = before is not None and (before["window"], before["ops_left"]) == (
                r["header"]["window"], r["header"]["ops_left"])
            free = free + 1 if same_budget else 0
            if free >= 50:
                return  # calls that spend nothing would never end the episode


class Replay(Policy):
    def __init__(self, records: list[dict[str, Any]], name: str = "replay"):
        self.records, self.name = records, name

    def run(self, client: Client) -> None:
        for rec in self.records:
            if rec.get("k") == "call":
                args = rec.get("args")
                client.call(rec["tool"], **(args if isinstance(args, dict) else {}))
                if client.done:
                    return


def sample_args(schema: dict[str, Any], rng: Rng) -> dict[str, Any]:
    """Arguments drawn from a JSON schema, for tools without fuzz hints."""
    out = {}
    for name, s in schema.get("properties", {}).items():
        if name not in schema.get("required", []) and rng.bernoulli(0.5):
            continue
        out[name] = _sample(s, rng)
    return out


def _sample(s: dict[str, Any], rng: Rng) -> Any:
    if "enum" in s:
        return rng.choice(s["enum"])
    t = s.get("type")
    if isinstance(t, list):
        t = next(x for x in t if x != "null")
    if t == "integer":
        return rng.randint(0, 50)
    if t == "number":
        return round(rng.uniform(0, 100), 2)
    if t == "boolean":
        return rng.bernoulli(0.5)
    if t == "array":
        return [_sample(s.get("items", {"type": "string"}), rng) for _ in range(rng.randint(0, 3))]
    if t == "object":
        return {}
    return rng.choice(["a", "b", "c", "x1", "item"])


def make_policy(spec: str, scenario: Scenario) -> Policy:
    env_class = scenario.env_class()
    registered = env_class.policies()
    head, _, rest = spec.partition(":")

    if spec == "reference" and scenario.reference != "reference":
        return make_policy(scenario.reference, scenario)  # the scenario decides what its reference run is
    if spec in registered:
        policy = registered[spec]()
        policy.name = spec
        return policy
    if spec == "do-nothing":
        return DoNothing()
    if spec == "absentee":
        return Absentee()
    if head == "stop-early":
        inner, _, frac = (rest or scenario.reference).partition("@")
        return StopEarly(make_policy(inner or scenario.reference, scenario), float(frac) if frac else 0.3)
    if head == "stop-after" and "@" in rest:
        inner, _, count = rest.rpartition("@")
        return StopAfter(make_policy(inner, scenario), int(count))
    if head == "random":
        return Random(env_class, int(rest) if rest else 0)
    if head == "spam" and rest:
        return Spam(env_class, rest)
    if head == "replay" and rest:
        return Replay(read_trace(resolve_path(rest)), name=spec)
    known = ["do-nothing", "absentee", "stop-early", "random", "spam:TOOL", "replay:PATH", *registered]
    raise KeyError(f"unknown policy '{spec}'. Known: {known}")


def resolve_path(path: str) -> Path:
    """Find a file given relative to the working directory or the repo/bundle root."""
    for base in (Path.cwd(), ROOT):
        p = base / path
        if p.exists():
            return p
    raise FileNotFoundError(f"{path} (looked in {Path.cwd()} and {ROOT})")
