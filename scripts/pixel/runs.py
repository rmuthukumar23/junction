"""Run discovery, metadata and the on-disk replay cache for the pixel site.

Agent runs: Harbor trial directories holding artifacts/var/lib/envkit/trace.jsonl, with
sibling result.json / config.json / exception.txt / verifier/{reward.txt,score.json}.
Policy runs: virtual ids "policy:<name>:s<seed>", played on demand through the real tools.
Nothing here raises on a missing or odd file: such a run is listed as partial or failed.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import replay as rp

ROOT = rp.ROOT
POLICY_SEEDS = (1, 2, 3)
LEGACY_TOOLS = {"advance", "finish_episode", "end_window", "get_status", "get_rules"}
_SCENARIO_CACHE: dict[str, Any] = {}
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def main_checkout() -> Path:
    """The main checkout (holds the shared artifacts/), resolved through git's common dir."""
    try:
        out = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=ROOT,
                             capture_output=True, text=True, timeout=10, check=True).stdout.strip()
        p = Path(out)
        if p.name == ".git":
            return p.parent
    except Exception:
        pass
    return ROOT


def default_artifacts() -> Path:
    return main_checkout() / "artifacts"


def cache_dir() -> Path:
    d = ROOT / "artifacts" / "pixel-cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _scenario(sid: str):
    if sid not in _SCENARIO_CACHE:
        try:
            _SCENARIO_CACHE[sid] = rp.load_scenario(rp.scenario_path(sid))
        except Exception:
            _SCENARIO_CACHE[sid] = None
    return _SCENARIO_CACHE[sid]


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _trace_summary(path: Path) -> dict[str, Any]:
    """Header and tool set of a trace, read without simulating anything."""
    header, tools, n = {}, set(), 0
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                x = json.loads(line)
            except Exception:
                continue
            if not isinstance(x, dict):
                continue
            if x.get("k") == "header":
                header = x
            elif x.get("k") == "call":
                n += 1
                tools.add(str(x.get("tool")))
    except Exception:
        pass
    return {"header": header, "tools": tools, "calls": n}


def _agent_meta(trace: Path, artifacts: Path) -> dict[str, Any]:
    trial = trace.parents[4]       # <trial>/artifacts/var/lib/envkit/trace.jsonl
    try:
        rel = trial.relative_to(artifacts).as_posix()
    except ValueError:
        rel = trial.as_posix()
    rid = "agent:" + hashlib.sha1(rel.encode()).hexdigest()[:10]
    cfg = _json(trial / "config.json") or {}
    res = _json(trial / "result.json") or {}
    sj = _json(trial / "verifier" / "score.json") or {}
    summ = _trace_summary(trace)
    hdr = summ["header"]
    scenario = hdr.get("scenario") or sj.get("scenario") or "unknown"
    seed = hdr.get("seed", sj.get("seed"))
    model = ((cfg.get("agent") or {}).get("model_name")) or (((res.get("config") or {}).get("agent") or {})
                                                                .get("model_name"))
    reward = None
    rj = (res.get("verifier_result") or {}).get("rewards") or {}
    if isinstance(rj.get("reward"), (int, float)):
        reward = float(rj["reward"])
    elif isinstance(sj.get("reward"), (int, float)):
        reward = float(sj["reward"])
    else:
        try:
            reward = float((trial / "verifier" / "reward.txt").read_text().strip())
        except Exception:
            pass
    profit = (sj.get("ledger") or {}).get("profit_eur")
    exc = res.get("exception_info")
    exc_text = None
    if isinstance(exc, dict):
        exc_text = f"{exc.get('exception_type', 'error')}: {str(exc.get('exception_message', ''))[:240]}"
    elif (trial / "exception.txt").is_file():
        try:
            exc_text = (trial / "exception.txt").read_text(encoding="utf-8", errors="replace").strip()[-240:]
        except Exception:
            exc_text = "exception.txt unreadable"
    sc = _scenario(str(scenario))
    status, failure = "complete", None
    if summ["calls"] == 0:
        status, failure = "failed", exc_text or "no tool calls were recorded (the agent never reached the tools)"
        reward = None
    elif sc is None:
        status, failure = "failed", f"scenario '{scenario}' is not in this checkout; the trace cannot be replayed"
    elif exc_text:
        status, failure = "partial", exc_text
    elif reward is None:
        status, failure = "partial", "no verifier score was found for this trial"
    if status != "failed" and "submit_day" not in summ["tools"] and summ["tools"] & LEGACY_TOOLS:
        status = "partial"
        failure = ("legacy trace, recorded before the daily turn (tools: " + ", ".join(sorted(summ["tools"]))[:80]
                   + "); replaying it here shows the unattended world, not the agent's play")
    try:
        started = res.get("started_at") or _iso(trace.stat().st_mtime)
    except Exception:
        started = None
    short = (model or "unknown model").split("/")[-1]
    sid = int(seed) if isinstance(seed, int) or str(seed).isdigit() else None
    base = rp.baseline_profit(str(scenario), sid) if sid is not None and sc else None
    meta = {"id": rid, "label": f"{short} · {scenario} s{seed}", "kind": "agent", "model": model, "policy": None,
            "scenario": scenario, "seed": sid, "score": reward, "profit_eur": profit,
            "baseline_profit_eur": base, "days": int(sc.shift.windows * sc.shift.window_hours // 24) if sc else 0,
            "status": status, "failure": failure, "started": started, "source": rel}
    meta["_trace"] = str(trace)
    return meta


def _policy_meta(name: str, seed: int, scenario_id: str) -> dict[str, Any]:
    sc = _scenario(scenario_id)
    cal = rp._calibration(scenario_id, seed) or {}
    anchor = (cal.get("anchors") or {}).get(name) or {}
    return {"id": f"policy:{name}:s{seed}", "label": f"{name} · s{seed}", "kind": "policy", "model": None,
            "policy": name, "scenario": scenario_id, "seed": seed, "score": anchor.get("reward"),
            "profit_eur": (anchor.get("metrics") or {}).get("profit_eur"),
            "baseline_profit_eur": rp.baseline_profit(scenario_id, seed),
            "days": int(sc.shift.windows * sc.shift.window_hours // 24) if sc else 0,
            "status": "complete" if sc else "failed", "failure": None if sc else f"scenario '{scenario_id}' missing",
            "started": None, "source": "policy"}


def public(meta: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in meta.items() if not k.startswith("_")}


class Runs:
    def __init__(self, artifacts: Path | None = None, policy_scenario: str = "normal-winter"):
        self.artifacts = Path(artifacts) if artifacts else default_artifacts()
        self.policy_scenario = policy_scenario

    def discover(self) -> list[dict[str, Any]]:
        metas: list[dict[str, Any]] = []
        if self.artifacts.is_dir():
            for trace in self.artifacts.glob("**/artifacts/var/lib/envkit/trace.jsonl"):
                try:
                    metas.append(_agent_meta(trace, self.artifacts))
                except Exception as exc:
                    metas.append({"id": "agent:" + hashlib.sha1(str(trace).encode()).hexdigest()[:10],
                                  "label": trace.parents[4].name, "kind": "agent", "model": None, "policy": None,
                                  "scenario": "unknown", "seed": None, "score": None, "profit_eur": None,
                                  "baseline_profit_eur": None, "days": 0, "status": "failed",
                                  "failure": f"unreadable run: {type(exc).__name__}: {exc}", "started": None,
                                  "source": str(trace), "_trace": str(trace)})
        metas.sort(key=lambda m: m.get("started") or "", reverse=True)
        pol = [_policy_meta(n, s, self.policy_scenario) for s in POLICY_SEEDS for n in rp.POLICY_NAMES]
        return metas + pol

    def list(self) -> list[dict[str, Any]]:
        return [public(m) for m in self.discover()]

    def find(self, run_id: str) -> dict[str, Any] | None:
        m = re.fullmatch(r"policy:([a-z\-]+):s(\d+)", run_id)
        if m:
            name, seed = m.group(1), int(m.group(2))
            if name not in rp.POLICY_NAMES or not 1 <= seed <= 9999:
                return None
            return _policy_meta(name, seed, self.policy_scenario)
        return next((x for x in self.discover() if x["id"] == run_id), None)

    def replay(self, run_id: str) -> dict[str, Any] | None:
        meta = self.find(run_id)
        if meta is None:
            return None
        trace = Path(meta["_trace"]) if meta.get("_trace") else None
        if trace is not None:
            stamp = trace.stat().st_mtime_ns
        else:
            sp = rp.scenario_path(meta["scenario"])
            stamp = max(sp.stat().st_mtime_ns, Path(rp.__file__).stat().st_mtime_ns)
        key = re.sub(r"[^A-Za-z0-9_.-]", "_", run_id)
        path = cache_dir() / f"{key}-{stamp}.json"
        with _LOCKS_GUARD:
            lock = _LOCKS.setdefault(run_id, threading.Lock())
        with lock:
            if path.is_file():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            if trace is not None:
                out = rp.replay_trace(trace, public(meta))
            else:
                out = rp.replay_policy(meta["policy"], meta["seed"], meta["scenario"], public(meta))
            # agents keep the verifier's score; a policy's score is recomputed from this very run
            m = out["meta"]
            if m.get("kind") == "policy" and m.get("ledger_score") is not None:
                m["score"] = m["ledger_score"]
            for old in cache_dir().glob(f"{key}-*.json"):
                try:
                    old.unlink()
                except OSError:
                    pass
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
            tmp.replace(path)
            return out
