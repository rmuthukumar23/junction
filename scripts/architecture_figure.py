"""How-a-run-works figure for the README: docs/img/architecture.svg.

    python3 scripts/architecture_figure.py

Dark, monospace, like the other figures; labels only. The score axis reads
runs/analysis.json; the demand bars are the broccoli order book in data/markets/nl_winter.toml.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "img" / "architecture.svg"

BG, PANEL, EDGE, FG, MUTED = "#0e1119", "#161b26", "#2a3242", "#e9edf3", "#8d97a8"
GREEN, BLUE, AMBER, RED, PURPLE, ORANGE, PINK = "#7bd88f", "#6cb8ff", "#ffc857", "#ff6b6b", "#c9a8ff", "#ff8a5c", "#ff8fb1"
FONT = "ui-monospace,SFMono-Regular,Menlo,monospace"
W, H = 1240, 640
el: list[str] = []


def t(x, y, s, size=14, fill=FG, anchor="middle", weight="bold"):
    el.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" font-weight="{weight}">{s}</text>')


def panel(x, y, w, h, title, color):
    el.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{PANEL}" stroke="{EDGE}"/>')
    el.append(f'<rect x="{x}" y="{y}" width="4" height="{h}" rx="2" fill="{color}"/>')
    t(x + 20, y + 30, title, 15, color, "start")


def chip(x, y, w, label, color, h=32):
    el.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="#1d2433" stroke="{color}"/>')
    t(x + w / 2, y + h / 2 + 5, label, 13, color)


def arrow(x1, y1, x2, y2, color, label=""):
    el.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="3" marker-end="url(#m{color[1:]})"/>')
    if label:
        t((x1 + x2) / 2, min(y1, y2) - 10, label, 12, color)


def house(x, y, crop, label):
    el.append(f'<rect x="{x}" y="{y + 16}" width="76" height="34" fill="#1d2433" stroke="{BLUE}"/>')
    el.append(f'<polygon points="{x},{y + 16} {x + 38},{y} {x + 76},{y + 16}" fill="#1d2433" stroke="{BLUE}"/>')
    for i in range(8):
        el.append(f'<rect x="{x + 6 + i * 8.5}" y="{y + 38}" width="6" height="8" fill="{crop}"/>')
    t(x + 38, y + 72, label, 13)


def build() -> str:
    # ---- the agent's day -----------------------------------------------------------
    panel(20, 20, 360, 440, "AGENT", PURPLE)
    cx, cy, r = 200, 250, 120
    stations = [(-90, "06:00 briefing", BLUE), (0, "submit_day", PURPLE), (90, "24 h, no one acts", AMBER), (180, "results", GREEN)]
    for i, (a0, _, _) in enumerate(stations):
        a1 = stations[(i + 1) % 4][0] + (360 if i == 3 else 0)
        s, e = math.radians(a0 + 25), math.radians(a1 - 25)
        el.append(f'<path d="M{cx + r * math.cos(s):.1f},{cy + r * math.sin(s):.1f} A{r},{r} 0 0 1 '
                  f'{cx + r * math.cos(e):.1f},{cy + r * math.sin(e):.1f}" fill="none" stroke="{MUTED}" stroke-width="2" marker-end="url(#m8d97a8)"/>')
    for a, label, col in stations:
        px, py = cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))
        el.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="8" fill="{col}"/>')
        t(px, py + (-18 if a == -90 else 28), label, 13, col)
    t(cx, cy + 4, "× 42", 30)
    t(cx, cy + 26, "days", 13, MUTED, weight="normal")

    # ---- the simulator --------------------------------------------------------------
    panel(430, 20, 500, 440, "SIMULATOR", GREEN)
    arrow(382, 220, 428, 220, PURPLE, "act")
    arrow(428, 300, 382, 300, BLUE, "brief")
    house(460, 64, GREEN, "broccoli A")
    house(600, 64, GREEN, "broccoli B")
    house(740, 64, PINK, "radish C")
    for i, (lab, col) in enumerate([("CHP", ORANGE), ("boiler", ORANGE), ("buffer", AMBER), ("CO2", BLUE), ("grid", AMBER)]):
        chip(460 + i * 92, 176, 84, lab, col)
    t(460, 250, "weekly demand, broccoli (t)", 13, FG, "start", "normal")
    for i, f in enumerate([0.6, 1.5, 0.5, 1.4, 0.7, 1.3]):
        d, x = 4 * f, 460 + i * 76
        el.append(f'<rect x="{x}" y="{390 - d * 18}" width="62" height="{d * 18}" fill="{GREEN}" fill-opacity="0.3" stroke="{GREEN}"/>')
        t(x + 31, 384 - d * 18, f"{d:.1f}", 12, GREEN)
        t(x + 31, 410, f"wk {i}", 12, MUTED, weight="normal")
    for i, (lab, col) in enumerate([("seed: 10 days", AMBER), ("hire: 3 days", PURPLE)]):
        chip(460 + i * 180, 420, 168, lab, col, 28)

    # ---- the outside world ----------------------------------------------------------
    panel(980, 20, 240, 440, "OUTSIDE", AMBER)
    arrow(978, 260, 932, 260, AMBER)
    for i, (lab, col) in enumerate([("weather", BLUE), ("power prices", AMBER), ("gas prices", ORANGE),
                                    ("storms", RED), ("boiler trips", ORANGE), ("late deliveries", AMBER)]):
        chip(1004, 70 + i * 58, 192, lab, col, 38)

    # ---- score ----------------------------------------------------------------------
    panel(20, 490, 1200, 130, "SCORE  (profit, replayed by a separate verifier)", RED)
    ax0, ax1, ay = 70, 1170, 570
    X = lambda v: ax0 + (ax1 - ax0) * v  # noqa: E731
    el.append(f'<line x1="{ax0}" y1="{ay}" x2="{ax1}" y2="{ay}" stroke="{MUTED}" stroke-width="1.5"/>')
    for v in (0, 0.5, 1.0):
        t(X(v), ay + 34, f"{v:.1f}", 12, MUTED, weight="normal")
    a = json.loads((ROOT / "runs" / "analysis.json").read_text())
    names = {"gemini-4-hydrogen": "Gemini", "claude-sonnet-5-5": "Sonnet", "claude-haiku-5-5": "Haiku"}
    up = {"gemini-4-hydrogen": True, "claude-sonnet-5-5": True, "claude-haiku-5-5": False}
    marks = [(0.0, "do nothing", MUTED, True, "start"), (0.24, "stop early", MUTED, True, "middle")]
    marks += [(r["mean"], f'{names[r["id"]]} {r["mean"]:.2f}', BLUE, up[r["id"]], "middle")
              for r in a["leaderboard"] if r["kind"] == "model" and r["id"] in names]
    marks.append((0.80, "planner 0.80", GREEN, False, "start"))
    for v, lab, col, above, anchor in marks:
        el.append(f'<circle cx="{X(v):.1f}" cy="{ay}" r="7" fill="{col}" stroke="{BG}" stroke-width="2"/>')
        t(X(v) - (8 if anchor == "start" else 0), ay - 16 if above else ay + 32, lab, 13, col, anchor)

    defs = "".join(f'<marker id="m{c[1:]}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto">'
                   f'<path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>' for c in (PURPLE, BLUE, AMBER, MUTED))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="{FONT}">'
            f'<defs>{defs}</defs><rect width="{W}" height="{H}" rx="10" fill="{BG}"/>\n' + "\n".join(el) + "\n</svg>\n")


if __name__ == "__main__":
    OUT.write_text(build())
    print(f"wrote {OUT}")
