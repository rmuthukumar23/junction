"""Shared building blocks for the data-file schemas.

Each owner's schema module (crop.py, facility.py, market.py) turns one TOML
table into a frozen dataclass using `Table`, which rejects missing keys, stray
keys and out-of-range values with an error naming the file and key:

    def parse_crop(raw: dict, source: str) -> CropSpec:
        t = Table(raw, source)
        spec = CropSpec(id=t.str("id"), density_per_m2=t.num("planting.density_per_m2", lo=0.1), ...)
        t.done()          # fails if the file has keys nobody read
        return spec

A value written `{min = a, max = b}` is a hidden per-seed parameter. `Table.param`
returns a `Range` for it (or a float for a plain number); `resolve` replaces every
Range in a spec with a value drawn from a seeded stream named after its key, so
adding a parameter to one file never shifts the draws of another.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, TypeVar

from envkit.rng import Rng

T = TypeVar("T")
_MISSING = object()


class ConfigError(ValueError):
    """A data file is invalid. The message names the file and the key."""


@dataclass(frozen=True)
class Range:
    """A hidden per-seed parameter: drawn uniformly in [min, max]. The range is
    published to the agent; the drawn value is not."""
    key: str          # dotted key in its file, also the RNG stream name
    min: float
    max: float

    def draw(self, rng: Rng) -> float:
        return self.min if self.min == self.max else rng.stream(self.key).uniform(self.min, self.max)


Param = float | Range


class Table:
    """Strict reader for one TOML document or sub-table."""

    def __init__(self, raw: dict[str, Any], source: str, prefix: str = ""):
        if not isinstance(raw, dict):
            raise ConfigError(f"{source}: {prefix or 'file'} must be a table")
        self.raw, self.source, self.prefix = raw, source, prefix
        self._read: set[str] = set()

    # -- access ------------------------------------------------------------------------

    def _get(self, key: str, default: Any = _MISSING) -> Any:
        node: Any = self.raw
        parts = key.split(".")
        for i, part in enumerate(parts):
            if not isinstance(node, dict) or part not in node:
                if default is _MISSING:
                    raise ConfigError(f"{self.source}: missing key '{self._full(key)}'")
                return default
            node = node[part]
        self._read.add(key)
        return node

    def _full(self, key: str) -> str:
        return f"{self.prefix}.{key}" if self.prefix else key

    def _fail(self, key: str, msg: str) -> ConfigError:
        return ConfigError(f"{self.source}: '{self._full(key)}' {msg}")

    def str(self, key: str, default: Any = _MISSING, choices: tuple[str, ...] | None = None) -> str:
        v = self._get(key, default)
        if not isinstance(v, str):
            raise self._fail(key, f"must be a string, got {v!r}")
        if choices is not None and v not in choices:
            raise self._fail(key, f"must be one of {list(choices)}, got {v!r}")
        return v

    def num(self, key: str, default: Any = _MISSING, lo: float | None = None, hi: float | None = None) -> float:
        v = self._get(key, default)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise self._fail(key, f"must be a number, got {v!r}")
        self._check_bounds(key, float(v), lo, hi)
        return float(v)

    def int(self, key: str, default: Any = _MISSING, lo: int | None = None, hi: int | None = None) -> int:
        v = self._get(key, default)
        if isinstance(v, bool) or not isinstance(v, int):
            raise self._fail(key, f"must be an integer, got {v!r}")
        self._check_bounds(key, v, lo, hi)
        return v

    def bool(self, key: str, default: Any = _MISSING) -> bool:
        v = self._get(key, default)
        if not isinstance(v, bool):
            raise self._fail(key, f"must be true or false, got {v!r}")
        return v

    def param(self, key: str, default: Any = _MISSING, lo: float | None = None, hi: float | None = None) -> Param:
        """A number, or `{min, max}` for a hidden per-seed parameter."""
        v = self._get(key, default)
        if isinstance(v, dict):
            if set(v) != {"min", "max"}:
                raise self._fail(key, "as a range must have exactly 'min' and 'max'")
            a, b = v["min"], v["max"]
            if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in (a, b)) or a > b:
                raise self._fail(key, f"needs numeric min <= max, got {v!r}")
            self._check_bounds(key, float(a), lo, hi)
            self._check_bounds(key, float(b), lo, hi)
            return Range(self._full(key), float(a), float(b))
        return self.num(key, default, lo, hi)

    def list(self, key: str, default: Any = _MISSING) -> list[Any]:
        v = self._get(key, default)
        if not isinstance(v, list):
            raise self._fail(key, f"must be a list, got {v!r}")
        return v

    def sub(self, key: str) -> "Table":
        """A nested table, read with its own done() check."""
        return Table(self._get(key), self.source, self._full(key))

    def has(self, key: str) -> bool:
        return self._get(key, None) is not None

    def done(self) -> None:
        """Fail on any key in the file that no reader asked for (typos, stale keys)."""
        stray = sorted(self._unread(self.raw, ""))
        if stray:
            raise ConfigError(f"{self.source}: unknown key(s) {[self._full(k) for k in stray]}")

    def _unread(self, node: dict[str, Any], path: str) -> list[str]:
        out = []
        for k, v in node.items():
            key = f"{path}.{k}" if path else k
            if key in self._read:
                continue
            if isinstance(v, dict) and any(r.startswith(key + ".") for r in self._read):
                out += self._unread(v, key)
            else:
                out.append(key)
        return out

    def _check_bounds(self, key: str, v: float, lo: float | None, hi: float | None) -> None:
        if lo is not None and v < lo:
            raise self._fail(key, f"must be >= {lo}, got {v}")
        if hi is not None and v > hi:
            raise self._fail(key, f"must be <= {hi}, got {v}")


def resolve(spec: T, rng: Rng) -> T:
    """Return a copy of a (nested) frozen dataclass with every Range drawn.
    Lists, tuples and dicts of dataclasses are resolved too."""
    def walk(v: Any) -> Any:
        if isinstance(v, Range):
            return v.draw(rng)
        if dataclasses.is_dataclass(v) and not isinstance(v, type):
            return dataclasses.replace(v, **{f.name: walk(getattr(v, f.name)) for f in dataclasses.fields(v)})
        if isinstance(v, tuple):
            return tuple(walk(x) for x in v)
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        return v
    return walk(spec)


def ranges(spec: Any) -> dict[str, tuple[float, float]]:
    """Every hidden parameter's published range, keyed by its dotted key (for get_rules)."""
    out: dict[str, tuple[float, float]] = {}

    def walk(v: Any) -> None:
        if isinstance(v, Range):
            out[v.key] = (v.min, v.max)
        elif dataclasses.is_dataclass(v) and not isinstance(v, type):
            for f in dataclasses.fields(v):
                walk(getattr(v, f.name))
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
    walk(spec)
    return out
