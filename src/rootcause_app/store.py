"""Runs: one episode each, persisted as an action trace.

A run is a directory:

    <data>/runs/<run_id>/meta.json     scenario, seed, bundle hash, player label, creation time
    <data>/runs/<run_id>/trace.jsonl   every request that could change the run, in order

The trace is the run. After a restart the episode is rebuilt from it
(`envkit.server.resume`), and every reported result is computed by replaying
it in a fresh engine and playing any unplayed days under the default plan.
No score is ever stored and read back, so editing files under <data> cannot
raise one: at most it changes which actions get replayed, and those are
validated like live requests.

Starting a new run never touches earlier ones.
"""
from __future__ import annotations

import json
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from envkit.bundle import ROOT, bundle_hash, source_files
from envkit.core import Episode, replay
from envkit.scenario import Scenario, load_scenario
from envkit.schema import ArgumentError, validate
from envkit.scoring import score
from envkit.server import resume
from envkit.trace import read_trace

from rootcause import outcome

from . import SCENARIO_ID

RUN_ID = re.compile(r"^r[0-9]{14}-[0-9a-f]{6}$")
READ_TOOLS = ("get_rules", "get_status", "get_forecast", "get_pending_tests", "get_events", "get_history")


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


def load_default_scenario() -> Scenario:
    return load_scenario(ROOT / "scenarios" / f"{SCENARIO_ID}.toml")


def evaluate_trace(scenario: Scenario, seed: int, records: list[dict[str, Any]]) -> dict[str, Any]:
    """The trusted result of a trace: replay it, play the remaining days under
    the default plan, and score the final day. This is what the verifier does."""
    episode, mismatches = replay(scenario, seed, records)
    # Days the player actually advanced through; later days ran without them.
    days_played = sum(1 for r in episode.trace.calls if r["tool"] == "advance_day" and r["ok"])
    ledger = episode.result()
    return {
        "reward": score(scenario, ledger, None)["reward"],
        "ledger": ledger,
        "days_played_by_player": days_played,
        "replay": {"calls": sum(1 for r in records if r.get("k") == "call"), "consistent": not mismatches},
        "episode": episode,
    }


class Run:
    def __init__(self, directory: Path, meta: dict[str, Any], scenario: Scenario, bundle: str):
        self.directory, self.meta, self.scenario = directory, meta, scenario
        self.lock = threading.Lock()
        self.episode: Episode = resume(scenario, int(meta["seed"]), directory / "trace.jsonl", bundle)
        self._summary_cache: tuple[int, dict[str, Any]] | None = None

    @property
    def sim(self) -> Any:
        return self.episode.env.sim

    def records(self) -> list[dict[str, Any]]:
        return read_trace(self.directory / "trace.jsonl")

    def read(self, tool: str, args: dict[str, Any] | None = None) -> Any:
        """A read through the tool's own handler and argument validation, without
        adding to the trace. Reads change nothing, so there is nothing to replay."""
        if tool not in READ_TOOLS:
            raise NotFound(f"'{tool}' is not a read")
        spec = self.episode.tools[tool]
        return spec.handler(**validate(list(spec.params), args or {}))

    def call(self, tool: str, args: Any) -> dict[str, Any]:
        """A request exactly as an agent makes it: validated, applied and logged by the engine."""
        return self.episode.call(str(tool), args)

    def summary(self) -> dict[str, Any]:
        n = len(self.episode.trace.records)
        if self._summary_cache and self._summary_cache[0] == n:
            return self._summary_cache[1]
        sim = self.sim
        out: dict[str, Any] = {
            **{k: self.meta.get(k) for k in ("run_id", "scenario", "seed", "player", "created_at", "bundle")},
            "day": sim.day, "days_total": sim.horizon, "done": self.episode.done,
            "end_reason": self.episode.end_reason, "plans_submitted": sim.plans_submitted,
            "tests_ordered": len(sim.tests),
        }
        # A run that is not over has no result, and none is projected: playing
        # the remaining days ahead of time would read hidden state and future
        # weather, and would let a player price a plan before committing to it.
        # If the player never returns, the run simply stays unfinished; ending it
        # (finish_episode) runs the default plan for every remaining day.
        if self.episode.done:
            graded = evaluate_trace(self.scenario, int(self.meta["seed"]), self.records())
            out["result"] = {"reward": graded["reward"],
                             **{k: graded["ledger"][k] for k in ("profit_eur", "revenue_eur", "harvest_kg",
                                                                 "cost_total_eur", "profit_floor_eur",
                                                                 "profit_ceiling_eur")}}
        self._summary_cache = (n, out)
        return out


class RunStore:
    def __init__(self, data_dir: Path, scenario: Scenario | None = None):
        self.scenario = scenario or load_default_scenario()
        self.bundle = bundle_hash(source_files(self.scenario))
        self.root = Path(data_dir) / "runs"
        self.root.mkdir(parents=True, exist_ok=True)
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()

    def create(self, seed: Any, player: Any = None) -> Run:
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 10 ** 9:
            raise ValueError("seed must be a whole number between 0 and 1,000,000,000")
        label = re.sub(r"[^\w .,'()-]", "", str(player or "")).strip()[:40] or "Guest"
        with self._lock:
            now = datetime.now(timezone.utc)
            run_id = f"r{now:%Y%m%d%H%M%S}-{secrets.token_hex(3)}"
            directory = self.root / run_id
            directory.mkdir(parents=True)
            meta = {"run_id": run_id, "scenario": self.scenario.id, "seed": seed, "player": label,
                    "created_at": now.isoformat(timespec="seconds"), "bundle": self.bundle}
            (directory / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")
            run = self._runs[run_id] = Run(directory, meta, self.scenario, self.bundle)
        return run

    def get(self, run_id: str) -> Run:
        if not RUN_ID.match(run_id or ""):
            raise NotFound("no such run")
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                directory = self.root / run_id
                meta_path = directory / "meta.json"
                if not meta_path.is_file():
                    raise NotFound("no such run")
                meta = json.loads(meta_path.read_text())
                if meta.get("scenario") != self.scenario.id:
                    raise NotFound("this run belongs to a different scenario")
                run = self._runs[run_id] = Run(directory, meta, self.scenario, self.bundle)
        return run

    def list(self) -> list[dict[str, Any]]:
        out = []
        for directory in sorted(self.root.iterdir(), reverse=True):
            if directory.is_dir() and RUN_ID.match(directory.name):
                try:
                    run = self.get(directory.name)
                    with run.lock:
                        out.append(run.summary())
                except (NotFound, ValueError, OSError, KeyError, json.JSONDecodeError):
                    continue   # an unreadable directory is skipped, never guessed at
        return out

    def view(self, run: Run) -> dict[str, Any]:
        """Everything the dashboard shows during play: the same reads an agent has."""
        zones = [z["zone_id"] for z in run.read("get_rules")["zones"]]
        return {
            "run": run.summary(),
            "rules": run.read("get_rules"),
            "status": run.read("get_status"),
            "forecast": run.read("get_forecast"),
            "tests": run.read("get_pending_tests"),
            "events": run.read("get_events"),
            "history": {z: run.read("get_history", {"zone_id": z}) for z in zones},
        }

    def report(self, run: Run) -> dict[str, Any]:
        """The end-of-episode result and analysis, from a fresh replay of the trace."""
        if not run.episode.done:
            raise Conflict("The analysis shows hidden state and opens only when the episode is over.")
        graded = evaluate_trace(self.scenario, int(run.meta["seed"]), run.records())
        replayed = graded.pop("episode")
        return {
            "run": run.summary(),
            "result": {"reward": graded["reward"], **graded["ledger"]},
            "replay": graded["replay"],
            "days_played_by_player": graded["days_played_by_player"],
            "bundle_matches": run.meta.get("bundle") == self.bundle,
            "analysis": outcome.report(replayed.env.sim),
        }


def is_argument_error(exc: Exception) -> bool:
    return isinstance(exc, ArgumentError)
