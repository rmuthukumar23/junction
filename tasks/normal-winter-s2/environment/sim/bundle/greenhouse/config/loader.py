"""Turn a scenario's `[env]` table into resolved specs for one seed.

    [env]
    facility      = "data/facilities/nl_two_compartment.toml"
    climate       = "data/climates/nl_january.toml"
    energy_prices = "data/energy_prices/nl_winter.toml"
    market        = "data/markets/nl_winter.toml"
    crops         = ["data/crops/lettuce_butterhead.toml", "data/crops/broccoli_micro.toml"]
    events        = ["data/events/boiler_trip.toml"]
    horizon_days  = 42
    substeps_per_hour = 12
    overrides = { "market.crops.broccoli_micro.price_eur" = 28.0, "crops.lettuce_butterhead.planting.density_per_m2" = 18 }

Each file is parsed by its owner's `parse_*` function (PARSERS) after
`overrides` are applied to the raw TOML. An override key is
`<kind>.<dotted key>` for a single-file kind, or `<kind>.<id>.<dotted key>` for
crops and events. Hidden `{min, max}` parameters are then drawn for this seed,
each from a stream named after its kind, file id and key, so changing one file
never shifts the draws of another. `published_ranges` lists every range for
get_rules.

Paths are relative to the project root, which is the bundle directory inside a
Harbor task (envkit copies the files there; see Environment.data_files).
"""
from __future__ import annotations

import copy
import importlib
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from envkit.bundle import ROOT
from envkit.rng import Rng

from .base import ConfigError, ranges, resolve

# kind -> (module, function, owner). Single-file kinds hold one spec; list kinds hold several.
PARSERS: dict[str, tuple[str, str, str]] = {
    "facility": ("greenhouse.config.facility", "parse_facility", "Emre"),
    "climate": ("greenhouse.config.facility", "parse_climate", "Emre"),
    "energy_prices": ("greenhouse.config.facility", "parse_energy_prices", "Emre"),
    "market": ("greenhouse.config.market", "parse_market", "Rowan"),
    "crops": ("greenhouse.config.crop", "parse_crop", "Lucas"),
    "events": ("greenhouse.config.market", "parse_event", "Rowan"),
}
SINGLE = ("facility", "climate", "energy_prices", "market")
LISTS = ("crops", "events")
_ENV_KEYS = {*SINGLE, *LISTS, "horizon_days", "substeps_per_hour", "overrides", "modules"}


@dataclass(frozen=True)
class Config:
    facility: Any
    climate: Any
    energy_prices: Any
    market: Any
    crops: dict[str, Any]                 # crop id -> CropSpec
    events: dict[str, Any]                # event id -> EventSpec
    horizon_h: int
    substeps_per_hour: int
    published_ranges: dict[str, dict[str, tuple[float, float]]] = field(default_factory=dict)


def data_files(env: dict[str, Any]) -> list[str]:
    """Every data file an [env] table names, for bundling."""
    files = [env[k] for k in SINGLE if k in env]
    for k in LISTS:
        files += list(env.get(k, []))
    return [str(f) for f in files]


def read_raw(env: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    """kind -> raw TOML dict (single kinds) or list of (path, dict) (list kinds)."""
    stray = sorted(set(env) - _ENV_KEYS)
    if stray:
        raise ConfigError(f"scenario [env]: unknown key(s) {stray}")
    raw: dict[str, Any] = {}
    for kind in SINGLE:
        if kind not in env:
            raise ConfigError(f"scenario [env]: missing '{kind}'")
        raw[kind] = (str(env[kind]), _read(root, env[kind]))
    for kind in LISTS:
        raw[kind] = [(str(p), _read(root, p)) for p in env.get(kind, [])]
    return raw


def load(env: dict[str, Any], rng: Rng, root: Path = ROOT,
         parsers: dict[str, Callable[[dict, str], Any]] | None = None) -> Config:
    """Read, override, parse and resolve. `parsers` replaces PARSERS (tests)."""
    raw = read_raw(env, root)
    _apply_overrides(raw, dict(env.get("overrides", {})))
    parse = {kind: (parsers or {}).get(kind) or _parser(kind) for kind in PARSERS}

    specs: dict[str, Any] = {kind: parse[kind](doc, path) for kind, (path, doc) in
                             ((k, raw[k]) for k in SINGLE)}
    lists: dict[str, dict[str, Any]] = {}
    for kind in LISTS:
        lists[kind] = {}
        for path, doc in raw[kind]:
            spec = parse[kind](doc, path)
            sid = _id_of(spec, path)
            if sid in lists[kind]:
                raise ConfigError(f"{path}: duplicate {kind} id '{sid}'")
            lists[kind][sid] = spec

    published = {kind: ranges(specs[kind]) for kind in SINGLE}
    published.update({f"{kind}.{sid}": ranges(s) for kind in LISTS for sid, s in lists[kind].items()})
    params = rng.stream("params")
    resolved = {kind: resolve(specs[kind], params.stream(f"{kind}/{_id_of(specs[kind], kind)}")) for kind in SINGLE}
    resolved_lists = {kind: {sid: resolve(s, params.stream(f"{kind}/{sid}")) for sid, s in lists[kind].items()}
                      for kind in LISTS}

    horizon_days = env.get("horizon_days")
    if not isinstance(horizon_days, (int, float)) or isinstance(horizon_days, bool) or horizon_days <= 0:
        raise ConfigError("scenario [env]: 'horizon_days' must be a positive number")
    substeps = env.get("substeps_per_hour", 12)
    if not isinstance(substeps, int) or isinstance(substeps, bool) or substeps < 1:
        raise ConfigError("scenario [env]: 'substeps_per_hour' must be a positive integer")
    return Config(resolved["facility"], resolved["climate"], resolved["energy_prices"], resolved["market"],
                  resolved_lists["crops"], resolved_lists["events"], round(horizon_days * 24), substeps,
                  {k: v for k, v in published.items() if v})


def _read(root: Path, rel: Any) -> dict[str, Any]:
    path = Path(str(rel))
    if path.is_absolute() or ".." in path.parts:
        raise ConfigError(f"data file {rel!r} must be a path inside the project")
    try:
        return tomllib.loads((root / path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"data file not found: {rel}") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{rel}: invalid TOML: {e}") from None


def _parser(kind: str) -> Callable[[dict, str], Any]:
    module, fn, owner = PARSERS[kind]
    try:
        return getattr(importlib.import_module(module), fn)
    except ModuleNotFoundError as e:
        if e.name != module:
            raise
        raise ConfigError(f"no parser for '{kind}' yet: {module}.{fn} is not built ({owner})") from None
    except AttributeError:
        raise ConfigError(f"no parser for '{kind}' yet: {module} has no {fn} ({owner})") from None


def _id_of(spec: Any, where: str) -> str:
    sid = getattr(spec, "id", None) if not isinstance(spec, dict) else spec.get("id")
    if not isinstance(sid, str) or not sid:
        raise ConfigError(f"{where}: a parsed spec needs a string 'id'")
    return sid


def _apply_overrides(raw: dict[str, Any], overrides: dict[str, Any]) -> None:
    for key, value in sorted(overrides.items()):
        kind, _, rest = key.partition(".")
        if kind in SINGLE:
            path, doc = raw[kind]
            dotted = rest
        elif kind in LISTS:
            sid, _, dotted = rest.partition(".")
            matches = [(p, d) for p, d in raw[kind] if d.get("id") == sid]
            if not matches:
                raise ConfigError(f"override '{key}': no {kind} file with id '{sid}'")
            path, doc = matches[0]
        else:
            raise ConfigError(f"override '{key}': unknown kind '{kind}'")
        if not dotted:
            raise ConfigError(f"override '{key}' needs a key after the kind")
        *parents, leaf = dotted.split(".")
        node = doc
        for part in parents:
            if isinstance(node, list):
                # An array of tables is addressed by its items' id: facility.compartments.A.crop
                found = [item for item in node if isinstance(item, dict) and item.get("id") == part]
                if not found:
                    raise ConfigError(f"override '{key}': {path} has no item with id '{part}'")
                node = found[0]
                continue
            if not isinstance(node.get(part), (dict, list)):
                raise ConfigError(f"override '{key}': {path} has no table '{part}'")
            node = node[part]
        if not isinstance(node, dict):
            raise ConfigError(f"override '{key}': name an item by its id after '{parents[-1]}'")
        if leaf not in node:
            raise ConfigError(f"override '{key}': {path} has no key '{dotted}' to override")
        node[leaf] = copy.deepcopy(value)
