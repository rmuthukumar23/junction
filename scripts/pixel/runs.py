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
    header, tools, n, days = {}, set(), 0, 0
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
                if x.get("tool") == "submit_day":
                    days += 1
    except Exception:
        pass
    return {"header": header, "tools": tools, "calls": n, "days_played": days}


def _line(text: Any, limit: int = 160) -> str:
    """One short line: first non-empty line, whitespace collapsed, cut to `limit`."""
    for ln in str(text or "").splitlines():
        ln = " ".join(ln.split())
        if ln:
            return ln if len(ln) <= limit else ln[:limit - 1] + "…"
    return ""


def _error_line(res: dict[str, Any], trial: Path) -> str | None:
    """A single short line for the trial's exception (no command lines or tracebacks)."""
    typ, msg = None, ""
    exc = res.get("exception_info")
    if isinstance(exc, dict):
        typ, msg = str(exc.get("exception_type") or "error"), str(exc.get("exception_message") or "")
    elif (trial / "exception.txt").is_file():
        try:
            lines = [ln for ln in (trial / "exception.txt").read_text(encoding="utf-8", errors="replace")
                     .strip().splitlines() if ln.strip()]
        except Exception:
            lines = []
        if not lines:
            return "exception.txt unreadable"
        last = lines[-1].strip()
        m = re.match(r"^([\w.]+(?:Error|Exception|Timeout)\w*):\s*(.*)$", last)
        typ, msg = (m.group(1), m.group(2)) if m else ("error", last)
    else:
        return None
    typ = typ.rsplit(".", 1)[-1]
    if typ == "NonZeroAgentExitCodeError":
        m = re.search(r"\(exit (-?\d+)\)", msg) or re.search(r"exit(?: code)? (-?\d+)", msg)
        out = f"Agent process exited with code {m.group(1)}" if m else "Agent process exited with a non-zero code"
        for needle, hint in (("ProviderAuthError", "provider API key missing"), ("NOT_FOUND", "model not found"),
                             ("INVALID_ARGUMENT", "provider rejected the request")):
            if needle in msg:
                return _line(f"{out} ({hint})")
        return _line(out)
    m = re.search(r"timed out after ([\d.]+)", msg)
    if "Timeout" in typ and m:
        what = "Agent setup" if "Setup" in typ else "Agent run" if "Agent" in typ else "Step"
        return f"{what} timed out after {float(m.group(1)):g} s"
    return _line(msg if typ == "error" and msg else f"{typ}: {msg}" if msg else typ)


def _classify(scenario: Any, task: str, tools: set[str], calls: int, sc: Any, err: str | None) -> tuple[str, str]:
    """(category, reason). Order: nothing ever called -> infra; other task -> shift_planner;
    submit_day on a known scenario -> replayable; everything else -> legacy."""
    if calls == 0:
        return "infra", "the agent never reached the tools" + (f" ({err})" if err else "")
    if "shift-planner" in str(scenario) or task.startswith("shift-planner") or tools & {"observe", "start_job"}:
        return "shift_planner", "Shift Planner task, not the greenhouse; its trace cannot be replayed here"
    if "submit_day" in tools and sc is not None:
        return "replayable", f"round-3 greenhouse trace (submit_day) on scenario '{scenario}'"
    if "submit_day" in tools:
        return "legacy", f"scenario '{scenario}' is not in this checkout; the trace cannot be replayed"
    acts = sorted(t for t in tools if not t.startswith("get_")) or sorted(tools)
    return "legacy", ("recorded before the daily turn (tools: " + ", ".join(acts[:4])
                      + (", ..." if len(acts) > 4 else "") + "); those tools no longer exist")


_META_CACHE: dict[str, tuple[Any, dict[str, Any]]] = {}


def _stamp(trace: Path) -> tuple:
    trial = trace.parents[4]
    out = []
    for p in (trace, trial / "result.json", trial / "config.json", trial / "exception.txt",
              trial / "verifier" / "score.json", trial / "verifier" / "reward.txt"):
        try:
            out.append(p.stat().st_mtime_ns)
        except OSError:
            out.append(None)
    return tuple(out)


def _agent_meta(trace: Path, artifacts: Path) -> dict[str, Any]:
    """Classified metadata of one trial, cached by the mtimes of the trace and its sibling files."""
    stamp = _stamp(trace)
    hit = _META_CACHE.get(str(trace))
    if hit and hit[0] == stamp:
        return dict(hit[1])
    meta = _build_agent_meta(trace, artifacts)
    _META_CACHE[str(trace)] = (stamp, meta)
    return dict(meta)


def _build_agent_meta(trace: Path, artifacts: Path) -> dict[str, Any]:
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
    err = _error_line(res, trial)
    sc = _scenario(str(scenario))
    days = int(sc.shift.windows * sc.shift.window_hours // 24) if sc else 0
    category, reason = _classify(scenario, str(res.get("task_name") or ""), summ["tools"], summ["calls"], sc, err)
    status, failure, exit_error = "complete", None, None
    if summ["calls"] == 0:
        status, failure, reward, profit = "failed", err or "no tool call was recorded (the agent never started)", None, None
    elif err:
        exit_error = err
        if reward is None and profit is None:
            status, failure = "failed", err          # died before anything was graded
        elif category == "replayable" and summ["days_played"] >= days:
            pass                                     # played every day; only the process exit was bad
        else:
            status, failure = "partial", err         # ended early (or length unknown without a replay)
    elif reward is None:
        status, failure = "partial", "no verifier score was found for this trial"
    try:
        started = res.get("started_at") or _iso(trace.stat().st_mtime)
    except Exception:
        started = None
    short = (model or "unknown model").split("/")[-1]
    sid = int(seed) if isinstance(seed, int) or str(seed).isdigit() else None
    base = rp.baseline_profit(str(scenario), sid) if sid is not None and sc else None
    meta = {"id": rid, "label": f"{short} · {scenario} s{seed}", "kind": "agent", "model": model, "policy": None,
            "scenario": scenario, "seed": sid, "score": reward, "profit_eur": profit,
            "baseline_profit_eur": base, "days": days, "status": status, "failure": failure,
            "agent_exit_error": exit_error, "category": category, "category_reason": reason,
            "started": started, "source": rel}
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
            "agent_exit_error": None, "category": "policy",
            "category_reason": "scripted policy played through the real tools",
            "started": None, "source": "policy"}


def fallback_replay(trace: Path | None, meta: dict[str, Any], reason: str) -> dict[str, Any]:
    """The non-replayable shape: tool calls read straight from the trace, no simulator."""
    actions: list[dict[str, Any]] = []
    if trace is not None:
        try:
            lines = trace.read_text(encoding="utf-8").splitlines()
        except Exception:
            lines = []
        for ln in lines:
            try:
                x = json.loads(ln)
            except Exception:
                continue
            if not isinstance(x, dict) or x.get("k") != "call":
                continue
            tool, args = str(x.get("tool")), x.get("args")
            args = args if isinstance(args, dict) else {}
            resp = x.get("response") if isinstance(x.get("response"), dict) else {}
            day = x.get("window") if isinstance(x.get("window"), int) else None
            ok = bool(x.get("ok", resp.get("ok", True)))
            err = resp.get("error")
            err = None if ok else (_line(err.get("message", err) if isinstance(err, dict) else err, 300) or "failed")
            result = resp.get("result") if ok else None
            if tool == "submit_day" and ok and isinstance(result, dict) and isinstance(args.get("actions"), list):
                results = result.get("results") or []
                for i, act in enumerate(args["actions"]):
                    act = act if isinstance(act, dict) else {}
                    res_i = results[i] if i < len(results) and isinstance(results[i], dict) else {}
                    a_ok = bool(res_i.get("ok"))
                    actions.append({"h": None, "day": day, "tool": str(act.get("tool")),
                                    "args": {k: v for k, v in act.items() if k != "tool"}, "ok": a_ok,
                                    "err": None if a_ok else _line(res_i.get("error"), 300) or "failed",
                                    "resp_summary": _line(rp._summ(res_i.get("result")), 200)})
            elif not tool.startswith("get_"):
                actions.append({"h": None, "day": day, "tool": tool, "args": args, "ok": ok, "err": err,
                                "resp_summary": _line(rp._summ(result), 200) if ok and result is not None else ""})
    return {"meta": public(meta), "replayable": False, "reason": reason, "actions": actions, "frames": [],
            "events": [], "alarms": [], "daily": []}


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
                                  "failure": _line(f"unreadable run: {type(exc).__name__}: {exc}"), "agent_exit_error": None,
                                  "category": "infra", "category_reason": "the trial could not be read", "started": None,
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
        key = re.sub(r"[^A-Za-z0-9_.-]", "_", run_id)
        replayable = meta["category"] in ("replayable", "policy")
        if trace is not None:
            stamp = trace.stat().st_mtime_ns
        elif replayable and _scenario(meta["scenario"]) is not None:
            sp = rp.scenario_path(meta["scenario"])
            stamp = max(sp.stat().st_mtime_ns, Path(rp.__file__).stat().st_mtime_ns)
        else:
            stamp = 0
        path = cache_dir() / f"{key}-v2-{stamp}.json"
        with _LOCKS_GUARD:
            lock = _LOCKS.setdefault(run_id, threading.Lock())
        with lock:
            out = None
            if path.is_file():
                try:
                    out = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    out = None
            if out is None:
                cacheable = True
                if not replayable:
                    out = fallback_replay(trace, meta, meta["category_reason"])
                else:
                    try:
                        if trace is not None:
                            out = rp.replay_trace(trace, public(meta))
                        else:
                            out = rp.replay_policy(meta["policy"], meta["seed"], meta["scenario"], public(meta))
                    except Exception as exc:       # never an error for a run that exists
                        out = fallback_replay(trace, meta, f"replay failed: {type(exc).__name__}: {_line(exc, 120)}")
                        cacheable = False
                if out.get("replayable") is not False:
                    out["replayable"] = True
                    # agents keep the verifier's score; a policy's score is recomputed from this very run
                    m = out["meta"]
                    if m.get("kind") == "policy" and m.get("ledger_score") is not None:
                        m["score"] = m["ledger_score"]
                if cacheable:
                    for old in cache_dir().glob(f"{key}-*.json"):
                        try:
                            old.unlink()
                        except OSError:
                            pass
                    tmp = path.with_suffix(".tmp")
                    tmp.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
                    tmp.replace(path)
            for k in ("status", "failure", "agent_exit_error", "category", "category_reason"):
                out["meta"][k] = meta.get(k)        # classification is always the live one
            return out
