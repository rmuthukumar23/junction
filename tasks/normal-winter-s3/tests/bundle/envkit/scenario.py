"""Scenario files.

A scenario is one TOML file that fully specifies a task: which environment
class to run, its configuration, the clock, the scripted events, and how the
terminal ledger is scored. The layout follows StoreBench's `task.toml`.

    [task]     id, title, env ("package.module:Class"), prompt, seeds, reference
    [shift]    windows (or horizon_days), window_hours, ops_per_window, start, max_calls (optional)
    [env]      free-form configuration handed to the environment
    [[events]] scripted changes: at_window (or at_days), kind, parameters, and
               an information channel:
                 default            -> announced (an alert states the change)
                 rumor = "..."      -> rumored   (the alert is only this text)
                 announce = false   -> silent    (no alert at all)
    [scoring]  [[scoring.components]] name, weight, kind ("anchored" | "mean")
    [calibration] anchors = [...]  extra policies to report alongside the
               required ones
    [audit]    optional limits for `envkit audit` (do_nothing_max, absentee_max)
    [harbor]   timeouts and resources for the generated Harbor task
"""
from __future__ import annotations

import hashlib
import importlib
import string
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CHANNELS = ("announced", "rumored", "silent")
_EVENT_RESERVED = {"at_window", "at_days", "kind", "rumor", "announce", "message"}


class ScenarioError(ValueError):
    pass


@dataclass(frozen=True)
class Shift:
    windows: int
    window_hours: float
    ops_per_window: int
    start: str = "2026-01-01 00:00:00"
    # Most requests (accepted, refused or malformed) an episode takes. Reaching it
    # ends the episode as if the player had stopped: every remaining window runs
    # unattended. None means no limit. It bounds the wall-clock length of a run.
    max_calls: int | None = None

    @property
    def horizon_days(self) -> float:
        return self.windows * self.window_hours / 24.0


@dataclass(frozen=True)
class Event:
    at_window: int
    kind: str
    params: dict[str, Any]
    channel: str = "announced"
    rumor: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class Component:
    name: str
    weight: float
    kind: str  # "anchored" | "mean"
    metrics: tuple[str, ...]
    zero_anchors: tuple[str, ...] = ()
    top_anchors: tuple[str, ...] = ()
    target: float = 0.70


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    prompt: str
    env_path: str
    env_config: dict[str, Any]
    shift: Shift
    events: tuple[Event, ...]
    components: tuple[Component, ...]
    seeds: tuple[int, ...]
    reference: str
    anchors: tuple[str, ...]
    pass_margin: float
    harbor: dict[str, Any] = field(default_factory=dict)
    audit: dict[str, Any] = field(default_factory=dict)
    source: str = ""  # raw TOML text, hashed into the bundle hash
    # A benchmark task (whole episodes): built and checked only when named or with --full,
    # never by the quick commands. Quick scenarios (smoke) are the default.
    benchmark: bool = False

    def env_class(self) -> type:
        module, _, cls = self.env_path.partition(":")
        if not cls:
            raise ScenarioError(f"[task].env must look like 'package.module:Class', got {self.env_path!r}")
        return getattr(importlib.import_module(module), cls)

    def render_prompt(self) -> str:
        """Substitute ${windows}, ${ops_per_window}, ${window_hours}, ${horizon_days}, ${max_calls},
        and any plain number or string in [env] (e.g. ${actions_per_day})."""
        s = self.shift
        values = {k: v for k, v in self.env_config.items()
                  if isinstance(v, (int, float, str)) and not isinstance(v, bool)}
        values |= {
            "windows": s.windows,
            "ops_per_window": s.ops_per_window,
            "max_calls": "no limit on" if s.max_calls is None else s.max_calls,
            "window_hours": f"{s.window_hours:g}",
            "horizon_days": f"{s.horizon_days:g}",
            "title": self.title,
        }
        return string.Template(self.prompt.strip()).safe_substitute(values) + "\n"

    def anchor_names(self) -> list[str]:
        """Every policy calibration must run, in a stable order."""
        names = ["do-nothing", "absentee", "stop-early"]
        for c in self.components:
            names += [*c.zero_anchors, *c.top_anchors]
        names += [*self.anchors, self.reference]
        return list(dict.fromkeys(names))


def load_scenario(path: str | Path) -> Scenario:
    path = Path(path)
    text = path.read_text()
    try:
        return parse_scenario(text)
    except ScenarioError as e:
        raise ScenarioError(f"{path}: {e}") from None


def parse_scenario(text: str) -> Scenario:
    data = tomllib.loads(text)
    task = _table(data, "task")
    for key in ("id", "env", "prompt"):
        if key not in task:
            raise ScenarioError(f"[task] is missing '{key}'")

    sh = _table(data, "shift")
    window_hours = float(sh.get("window_hours", 24))
    if "windows" in sh:
        windows = int(sh["windows"])
    elif "horizon_days" in sh:
        windows = round(float(sh["horizon_days"]) * 24 / window_hours)
    else:
        raise ScenarioError("[shift] needs 'windows' or 'horizon_days'")
    if windows < 1 or int(sh.get("ops_per_window", 0)) < 1:
        raise ScenarioError("[shift] needs windows >= 1 and ops_per_window >= 1")
    max_calls = sh.get("max_calls")
    if max_calls is not None and int(max_calls) < 1:
        raise ScenarioError("[shift] max_calls must be at least 1")
    shift = Shift(windows, window_hours, int(sh["ops_per_window"]), str(sh.get("start", Shift.start)),
                  None if max_calls is None else int(max_calls))

    events = []
    for raw in data.get("events", []):
        if "kind" not in raw:
            raise ScenarioError("every [[events]] entry needs a 'kind'")
        if "at_window" in raw:
            at = int(raw["at_window"])
        elif "at_days" in raw:
            at = round(float(raw["at_days"]) * 24 / window_hours)
        else:
            raise ScenarioError(f"event '{raw['kind']}' needs 'at_window' or 'at_days'")
        if not 0 <= at < windows:
            raise ScenarioError(f"event '{raw['kind']}' fires at window {at}, outside 0..{windows - 1}")
        if raw.get("announce", True) is False:
            channel = "silent"
        elif raw.get("rumor"):
            channel = "rumored"
        else:
            channel = "announced"
        params = {k: v for k, v in raw.items() if k not in _EVENT_RESERVED}
        events.append(Event(at, str(raw["kind"]), params, channel, raw.get("rumor"), raw.get("message")))
    events.sort(key=lambda e: e.at_window)  # stable: file order within a window

    scoring = _table(data, "scoring")
    components = []
    for raw in scoring.get("components", []):
        metrics = raw.get("metrics", raw.get("metric"))
        if isinstance(metrics, str):
            metrics = [metrics]
        if not metrics:
            raise ScenarioError(f"scoring component '{raw.get('name')}' needs 'metric' or 'metrics'")
        kind = raw.get("kind", "mean")
        comp = Component(
            name=str(raw["name"]),
            weight=float(raw["weight"]),
            kind=kind,
            metrics=tuple(metrics),
            zero_anchors=tuple(raw.get("zero_anchors", ("do-nothing", "absentee") if kind == "anchored" else ())),
            top_anchors=tuple(raw.get("top_anchors", ())),
            target=float(raw.get("target", 0.70)),
        )
        if kind not in ("anchored", "mean"):
            raise ScenarioError(f"component '{comp.name}': kind must be 'anchored' or 'mean'")
        if kind == "anchored" and (len(comp.metrics) != 1 or not comp.top_anchors):
            raise ScenarioError(f"anchored component '{comp.name}' needs exactly one metric and 'top_anchors'")
        if not 0 < comp.target <= 1:
            raise ScenarioError(f"component '{comp.name}': target must be in (0, 1]")
        components.append(comp)
    if not components:
        raise ScenarioError("[scoring] needs at least one [[scoring.components]] entry")
    total = sum(c.weight for c in components)
    if abs(total - 1.0) > 1e-9 or any(c.weight < 0 for c in components):
        raise ScenarioError(f"scoring weights must be non-negative and sum to 1 (got {total:g})")
    if len({c.name for c in components}) != len(components):
        raise ScenarioError("scoring component names must be unique")

    seeds = tuple(int(s) for s in task.get("seeds", [1]))
    if not seeds:
        raise ScenarioError("[task].seeds must not be empty")

    return Scenario(
        id=str(task["id"]),
        title=str(task.get("title", task["id"])),
        prompt=str(task["prompt"]),
        env_path=str(task["env"]),
        env_config=dict(data.get("env", {})),
        shift=shift,
        events=tuple(events),
        components=tuple(components),
        seeds=seeds,
        reference=str(task.get("reference", "reference")),
        anchors=tuple(data.get("calibration", {}).get("anchors", ())),
        pass_margin=float(scoring.get("pass_margin", 0.01)),
        harbor=dict(data.get("harbor", {})),
        audit=dict(data.get("audit", {})),
        source=text,
        benchmark=bool(task.get("benchmark", False)),
    )


def _table(data: dict[str, Any], name: str) -> dict[str, Any]:
    if not isinstance(data.get(name), dict):
        raise ScenarioError(f"missing [{name}] table")
    return data[name]


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
