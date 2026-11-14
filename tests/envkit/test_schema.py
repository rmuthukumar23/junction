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
    assert p["mode"] == {"enum": ["a", "b"], "default": "a"}
    assert p["tags"]["items"] == {"type": "string"}
    assert p["limits"]["additionalProperties"] == {"type": "number"}
    assert p["note"] == {"type": "string"}          # omittable, so null is not advertised


def test_omittable_optionals_never_advertise_null_but_still_accept_it():
    """Gemini's function-calling validator rejects nullable unions (a nullable array
    stopped every Gemini run on the greenhouse before its first call)."""
    def tool_fn(self, hours: Optional[list[int]] = None, caps: Optional[dict[str, float]] = None,
                mode: Optional[Literal["on", "off"]] = None, must: Optional[int] = ...):
        """A tool."""
    params = [p for p in params_of(tool_fn)]
    props = input_schema(params)["properties"]
    assert props["hours"] == {"type": "array", "items": {"type": "integer"}}
    assert props["caps"] == {"type": "object", "additionalProperties": {"type": "number"}}
    assert props["mode"] == {"enum": ["on", "off"]}
    assert "null" not in str({k: v for k, v in props.items() if k != "must"})
    assert validate(params, {"hours": None, "caps": None, "mode": None, "must": 1}) == \
        {"hours": None, "caps": None, "mode": None, "must": 1}


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
