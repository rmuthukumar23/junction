"""The composite scorer.

The score is a pure, linear function of a terminal ledger and the committed
calibration constants, so it can be recomputed by anyone from a ledger alone:

    reward = sum(weight_i * component_i)          each component in [0, 1]

Two kinds of component, both taken from StoreBench:

  anchored   clip01((raw - zero) / scale). `zero` is the best raw result among
             the do-nothing-style anchors, so anything a non-player achieves
             maps to 0. `scale` maps the best scripted "judgment" anchor to
             `target` (0.70 by default), leaving headroom above it.
  mean       the mean of ledger rates that are each already in [0, 1],
             ignoring undefined ones, and 0 if all are undefined, so an
             empty denominator never reads as a perfect rate.

No model, no text matching and no randomness is involved anywhere here.
"""
from __future__ import annotations

from typing import Any

from .scenario import Component, Scenario


def clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def anchored(raw: float | None, zero: float, scale: float) -> float:
    if raw is None or scale <= 0:
        return 0.0
    return clip01((raw - zero) / scale)


def mean_rate(values: list[float | None]) -> float:
    rates = [clip01(float(v)) for v in values if v is not None]
    return sum(rates) / len(rates) if rates else 0.0


def fit_anchor(zero_values: list[float], top_values: list[float], target: float) -> tuple[float, float]:
    """Calibration constants for an anchored component.

    zero  = best raw result among the zero anchors
    scale = (best raw result among the top anchors - zero) / target, rounded
            to two decimals, so the best top anchor scores about `target`.
    """
    zero = max(zero_values)
    scale = round((max(top_values) - zero) / target, 2)
    return zero, scale


def component_value(comp: Component, ledger: dict[str, Any], constants: dict[str, Any] | None) -> float:
    if comp.kind == "anchored":
        if not constants or comp.name not in constants:
            raise KeyError(f"no calibration constants for component '{comp.name}'")
        c = constants[comp.name]
        return anchored(_num(ledger.get(comp.metrics[0])), c["zero"], c["scale"])
    return mean_rate([_num(ledger.get(m)) for m in comp.metrics])


def score(scenario: Scenario, ledger: dict[str, Any], calibration: dict[str, Any] | None) -> dict[str, Any]:
    """Grade a ledger. `calibration` is this scenario-seed's entry from
    calibration.json: {"components": {name: {"zero", "scale"}}, "threshold"}."""
    constants = (calibration or {}).get("components")
    components = {c.name: component_value(c, ledger, constants) for c in scenario.components}
    reward = clip01(sum(c.weight * components[c.name] for c in scenario.components))
    threshold = (calibration or {}).get("threshold")
    return {
        "reward": round(reward, 4),
        "components": {k: round(v, 4) for k, v in components.items()},
        "weights": {c.name: c.weight for c in scenario.components},
        "threshold": threshold,
        "passed": None if threshold is None else bool(round(reward, 4) >= threshold),
    }


def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None
