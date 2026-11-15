"""Architecture diagram for the README: docs/img/architecture.svg.

    python3 scripts/architecture_figure.py

Hand-laid SVG, no dependencies. The numbers in it are facts of the committed scenario
(scenarios/normal-winter.toml, data/), so update them here if the scenario changes.
"""
from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs" / "img" / "architecture.svg"
W, H = 1340, 900
SERIF = "Georgia, 'Times New Roman', serif"

# (fill, stroke) per block, after the StoreBench figure's palette
BLUE, PURPLE, GREEN, GREY, TAN, PINK = (("#eef2fb", "#4a6fb5"), ("#f3effa", "#7b5ea7"), ("#eef6ee", "#4f8a55"),
                                        ("#f4f4f4", "#9a9a9a"), ("#f7f1e3", "#9b7a3a"), ("#fbf0f2", "#a0566a"))
el: list[str] = []


def box(x, y, w, h, c, r=14, dash=False, sw=2.2):
    d = ' stroke-dasharray="7 6"' if dash else ""
    el.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{c[0]}" stroke="{c[1]}" stroke-width="{sw}"{d}/>')


def head(x, y, w, c, icon, title, size=34, h=58):
    el.append(f'<path d="M{x + 14},{y} h{w - 28} a14,14 0 0 1 14,14 v{h - 14} h-{w} v-{h - 14} a14,14 0 0 1 14,-14 z" '
              f'fill="{c[1]}" fill-opacity="0.16"/>')
    el.append(f'<line x1="{x}" y1="{y + h}" x2="{x + w}" y2="{y + h}" stroke="{c[1]}" stroke-width="1.5"/>')
    el.append(f'<text x="{x + w / 2}" y="{y + h / 2 + size * 0.36}" font-size="{size}" font-weight="bold" text-anchor="middle">'
              f'<tspan font-size="{size * 0.9}">{icon}</tspan>  {title}</text>')


def text(x, y, s, size=17, anchor="middle", weight="normal", italic=False, fill="#222"):
    st = ' font-style="italic"' if italic else ""
    el.append(f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" font-weight="{weight}" fill="{fill}"{st}>{s}</text>')


def tile(x, y, w, h, c, label, icon, size=18):
    box(x, y, w, h, c, r=8, sw=1.6)
    if h >= 80:
        text(x + w / 2, y + 30, label, size, weight="bold")
        text(x + w / 2, y + h - 18, icon, 30)
    else:
        text(x + w / 2, y + h / 2 + 6, f'<tspan font-size="{size + 2}">{icon}</tspan> {label}', size, weight="bold")


def arrow(x1, y1, x2, y2, color, sw=4):
    el.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{sw}" marker-end="url(#a{color[1:]})"/>')


def build() -> str:
    # ---- agent ----
    box(16, 10, 536, 392, BLUE)
    head(16, 10, 536, BLUE, "🤖", "Greenhouse Agent")
    text(284, 98, "Harness-agnostic (OpenCode via Harbor in our runs)", 19, italic=True, fill="#666")
    for i, (lab, ic) in enumerate([("Climate &amp; Lamps", "🌡️"), ("Energy Centre", "⚡"),
                                   ("Sowing &amp; Harvest", "🌱"), ("Orders, Crew &amp; Repairs", "📦")]):
        tile(42 + (i % 2) * 250, 130 + (i // 2) * 134, 234, 118, BLUE, lab, ic)

    # ---- MCP ----
    box(574, 10, 116, 762, PURPLE)
    head(574, 10, 116, PURPLE, "🔌", "MCP", size=26)
    text(632, 100, "1 tool", 19, italic=True, fill="#666")
    text(632, 124, "submit_day", 15, fill="#555")
    arrow(554, 186, 708, 186, "#4a6fb5")
    text(632, 214, "up to 5", 15, weight="bold", fill="#3d5f9e")
    text(632, 233, "actions", 15, weight="bold", fill="#3d5f9e")
    text(632, 252, "a morning", 15, weight="bold", fill="#3d5f9e")
    arrow(712, 278, 556, 278, "#a8743a")
    text(632, 306, "briefing:", 15, weight="bold", fill="#8a5a24")
    text(632, 325, "status,", 15, weight="bold", fill="#8a5a24")
    text(632, 344, "alarms,", 15, weight="bold", fill="#8a5a24")
    text(632, 363, "forecast", 15, weight="bold", fill="#8a5a24")

    # ---- environment ----
    box(712, 10, 618, 444, GREEN)
    head(712, 10, 618, GREEN, "🏡", "Greenhouse Bench")
    text(1021, 96, "the real simulator, in a sidecar container", 19, italic=True, fill="#666")
    box(728, 116, 586, 136, GREEN, r=10, sw=1.6)
    text(744, 152, '<tspan font-size="26">🌿</tspan> Facility', 27, anchor="start", weight="bold")
    text(1298, 150, "3 houses · 4,986 m²", 18, anchor="end", fill="#555")
    for i, (lab, ic) in enumerate([("Broccoli A·B", "🥦"), ("Radish C", "🌱"), ("CHP · Boiler", "🔥"), ("Crew", "👷")]):
        tile(740 + i * 143, 176, 134, 56, GREEN, lab, ic, 13.5)
    arrow(1021, 256, 1021, 286, "#3f7a49", 3)
    box(728, 290, 586, 140, GREEN, r=10, sw=1.6)
    text(744, 326, '<tspan font-size="26">🧺</tspan> Buyers &amp; Suppliers', 27, anchor="start", weight="bold")
    text(1298, 324, "weekly order book", 18, anchor="end", fill="#555")
    for i, (lab, ic) in enumerate([("Rolling week", "📅"), ("Glut at 1.25×", "📉"), ("Seed in 10 d", "⏳"), ("Contractors", "🔧")]):
        tile(740 + i * 143, 352, 134, 56, GREEN, lab, ic, 13.5)

    # ---- recorded world ----
    arrow(1021, 458, 1021, 474, "#888", 3)
    box(712, 478, 618, 294, GREY, dash=True)
    el.append(f'<path d="M{712 + 14},478 h{618 - 28} a14,14 0 0 1 14,14 v44 h-618 v-44 a14,14 0 0 1 14,-14 z" fill="#e2e2e2"/>')
    text(740, 520, '<tspan font-size="28">🎲</tspan> Recorded World', 30, anchor="start", weight="bold")
    text(1312, 518, "schedule unseen; rates published", 17, anchor="end", italic=True, fill="#777")
    steps = [("🌬️", "Wind"), ("🌩️", "Storm"), ("🪟", "Glass breaks"), ("🌡️", "Heat leaks"), ("🔥", "Gas burnt")]
    box(740, 550, 562, 108, TAN, r=10, sw=1.6)
    for i, (ic, lab) in enumerate(steps):
        cx = 790 + i * 116
        text(cx, 594, ic, 28)
        text(cx, 634, lab, 15, weight="bold")
        if i < len(steps) - 1:
            arrow(cx + 34, 588, cx + 80, 588, "#a8743a", 2.5)
    text(1021, 680, "KNMI De Bilt weather · day-ahead electricity · TTF gas, the same for every agent on a seed", 13.5, fill="#777")
    for i, (lab, ic) in enumerate([("Storms", "🌩️"), ("Boiler trips", "🧯"), ("Late deliveries", "🚚")]):
        tile(740 + i * 190, 696, 180, 56, GREY, lab, ic, 14.5)

    # ---- evaluation ----
    box(16, 418, 536, 354, TAN)
    head(16, 418, 536, TAN, "📊", "Evaluation")
    box(30, 490, 508, 84, TAN, r=10, sw=1.6)
    text(46, 524, '<tspan font-size="22">📅</tspan> Day 1', 19, anchor="start", weight="bold")
    text(524, 524, 'Day 42 <tspan font-size="22">📅</tspan>', 19, anchor="end", weight="bold")
    el.append('<line x1="150" y1="518" x2="420" y2="518" stroke="#9b7a3a" stroke-width="2" stroke-dasharray="7 5" marker-end="url(#a9b7a3a)"/>')
    text(284, 508, "one turn each morning, 06:00", 16, weight="bold")
    text(284, 560, "⏱ 1 call = 1 day · the day and night run with nobody acting", 15)
    box(30, 584, 508, 88, TAN, r=10, sw=1.6)
    text(284, 612, "Score: profit only", 21, weight="bold")
    text(284, 646, "0.8 × (profit − nobody) / (planner − nobody)", 17)
    text(284, 664, "replayed by a separate verifier container", 13.5, italic=True, fill="#666")
    box(30, 682, 508, 80, TAN, r=10, sw=1.6)
    text(284, 704, "Calibrated against scripted growers", 18, weight="bold")
    el.append('<line x1="56" y1="730" x2="512" y2="730" stroke="#555" stroke-width="1.5"/>')
    ticks = [(0.0, "nobody", 0), (0.10, "harvest-early", 1), (0.24, "stop-early", 0), (0.80, "planner", 0)]
    for v, lab, up in ticks:
        x = 56 + v * 456 / 0.9
        el.append(f'<line x1="{x:.0f}" y1="725" x2="{x:.0f}" y2="735" stroke="#555" stroke-width="1.5"/>')
        text(x, 752 if not up else 718, lab, 13, fill="#444")
    xp = 56 + 0.80 * 456 / 0.9
    el.append(f'<line x1="{xp:.0f}" y1="716" x2="{xp:.0f}" y2="740" stroke="#2e7d32" stroke-width="3" stroke-dasharray="4 3"/>')
    text(xp + 6, 724, "0.8", 13, anchor="start", weight="bold", fill="#2e7d32")

    # ---- bottom: harbor & trajectories ----
    arrow(632, 852, 632, 778, "#a0566a", 4)
    box(16, 790, 1314, 100, PINK)
    text(36, 850, '<tspan font-size="28">🛳️</tspan> Harbor runs', 28, anchor="start", weight="bold")
    text(262, 850, "17 trials · Gemini, Sonnet, Haiku", 19, anchor="start", italic=True, fill="#666")
    for i, (lab, ic) in enumerate([("Trajectories", "🗂️"), ("Hour-by-hour replay", "🔁"), ("Same budget &amp; grading", "⚖️")]):
        tile(668 + i * 220, 812, 210, 58, PINK, lab, ic, 14)

    defs = "".join(f'<marker id="a{c}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto">'
                   f'<path d="M0,0 L10,5 L0,10 z" fill="#{c}"/></marker>' for c in ("4a6fb5", "a8743a", "3f7a49", "888", "9b7a3a", "a0566a"))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="{SERIF}">'
            f'<defs>{defs}</defs><rect width="{W}" height="{H}" fill="#ffffff"/>' + "\n".join(el) + "</svg>\n")


if __name__ == "__main__":
    OUT.write_text(build())
    print(f"wrote {OUT}")
