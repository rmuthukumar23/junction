"""Write the fine-tuning results into the README, between the finetune markers.

    uv run --no-sync python scripts/finetune/report.py
    uv run --no-sync python scripts/finetune/report.py --print      # show the block, change nothing

Reads artifacts/finetune/eval/<label>/results.json (play_llm.py; labels base and finetuned
by default), every artifacts/finetune/harbor/*/summary.json (harbor_run.sh),
artifacts/finetune/train_info.json (modal_train.py) and artifacts/finetune/data/manifest.json
(gen_data.py). Only the text between <!-- finetune:start --> and <!-- finetune:end --> changes.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ARTIFACTS, ROOT  # noqa: E402

START, END = "<!-- finetune:start -->", "<!-- finetune:end -->"
NAMES = {"base": "base", "finetuned": "round 1", "finetuned-r2": "round 2"}    # label -> column name


def load(path: Path) -> Any:
    return json.loads(path.read_text()) if path.exists() else None


def eur(x: Any) -> str:
    return "–" if x is None else f"{x / 1000:,.0f} k"


def cell(ep: dict[str, Any] | None) -> str:
    if not ep:
        return "–"
    if ep.get("infrastructure_failure"):
        return "infra failure"
    return f"{ep['reward']:.2f} ({eur(ep['profit_eur'])})"


def _days(ep: dict[str, Any] | None) -> str:
    """Days played, why it ended if not the horizon, and malformed days if any."""
    if not ep:
        return "–"
    end = str(ep.get("end_reason") or "")
    out = str(ep["days"]) + (" (bankrupt)" if "bankrupt" in end else f" ({end})" if end and end != "horizon" else "")
    return out + (f", {ep['malformed_days']} malformed" if ep.get("malformed_days") else "")


def mean(values: list[float]) -> str:
    return f"{statistics.fmean(values):.2f}" if values else "–"


RUNS = ROOT / "runs" / "finetune"


def block(labels: list[str], root: Path = ARTIFACTS, runs: Path = RUNS) -> str:
    """Prefers the committed copies under runs/finetune/ (<label>/results.json,
    train_info-round<N>.json, data_manifest.json), else artifacts/finetune/."""
    evals = {lab: load(runs / lab / "results.json") or load(root / "eval" / lab / "results.json") for lab in labels}
    evals = {k: v for k, v in evals.items() if v}
    harbor = [s for s in (load(p) for p in sorted((root / "harbor").glob("*/summary.json"))) if s]
    rounds = [load(p) for p in sorted(runs.glob("train_info-round*.json"))] or [load(root / "train_info.json")]
    rounds = [t for t in rounds if t]
    manifest = load(runs / "data_manifest.json") or load(root / "data" / "manifest.json")
    lines = [START, ""]
    if not evals:
        lines += ["No fine-tuning results yet: see [docs/FINETUNE.md](docs/FINETUNE.md).", "", END]
        return "\n".join(lines)

    seeds = sorted({(e["seed"], e["run"]) for r in evals.values() for e in r["episodes"]})
    first = next(iter(evals.values()))
    kind = "held-out seeds" if all(s >= 101 for s, _ in seeds) else "seeds"
    lines += [f"In-process loop ({first['scenario']}, {kind} {sorted({s for s, _ in seeds})}; score 0 = nobody "
              "acts, 0.80 = the reference planner). Score with profit in brackets.", ""]
    header = "| Seed | Reference profit | " + " | ".join(
        f"{NAMES.get(lab, lab)} (`{evals[lab]['model']}`)" for lab in evals) + " | Days played (" + ", ".join(
        NAMES.get(lab, lab) for lab in evals) + ") |"
    lines += [header, "|" + "---|" * (3 + len(evals))]
    for seed, run in seeds:
        eps = {lab: next((e for e in r["episodes"] if (e["seed"], e["run"]) == (seed, run)), None)
               for lab, r in evals.items()}
        ref = next((e.get("reference_profit_eur") for e in eps.values() if e), None)
        malformed = ", ".join(_days(e) for e in eps.values())
        name = f"{seed}" + (f" (run {run})" if run > 1 else "")
        lines.append(f"| {name} | {eur(ref)} | " + " | ".join(cell(e) for e in eps.values()) + f" | {malformed} |")
    lines.append("| **Mean** | | " + " | ".join(
        f"**{mean([e['reward'] for e in r['episodes'] if e['reward'] is not None])}** "
        f"({eur(statistics.fmean([e['profit_eur'] for e in r['episodes']]))})" for r in evals.values())
        + " | |")
    lines.append("")
    for lab, r in evals.items():
        eps = r["episodes"]
        lines.append(f"- **{NAMES.get(lab, lab)}**: refused actions {sum(e['refused_actions'] for e in eps)}, sowings without seed "
                     f"{sum(e['seed_stockouts'] for e in eps)}, over-limit days {sum(e['truncated_days'] for e in eps)}, "
                     f"infrastructure failures {r.get('infrastructure_failures', 0)}.")
    if harbor:
        lines += ["", "Harbor + OpenCode (the official harness), same endpoint:", ""]
        for s in harbor:
            for t in s["trials"]:
                got = (f"score {t['reward']:.2f}, profit {eur(t.get('profit_eur'))}, end: {t.get('end_reason')}"
                       if t.get("reward") is not None else f"no score ({t.get('error', 'failed')})")
                lines.append(f"- seed {t.get('seed', '?')}, `{s['job']}`: {got}")
    lines += ["", "<details><summary>How these numbers were made</summary>", ""]
    if manifest:
        kept = sum(1 for e in manifest["episodes"] if e["kept"])
        lines.append(f"- Data: reference planner on {manifest['scenario']} seeds {manifest['seeds']}, "
                     f"{manifest['variants']} variants per seed (drop probability {manifest['drop_prob']}), "
                     f"{kept} episodes kept, {manifest['rows']} rows, ~{manifest['approx_tokens']:,} tokens; "
                     f"code `{manifest['code_sha'][:10]}`.")
    for i, train in enumerate(rounds, 1):
        how = (f"continued from round {i - 1}, {round(100 * 0.75)} % of examples using {', '.join(train['focus'])}"
               if train.get("focus") and i > 1 else "from the base model")
        lines.append(f"- Training round {i}: LoRA r={train['lora_rank']} (alpha {train['lora_alpha']}) on "
                     f"{train['base_model']}, {how}; {train['examples']} examples, {train['epochs']} epoch, "
                     f"lr {train['lr']}, loss {train['first_loss']:.3f} → {train['last_loss']:.3f}, "
                     f"{train['minutes']} min on one H100 (Modal)"
                     + (f"; stopped at step {train['step']} of {train['steps']}" if train.get("partial") else "") + ".")
    for lab, r in evals.items():
        lines.append(f"- {NAMES.get(lab, lab)}: `{r['command']}` (code `{r['code_sha'][:10]}`, {r['created']}, "
                     f"temperature {r['settings']['temperature']}, tool_choice {r['settings']['tool_choice']}).")
    lines += ["- The in-process loop is not the Harbor/OpenCode harness; its prompt is the training prompt "
              "(a compact system prompt, own recent actions, today's briefing). Steps: [docs/FINETUNE.md](docs/FINETUNE.md).",
              "", "</details>", "", END]
    return "\n".join(lines)


def replace_block(text: str, new: str) -> str:
    if START not in text or END not in text:
        raise ValueError(f"README has no {START} ... {END} block")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    return head + new + tail


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--labels", default="base,finetuned")
    ap.add_argument("--readme", default=str(ROOT / "README.md"))
    ap.add_argument("--print", action="store_true", dest="show")
    a = ap.parse_args(argv)
    new = block([x.strip() for x in a.labels.split(",") if x.strip()])
    if a.show:
        print(new)
        return 0
    readme = Path(a.readme)
    readme.write_text(replace_block(readme.read_text(), new))
    print(f"updated {readme}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
