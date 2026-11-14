"""Tool-argument schemas derived from Python type hints.

    @tool
    def order_stock(self, item: Annotated[str, "Item id"], qty: int = 1): ...

becomes a JSON Schema for the MCP tool listing and a validator used by the
engine. The engine validates every call itself, so a call made through MCP, a
scripted policy, the console or a replay is checked by exactly the same code.

Supported annotations: int, float, str, bool, list[T], dict[str, T],
Literal[...], Optional[T], Annotated[T, "description"], and a TypedDict (an object
with named, typed fields; `Required`/`total=False` mark which are required).
"""
from __future__ import annotations

import inspect
import math
import types
import typing
from dataclasses import dataclass
from typing import Any, Callable, Literal, Union, get_args, get_origin

_MISSING = object()


class ArgumentError(ValueError):
    """A call's arguments do not match the tool's schema."""


@dataclass(frozen=True)
class Param:
    name: str
    annotation: Any
    default: Any = _MISSING
    description: str = ""

    @property
    def required(self) -> bool:
        return self.default is _MISSING


def params_of(fn: Callable[..., Any]) -> list[Param]:
    """Read a method's parameters (skipping `self`) into Param objects."""
    hints = typing.get_type_hints(fn, include_extras=True)
    out = []
    for name, p in inspect.signature(fn).parameters.items():
        if name == "self":
            continue
        if p.kind not in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY):
            raise TypeError(f"{fn.__name__}: *args/**kwargs are not allowed in tools")
        if name not in hints:
            raise TypeError(f"{fn.__name__}: parameter '{name}' needs a type hint")
        ann, desc = hints[name], ""
        if get_origin(ann) is typing.Annotated:
            ann, *meta = get_args(ann)
            desc = " ".join(m for m in meta if isinstance(m, str))
        _json_schema(ann)  # fail at import time on unsupported annotations
        default = _MISSING if p.default is inspect.Parameter.empty else p.default
        out.append(Param(name, ann, default, desc))
    return out


def input_schema(params: list[Param]) -> dict[str, Any]:
    props, required = {}, []
    for p in params:
        s = dict(_json_schema(p.annotation))
        if p.description:
            s["description"] = p.description
        if p.required:
            required.append(p.name)
        elif p.default is not None:
            s["default"] = p.default
        props[p.name] = s
    schema: dict[str, Any] = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


def validate(params: list[Param], args: Any, strict: bool = False) -> dict[str, Any]:
    """Return keyword arguments, or raise ArgumentError. Loose number encodings
    ("5", 5.0 for an integer) are accepted unless `strict` is set."""
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ArgumentError("arguments must be an object")
    known = {p.name for p in params}
    extra = sorted(set(args) - known)
    if extra:
        raise ArgumentError(
            f"unknown argument(s) {extra}; valid arguments: {sorted(known) or 'none'}"
        )
    out = {}
    for p in params:
        if p.name in args:
            out[p.name] = _coerce(p.annotation, args[p.name], p.name, strict)
        elif p.required:
            raise ArgumentError(f"missing required argument '{p.name}'")
        else:
            out[p.name] = p.default
    return out


# -- internals ----------------------------------------------------------------

def _is_optional(ann: Any) -> tuple[bool, Any]:
    if get_origin(ann) in (Union, types.UnionType):
        rest = [a for a in get_args(ann) if a is not type(None)]
        if len(rest) == 1 and len(get_args(ann)) == 2:
            return True, rest[0]
        raise TypeError(f"unsupported union {ann!r}; only Optional[T] is supported")
    return False, ann


def _json_schema(ann: Any) -> dict[str, Any]:
    optional, inner = _is_optional(ann)
    if optional:
        # An Optional parameter is simply not required; `validate` still accepts null.
        # No "null" in the schema: Gemini's function declarations reject type lists and
        # an anyOf around an array (OpenCode leaves `items` outside the anyOf).
        return _json_schema(inner)
    if ann is bool:
        return {"type": "boolean"}
    if ann is int:
        return {"type": "integer"}
    if ann is float:
        return {"type": "number"}
    if ann is str:
        return {"type": "string"}
    origin = get_origin(ann)
    if origin is Literal:
        values = list(get_args(ann))
        kinds = {type(v) for v in values}
        if kinds == {str}:
            return {"type": "string", "enum": values}   # Gemini wants a type with every enum
        return {"enum": values}
    if origin is list:
        (item,) = get_args(ann) or (str,)
        return {"type": "array", "items": _json_schema(item)}
    if origin is dict:
        key, val = get_args(ann) or (str, str)
        if key is not str:
            raise TypeError("dict keys must be str")
        return {"type": "object", "additionalProperties": _json_schema(val)}
    if typing.is_typeddict(ann):
        props = {}
        for name, field in _fields(ann).items():
            inner, desc = _annotated(field)
            props[name] = {**_json_schema(inner), **({"description": desc} if desc else {})}
        out: dict[str, Any] = {"type": "object", "properties": props, "additionalProperties": False}
        required = _required(ann)
        if required:
            out["required"] = required
        return out
    raise TypeError(f"unsupported tool parameter type {ann!r}")


def _required(ann: Any) -> list[str]:
    """Required fields of a TypedDict, also when its annotations are strings."""
    fields = _fields(ann)
    marked = {n for n, f in fields.items() if get_origin(f) is typing.Required}
    unmarked = {n for n, f in fields.items() if get_origin(f) is typing.NotRequired}
    return sorted((set(ann.__required_keys__) | marked) - unmarked)


def _fields(ann: Any) -> dict[str, Any]:
    return typing.get_type_hints(ann, include_extras=True)


def _annotated(ann: Any) -> tuple[Any, str]:
    """Strip Annotated (and Required/NotRequired) from a field; return its description."""
    desc = ""
    while True:
        origin = get_origin(ann)
        if origin is typing.Annotated:
            ann, *meta = get_args(ann)
            desc = " ".join(m for m in meta if isinstance(m, str)) or desc
        elif origin in (typing.Required, typing.NotRequired):
            (ann,) = get_args(ann)
        else:
            return ann, desc


def _coerce(ann: Any, value: Any, path: str, strict: bool = False) -> Any:
    optional, inner = _is_optional(ann)
    if optional:
        return None if value is None else _coerce(inner, value, path, strict)
    if value is None:
        raise ArgumentError(f"'{path}' must not be null")
    if ann is bool:
        if isinstance(value, bool):
            return value
        if not strict and isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        raise ArgumentError(f"'{path}' must be a boolean")
    if ann is int or ann is float:
        return _number(ann, value, path, strict)
    if ann is str:
        if not isinstance(value, str):
            raise ArgumentError(f"'{path}' must be a string")
        return value
    origin = get_origin(ann)
    if origin is Literal:
        choices = get_args(ann)
        if value not in choices or isinstance(value, bool) != isinstance(
            choices[choices.index(value)], bool
        ):
            raise ArgumentError(f"'{path}' must be one of {list(choices)}")
        return value
    if origin is list:
        (item,) = get_args(ann) or (str,)
        if not isinstance(value, list):
            raise ArgumentError(f"'{path}' must be an array")
        return [_coerce(item, v, f"{path}[{i}]", strict) for i, v in enumerate(value)]
    if origin is dict:
        _, val = get_args(ann) or (str, str)
        if not isinstance(value, dict):
            raise ArgumentError(f"'{path}' must be an object")
        return {str(k): _coerce(val, v, f"{path}.{k}", strict) for k, v in value.items()}
    if typing.is_typeddict(ann):
        if not isinstance(value, dict):
            raise ArgumentError(f"'{path}' must be an object")
        fields = _fields(ann)
        extra = sorted(set(value) - set(fields))
        if extra:
            raise ArgumentError(f"'{path}': unknown field(s) {extra}")
        missing = sorted(set(_required(ann)) - set(value))
        if missing:
            raise ArgumentError(f"'{path}': missing field(s) {missing}")
        return {k: _coerce(_annotated(fields[k])[0], v, f"{path}.{k}", strict) for k, v in value.items()}
    raise ArgumentError(f"'{path}': unsupported type")


def _number(ann: Any, value: Any, path: str, strict: bool = False) -> Any:
    # Agents and harnesses are loose with number encodings ("5", 5.0), so accept
    # anything that is unambiguously the right number rather than failing the
    # call on formatting.
    if isinstance(value, bool):
        raise ArgumentError(f"'{path}' must be a number, not a boolean")
    if strict and ann is int and type(value) is not int:
        raise ArgumentError(f"'{path}' must be an integer")
    if isinstance(value, str) and not strict:
        try:
            value = float(value.strip())
        except ValueError:
            raise ArgumentError(f"'{path}' must be a number") from None
    if not isinstance(value, (int, float)):
        raise ArgumentError(f"'{path}' must be a number")
    if isinstance(value, float) and not math.isfinite(value):
        raise ArgumentError(f"'{path}' must be finite")
    if ann is int:
        if float(value) != math.floor(float(value)):
            raise ArgumentError(f"'{path}' must be a whole number")
        return int(value)
    return float(value)
