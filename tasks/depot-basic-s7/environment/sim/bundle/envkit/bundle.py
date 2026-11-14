"""Bundles: the self-contained copy of code + scenario shipped inside a task.

A Harbor task directory must stand alone, and a container build context
cannot reach outside its own directory. So the generator copies the same
bundle into the three places that need it:

    environment/sim/bundle/   the simulation sidecar (never visible to the agent)
    tests/bundle/             the verifier image
    solution/bundle/          the oracle's reference policy

A bundle holds the `envkit` package, the environment's package, the scenario,
any recorded traces the scenario's policies replay, this task's calibration
entry, and a manifest. The bundle hash covers code, scenario and traces, so
calibration computed against one version of the world can never be applied
silently to another.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from . import __version__
from .scenario import Scenario, load_scenario, sha256_hex

ROOT = Path(__file__).resolve().parent.parent


def source_files(scenario: Scenario, root: Path = ROOT) -> dict[str, bytes]:
    """Relative path -> content for everything the bundle hash covers."""
    files: dict[str, bytes] = {}

    def add_tree(rel: Path) -> None:
        for p in sorted((root / rel).rglob("*.py")):
            if "__pycache__" not in p.parts:
                files[p.relative_to(root).as_posix()] = p.read_bytes()

    add_tree(Path("envkit"))
    # The environment's package: "envs.depot:Depot" -> envs/__init__.py + envs/depot/**
    parts = scenario.env_path.partition(":")[0].split(".")
    top = Path(parts[0])
    if (root / top).is_dir():
        init = root / top / "__init__.py"
        if init.exists():
            files[(top / "__init__.py").as_posix()] = init.read_bytes()
        sub = top / parts[1] if len(parts) > 1 else top
        if (root / sub).is_dir():
            add_tree(sub)
        elif (root / sub).with_suffix(".py").exists():
            files[sub.with_suffix(".py").as_posix()] = (root / sub).with_suffix(".py").read_bytes()
    else:
        files[top.with_suffix(".py").as_posix()] = (root / top).with_suffix(".py").read_bytes()

    files["scenario.toml"] = scenario.source.encode()
    for name in [scenario.reference, *scenario.anchors]:
        if name.startswith("replay:"):
            rel = name.partition(":")[2]
            files[rel] = (root / rel).read_bytes()
    return files


def bundle_hash(files: dict[str, bytes]) -> str:
    lines = [f"{path}\0{sha256_hex(data)}" for path, data in sorted(files.items())]
    return sha256_hex("\n".join(lines).encode())[:16]


def write_bundle(dest: Path, scenario: Scenario, seed: int, calibration: dict[str, Any] | None,
                 root: Path = ROOT) -> str:
    """Write a bundle directory and return its hash."""
    files = source_files(scenario, root)
    h = bundle_hash(files)
    if dest.exists():
        shutil.rmtree(dest)
    for rel, data in files.items():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = {"scenario": scenario.id, "seed": int(seed), "bundle": h, "engine": __version__}
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    if calibration is not None:
        (dest / "calibration.json").write_text(json.dumps(calibration, indent=1, sort_keys=True) + "\n")
    return h


def load_bundle(directory: str | Path) -> tuple[Scenario, dict[str, Any], dict[str, Any] | None]:
    d = Path(directory)
    scenario = load_scenario(d / "scenario.toml")
    manifest = json.loads((d / "manifest.json").read_text())
    cal_path = d / "calibration.json"
    calibration = json.loads(cal_path.read_text()) if cal_path.exists() else None
    return scenario, manifest, calibration
