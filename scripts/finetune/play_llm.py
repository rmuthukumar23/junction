"""Local benchmark: a model behind an OpenAI-compatible endpoint plays Greenhouse Bench in-process.

    uv run --no-sync python scripts/finetune/play_llm.py --model greenhouse --label finetuned
    uv run --no-sync python scripts/finetune/play_llm.py --model Qwen/Qwen3-4B-Instruct-2507 --label base

Each morning the model gets the same prompt it was trained on (scripts/finetune/common.py:
the task instruction, its own recent actions, today's briefing) and answers with one
`env_submit_day` tool call. The episode is the real simulator (envkit Episode, the same one
the Harbor sidecar runs), every call is written to a trace.jsonl, and the score is computed
from the terminal ledger with the same calibration constants the verifier uses. Any trace can
be regraded with `uv run --no-sync envkit replay normal-winter <trace>` (committed seeds).

This is NOT the Harbor/OpenCode harness: no OpenCode system prompt, no extra tools, and the
history is compacted. Report it as "in-process loop" and keep it apart from Harbor results
(scripts/finetune/harbor_run.sh runs the official path).

Malformed output (no tool call, bad JSON) becomes an empty action list for that day and is
counted. More than the day's action limit is cut to the limit and counted. If the endpoint
fails three times in a row, the episode is reported as an infrastructure failure, not scored.

Reads FT_BASE_URL and VLLM_API_KEY from the environment or .env. Writes
artifacts/finetune/eval/<label>/results.json and one folder per episode (trace, transcript).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (ARTIFACTS, ROOT, anchor_profit, calibration, code_sha, history_entry,  # noqa: E402
                    system_prompt, messages_for, parse_actions, parse_seeds, scenario_from, tool_schema)

from envkit.bundle import bundle_hash, source_files  # noqa: E402
from envkit.clients import InProcessClient  # noqa: E402
from envkit.core import Episode  # noqa: E402
from envkit.policies import Client, Policy  # noqa: E402
from envkit.scoring import score  # noqa: E402
from envkit.trace import Trace  # noqa: E402

Chat = Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]]


class InfraError(RuntimeError):
    """The model endpoint could not be reached; not the agent's fault."""


def load_dotenv(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def http_chat(base_url: str, model: str, api_key: str | None, *, temperature: float = 0.0,
              max_tokens: int = 2048, tool_choice: str = "auto", timeout: float = 900.0) -> Chat:
    """A chat function for an OpenAI-compatible /chat/completions endpoint (vLLM)."""
    url = base_url.rstrip("/") + "/chat/completions"

    def chat(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        body = json.dumps({"model": model, "messages": messages, "tools": tools, "tool_choice": tool_choice,
                           "temperature": temperature, "max_tokens": max_tokens}).encode()
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        last: Exception | None = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read())
                return data["choices"][0]["message"]
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:500]
                if e.code == 400:            # e.g. prompt longer than the context: the model's fault, not infra
                    return {"content": "", "error": f"HTTP 400: {detail}"}
                last = RuntimeError(f"HTTP {e.code}: {detail}")
            except (urllib.error.URLError, TimeoutError, OSError, KeyError, json.JSONDecodeError) as e:
                last = e
            time.sleep(5 * (attempt + 1))
        raise InfraError(f"{url}: {last}")

    return chat


class LLMPolicy(Policy):
    """Plays one submit_day per morning with whatever `chat` answers."""

    name = "llm"

    def __init__(self, scenario, seed: int, chat: Chat, transcript: list[dict[str, Any]] | None = None):
        self.scenario, self.seed, self.chat = scenario, seed, chat
        self.transcript = transcript if transcript is not None else []
        self.stats = {"days": 0, "malformed_days": 0, "truncated_days": 0, "rejected_calls": 0,
                      "refused_actions": 0, "seed_stockouts": 0, "actions": 0}

    def run(self, client: Client) -> None:
        opening = client.opening() or {}
        system = system_prompt(self.scenario, self.seed, opening)
        tools = tool_schema(client.tools())
        limit = int(opening.get("rules", {}).get("turn", {}).get("actions_per_day", 5))
        briefing = opening.get("briefing", {})
        history: list[dict[str, Any]] = []
        guard = 0
        while not client.done and guard < 1000:
            guard += 1
            day = len(history)
            started = time.monotonic()
            message = self.chat(messages_for(system, day, briefing, history), tools)
            actions, malformed = parse_actions(message)
            truncated = len(actions) > limit
            actions = actions[:limit]
            response = client.call("submit_day", actions=actions)
            if not response.get("ok") and not client.done:
                self.stats["rejected_calls"] += 1
                response = client.call("submit_day", actions=[])
                actions = []
            results = (response.get("result") or {}).get("results", [])
            refused = [r for r in results if not r.get("ok")]
            self.stats["days"] += 1
            self.stats["malformed_days"] += int(malformed)
            self.stats["truncated_days"] += int(truncated)
            self.stats["actions"] += len(actions)
            self.stats["refused_actions"] += len(refused)
            self.stats["seed_stockouts"] += sum(1 for r in refused if r.get("tool") == "plant"
                                                and "seed" in json.dumps(r.get("error", "")).lower())
            self.transcript.append({"day": day, "message": message, "actions": actions, "malformed": malformed,
                                    "truncated": truncated, "ok": response.get("ok"),
                                    "refused": refused, "seconds": round(time.monotonic() - started, 1)})
            history.append(history_entry(day, actions, response))
            nxt = (response.get("result") or {}).get("briefing")
            if not nxt:
                break
            briefing = nxt


def play_episode(scenario_name: str, seed: int, run: int, out_dir: str, chat: Chat | None = None,
                 endpoint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Play and score one episode. `chat` for tests; `endpoint` (picklable) for real runs."""
    scenario = scenario_from(scenario_name)
    if chat is None:
        chat = http_chat(**(endpoint or {}))
    folder = Path(out_dir) / f"s{seed}-r{run}"
    folder.mkdir(parents=True, exist_ok=True)
    trace_path = folder / "trace.jsonl"
    trace_path.unlink(missing_ok=True)
    started = time.monotonic()
    episode = Episode(scenario, seed, Trace(trace_path), bundle_hash(source_files(scenario)))
    transcript: list[dict[str, Any]] = []
    policy = LLMPolicy(scenario, seed, chat, transcript)
    infra = None
    try:
        policy.run(InProcessClient(episode))
    except InfraError as e:
        infra = str(e)
    episode.finalize()
    episode.trace.close()
    ledger = episode.result()
    entry = calibration(scenario, seed)
    graded = score(scenario, ledger, entry)
    with (folder / "transcript.jsonl").open("w") as f:
        for t in transcript:
            f.write(json.dumps(t, separators=(",", ":")) + "\n")
    result = {
        "seed": seed, "run": run, "reward": None if infra else graded["reward"],
        "profit_eur": ledger.get("profit_eur"), "end_reason": ledger.get("end_reason"),
        "infrastructure_failure": infra, **policy.stats,
        "reference_profit_eur": anchor_profit(entry, scenario.reference),
        "nobody_profit_eur": anchor_profit(entry, "do-nothing"),
        "reference_reward": ((entry.get("anchors") or {}).get(scenario.reference) or {}).get("reward"),
        "seconds": round(time.monotonic() - started, 1), "trace": str(trace_path.relative_to(ROOT))
        if trace_path.is_relative_to(ROOT) else str(trace_path),
    }
    (folder / "result.json").write_text(json.dumps(result, indent=1) + "\n")
    return result


def _calibrate(scenario_name: str, seed: int) -> int:
    calibration(scenario_from(scenario_name), seed)
    return seed


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", required=True, help="served model name, e.g. greenhouse or Qwen/Qwen3-4B-Instruct-2507")
    ap.add_argument("--label", required=True, help="results folder name, e.g. base or finetuned")
    ap.add_argument("--base-url", default=os.environ.get("FT_BASE_URL"), help="default: $FT_BASE_URL (ends in /v1)")
    ap.add_argument("--api-key-env", default="VLLM_API_KEY")
    ap.add_argument("--scenario", default="normal-winter")
    ap.add_argument("--seeds", default="101,104,107")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--parallel", type=int, default=6)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--tool-choice", default="auto", help="auto (as OpenCode) or required")
    ap.add_argument("--out", default=None, help="default: artifacts/finetune/eval/<label>")
    a = ap.parse_args(argv)
    if not a.base_url:
        ap.error("set FT_BASE_URL in .env or pass --base-url (the Modal URL plus /v1)")

    seeds = parse_seeds(a.seeds)
    out = Path(a.out) if a.out else ARTIFACTS / "eval" / a.label
    out.mkdir(parents=True, exist_ok=True)
    endpoint = {"base_url": a.base_url, "model": a.model, "api_key": os.environ.get(a.api_key_env),
                "temperature": a.temperature, "max_tokens": a.max_tokens, "tool_choice": a.tool_choice}
    started = time.monotonic()
    jobs = [(a.scenario, s, r) for s in seeds for r in range(1, a.runs + 1)]
    with ProcessPoolExecutor(max(1, min(a.parallel, len(jobs)))) as pool:
        print(f"calibration for seeds {seeds} (cached after the first time)")
        list(pool.map(_calibrate, [a.scenario] * len(seeds), seeds))
        print(f"playing {len(jobs)} episodes with {a.model} at {a.base_url}")
        futures = [pool.submit(play_episode, sc, s, r, str(out), None, endpoint) for sc, s, r in jobs]
        results = []
        for f in futures:
            res = f.result()
            results.append(res)
            shown = "INFRASTRUCTURE FAILURE" if res["infrastructure_failure"] else f"score {res['reward']:.3f}"
            ref = res["reference_profit_eur"]
            print(f"  seed {res['seed']} run {res['run']}: {shown}, profit EUR {res['profit_eur']:,.0f} "
                  f"(reference {'n/a' if ref is None else f'{ref:,.0f}'}), malformed days {res['malformed_days']}/"
                  f"{res['days']}, refused actions {res['refused_actions']}, {res['seconds']:.0f} s")
    scored = [r["reward"] for r in results if r["reward"] is not None]
    report = {
        "label": a.label, "model": a.model, "base_url": a.base_url, "scenario": a.scenario, "seeds": seeds,
        "runs": a.runs, "harness": "in-process loop (scripts/finetune/play_llm.py)",
        "settings": {k: endpoint[k] for k in ("temperature", "max_tokens", "tool_choice")},
        "code_sha": code_sha(), "created": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "seconds": round(time.monotonic() - started, 1),
        "mean_reward": round(sum(scored) / len(scored), 4) if scored else None,
        "infrastructure_failures": sum(1 for r in results if r["infrastructure_failure"]),
        "command": "uv run --no-sync python scripts/finetune/play_llm.py " + " ".join(argv or sys.argv[1:]),
        "episodes": results,
    }
    (out / "results.json").write_text(json.dumps(report, indent=1) + "\n")
    print(f"mean score {report['mean_reward']} over {len(scored)} scored episodes; wrote {out / 'results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
