"""The action log.

An episode's state is a pure function of (scenario, seed, sequence of calls).
The trace records that sequence, one JSON object per line, so a run can be

  * regraded: the verifier replays the trace in a fresh process and computes
    the score itself, instead of trusting a number produced next to the agent;
  * audited: each record carries a digest of the response the live server
    returned, and replay must reproduce every digest;
  * resumed: if the server restarts mid-episode it rebuilds its state from
    the trace;
  * reused: a recorded human session replays as a reference run, and the
    (call, response) pairs are training data.

Records:
  {"k": "header", "scenario", "seed", "bundle", "engine"}
  {"k": "call", "i", "window", "tool", "args", "ok", "spent", "digest", "response"}
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable


def canonical(obj: Any) -> str:
    """Stable JSON. Floats are rounded to 10 significant digits so a digest
    does not depend on the last bit of a libm result."""
    return json.dumps(_round(obj), sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(obj: Any) -> str:
    return hashlib.sha256(canonical(obj).encode()).hexdigest()[:16]


def _round(obj: Any) -> Any:
    if isinstance(obj, float):
        return float(f"{obj:.10g}")
    if isinstance(obj, dict):
        return {str(k): _round(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_round(v) for v in obj]
    return obj


class Trace:
    """In-memory record list with an optional append-only file behind it."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.records: list[dict[str, Any]] = []
        self._fh = None

    def append(self, record: dict[str, Any]) -> None:
        self.records.append(record)
        if self.path is None:
            return
        if self._fh is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, "a", encoding="utf-8")
        self._fh.write(json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())  # the verifier reads this file; never lose a call

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    @property
    def calls(self) -> list[dict[str, Any]]:
        return [r for r in self.records if r.get("k") == "call"]

    @property
    def header(self) -> dict[str, Any] | None:
        return next((r for r in self.records if r.get("k") == "header"), None)


def read_trace(path: str | Path) -> list[dict[str, Any]]:
    """Read a trace file. A torn final line (crash mid-write) is dropped."""
    records = []
    p = Path(path)
    if not p.exists():
        return records
    lines = p.read_text(encoding="utf-8").splitlines()
    for n, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            if n == len(lines) - 1:
                break
            raise ValueError(f"{p}: line {n + 1} is not valid JSON") from None
        if isinstance(rec, dict):
            records.append(rec)
    return records


def write_trace(path: str | Path, records: Iterable[dict[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, separators=(",", ":"), allow_nan=False) + "\n")
