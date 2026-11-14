"""Build the subsystems sim.py composes.

`[env] modules` names a builder `"package.module:function"` with the signature
`build(env_config, rng) -> Modules`. The default, `build` below, loads the data
files and calls each owner's factory. Tests point it at fakes
(`tests/greenhouse/fakes.py`) so the simulator and the tools can be exercised
before every module exists.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Callable

from envkit.rng import Rng

from ..config.loader import load
from ..contracts import BusinessModel, FacilityModel, GrowthModel

DEFAULT_BUILDER = "greenhouse.world.modules:build"


@dataclass
class Modules:
    facility: FacilityModel
    business: BusinessModel
    growth: dict[str, GrowthModel]        # crop id -> model
    horizon_h: int
    substeps_per_hour: int = 12
    published_ranges: dict[str, Any] = field(default_factory=dict)


def builder(env: dict[str, Any]) -> Callable[[dict[str, Any], Rng], Modules]:
    path = str(env.get("modules", DEFAULT_BUILDER))
    module, _, fn = path.partition(":")
    if not fn:
        raise ValueError(f"[env] modules must look like 'package.module:function', got {path!r}")
    return getattr(importlib.import_module(module), fn)


def build(env: dict[str, Any], rng: Rng) -> Modules:
    """The real facility, business and crop models from the scenario's data files."""
    cfg = load(env, rng)
    from .crop import model_for                  # Lucas
    from .energy import build_facility           # Emre
    from .operations import build_business       # Rowan

    facility = build_facility(cfg.facility, cfg.climate, cfg.energy_prices, rng.stream("facility"))
    growth = {cid: model_for(spec) for cid, spec in cfg.crops.items()}
    business = build_business(cfg.market, list(cfg.events.values()), tuple(growth), facility.equipment_ids(),
                              cfg.horizon_h, rng.stream("business"))
    return Modules(facility, business, growth, cfg.horizon_h, cfg.substeps_per_hour, cfg.published_ranges)
