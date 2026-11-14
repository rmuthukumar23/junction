"""Tool schemas from type hints, and scenario validation."""
from typing import Annotated, Literal, Optional

import pytest

from envkit.core import Environment, tool
from envkit.scenario import ScenarioError, parse_scenario
from envkit.schema import ArgumentError, input_schema, params_of, validate

from conftest import ROOT


def sample(self, name: Annotated[str, "Who"], n: int = 1, ratio: float = 0.5, flag: bool = False,
           mode: Literal["a", "b"] = "a", tags: list[str] = [], limits: dict[str, float] = {},
           note: Optional[str] = None):
    """A tool."""


PARAMS = params_of(sample)


def test_json_schema():
    s = input_schema(PARAMS)
    assert s["required"] == ["name"] and s["additionalProperties"] is False
    p = s["properties"]
    assert p["name"] == {"type": "string", "description": "Who"}
    assert p["n"] == {"type": "integer", "default": 1}
    assert p["mode"] == {"type": "string", "enum": ["a", "b"], "default": "a"}
    assert p["tags"]["items"] == {"type": "string"}
    assert p["limits"]["additionalProperties"] == {"type": "number"}
    assert p["note"] == {"type": "string"}        # optional = not required; null still validates


def _walk(schema):
    yield schema
    for key in ("items", "additionalProperties"):
        if isinstance(schema.get(key), dict):
            yield from _walk(schema[key])
    for sub in schema.get("properties", {}).values():
        yield from _walk(sub)


def test_every_greenhouse_tool_schema_is_gemini_compatible():
    """Gemini rejected set_climate's Optional[list[int]] as a type list ("items: field
    predicate failed"), so the agent made 0 calls. Keep to the subset Gemini accepts."""
    from envkit.core import Episode
    from envkit.scenario import load_scenario
    tools = Episode(load_scenario(ROOT / "scenarios" / "smoke.toml"), 1).describe_tools()
    assert any(t["name"] == "set_climate" for t in tools)
    for t in tools:
        for node in _walk(t["input_schema"]):
            assert not isinstance(node.get("type"), list), (t["name"], node)
            assert "anyOf" not in node, (t["name"], node)
            if node.get("type") == "array":
                assert "items" in node, (t["name"], node)
            if "enum" in node:
                assert "type" in node, (t["name"], node)


def test_validate_fills_defaults_and_coerces():
    out = validate(PARAMS, {"name": "x", "n": "3", "ratio": 2, "limits": {"hi": 1}})
    assert out == {"name": "x", "n": 3, "ratio": 2.0, "flag": False, "mode": "a", "tags": [],
                   "limits": {"hi": 1.0}, "note": None}


@pytest.mark.parametrize("args", [
    {}, {"name": 1}, {"name": "x", "n": True}, {"name": "x", "n": 1.5}, {"name": "x", "mode": "c"},
    {"name": "x", "tags": "a"}, {"name": "x", "ratio": float("nan")}, {"name": "x", "extra": 1}, "not an object",
])
def test_validate_rejects(args):
    with pytest.raises(ArgumentError):
        validate(PARAMS, args)


def test_tools_need_docstrings_and_type_hints():
    class NoDoc(Environment):
        @tool
        def act(self, x: int):
            pass

    with pytest.raises(TypeError, match="docstring"):
        NoDoc({}, None, None).tool_specs()

    def untyped(self, x):
        """Doc."""

    with pytest.raises(TypeError, match="type hint"):
        params_of(untyped)


def _edited(old: str, new: str) -> str:
    text = (ROOT / "tests" / "envkit" / "fixtures" / "depot-basic.toml").read_text()
    assert old in text
    return text.replace(old, new)


@pytest.mark.parametrize("old,new,message", [
    ("weight = 0.7", "weight = 0.6", "sum to 1"),
    ("at_window = 8", "at_window = 99", "outside"),
    ('top_anchors = ["rule-based"]\n', "", "top_anchors"),
    ("ops_per_window = 12", "ops_per_window = 0", "ops_per_window"),
])
def test_scenario_errors_are_caught_at_load(old, new, message):
    with pytest.raises(ScenarioError, match=message):
        parse_scenario(_edited(old, new))


def test_event_channels(scenario):
    assert [e.channel for e in scenario.events] == ["announced", "silent", "rumored", "announced"]


def test_prompt_placeholders_are_filled(scenario):
    prompt = scenario.render_prompt()
    assert "$" not in prompt and "30 windows of 12 hours" in prompt and "12 tool operations" in prompt
