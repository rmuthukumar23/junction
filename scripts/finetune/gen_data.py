"""Expert data for fine-tuning: the reference planner's daily decisions, one row per morning.

    uv run --no-sync python scripts/finetune/gen_data.py                       # normal-winter, dev seeds 1-6
    uv run --no-sync python scripts/finetune/gen_data.py --variants 1          # clean reference only
    uv run --no-sync python scripts/finetune/gen_data.py --scenario smoke --seeds 1 --variants 1

The reference (src/greenhouse/policies/reference.py) plays through the same `submit_day`
turn an agent gets and reads only what an agent reads. A logging client sits between it and
the episode and records, for every morning, what the player was shown and the actions it
chose. Variant 0 is the clean reference; variants 1..N-1 drop one of the day's actions with
probability --drop-prob before it reaches the world, while the row keeps the reference's
full choice as the label. The planner then sees the consequences the next morning and
reacts, which gives the student examples of recovering from states the clean run never
visits. Variant episodes that earn less than --min-profit-frac of the clean run are dropped.

Only development seeds (1-6) belong here; held-out seeds 101-108 are for evaluation.

Writes artifacts/finetune/data/train.jsonl ({"messages", "tools", "meta"} per row) and
manifest.json next to it.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (ARTIFACTS, code_sha, history_entry, system_prompt, messages_for,  # noqa: E402
                    parse_seeds, scenario_from, tool_schema)

from envkit.clients import InProcessClient  # noqa: E402
from envkit.core import Episode  # noqa: E402
from envkit.policies import StopPolicy, make_policy  # noqa: E402
from envkit.trace import Trace  # noqa: E402

HELD_OUT = range(101, 109)


class LoggingClient(InProcessClient):
    """Records (briefing, history, chosen actions) for every submit_day, and optionally
    drops one action before it reaches the world."""

    def __init__(self, episode: Episode, drop_prob: float, rng: random.Random):
        super().__init__(episode)
        self.drop_prob, self.rng = drop_prob, rng
        opening = episode.opening or {}
        self.briefing = opening.get("briefing", {})
        self.history: list[dict[str, Any]] = []
        self.rows: list[dict[str, Any]] = []
        self.dropped = 0

    def call(self, tool: str, **args: Any) -> dict[str, Any]:
        if tool != "submit_day":
            return super().call(tool, **args)
        chosen = list(args.get("actions") or [])
        sent = list(chosen)
        if sent and self.drop_prob > 0 and self.rng.random() < self.drop_prob:
            sent.pop(self.rng.randrange(len(sent)))
            self.dropped += 1
        day = len(self.history)
        self.rows.append({"day": day, "briefing": self.briefing, "history": list(self.history), "actions": chosen})
        response = super().call(tool, actions=sent)
        self.history.append(history_entry(day, sent, response))
        result = response.get("result") or {}
        if response.get("ok") and result.get("briefing"):
            self.briefing = result["briefing"]
        return response


def play(scenario_name: str, seed: int, variant: int, drop_prob: float) -> dict[str, Any]:
    scenario = scenario_from(scenario_name)
    started = time.monotonic()
    episode = Episode(scenario, seed, Trace(None))
    client = LoggingClient(episode, drop_prob if variant else 0.0, random.Random(f"{seed}:{variant}"))
    try:
        make_policy("reference", scenario).run(client)
    except StopPolicy:
        pass
    episode.finalize()
    ledger = episode.result()
    system = system_prompt(scenario, seed, episode.opening)
    tools = tool_schema(episode.describe_tools())
    rows = [{"messages": messages_for(system, r["day"], r["briefing"], r["history"], r["actions"]),
             "tools": tools, "meta": {"scenario": scenario.id, "seed": seed, "variant": variant, "day": r["day"]}}
            for r in client.rows]
    return {"seed": seed, "variant": variant, "profit_eur": ledger.get("profit_eur"), "dropped": client.dropped,
            "days": len(rows), "seconds": round(time.monotonic() - started, 1), "rows": rows}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scenario", default="normal-winter")
    ap.add_argument("--seeds", default="1-6")
    ap.add_argument("--variants", type=int, default=4, help="episodes per seed (variant 0 is the clean reference)")
    ap.add_argument("--drop-prob", type=float, default=0.15)
    ap.add_argument("--min-profit-frac", type=float, default=0.9)
    ap.add_argument("--workers", type=int, default=0, help="parallel processes (default: one per episode, max 8)")
    ap.add_argument("--out", default=str(ARTIFACTS / "data"))
    a = ap.parse_args(argv)

    seeds = parse_seeds(a.seeds)
    leaked = [s for s in seeds if s in HELD_OUT]
    if leaked:
        ap.error(f"seeds {leaked} are held-out evaluation seeds; train on development seeds only")
    jobs = [(a.scenario, s, v, a.drop_prob) for s in seeds for v in range(max(1, a.variants))]
    workers = a.workers or min(8, len(jobs))
    print(f"playing {len(jobs)} reference episodes ({a.scenario}, seeds {seeds}) on {workers} processes")
    started = time.monotonic()
    if workers > 1:
        with ProcessPoolExecutor(workers) as pool:
            episodes = list(pool.map(play, *zip(*jobs)))
    else:
        episodes = [play(*j) for j in jobs]

    clean = {e["seed"]: e["profit_eur"] for e in episodes if e["variant"] == 0}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    kept, summary, chars = 0, [], 0
    with (out / "train.jsonl").open("w") as f:
        for e in sorted(episodes, key=lambda e: (e["seed"], e["variant"])):
            base = clean.get(e["seed"])
            keep = e["variant"] == 0 or (base is not None and e["profit_eur"] is not None
                                         and e["profit_eur"] >= a.min_profit_frac * base)
            summary.append({k: e[k] for k in ("seed", "variant", "profit_eur", "dropped", "days", "seconds")}
                           | {"kept": keep})
            print(f"  seed {e['seed']} variant {e['variant']}: profit EUR {e['profit_eur']:,.0f}, "
                  f"{e['dropped']} actions dropped, {e['days']} days, {'kept' if keep else 'skipped'}")
            if not keep:
                continue
            for row in e["rows"]:
                line = json.dumps(row, separators=(",", ":"))
                chars += len(line)
                f.write(line + "\n")
                kept += 1
    manifest = {
        "scenario": a.scenario, "seeds": seeds, "variants": a.variants, "drop_prob": a.drop_prob,
        "min_profit_frac": a.min_profit_frac, "rows": kept, "approx_tokens": int(chars / 2.4),
        "approx_tokens_per_row": int(chars / 2.4 / max(1, kept)), "episodes": summary,
        "code_sha": code_sha(), "seconds": round(time.monotonic() - started, 1),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"wrote {kept} rows (~{manifest['approx_tokens']:,} tokens, "
          f"~{manifest['approx_tokens_per_row']:,} per row) to {out / 'train.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
