"""The Environment base class and the Episode engine.

An Environment is the world: its hidden state, its tools, and how it changes
when time passes. The Episode owns everything that is the same for every
world: the clock, the operation budget, argument validation, scripted events
and their information channels, the action log, and finalization.

Time is metered in operations, as in StoreBench. Each accepted tool call
spends operations from the current window's budget; spending the last one, or
calling `end_window`, closes the window and advances the world. Time is
therefore a pure function of the action sequence and never depends on how
fast the model or the harness is.

When the agent stops, for any reason, `finalize()` runs every remaining window
with nobody acting. Stopping early is never a way to freeze a good position.
"""
from __future__ import annotations

import datetime as _dt
import traceback
from dataclasses import dataclass
from typing import Any, Callable

from . import __version__
from .rng import Rng
from .scenario import Event, Scenario, Shift
from .schema import ArgumentError, Param, input_schema, params_of, validate
from .trace import Trace, digest


class ToolError(Exception):
    """Raise inside a tool for a domain failure the agent should see
    ("not enough cash"). The operation is still spent: it was a real attempt.
    Raise it before mutating state, so a failed call changes nothing."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    params: tuple[Param, ...]
    handler: Callable[..., Any]
    cost: int = 1

    @property
    def input_schema(self) -> dict[str, Any]:
        return input_schema(list(self.params))

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "cost": self.cost,
            "input_schema": self.input_schema,
        }


def tool(fn: Callable[..., Any] | None = None, *, cost: int = 1, name: str | None = None):
    """Mark an Environment method as a tool. The docstring is the description
    the agent sees; parameters come from the type hints."""

    def mark(f: Callable[..., Any]) -> Callable[..., Any]:
        if cost < 0:
            raise ValueError("tool cost must be >= 0")
        f.__envkit_tool__ = {"cost": cost, "name": name or f.__name__}
        return f

    return mark(fn) if fn is not None else mark


class Environment:
    """Subclass this to build a world.

    Rules that keep an environment gradeable:
      * all randomness comes from `self.rng` (use named streams);
      * no wall-clock time, no I/O, no global state;
      * tools return JSON-serializable values and reveal only what an operator
        could legitimately see;
      * `ledger()` returns numbers where higher is better, and every rate in
        it must be 0 when the agent does nothing.
    """

    def __init__(self, config: dict[str, Any], shift: Shift, rng: Rng):
        self.config = config
        self.shift = shift
        self.rng = rng

    # -- lifecycle hooks -------------------------------------------------------

    def setup(self) -> None:
        """Build the initial state. Called once, before window 0 opens."""

    def apply_event(self, event: Event) -> str | None:
        """Apply a scripted event. Return the announcement text for it; the
        engine shows it only if the event's channel is 'announced'."""
        raise NotImplementedError(f"{type(self).__name__} does not handle event kind '{event.kind}'")

    def on_window_end(self, window: int) -> None:
        """Advance the world by one window. Called whether or not anyone acted."""

    def on_finish(self) -> None:
        """Settle anything still in flight once the last window has closed."""

    def terminated(self) -> str | None:
        """Return a reason to end the episode early (e.g. 'bankrupt')."""
        return None

    # -- observation and outcome -----------------------------------------------

    def header(self) -> dict[str, Any]:
        """A few visible status fields attached to every tool result."""
        return {}

    def snapshot(self) -> dict[str, Any]:
        """Per-window metrics for analysis. May include hidden state: it is
        written to the trace timeline, never shown to the agent."""
        return {}

    def ledger(self) -> dict[str, float | None]:
        """Terminal metrics the scorer reads. Called after on_finish()."""
        raise NotImplementedError

    # -- scripted policies -----------------------------------------------------

    @classmethod
    def policies(cls) -> dict[str, Callable[[], Any]]:
        """Named scripted policies for this environment, e.g.
        {"rule-based": RuleBased, "reference": Reference}."""
        return {}

    @classmethod
    def fuzz_args(cls, tool_name: str, rng: Rng) -> dict[str, Any] | None:
        """Plausible arguments for a tool, for the random policy. Return None
        to fall back to sampling from the schema."""
        return None

    # -- internals -------------------------------------------------------------

    def tool_specs(self) -> list[ToolSpec]:
        specs = []
        seen = set()
        for klass in reversed(type(self).__mro__):
            for attr, fn in vars(klass).items():
                meta = getattr(fn, "__envkit_tool__", None)
                if meta is None or attr in seen:
                    continue
                seen.add(attr)
                doc = " ".join((fn.__doc__ or "").split())
                if not doc:
                    raise TypeError(f"tool '{meta['name']}' needs a docstring; it is what the agent reads")
                specs.append(ToolSpec(meta["name"], doc, tuple(params_of(fn)), getattr(self, attr), meta["cost"]))
        return specs


RESERVED_LEDGER_KEYS = (
    "seed", "continuity", "windows_total", "windows_acted", "windows_played",
    "ops_used", "calls", "rejected", "faults", "stopped_early", "end_reason",
)


class Episode:
    """One run of one scenario at one seed."""

    def __init__(self, scenario: Scenario, seed: int, trace: Trace | None = None, bundle_hash: str = ""):
        self.scenario = scenario
        self.seed = int(seed)
        self.shift = scenario.shift
        self.trace = trace if trace is not None else Trace()
        self.env: Environment = scenario.env_class()(dict(scenario.env_config), self.shift, Rng(self.seed))

        self.window = 0
        self.ops_left = self.shift.ops_per_window
        self.acted = [False] * self.shift.windows
        self.windows_played = 0
        self.done = False
        self.end_reason: str | None = None
        self.stopped_early = False
        self.alerts: list[dict[str, Any]] = []
        self._alerts_read = 0
        self.calls = 0
        self.rejected = 0
        self.faults = 0
        self.ops_used = 0
        self.timeline: list[dict[str, Any]] = []
        self.fault_log: list[str] = []
        self._n_recorded = 0

        specs = [
            ToolSpec("end_window", "Close the current window now and advance the clock to the next one. "
                     "Unused operations are lost. Costs no operation.", (), self._end_window, 0),
            ToolSpec("read_alerts", "Read alerts and news that have arrived (announcements and rumors about "
                     "changes in the world). Returns unread alerts, or all of them with all=true.",
                     tuple(params_of(self._read_alerts)), self._read_alerts, 1),
            *self.env.tool_specs(),
        ]
        self.tools: dict[str, ToolSpec] = {}
        for spec in specs:
            if spec.name in self.tools:
                raise TypeError(f"duplicate tool name '{spec.name}'")
            self.tools[spec.name] = spec

        if not self.trace.records:
            self.trace.append({"k": "header", "scenario": scenario.id, "seed": self.seed,
                               "bundle": bundle_hash, "engine": __version__})
        self.env.setup()
        self._open_window()

    # -- the one entry point for agents, policies, humans and replay -----------

    def call(self, name: str, args: dict[str, Any] | None = None, *, record: bool = True) -> dict[str, Any]:
        window_before = self.window
        ok, spent, result, error = False, 0, None, None
        spec = self.tools.get(name)
        if self.done:
            error = {"code": "episode_over", "message": "The episode has ended; no further actions are possible."}
        elif spec is None:
            error = {"code": "unknown_tool", "message": f"No tool named '{name}'. Available: {sorted(self.tools)}"}
        elif spec.cost > self.ops_left:
            error = {"code": "insufficient_ops",
                     "message": f"'{name}' costs {spec.cost} operations but only {self.ops_left} remain in this window."}
        else:
            try:
                kwargs = validate(list(spec.params), args)
            except ArgumentError as e:
                error = {"code": "invalid_arguments", "message": str(e)}
            else:
                try:
                    result = spec.handler(**kwargs)
                    ok = True
                    spent = spec.cost
                except ToolError as e:
                    error = {"code": "tool_error", "message": str(e)}
                    spent = spec.cost
                except Exception:  # a bug in the environment, never the agent's fault
                    self.faults += 1
                    self.fault_log.append(f"{name}({args!r})\n{traceback.format_exc()}")
                    error = {"code": "internal_error",
                             "message": "The environment hit an internal error. No operation was spent."}
                args = kwargs

        accepted = ok or (error is not None and error["code"] == "tool_error")
        if accepted:
            self.calls += 1
            self.ops_used += spent
            self.ops_left -= spent
            self.acted[self.window] = True
            if name == "end_window" or self.ops_left <= 0:
                self._close_window()
        elif error["code"] != "episode_over":  # calls after the end never touch the ledger
            self.rejected += 1

        response: dict[str, Any] = {"ok": ok}
        if ok:
            response["result"] = result
        else:
            response["error"] = error
        response["header"] = self.header()

        if record:
            self.trace.append({
                "k": "call", "i": self._n_recorded, "window": window_before, "tool": name,
                "args": args if isinstance(args, dict) else {}, "ok": ok, "spent": spent,
                "digest": digest(response), "response": response,
            })
            self._n_recorded += 1
        return response

    def describe_tools(self) -> list[dict[str, Any]]:
        return [spec.describe() for spec in self.tools.values()]

    def header(self) -> dict[str, Any]:
        s = self.shift
        clock = _dt.datetime.fromisoformat(s.start) + _dt.timedelta(hours=s.window_hours * self.window)
        head = {
            "window": min(self.window + 1, s.windows),
            "windows_total": s.windows,
            "ops_left": 0 if self.done else self.ops_left,
            "clock": clock.strftime("%Y-%m-%d %H:%M"),
            "unread_alerts": len(self.alerts) - self._alerts_read,
            "done": self.done,
        }
        if self.done:
            head["end_reason"] = self.end_reason
        head.update(self.env.header())
        return head

    # -- time ------------------------------------------------------------------

    def finalize(self) -> None:
        """Run every remaining window unattended, then settle. Idempotent."""
        if not self.done:
            self.stopped_early = True
        while not self.done:
            self._close_window()

    def _open_window(self) -> None:
        for ev in self.scenario.events:
            if ev.at_window != self.window:
                continue
            text = self.env.apply_event(ev)
            if ev.channel == "silent":
                continue
            if ev.channel == "rumored":
                text = ev.rumor
            else:
                text = ev.message or text or f"Change in effect: {ev.kind}."
            self.alerts.append({"window": self.window + 1, "channel": ev.channel, "text": text})

    def _close_window(self) -> None:
        w = self.window
        self.env.on_window_end(w)
        self.windows_played += 1
        self.timeline.append({"window": w + 1, "acted": self.acted[w], **self.env.snapshot()})
        self.window += 1
        reason = self.env.terminated()
        if self.window >= self.shift.windows:
            self._finish("horizon")
        elif reason:
            self._finish(f"terminated:{reason}")
        else:
            self.ops_left = self.shift.ops_per_window
            self._open_window()

    def _finish(self, reason: str) -> None:
        self.env.on_finish()
        self.done = True
        self.end_reason = reason

    # -- built-in tools --------------------------------------------------------

    def _end_window(self) -> dict[str, Any]:
        return {"closed_window": self.window + 1}

    def _read_alerts(self, all: bool = False) -> dict[str, Any]:
        items = self.alerts if all else self.alerts[self._alerts_read:]
        self._alerts_read = len(self.alerts)
        return {"alerts": list(items)}

    # -- outcome ---------------------------------------------------------------

    def result(self) -> dict[str, Any]:
        """The graded terminal ledger. Finalizes the episode if needed."""
        self.finalize()
        ledger = dict(self.env.ledger())
        clash = sorted(set(ledger) & set(RESERVED_LEDGER_KEYS))
        if clash:
            raise TypeError(f"ledger() must not use reserved keys {clash}")
        total = self.shift.windows
        ledger.update({
            "seed": self.seed,
            "continuity": sum(self.acted) / total,
            "windows_total": total,
            "windows_acted": sum(self.acted),
            "windows_played": self.windows_played,
            "ops_used": self.ops_used,
            "calls": self.calls,
            "rejected": self.rejected,
            "faults": self.faults,
            "stopped_early": self.stopped_early,
            "end_reason": self.end_reason,
        })
        return ledger


def replay(scenario: Scenario, seed: int, records: list[dict[str, Any]]) -> tuple[Episode, list[dict[str, Any]]]:
    """Rebuild an episode from a trace. Returns the episode (not finalized)
    and the list of calls whose response did not reproduce."""
    episode = Episode(scenario, seed)
    mismatches = []
    for rec in records:
        if rec.get("k") != "call":
            continue
        response = episode.call(str(rec.get("tool")), rec.get("args"), record=True)
        expected = rec.get("digest")
        if expected is not None and digest(response) != expected:
            mismatches.append({"i": rec.get("i"), "tool": rec.get("tool"), "window": rec.get("window")})
    return episode, mismatches
