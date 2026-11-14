"""The closed library of response curves a data file can choose by name.

    temperature = { curve = "cardinal", t_min = 2.0, t_opt = 20.0, t_max = 30.0 }

    curve = parse_curve(table.sub("growth.temperature"))
    factor = curve(temp_c)

Adding a curve kind is a code change here, with a test. Choosing and tuning
one is a data change only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .base import ConfigError, Table


@dataclass(frozen=True)
class Cardinal:
    """0 at or beyond t_min and t_max, 1 at t_opt (Yan and Hunt 1999 beta form)."""
    t_min: float
    t_opt: float
    t_max: float

    def __call__(self, x: float) -> float:
        if x <= self.t_min or x >= self.t_max:
            return 0.0
        a = (self.t_opt - self.t_min) / (self.t_max - self.t_opt)
        return ((self.t_max - x) / (self.t_max - self.t_opt)) * ((x - self.t_min) / (self.t_opt - self.t_min)) ** a


@dataclass(frozen=True)
class Saturating:
    """x / (x + half_sat): 0 at 0, 0.5 at half_sat, towards 1. Negative x gives 0."""
    half_sat: float

    def __call__(self, x: float) -> float:
        return 0.0 if x <= 0 else x / (x + self.half_sat)


@dataclass(frozen=True)
class LinearAbove:
    """rate per unit above threshold, 0 below it. Used for stress accumulation."""
    threshold: float
    rate: float

    def __call__(self, x: float) -> float:
        return self.rate * max(0.0, x - self.threshold)


@dataclass(frozen=True)
class LinearBelow:
    """rate per unit below threshold, 0 above it."""
    threshold: float
    rate: float

    def __call__(self, x: float) -> float:
        return self.rate * max(0.0, self.threshold - x)


@dataclass(frozen=True)
class Piecewise:
    """Linear interpolation between points sorted by x, flat beyond the ends."""
    points: tuple[tuple[float, float], ...]

    def __call__(self, x: float) -> float:
        pts = self.points
        if x <= pts[0][0]:
            return pts[0][1]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x <= x1:
                return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
        return pts[-1][1]


Curve = Cardinal | Saturating | LinearAbove | LinearBelow | Piecewise
KINDS = ("cardinal", "saturating", "linear_above", "linear_below", "piecewise")


def parse_curve(t: Table) -> Curve:
    """Read `{curve = "<kind>", ...}`. Calls t.done(), so stray keys fail."""
    kind = t.str("curve", choices=KINDS)
    if kind == "cardinal":
        c: Curve = Cardinal(t.num("t_min"), t.num("t_opt"), t.num("t_max"))
        if not c.t_min < c.t_opt < c.t_max:
            raise ConfigError(f"{t.source}: '{t.prefix}' needs t_min < t_opt < t_max")
    elif kind == "saturating":
        c = Saturating(t.num("half_sat", lo=1e-12))
    elif kind == "linear_above":
        c = LinearAbove(t.num("threshold"), t.num("rate", lo=0))
    elif kind == "linear_below":
        c = LinearBelow(t.num("threshold"), t.num("rate", lo=0))
    else:
        raw = t.list("points")
        try:
            pts = tuple((float(p[0]), float(p[1])) for p in raw)
        except (TypeError, ValueError, IndexError):
            raise ConfigError(f"{t.source}: '{t.prefix}.points' must be a list of [x, y] pairs") from None
        if len(pts) < 2 or any(b[0] <= a[0] for a, b in zip(pts, pts[1:])) or \
                any(not math.isfinite(v) for p in pts for v in p):
            raise ConfigError(f"{t.source}: '{t.prefix}.points' needs >= 2 finite points with increasing x")
        c = Piecewise(pts)
    t.done()
    return c
