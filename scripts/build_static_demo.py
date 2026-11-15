"""Build a static copy of the viewer for hosting without a server (e.g. Vercel).

    .venv/bin/python scripts/build_static_demo.py

Plays the six default growers on seed 1 and two recorded model runs once, through the real
simulator (scripts/viz/server.py), and writes everything the page needs into demo/:
index.html, style.css, scene.js, ui.js (reading data/*.json instead of /api), vendor/, data/.
Launching new model runs is switched off in the copy, and it opens on the reference planner, maximized. Deploy demo/ as a static site.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIZ = ROOT / "scripts" / "viz"
OUT = ROOT / "demo"
sys.path[:0] = [str(VIZ), str(ROOT / "scripts"), str(ROOT / "src")]
import server  # noqa: E402

SEED = 1
MODEL_RUNS = ["runs/normal-winter/gemini-4-hydrogen-s1-8astgmr/trace.jsonl",
              "runs/normal-winter/claude-sonnet-5-5-s1-lbtq2lu/trace.jsonl"]
SCRIPTED = ["reference", "rule-based", "naive", "stop-after:reference@21", "do-nothing"]


def slug(spec: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", spec).strip("-").lower()


def main() -> int:
    server.POOL = ThreadPoolExecutor(max_workers=4)
    for old in (OUT.iterdir() if OUT.exists() else []):   # keep dot-files: .vercel/, .gitignore, .vercelignore
        if not old.name.startswith("."):
            shutil.rmtree(old) if old.is_dir() else old.unlink()
    (OUT / "data" / "run").mkdir(parents=True)

    sc = server.load_scenario(server.SCENARIO)
    traces = [t for t in server.trace_players() if t["id"] in {f"trace:{p}" for p in MODEL_RUNS}]
    builtin = [p for p in server.builtin_players(sc) if p["id"] in SCRIPTED]
    players = {"scenario": sc.id, "title": sc.title, "builtin": builtin, "traces": traces,
               "slots": ["reference", traces[0]["id"], "rule-based", "naive", "stop-after:reference@21", "do-nothing"]}
    (OUT / "data" / "players.json").write_text(json.dumps(players, separators=(",", ":")))

    for spec in SCRIPTED + [t["id"] for t in traces]:
        game = server.run_for(spec, SEED)
        name = slug(spec) if spec.startswith("trace:") else f"{slug(spec)}-s{SEED}"
        (OUT / "data" / "run" / f"{name}.json").write_text(json.dumps(game, separators=(",", ":")))
        print(f"{spec}: profit {game['profit']:,.0f}")

    for f in ("index.html", "style.css", "scene.js", "tour.js"):
        shutil.copy(VIZ / f, OUT / f)
    shutil.copytree(VIZ / "vendor", OUT / "vendor")
    ui = (VIZ / "ui.js").read_text()
    shim = '''// Static demo: recorded games are read from data/ instead of the live server.
  const slugOf = (s) => s.replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-|-$/g, "").toLowerCase();
  const runUrl = (spec, seed) => spec.startsWith("trace:") ? `data/run/${slugOf(spec)}.json` : `data/run/${slugOf(spec)}-s${seed}.json`;
'''
    replacements = [
        ('const r = await fetch("/api/players");', 'const r = await fetch("data/players.json");'),
        ("const r = await fetch(`/api/run?player=${encodeURIComponent(p.spec)}&seed=${seed}`);",
         "const r = await fetch(runUrl(p.spec, seed));"),
        ('if (q.get("layout")) setLayout(q.get("layout"), focus, q.get("with") ? +q.get("with") - 1 : undefined);',
         'setLayout(q.get("layout") || "focus", focus, q.get("with") ? +q.get("with") - 1 : undefined);   // demo opens on the planner, maximized'),
        ('const j = await (await fetch("/api/jobs")).json();',
         'const j = { jobs: [], env_model: "", backend: "docker" };'),
        ('const r = await fetch("/api/launch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });',
         'const r = { ok: false, json: async () => ({ error: "Launching new model runs needs Docker and API keys; this online demo replays recorded runs." }) };'),
    ]
    for old, new in replacements:
        if old not in ui:
            raise SystemExit(f"ui.js changed; update build_static_demo.py: {old[:60]}")
        ui = ui.replace(old, new)
    first = ui.index("\n", ui.index("{")) + 1          # inside the top-level function
    ui = ui[:first] + "  " + shim + ui[first:]
    (OUT / "ui.js").write_text(ui)
    html = (OUT / "index.html").read_text()
    html = re.sub(r'(<input[^>]*id="seed")', r'\1 disabled title="The online demo replays seed 1"', html, count=1)
    html = html.replace('<script src="ui.js"></script>', '<script src="ui.js"></script>\n<script src="tour.js"></script>')   # first-visit tour
    (OUT / "index.html").write_text(html)
    (OUT / "vercel.json").write_text(json.dumps({"cleanUrls": True}) + "\n")
    size = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file()) / 1e6
    print(f"wrote {OUT} ({size:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
