"""The prompt format shared by data generation, training and the local benchmark.

One training example is one morning: the task instruction (exactly what Harbor shows the
agent), then a user turn holding the agent's own recent actions and today's briefing, then
the assistant's single `env_submit_day` tool call. A whole 42-day conversation is about
200k tokens, too long for a small model, so the history is compacted instead.

The tool is named `env_submit_day` because that is how OpenCode exposes the `submit_day`
tool of the MCP server `env` (see any runs/normal-winter/*/trajectory.json); training on the
same name lets one model play both here and through Harbor.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from envkit.core import Environment, Episode  # noqa: E402
from envkit.harbor import SIM_PORT, SIM_SERVICE  # noqa: E402
from envkit.scenario import Scenario, load_scenario  # noqa: E402

TOOL = "env_submit_day"
HISTORY_DAYS = 7
FORECAST_HOURS = 48
# The rules the student is shown. The crop growth tables, the facility and the hidden-parameter
# ranges are the same on every seed, so the student learns them from the examples; dropping
# them (and the day-0 briefing, which the first user turn repeats) halves the prompt, and
# attention cost grows with its square. See docs/DECISIONS.md, "fine-tuning prompt".
KEPT_RULES = ("objective", "business", "turn", "repairs", "settings", "clock")
ARTIFACTS = ROOT / "artifacts" / "finetune"


def scenario_from(name: str) -> Scenario:
    """A scenario by id (`normal-winter`) or by path."""
    path = Path(name)
    if not path.suffix:
        path = ROOT / "scenarios" / f"{name}.toml"
    return load_scenario(path)


def parse_seeds(text: str) -> list[int]:
    """'1-6' or '101,104,107' or '1-3,5'."""
    seeds: list[int] = []
    for part in str(text).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            seeds.extend(range(int(lo), int(hi) + 1))
        else:
            seeds.append(int(part))
    return seeds


def code_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def instruction(scenario: Scenario, seed: int, opening: Any = None) -> str:
    """The task instruction, byte for byte as src/envkit/harbor.py writes instruction.md."""
    h = scenario.harbor
    mcp_name = str(h.get("mcp_name", "env"))
    url = f"http://{SIM_SERVICE}:{SIM_PORT}/mcp"
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
    if opening is None:
        opening = Episode(scenario, seed).opening
    shown = "" if opening is None else (
        "\n## Before your first call\n\nThis is everything you are shown before your first tool call "
        "(the rules, and the state of the world now), as JSON:\n\n```json\n"
        + json.dumps(opening, sort_keys=True, separators=(",", ":")) + "\n```\n")
    return scenario.render_prompt() + shown + f'''
## Interface

Every action goes through the tools of the MCP server `{mcp_name}` (`{url}`), which is already connected. Nothing in this container's filesystem affects your result.

{chr(10).join(notes)}
'''


def calibration(scenario: Scenario, seed: int) -> dict[str, Any]:
    """The scoring constants for a scenario and seed: the committed entry when it matches the
    current code, else a cached or fresh `calibrate()` (held-out seeds are not committed;
    calibrating plays every anchor policy once, a few minutes on normal-winter)."""
    from envkit.bundle import ROOT as BUNDLE_ROOT, bundle_hash, source_files
    from envkit.calibrate import calibrate, entry_for, load_calibration

    bundle = bundle_hash(source_files(scenario))
    entry = entry_for(load_calibration(BUNDLE_ROOT), scenario.id, seed)
    if entry and entry.get("bundle") == bundle:
        return entry
    cache = ARTIFACTS / "calibration" / f"{scenario.id}-s{int(seed)}-{bundle}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    entry = calibrate(scenario, seed)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(entry, indent=1, sort_keys=True) + "\n")
    return entry


def anchor_profit(entry: dict[str, Any], name: str) -> float | None:
    return ((entry.get("anchors") or {}).get(name) or {}).get("metrics", {}).get("profit_eur")


def system_prompt(scenario: Scenario, seed: int, opening: Any = None) -> str:
    """The student's system prompt: the scenario prompt and the rules that change decisions day
    to day (market order book, action docs, objective, repairs). About 5k tokens, against about
    16k for the full instruction (`instruction()`), which OpenCode sees through Harbor."""
    if opening is None:
        opening = Episode(scenario, seed).opening
    rules = (opening or {}).get("rules", {})
    kept = {k: rules[k] for k in KEPT_RULES if k in rules}
    return (scenario.render_prompt()
            + "\n## Rules (abridged)\n\nThe crop, facility and hidden-parameter tables are omitted; "
              "they are the same every season.\n\n```json\n"
            + json.dumps(kept, sort_keys=True, separators=(",", ":")) + "\n```\n")


def trim_briefing(briefing: dict[str, Any]) -> dict[str, Any]:
    """The briefing with every forecast series cut to the next FORECAST_HOURS hours."""
    def cut(v: Any) -> Any:
        if isinstance(v, list):
            return v[:FORECAST_HOURS]
        if isinstance(v, dict):
            return {k: cut(x) for k, x in v.items()}
        return v
    if not isinstance(briefing, dict) or "forecast" not in briefing:
        return briefing
    return {**briefing, "forecast": cut(briefing["forecast"])}


def tool_schema(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OpenAI function specs for the episode's tools, `submit_day` renamed to TOOL."""
    out = []
    for t in tools:
        if t["name"] != "submit_day":
            continue
        out.append({"type": "function", "function": {
            "name": TOOL, "description": t.get("description", ""), "parameters": t["input_schema"]}})
    return out


def compact_action(action: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in action.items() if v not in (None, [], {})}


def history_entry(day: int, actions: list[dict[str, Any]], response: dict[str, Any] | None) -> dict[str, Any]:
    """What the player keeps from one day: its actions and which were refused."""
    entry: dict[str, Any] = {"day": day, "actions": [compact_action(a) for a in actions]}
    if response is None:
        return entry
    if not response.get("ok"):
        entry["call_refused"] = (response.get("error") or {}).get("message", "refused")
        return entry
    refused = [{"tool": r.get("tool"), "error": _message(r.get("error"))}
               for r in (response.get("result") or {}).get("results", []) if not r.get("ok")]
    if refused:
        entry["refused"] = refused
    return entry


def _message(error: Any) -> str:
    """A refused action's error: submit_day gives a plain string (env.py), a refused call a dict."""
    if isinstance(error, dict):
        return str(error.get("message", ""))
    return "" if error is None else str(error)


def user_turn(day: int, briefing: dict[str, Any], history: list[dict[str, Any]]) -> str:
    recent = history[-HISTORY_DAYS:]
    return (f"Morning of day {day}. Your turn: one {TOOL} call with today's actions.\n\n"
            f"Your actions on the last {len(recent)} days (oldest first):\n"
            + json.dumps(recent, sort_keys=True, separators=(",", ":"))
            + "\n\nThis morning's briefing:\n"
            + json.dumps(trim_briefing(briefing), sort_keys=True, separators=(",", ":")))


def messages_for(system: str, day: int, briefing: dict[str, Any], history: list[dict[str, Any]],
                 actions: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The chat for one morning; with `actions`, ends in the assistant's tool call (training)."""
    msgs: list[dict[str, Any]] = [{"role": "system", "content": system},
                                  {"role": "user", "content": user_turn(day, briefing, history)}]
    if actions is not None:
        msgs.append({"role": "assistant", "content": "", "tool_calls": [{
            "id": f"call_{day}", "type": "function",
            "function": {"name": TOOL, "arguments": json.dumps({"actions": actions}, separators=(",", ":"))}}]})
    return msgs


_JSON_OBJECT = re.compile(r"\{.*\}", re.S)


def parse_actions(message: dict[str, Any] | None) -> tuple[list[dict[str, Any]], bool]:
    """(actions, malformed) from an OpenAI chat message. A tool call is preferred; a JSON
    object in the text (`{"actions": [...]}`, or Qwen's `<tool_call>` block that a server did
    not parse) is accepted too. Anything else is malformed and becomes no actions."""
    if not message:
        return [], True
    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        if fn.get("name") not in (TOOL, "submit_day"):
            continue
        args = fn.get("arguments")
        try:
            args = json.loads(args) if isinstance(args, str) else args
        except json.JSONDecodeError:
            return [], True
        return _actions_of(args)
    text = message.get("content") or ""
    m = _JSON_OBJECT.search(text)
    if not m:
        return [], True
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return [], True
    if isinstance(obj, dict) and "arguments" in obj:          # {"name": ..., "arguments": {...}}
        obj = obj["arguments"]
    return _actions_of(obj)


def _actions_of(args: Any) -> tuple[list[dict[str, Any]], bool]:
    if not isinstance(args, dict) or not isinstance(args.get("actions"), list):
        return [], True
    actions = [a for a in args["actions"] if isinstance(a, dict) and isinstance(a.get("tool"), str)]
    return actions, len(actions) != len(args["actions"])
