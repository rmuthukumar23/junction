"""How-a-run-works figure for the README: docs/img/architecture.svg.

    .venv/bin/python scripts/architecture_figure.py

Drawn in the same dark, monospace style as the other figures. The sparklines are the real
recorded inputs of seed 1 (replayed through the simulator); the score axis reads
runs/analysis.json. The facility numbers are facts of scenarios/normal-winter.toml.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "docs" / "img" / "architecture.svg"

BG, PANEL, EDGE, FG, MUTED = "#0e1119", "#161b26", "#2a3242", "#e9edf3", "#8d97a8"
GREEN, BLUE, AMBER, RED, PURPLE, ORANGE = "#7bd88f", "#6cb8ff", "#ffc857", "#ff6b6b", "#c9a8ff", "#ff8a5c"
FONT = "ui-monospace,SFMono-Regular,Menlo,monospace"
W, H = 1340, 812
el: list[str] = []


def t(x, y, s, size=13, fill=FG, anchor="start", weight="normal"):
    el.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" font-weight="{weight}">{s}</text>')


def panel(x, y, w, h, title, color):
    el.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{PANEL}" stroke="{EDGE}"/>')
    el.append(f'<rect x="{x}" y="{y}" width="4" height="{h}" rx="2" fill="{color}"/>')
    t(x + 18, y + 26, title, 12, color, weight="bold")


def arrow(x1, y1, x2, y2, color, label="", lx=0, ly=-8):
    el.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="2.5" marker-end="url(#m{color[1:]})"/>')
    if label:
        t((x1 + x2) / 2 + lx, (y1 + y2) / 2 + ly, label, 11, color, "middle", "bold")


def house(x, y, crop_color, label, area):
    """A small pixel greenhouse: glass box, gabled roof, a row of crop."""
    el.append(f'<rect x="{x}" y="{y + 14}" width="64" height="30" fill="#1d2433" stroke="{BLUE}" stroke-opacity="0.7"/>')
    el.append(f'<polygon points="{x},{y + 14} {x + 32},{y} {x + 64},{y + 14}" fill="#1d2433" stroke="{BLUE}" stroke-opacity="0.7"/>')
    for i in range(7):
        el.append(f'<rect x="{x + 5 + i * 8}" y="{y + 34}" width="6" height="7" fill="{crop_color}"/>')
    t(x + 32, y + 62, label, 11, FG, "middle", "bold")
    t(x + 32, y + 77, area, 10.5, MUTED, "middle")


def spark(x, y, w, h, vals, color, label, unit, nd=1):
    lo, hi = min(vals), max(vals)
    pts = " ".join(f"{x + w * i / (len(vals) - 1):.1f},{y + h - h * (v - lo) / ((hi - lo) or 1):.1f}" for i, v in enumerate(vals))
    el.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.3"/>')
    t(x, y - 6, label, 11, FG, weight="bold")
    t(x + w, y - 6, f"{lo:.{nd}f} to {hi:.{nd}f} {unit}", 10, MUTED, "end")


def recorded_series() -> dict[str, list[float]]:
    import replay_record as r
    frames = r.play("do-nothing", 1)["frames"]
    every = frames[::3]
    return {"temp": [f["out"]["t"] for f in every], "wind": [f["out"]["wind"] for f in every],
            "price": [f["ec"]["p_imp"] for f in every]}


def build() -> str:
    t(24, 38, "How a run works", 20, FG, weight="bold")
    t(24, 60, "One tool, one turn a morning, 42 days. Everything below the agent is the real simulator in its own container.", 12.5, MUTED)

    # ---- the daily loop -------------------------------------------------------------
    panel(24, 80, 404, 520, "THE AGENT'S DAY", PURPLE)
    cx, cy, r = 226, 322, 118
    stations = [(-90, "06:00", "briefing", "status · alarms · forecast", BLUE),
                (0, "submit_day", "≤ 5 of 10 actions", "climate · energy · sow · cut · order · hire · repair", PURPLE),
                (90, "24 hours", "run unattended", "day settings, then the night schedule", AMBER),
                (180, "results", "what happened", "sales · faults · refusals", GREEN)]
    for i, (a0, *_rest) in enumerate(stations):
        a1 = stations[(i + 1) % 4][0] + (360 if i == 3 else 0)
        s, e = math.radians(a0 + 27), math.radians(a1 - 27)
        x1, y1, x2, y2 = cx + r * math.cos(s), cy + r * math.sin(s), cx + r * math.cos(e), cy + r * math.sin(e)
        el.append(f'<path d="M{x1:.1f},{y1:.1f} A{r},{r} 0 0 1 {x2:.1f},{y2:.1f}" fill="none" stroke="{MUTED}" stroke-width="2" marker-end="url(#m8d97a8)"/>')
    for a, head, sub, detail, col in stations:
        px, py = cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))
        el.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="7" fill="{col}"/>')
        dx = {-90: 0, 0: -6, 90: 0, 180: 6}[a]
        dy = {-90: -34, 0: 30, 90: 30, 180: 30}[a]
        anchor = {-90: "middle", 0: "middle", 90: "middle", 180: "middle"}[a]
        t(px + dx, py + dy, head, 13, col, anchor, "bold")
        t(px + dx, py + dy + 15, sub, 11, FG, anchor)
    t(cx, cy + 4, "× 42", 30, FG, "middle", "bold")
    t(cx, cy + 24, "mornings", 11, MUTED, "middle")
    t(44, 530, "At most 400 calls; no read tools: the briefing", 11, MUTED)
    t(44, 548, "is all it sees.", 11, MUTED)
    t(44, 566, "Storms and trips wait for the next morning.", 11, MUTED)
    t(44, 584, "Harness-agnostic; our runs use OpenCode via Harbor.", 11, MUTED)

    # ---- the simulator --------------------------------------------------------------
    panel(470, 80, 470, 520, "THE SIMULATOR  (sidecar, reached over MCP)", GREEN)
    arrow(430, 300, 468, 300, PURPLE)
    arrow(468, 360, 430, 360, BLUE)
    t(449, 290, "act", 10.5, PURPLE, "middle", "bold")
    t(449, 380, "brief", 10.5, BLUE, "middle", "bold")
    t(490, 124, "Houses", 13, FG, weight="bold")
    house(500, 138, GREEN, "A · broccoli", "1,686 m²")
    house(620, 138, GREEN, "B · broccoli", "1,512 m²")
    house(740, 138, "#ff8fb1", "C · radish", "1,788 m²")
    t(840, 160, "climate, CO2,", 10.5, MUTED)
    t(840, 175, "lamps, growth", 10.5, MUTED)
    t(840, 190, "every hour", 10.5, MUTED)
    el.append(f'<line x1="490" y1="244" x2="920" y2="244" stroke="{EDGE}"/>')
    t(490, 270, "Energy centre", 13, FG, weight="bold")
    for i, (lab, col) in enumerate([("CHP", ORANGE), ("boiler", ORANGE), ("heat buffer", AMBER), ("CO2 store", BLUE), ("grid", AMBER)]):
        x = 490 + i * 88
        el.append(f'<rect x="{x}" y="282" width="80" height="26" rx="5" fill="#1d2433" stroke="{col}" stroke-opacity="0.8"/>')
        t(x + 40, 299, lab, 11, col, "middle")
    t(490, 330, "gas → heat + power + CO2; lamps buy or sell at hourly prices", 10.5, MUTED)
    el.append(f'<line x1="490" y1="346" x2="920" y2="346" stroke="{EDGE}"/>')
    t(490, 372, "Buyers' order book  (broccoli, t per rolling week)", 13, FG, weight="bold")
    factors, x0, base, step, bw = [0.6, 1.5, 0.5, 1.4, 0.7, 1.3], 500, 470, 56, 48
    for i, f in enumerate(factors):
        d = 4 * f
        el.append(f'<rect x="{x0 + i * step}" y="{base - d * 12}" width="{bw}" height="{d * 12}" fill="{GREEN}" fill-opacity="0.35" stroke="{GREEN}"/>')
        el.append(f'<line x1="{x0 + i * step}" x2="{x0 + i * step + bw}" y1="{base - 1.25 * d * 12}" y2="{base - 1.25 * d * 12}" stroke="{RED}" stroke-dasharray="3 3"/>')
        t(x0 + i * step + bw / 2, base + 14, f"wk {i}", 10, MUTED, "middle")
    t(852, 420, "full price", 10.5, GREEN)
    t(852, 434, "up to demand,", 10.5, GREEN)
    t(852, 452, "zero at 1.25×", 10.5, RED)
    el.append(f'<line x1="490" y1="502" x2="920" y2="502" stroke="{EDGE}"/>')
    t(490, 526, "Lead times", 13, FG, weight="bold")
    for i, (lab, col) in enumerate([("seed 10 d", AMBER), ("hire 3 d", PURPLE), ("parts + contractor", ORANGE)]):
        x = 490 + [0, 112, 224][i]
        el.append(f'<rect x="{x}" y="538" width="{[100, 100, 170][i]}" height="26" rx="5" fill="#1d2433" stroke="{col}" stroke-opacity="0.8"/>')
        t(x + [50, 50, 85][i], 555, lab, 11, col, "middle")
    t(490, 586, "a decision today pays off 10 days later, or not at all", 10.5, MUTED)

    # ---- the recorded world ---------------------------------------------------------
    panel(982, 80, 334, 520, "THE RECORDED WORLD  (seed 1)", AMBER)
    arrow(980, 330, 942, 330, AMBER)
    s = recorded_series()
    spark(1002, 140, 294, 56, s["temp"], BLUE, "outside °C", "°C")
    spark(1002, 240, 294, 56, s["wind"], PURPLE, "wind", "m/s")
    spark(1002, 340, 294, 56, s["price"], AMBER, "electricity", "€/kWh", 2)
    t(1002, 430, "KNMI De Bilt · day-ahead power · TTF gas", 10.5, MUTED)
    t(1002, 446, "the same for every agent on a seed", 10.5, MUTED)
    t(1002, 482, "Events, drawn from the seed", 12, FG, weight="bold")
    for i, (lab, col) in enumerate([("storms break glass", RED), ("boiler trips", ORANGE), ("late deliveries", AMBER)]):
        el.append(f'<rect x="1002" y="{494 + i * 30}" width="200" height="24" rx="5" fill="#1d2433" stroke="{col}" stroke-opacity="0.8"/>')
        t(1012, 510 + i * 30, lab, 11, col)
    t(1214, 510, "schedule", 10.5, MUTED)
    t(1214, 524, "hidden,", 10.5, MUTED)
    t(1214, 538, "rates", 10.5, MUTED)
    t(1214, 552, "published", 10.5, MUTED)

    # ---- scoring --------------------------------------------------------------------
    panel(24, 620, 1292, 176, "SCORING  (a separate verifier container replays every call; profit is the only thing scored)", RED)
    ax0, ax1, ay = 90, 1270, 722
    X = lambda v: ax0 + (ax1 - ax0) * v  # noqa: E731
    el.append(f'<line x1="{ax0}" y1="{ay}" x2="{ax1}" y2="{ay}" stroke="{MUTED}" stroke-width="1.5"/>')
    for v in (0, 0.2, 0.4, 0.6, 0.8, 1.0):
        el.append(f'<line x1="{X(v):.1f}" y1="{ay - 4}" x2="{X(v):.1f}" y2="{ay + 4}" stroke="{MUTED}"/>')
        t(X(v), ay + 20, f"{v:.1f}", 10.5, MUTED, "middle")
    t(ax0 - 20, 666, "score = 0.8 × (profit − nobody acts) / (planner − nobody acts), capped at 1", 12, FG)
    a = json.loads((ROOT / "runs" / "analysis.json").read_text())
    names = {"gemini-4-hydrogen": "Gemini", "claude-sonnet-5-5": "Sonnet", "claude-haiku-5-5": "Haiku"}
    marks = [(0.0, "nobody · naive · rule-based", MUTED, 1, "start"), (0.10, "harvest-early", MUTED, -1, "middle"),
             (0.24, "stop-early", MUTED, 1, "middle")]
    side = {"gemini-4-hydrogen": -1, "claude-sonnet-5-5": -1, "claude-haiku-5-5": 1}
    marks += [(r["mean"], f'{names.get(r["id"], r["id"])} {r["mean"]:.2f}', BLUE, side.get(r["id"], 1), "middle")
              for r in a["leaderboard"] if r["kind"] == "model"]
    marks.append((0.80, "reference planner 0.80", GREEN, 1, "start"))
    for v, lab, col, sd, anchor in marks:
        el.append(f'<circle cx="{X(v):.1f}" cy="{ay}" r="6" fill="{col}" stroke="{BG}" stroke-width="2"/>')
        dx = -8 if anchor == "start" and v == 0 else (-4 if anchor == "start" else 0)
        t(X(v) + dx, ay - 16 if sd < 0 else ay + 38, lab, 11, col, anchor, "bold")
    t(ax1, 784, "model dots: mean over 3-7 runs each (runs/ANALYSIS.md)", 10.5, MUTED, "end")

    marks_defs = "".join(f'<marker id="m{c[1:]}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">'
                         f'<path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>' for c in (PURPLE, BLUE, AMBER, MUTED, GREEN))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="{FONT}">'
            f'<defs>{marks_defs}</defs><rect width="{W}" height="{H}" rx="10" fill="{BG}"/>\n' + "\n".join(el) + "\n</svg>\n")


if __name__ == "__main__":
    OUT.write_text(build())
    print(f"wrote {OUT}")
