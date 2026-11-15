"""Figures for the README that analyze_runs.py does not make.

    .venv/bin/python scripts/readme_figures.py

docs/img/market-window.svg: broccoli sales against the rolling-week demand, the reference
planner and one model run on the same seed, replayed in the real simulator.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from envkit.clients import run_inprocess  # noqa: E402
from envkit.policies import Replay, make_policy  # noqa: E402
from envkit.scenario import load_scenario  # noqa: E402
from greenhouse.world import business as B  # noqa: E402

IMG = ROOT / "docs" / "img"
BG, FG, MUTED, GRID = "#0e1119", "#e9edf3", "#8d97a8", "#2a3242"
GOOD, MID, BAD, LINE = "#7bd88f", "#ffc857", "#ff6b6b", "#6cb8ff"
FONT = 'font-family="ui-monospace,SFMono-Regular,Menlo,monospace"'


def sales_of(policy, seed: int, crop: str) -> tuple[list[dict], float, B.Business]:
    log: list[dict] = []
    orig = B.Business.sell
    holder: dict = {}

    def sell(self, hour, h):
        f = self.market_factor(h.crop_id, hour, h.units) if h.sellable else 1.0
        e = orig(self, hour, h)
        holder["biz"] = self
        if h.crop_id == crop:
            log.append({"h": hour, "kg": h.units, "share": f * (h.price_factor or 0.0), "eur": e.eur})
        return e
    B.Business.sell = sell
    try:
        sc = load_scenario(ROOT / "scenarios" / "normal-winter.toml")
        profit = run_inprocess(sc, seed, policy).result()["profit_eur"]
    finally:
        B.Business.sell = orig
    return log, profit, holder["biz"]


def panel(y0: float, title: str, log: list[dict], biz: B.Business, crop: str, w: float, h: float) -> list[str]:
    x0, x1 = 70, w - 20
    top = 9000.0
    X = lambda hr: x0 + (x1 - x0) * hr / 1008  # noqa: E731
    Y = lambda kg: y0 + h - h * min(kg, top) / top  # noqa: E731
    out = [f'<text x="{x0}" y="{y0 - 10}" fill="{FG}" font-size="14" font-weight="bold">{title}</text>']
    for kg in (2000, 4000, 6000, 8000):
        out.append(f'<line x1="{x0}" x2="{x1}" y1="{Y(kg):.1f}" y2="{Y(kg):.1f}" stroke="{GRID}"/>'
                   f'<text x="{x0 - 8}" y="{Y(kg) + 4:.1f}" fill="{MUTED}" font-size="10" text-anchor="end">{kg // 1000} t</text>')
    for d in range(0, 43, 7):
        out.append(f'<line x1="{X(24 * d):.1f}" x2="{X(24 * d):.1f}" y1="{y0}" y2="{y0 + h}" stroke="{GRID}"/>'
                   f'<text x="{X(24 * d):.1f}" y="{y0 + h + 14}" fill="{MUTED}" font-size="10" text-anchor="middle">day {d}</text>')
    # rolling-week load
    pts = []
    for hr in range(0, 1008, 3):
        load = sum(s["kg"] for s in log if hr - 168 < s["h"] <= hr)
        pts.append(f"{X(hr):.1f},{Y(load):.1f}")
    out.append(f'<polygon points="{X(0):.1f},{Y(0):.1f} {" ".join(pts)} {X(1005):.1f},{Y(0):.1f}" fill="{LINE}" fill-opacity="0.18" stroke="{LINE}" stroke-width="1.5"/>')
    # demand in force and the glut line
    dem, glut = [], []
    for hr in range(0, 1009, 168):
        d = biz.demand_at(crop, min(hr, 1007)) or 0.0
        dem.append(f"{X(hr):.1f},{Y(d):.1f} {X(min(hr + 168, 1008)):.1f},{Y(d):.1f}")
        glut.append(f"{X(hr):.1f},{Y(1.25 * d):.1f} {X(min(hr + 168, 1008)):.1f},{Y(1.25 * d):.1f}")
    out.append(f'<polyline points="{" ".join(dem)}" fill="none" stroke="{GOOD}" stroke-width="2.5"/>')
    out.append(f'<polyline points="{" ".join(glut)}" fill="none" stroke="{BAD}" stroke-width="1.2" stroke-dasharray="4 4"/>')
    lost: dict[int, list[dict]] = {}
    for s in log:
        c = GOOD if s["share"] >= 0.9 else MID if s["share"] >= 0.3 else BAD
        r = 3 + 6 * min(1.0, s["kg"] / 4000)
        out.append(f'<circle cx="{X(s["h"]):.1f}" cy="{Y(0) - 2:.1f}" r="{r:.1f}" fill="{c}" stroke="{BG}"/>')
        if s["share"] < 0.3:
            lost.setdefault(s["h"] // 168, []).append(s)
    for rows in lost.values():                       # one label per week of near-worthless sales
        kg, eur = sum(r["kg"] for r in rows), sum(r["eur"] for r in rows)
        hx = sum(r["h"] for r in rows) / len(rows)
        anchor = "end" if X(hx) > x1 - 90 else "middle"
        out.append(f'<text x="{min(X(hx), x1):.1f}" y="{Y(0) - 18:.1f}" fill="{BAD}" font-size="11" font-weight="bold" text-anchor="{anchor}">'
                   f'{kg / 1000:.1f} t sold for €{eur:,.0f}</text>')
    return out


def market_window() -> None:
    seed, crop, run = 2, "broccoli_micro", "claude-haiku-5-5-s2-sugfugl"
    sc = load_scenario(ROOT / "scenarios" / "normal-winter.toml")
    ref, ref_profit, biz = sales_of(make_policy("reference", sc), seed, crop)
    recs = [json.loads(line) for line in (ROOT / "runs" / "normal-winter" / run / "trace.jsonl").read_text().splitlines() if line.strip()]
    mod, mod_profit, _ = sales_of(Replay(recs), seed, crop)
    w, h = 1000, 165
    rev = lambda log: sum(s["eur"] for s in log)  # noqa: E731
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} 520" {FONT}>', f'<rect width="{w}" height="520" rx="8" fill="{BG}"/>',
           f'<text x="20" y="28" fill="{FG}" font-size="15" font-weight="bold">Broccoli sales against the rolling-week demand (seed {seed}, replayed)</text>',
           f'<text x="20" y="46" fill="{MUTED}" font-size="11">green: demand in force · red dashes: price reaches 0 · blue: sold in the last 7 days (must stay under green)</text>',
           f'<text x="20" y="62" fill="{MUTED}" font-size="11">dots: each harvest sold (green full price, amber discounted, red almost nothing)</text>']
    out += panel(95, f"Reference planner: broccoli revenue €{rev(ref):,.0f}", ref, biz, crop, w, h)
    out += panel(325, f"Claude Haiku 5.5: broccoli revenue €{rev(mod):,.0f} (sells into a window that is already full)", mod, biz, crop, w, h)
    out.append("</svg>")
    (IMG / "market-window.svg").write_text("\n".join(out) + "\n")


if __name__ == "__main__":
    IMG.mkdir(parents=True, exist_ok=True)
    market_window()
    print("wrote docs/img/market-window.svg")
