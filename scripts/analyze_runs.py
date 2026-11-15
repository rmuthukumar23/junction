"""Evaluation report: score matrix, leaderboard, failure modes and charts from recorded runs.

    .venv/bin/python scripts/analyze_runs.py

Reads every model run under runs/normal-winter/<run>/ (the Harbor trial's trace, verifier
score and agent trajectory, collected by scripts/collect_runs.py). Each trace is re-issued
call for call against a fresh simulator, the same replay the verifier does, so every number
is measured on the world the agent actually played, hour by hour. The scripted ladder
(reference, rule-based, naive, stop-early, nobody acts) is played on the same seeds.
Writes runs/ANALYSIS.md, runs/analysis.json and docs/img/*.svg. Nothing here feeds the
reward; failure-mode flags are thresholds on measured numbers (FAILURE_MODES).
"""
from __future__ import annotations

import json
import random
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import replay_record as server  # noqa: E402  (records one frame per simulated hour)
from envkit.policies import Replay, make_policy  # noqa: E402
from envkit.scenario import load_scenario  # noqa: E402
from envkit.trace import read_trace  # noqa: E402

RUNS, IMG = ROOT / "runs", ROOT / "docs" / "img"
SCRIPTED = ["do-nothing", "naive", "rule-based", "stop-early", "reference"]
PASS = 0.5     # pass threshold: midway between the two best scripted policies (reference 0.8, stop-early ~0.2)
ACTIONS = ("set_climate", "set_night_schedule", "set_energy", "place_orders", "plant", "harvest",
           "book_contractor", "hire", "release", "cancel_order")
NAMES = {"gemini-4-hydrogen": "Gemini 4 Hydrogen", "claude-haiku-5-5": "Claude Haiku 5.5", "claude-sonnet-5-5": "Claude Sonnet 5.5",
         "do-nothing": "nobody acts", "naive": "naive", "rule-based": "rule-based", "stop-early": "stop-early", "reference": "reference planner"}


def constants(seed: int) -> dict[str, float]:
    return json.loads((ROOT / "calibration.json").read_text())["tasks"]["normal-winter"][str(seed)]["components"]["profit"]


def measure(run: dict[str, Any]) -> dict[str, Any]:
    """Numbers read off one played episode: one frame per hour plus the decision log."""
    frames, calls, hours = run["frames"], run["calls"], run["hours"]
    money = frames[-1]["money"]
    acts = [c for c in calls if c["tool"] in ACTIONS]
    floor = sum(b["area"] for b in frames[0]["b"] if b["st"] != "harvested") + sum(frames[0]["c"][c]["free"] for c in frames[0]["c"])
    empty = [sum(f["c"][c]["free"] for c in f["c"]) / (floor or 1.0) for f in frames]
    seen, sold_h = {}, {}
    for f in frames:
        for b in f["b"]:
            seen.setdefault(b["id"], f["h"])
            if b["st"] == "harvested":
                sold_h.setdefault(b["id"], f["h"])
    later = [i for i in sold_h if seen[i] > 6]
    market, revenue = run.get("market", {}), money["harvest_revenue_eur"]
    loss = market.get("loss_eur", 0.0)
    demand, weeks = market.get("demand_per_week", {}), hours / 168
    supply = {c: market.get("sold_units", {}).get(c, 0.0) / (d * weeks) for c, d in demand.items() if d}
    refused = [c for c in acts if not c["ok"]]
    active = {c["h"] // 24 for c in acts}
    return {
        "profit_eur": run["profit"], "revenue_eur": round(revenue), "market_loss_eur": round(loss),
        "market_loss_pct": round(100 * loss / (revenue + loss), 1) if revenue + loss > 0 else 0.0,
        "demand_met_pct": round(100 * sum(v["full"] for v in market.get("full_price_units", {}).values())
                                / max(1.0, sum(v["demand"] for v in market.get("full_price_units", {}).values())), 1),
        "supply_ratio": round(statistics.fmean(supply.values()), 2) if supply else None,
        "supply_by_crop": {c: round(v, 2) for c, v in supply.items()},
        "cycle_days": round(statistics.fmean((sold_h[i] - seen[i]) / 24 for i in later), 1) if later else None,
        "empty_area_pct": round(100 * statistics.fmean(empty), 1),
        "energy_eur": round(money.get("electricity_bought_eur", 0.0) + money.get("gas_eur", 0.0) + money.get("electricity_sold_eur", 0.0)),
        "seed_eur": round(money.get("seedlings_eur", 0.0)),
        "damage_hours": sum(1 for f in frames if f["faults"]),
        "boiler_down_hours": sum(1 for f in frames if "boiler" in f["faults"]),
        "days_played": sum(1 for c in calls if c["tool"] == "submit_day"),
        "idle_days_late": sum(1 for d in range(21, 42) if d not in active),
        "actions": len(acts), "refused": len(refused),
        "seed_stockouts": sum(1 for c in refused if c["tool"] == "plant" and "seedlings" in str(c.get("err"))),
        "malformed": sum(1 for c in refused if any(w in str(c.get("err")) for w in ("unknown", "invalid", "must not"))),
        "daily_profit": [frames[min(h, hours)]["money"]["profit_so_far_eur"] for h in range(0, hours + 1, 24)],
    }


FAILURE_MODES = [   # (name, flagged when, test on measure())
    ("Floods the market", "sells more than 1.3x the published weekly demand, so its own harvests crash the price",
     lambda m: (m["supply_ratio"] or 0) > 1.3),
    ("Sells into a glut", "over 8% of harvest value lost to selling above the rolling week's demand (the reference loses about 3%)",
     lambda m: m["market_loss_pct"] > 8),
    ("Misses the demand", "under 75% of the published demand sold at full price (wrong week, too little, or into a full window)",
     lambda m: m["demand_met_pct"] < 75),
    ("Seed stock-outs", "tries to sow with no seed in stock (did not order ahead of the lead time)", lambda m: m["seed_stockouts"] > 0),
    ("Session ended early", "the agent stopped calling before day 42 (e.g. a reasoning step hit the output limit with no "
     "tool call, so the harness ended the attempt); the farm ran on unattended", lambda m: m["days_played"] < 42),
    ("Malformed actions", "actions refused for unknown items or invalid arguments", lambda m: m["malformed"] > 0),
    ("Boiler left broken", "a tripped boiler left unrepaired for over a week (the reference: about 4 days)", lambda m: m["boiler_down_hours"] > 168),
]

# ---------------------------------------------------------------- charts: plain SVG, no dependencies
BG, FG, MUTED, GRID = "#0e1119", "#e9edf3", "#8d97a8", "#2a3242"
FONT = 'font-family="ui-monospace,SFMono-Regular,Menlo,monospace"'


def heat(v: float | None) -> str:
    if v is None:
        return "#1b2030"
    stops = [(0.0, (122, 30, 38)), (0.25, (176, 72, 42)), (0.5, (196, 150, 48)), (0.75, (74, 152, 82)), (1.0, (34, 118, 70))]
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        if v <= b:
            k = (v - a) / (b - a)
            return "#%02x%02x%02x" % tuple(round(x + (y - x) * k) for x, y in zip(ca, cb))
    return "#%02x%02x%02x" % stops[-1][1]


def svg(w: int, h: int, title: str) -> list[str]:
    return [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" {FONT}>', f'<rect width="{w}" height="{h}" rx="8" fill="{BG}"/>',
            f'<text x="18" y="28" fill="{FG}" font-size="15" font-weight="bold">{title}</text>']


def svg_matrix(path: Path, rows: list[str], cols: list[str], cell: dict, title: str, note: str) -> None:
    cw, ch, L, T = 112, 50, 96, 82
    W, H = L + cw * len(cols) + 18, T + ch * len(rows) + 48
    o = svg(W, H, title)
    for j, c in enumerate(cols):
        for k, part in enumerate(c.split("\n")):
            o.append(f'<text x="{L + j * cw + cw / 2}" y="{T - 26 + k * 13}" fill="{FG}" font-size="11" text-anchor="middle">{part}</text>')
    for i, r in enumerate(rows):
        y = T + i * ch
        if r == "all seeds":
            o.append(f'<line x1="18" x2="{W - 18}" y1="{y}" y2="{y}" stroke="{MUTED}"/>')
        o.append(f'<text x="{L - 12}" y="{y + ch / 2 + 4}" fill="{FG}" font-size="12" text-anchor="end">{r}</text>')
        for j, c in enumerate(cols):
            v, n, sd = cell.get((r, c), (None, 0, None))
            x = L + j * cw
            o.append(f'<rect x="{x + 3}" y="{y + 3}" width="{cw - 6}" height="{ch - 6}" rx="4" fill="{heat(v)}"/>')
            if v is None:
                o.append(f'<text x="{x + cw / 2}" y="{y + ch / 2 + 4}" fill="{MUTED}" font-size="11" text-anchor="middle">not run</text>')
                continue
            o.append(f'<text x="{x + cw / 2}" y="{y + ch / 2 + 2}" fill="#fff" font-size="15" font-weight="bold" text-anchor="middle">{v:.3f}</text>')
            o.append(f'<text x="{x + cw / 2}" y="{y + ch / 2 + 16}" fill="#ffffffb8" font-size="9.5" text-anchor="middle">n={n}{f"  sd {sd:.2f}" if sd else ""}</text>')
    o.append(f'<text x="18" y="{H - 18}" fill="{MUTED}" font-size="10.5">{note}</text></svg>')
    path.write_text("\n".join(o) + "\n")


def svg_leaderboard(path: Path, rows: list[dict], title: str) -> None:
    L, T, bw, rh = 200, 62, 430, 34
    W, H = L + bw + 190, T + rh * len(rows) + 46
    X = lambda v: L + bw * v  # noqa: E731
    o = svg(W, H, title)
    for v in (0, 0.25, 0.5, 0.75, 1.0):
        o.append(f'<line x1="{X(v)}" x2="{X(v)}" y1="{T - 10}" y2="{H - 34}" stroke="{GRID}"/><text x="{X(v)}" y="{H - 16}" fill="{MUTED}" font-size="10" text-anchor="middle">{v:.2f}</text>')
    o.append(f'<line x1="{X(PASS)}" x2="{X(PASS)}" y1="{T - 10}" y2="{H - 34}" stroke="#ffc857" stroke-dasharray="4 3"/><text x="{X(PASS) + 5}" y="{T - 14}" fill="#ffc857" font-size="10">pass threshold {PASS}</text>')
    for i, r in enumerate(rows):
        y = T + i * rh
        colour = {"reference": "#7bd88f", "baseline": "#5d6577"}.get(r["kind"], "#6cb8ff")
        o.append(f'<text x="{L - 12}" y="{y + 19}" fill="{FG}" font-size="12" text-anchor="end">{r["name"]}</text>')
        o.append(f'<rect x="{L}" y="{y + 7}" width="{max(1.5, bw * r["mean"])}" height="18" rx="2" fill="{colour}"/>')
        if r.get("lo") is not None:
            o.append(f'<path d="M{X(r["lo"])} {y + 11}v8M{X(r["lo"])} {y + 15}H{X(r["hi"])}M{X(r["hi"])} {y + 11}v8" stroke="{FG}" stroke-width="1.5"/>')
        extra = f'  95% CI {r["lo"]:.2f}–{r["hi"]:.2f}' if r.get("lo") is not None else ""
        o.append(f'<text x="{L + bw + 10}" y="{y + 20}" fill="{FG}" font-size="11">{r["mean"]:.3f}{extra}</text>')
    o.append("</svg>")
    path.write_text("\n".join(o) + "\n")


def svg_lines(path: Path, title: str, series: list[tuple[str, str, list[float], bool]]) -> None:
    W, H, L, R, T, B = 800, 350, 72, 200, 46, 34
    lo = min(0, min(min(v) for *_, v, _ in series)); hi = max(1, max(max(v) for *_, v, _ in series))
    n = max(len(v) for *_, v, _ in series) - 1
    X = lambda i: L + (W - L - R) * i / n  # noqa: E731
    Y = lambda v: T + (H - T - B) * (1 - (v - lo) / (hi - lo))  # noqa: E731
    f = lambda v: f"{v / 1e6:.2f}M" if abs(v) >= 1e6 else f"{v / 1e3:.0f}k" if abs(v) >= 1e3 else f"{v:.0f}"  # noqa: E731
    o = svg(W, H, title)
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        o.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{GRID}"/><text x="{L - 6}" y="{Y(v) + 4:.1f}" fill="{MUTED}" font-size="10" text-anchor="end">€{f(v)}</text>')
    for d in range(0, n + 1, 7):
        o.append(f'<text x="{X(d):.1f}" y="{H - 12}" fill="{MUTED}" font-size="10" text-anchor="middle">day {d}</text>')
    for i, (label, colour, values, dashed) in enumerate(series):
        pts = " ".join(f"{X(j):.1f},{Y(v):.1f}" for j, v in enumerate(values))
        o.append(f'<polyline points="{pts}" fill="none" stroke="{colour}" stroke-width="{2.6 if "reference" in label else 1.6}"' + (' stroke-dasharray="5 4"' if dashed else "") + "/>")
        o.append(f'<rect x="{W - R + 14}" y="{T + i * 17}" width="12" height="3" fill="{colour}"/><text x="{W - R + 32}" y="{T + i * 17 + 5}" fill="{FG}" font-size="10.5">{label}</text>')
    o.append("</svg>")
    path.write_text("\n".join(o) + "\n")


def svg_failures(path: Path, models: list[str], rates: dict) -> None:
    cw, rh, L, T = 158, 32, 250, 72
    W, H = L + cw * len(models) + 18, T + rh * len(FAILURE_MODES) + 26
    o = svg(W, H, "Failure modes: runs showing each one")
    for j, m in enumerate(models):
        o.append(f'<text x="{L + j * cw + cw / 2}" y="{T - 16}" fill="{FG}" font-size="11.5" text-anchor="middle">{m}</text>')
    for i, (name, _, _) in enumerate(FAILURE_MODES):
        y = T + i * rh
        o.append(f'<text x="{L - 12}" y="{y + 20}" fill="{FG}" font-size="11.5" text-anchor="end">{name}</text>')
        for j, m in enumerate(models):
            k, n = rates[m][name]
            s = k / n if n else 0
            o.append(f'<rect x="{L + j * cw + 3}" y="{y + 3}" width="{cw - 6}" height="{rh - 6}" rx="4" fill="{heat(1 - s) if n else "#1b2030"}"/>')
            o.append(f'<text x="{L + j * cw + cw / 2}" y="{y + 20}" fill="#fff" font-size="11.5" text-anchor="middle">{k}/{n} runs ({100 * s:.0f}%)</text>')
    o.append("</svg>")
    path.write_text("\n".join(o) + "\n")


def bootstrap(xs: list[float], n: int = 4000) -> tuple[float, float] | None:
    if len(xs) < 2:
        return None
    rng = random.Random(7)
    means = sorted(statistics.fmean(rng.choice(xs) for _ in xs) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n)]


def main() -> int:
    recorded = server.recorded_runs()
    if not recorded:
        print("no runs under runs/normal-winter/")
        return 1
    meta = {k: json.loads((v["trace"].parent / "meta.json").read_text()) for k, v in recorded.items()}
    seeds = sorted({v["seed"] for v in recorded.values()} | {1, 2, 3})
    scenario = load_scenario(ROOT / "scenarios" / "normal-winter.toml")
    IMG.mkdir(parents=True, exist_ok=True)
    res: dict[str, Any] = {"pass_threshold": PASS, "ladder": {}, "runs": {}}
    for seed in seeds:
        const = constants(seed)
        score = lambda p: max(0.0, min(1.0, (p - const["zero"]) / const["scale"]))  # noqa: E731
        res["ladder"][str(seed)] = {}
        for name in SCRIPTED:
            pol = make_policy(name, scenario) if name in ("stop-early", "naive", "rule-based") else None
            m = measure(server.play(name, seed, runner=pol))
            res["ladder"][str(seed)][name] = {**m, "score": round(score(m["profit_eur"]), 4)}
        for name, info in recorded.items():
            if info["seed"] == seed:
                m = measure(server.play("x", seed, runner=Replay(read_trace(info["trace"]))))
                m.update(score=round(score(m["profit_eur"]), 4), verifier_reward=meta[name].get("reward"), model=meta[name]["model"], seed=seed)
                m["failure_modes"] = [n for n, _, test in FAILURE_MODES if test(m)]
                res["runs"][name] = m
        mine = sorted(n for n in res["runs"] if res["runs"][n]["seed"] == seed)
        if mine:
            pal = ["#6cb8ff", "#c9a8ff", "#ffc857", "#ff8a5c", "#e06aa8", "#5ad1c9", "#9be05a", "#f2b33d"]
            series = [("reference planner", "#7bd88f", res["ladder"][str(seed)]["reference"]["daily_profit"], False)]
            series += [(f'{NAMES.get(res["runs"][n]["model"], n).replace("Claude ", "")} #{i + 1}', pal[i % 8], res["runs"][n]["daily_profit"], False) for i, n in enumerate(mine)]
            series += [("rule-based", "#8d97a8", res["ladder"][str(seed)]["rule-based"]["daily_profit"], True), ("nobody acts", "#5a6070", res["ladder"][str(seed)]["do-nothing"]["daily_profit"], True)]
            svg_lines(IMG / f"profit-seed{seed}.svg", f"Cumulative profit over 42 days, seed {seed}", series)

    models = [m for m in NAMES if m in {r["model"] for r in res["runs"].values()}]
    cols = ["do-nothing", "naive", "rule-based", "stop-early", *models, "reference"]
    label = {c: NAMES[c].replace("Claude ", "Claude\n").replace("Gemini 4 ", "Gemini 4\n").replace("reference planner", "reference\nplanner").replace("nobody acts", "nobody\nacts") for c in cols}
    def scores(c: str, seed: int | None = None) -> list[float]:
        if c in SCRIPTED:
            return [res["ladder"][str(s)][c]["score"] for s in seeds if seed in (None, s)]
        return [r["score"] for r in res["runs"].values() if r["model"] == c and seed in (None, r["seed"])]
    cell = {}
    for row, seed in [(f"seed {s}", s) for s in seeds] + [("all seeds", None)]:
        for c in cols:
            xs = scores(c, seed)
            cell[(row, label[c])] = (statistics.fmean(xs), len(xs), statistics.pstdev(xs) if len(xs) > 1 else None) if xs else (None, 0, None)
    svg_matrix(IMG / "matrix.svg", [f"seed {s}" for s in seeds] + ["all seeds"], [label[c] for c in cols], cell,
               "Score by seed and grower  (0 = nobody acts, 0.8 = reference planner, capped at 1)",
               "Models: Harbor + OpenCode, normal-winter (42 days). Cell = mean of n runs, sd across runs. Scripted rows are deterministic.")
    board = []
    for c in cols:
        xs = scores(c)
        ci = bootstrap(xs) if c in models else None
        board.append({"id": c, "name": NAMES[c], "kind": "reference" if c == "reference" else "model" if c in models else "baseline",
                      "mean": statistics.fmean(xs), "lo": ci[0] if ci else None, "hi": ci[1] if ci else None, "n": len(xs),
                      "pass_rate": sum(1 for x in xs if x >= PASS) / len(xs)})
    board.sort(key=lambda r: -r["mean"])
    svg_leaderboard(IMG / "leaderboard.svg", board, "Composite score, normal-winter (mean over runs and seeds)")
    rates = {NAMES[m]: {n: (sum(1 for r in res["runs"].values() if r["model"] == m and n in r["failure_modes"]),
                            sum(1 for r in res["runs"].values() if r["model"] == m)) for n, _, _ in FAILURE_MODES} for m in models}
    svg_failures(IMG / "failure-modes.svg", [NAMES[m] for m in models], rates)
    res.update(leaderboard=board, failure_rates={m: {k: list(v) for k, v in r.items()} for m, r in rates.items()})
    (RUNS / "analysis.json").write_text(json.dumps(res, indent=1) + "\n")
    write_markdown(res, seeds, board)
    print((RUNS / "ANALYSIS.md").read_text())
    return 0


def write_markdown(res: dict, seeds: list[int], board: list[dict]) -> None:
    L = ["# Evaluation report: normal-winter", "",
         "Generated by `scripts/analyze_runs.py`. Each model run is a Harbor + OpenCode trial; its recorded calls are replayed",
         "in the simulator hour by hour, so every column is measured, and `Score` equals the verifier's reward.", "",
         "## Leaderboard", "", "| Grower | Score | 95% CI | Pass rate (score ≥ 0.5) | Runs |", "|---|---:|---|---:|---:|"]
    L += [f'| {r["name"]} | {r["mean"]:.3f} | {f"{r[chr(108)+chr(111)]:.3f} – {r[chr(104)+chr(105)]:.3f}" if r["lo"] is not None else "deterministic"} | {100 * r["pass_rate"]:.0f}% | {r["n"]} |' for r in board]
    L += ["", "## Every run", "",
          "| Run | Seed | Score | Verifier | Profit € | Revenue € | Demand met at full price | Lost to oversupply | Supply ÷ demand | Empty floor | Energy € | Stock-outs | Malformed | Idle late days | Failure modes |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    def row(name: str, m: dict, seed: int, ver: Any) -> str:
        return (f'| {name} | {seed} | {m["score"]:.3f} | {ver} | {m["profit_eur"]:,.0f} | {m["revenue_eur"]:,} | {m["demand_met_pct"]}% | {m["market_loss_pct"]}% | {m["supply_ratio"]} | '
                f'{m["empty_area_pct"]}% | {m["energy_eur"]:,} | {m["seed_stockouts"]} | {m["malformed"]} | {m["idle_days_late"]} | {", ".join(m.get("failure_modes", [])) or "–"} |')
    for seed in seeds:
        L.append(row("**reference planner**", res["ladder"][str(seed)]["reference"], seed, "–"))
        for name, m in sorted(res["runs"].items(), key=lambda kv: (kv[1]["model"], kv[0])):
            if m["seed"] == seed:
                L.append(row(f'{NAMES[m["model"]]} `{name.split("-")[-1]}`', m, seed, m["verifier_reward"]))
    L += ["", "## Failure-mode definitions", "", "| Mode | Flagged when |", "|---|---|"] + [f"| {n} | {d} |" for n, d, _ in FAILURE_MODES]
    L += ["", "## Scripted ladder (score, profit €)", "", "| Seed | " + " | ".join(NAMES[p] for p in SCRIPTED) + " |", "|---|" + "---:|" * len(SCRIPTED)]
    L += [f"| {s} | " + " | ".join(f'{res["ladder"][str(s)][p]["score"]:.3f} ({res["ladder"][str(s)][p]["profit_eur"]:,.0f})' for p in SCRIPTED) + " |" for s in seeds]
    (RUNS / "ANALYSIS.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
