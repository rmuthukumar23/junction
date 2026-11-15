"""Build the phone demo ("Beat the AI") as static files, so it runs from a link on any device.

    .venv/bin/python scripts/build_phone_demo.py      # writes demo/play/ (served at /play on the static site)

The demo has three on/off choices per morning (heat, harvest, order seed) and two mornings, so every
game is one of 8 x 8 = 64 two-day plans. Each one is played here once through the real simulator
(scripts/viz/server.py: the same Episode and submit_day tool the models used), and the page reads the
results instead of calling a server: data/start.json (the first morning, and the 7 recorded AI runs on
the seed with their checks), data/d1_<a>.json (day 1 for plan a: frames and the next morning) and
data/d2_<a><b>.json (day 2 and the player's checks). Choice code: heat 1 + harvest 2 + seed 4.
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIZ = ROOT / "scripts" / "viz"
OUT = ROOT / "demo" / "play"
sys.path[:0] = [str(VIZ), str(ROOT / "scripts"), str(ROOT / "src")]
import server  # noqa: E402
from envkit.clients import InProcessClient  # noqa: E402
from envkit.core import Episode  # noqa: E402
from envkit.trace import Trace  # noqa: E402

SEED = server.GAME_SEED
SEED_M2 = 1600          # "order seed": seed for about 1600 m2 of each crop (demo.js says ~8 benches)


def ready(st: dict) -> list[dict]:
    out = []
    for b in st.get("batches", []):
        e = b.get("estimate") or {}
        if not b.get("harvest_queued") and (b["status"] == "ready" or (b["status"] == "growing" and (e.get("days_to_ready") if e.get("days_to_ready") is not None else 9) <= 0.05)):
            out.append(b)
    return out


def summary(briefing: dict, rules: dict) -> dict:
    """What the morning card says: the same facts the briefing gives, in a few fields."""
    st, biz = briefing["status"], briefing["status"]["business"]
    heat = min(v.get("heat_day_c", 99) for v in st["settings"]["climate"].values())
    prices = rules["business"]["crop_prices_eur_per_unit"]
    r = ready(st)
    news = (briefing.get("news_last_3_days") or [])[-1:]
    return {"day": briefing["clock"]["day"], "hour": briefing["clock"]["hour"], "heat_c": heat, "cold": heat < 12,
            "ready": [{"id": b["id"], "crop": b["crop"], "units": round((b.get("estimate") or {}).get("units", 0)),
                       "value": round((b.get("estimate") or {}).get("units", 0) * prices.get(b["crop"], 0))} for b in r],
            "seed_coming": any(o["item"].startswith("seedlings:") for o in biz.get("open_orders", [])),
            "news": news[0]["headline"] if news else None, "damage": bool(biz.get("outages"))}


def actions(code: int, briefing: dict, rules: dict, crops: dict, compartments: dict) -> list[dict]:
    """The same mapping demo.js uses on the live server."""
    ids = sorted(compartments)
    a: list[dict] = []
    if code & 1:
        mid = lambda r, d: (r[0] + r[1]) / 2 if isinstance(r, list) else (r if r is not None else d)  # noqa: E731
        ts = [(crops.get(compartments[i]["crop"]) or {}).get("climate_targets") or {} for i in ids]
        avg = lambda k, d: round(sum(mid(t.get(k), d) for t in ts) / len(ts), 1)  # noqa: E731
        a.append({"tool": "set_climate", "heat_day_c": avg("day_temp_c", 20), "heat_night_c": avg("night_temp_c", 17),
                  "co2_ppm": avg("co2_ppm", 900), "lamp_hours": list(range(6, 18)), "lamp_intensity_pct": 100})
        a.append({"tool": "set_night_schedule", "from_hour": 18, "copy_day": True})
    r = ready(briefing["status"])
    if code & 2 and r:
        a.append({"tool": "harvest", "batch_ids": [b["id"] for b in r]})
    if code & 4:
        orders = {}
        for crop in sorted({compartments[i]["crop"] for i in ids}):
            it = rules["business"]["items"]["seedlings:" + crop]
            dens = ((crops.get(crop) or {}).get("planting") or {}).get("density_per_m2") or 1
            orders["seedlings:" + crop] = max(it["min_quantity"], -(-SEED_M2 * dens // 1))
        a.append({"tool": "place_orders", "orders": orders})
    return a


def dump(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, separators=(",", ":")))


def main() -> int:
    server.POOL = ThreadPoolExecutor(2)
    data = OUT / "data"
    if OUT.exists():
        shutil.rmtree(OUT)
    data.mkdir(parents=True)
    g = server.challenge_start(f"s{SEED}")
    rules, crops, comps = g["rules"], g["crops"], g["compartments"]
    ai = server._ai_side(SEED)
    sc = server.load_scenario(server.SCENARIO)
    base = Episode(sc, SEED, Trace(None), "")
    b0 = base.opening["briefing"]
    dump(data / "start.json", {
        "seed": SEED, "frames": g["frames"], "first_hour": g["first_hour"], "compartments": comps, "crops": crops,
        "morning": summary(b0, rules),
        "ai": [{k: e[k] for k in ("name", "run", "kind", "checks_passed", "checks_total", "two_day_profit", "failures", "real")} for e in ai["entries"]]})
    n = 0
    for c1 in range(8):
        e1 = copy.deepcopy(base)
        f1: list = []
        d1 = server._play_morning(e1, InProcessClient(e1), b0, actions(c1, b0, rules, crops, comps), f1)
        dump(data / f"d1_{c1}.json", {"frames": f1[:24], "morning": summary(d1["next"], rules),
                                      "refused": [x for x in server_refusals(d1["results"])]})
        for c2 in range(8):
            e2 = copy.deepcopy(e1)
            f2: list = []
            d2 = server._play_morning(e2, InProcessClient(e2), d1["next"], actions(c2, d1["next"], rules, crops, comps), f2)
            you = server._side(rules, [d1, d2])
            dump(data / f"d2_{c1}{c2}.json", {"frames": f2[:24], "you": {k: you[k] for k in ("checks_passed", "checks_total", "two_day_profit", "failures", "good")},
                                              "refused": server_refusals(d2["results"])})
            n += 1
    for name in ("scene.js",):
        shutil.copy(VIZ / name, OUT / name)
    shutil.copytree(VIZ / "vendor", OUT / "vendor")
    html = (VIZ / "demo.html").read_text().replace('<script src="demo.js"></script>', '<script>window.STATIC_DATA = "data/";</script>\n<script src="demo.js"></script>')
    (OUT / "index.html").write_text(html)
    shutil.copy(VIZ / "demo.js", OUT / "demo.js")
    size = sum(p.stat().st_size for p in data.iterdir())
    print(f"demo/play: {n} two-day plans, {len(list(data.iterdir()))} data files, {size / 1e6:.1f} MB")
    return 0


def server_refusals(results: list | None) -> list[str]:
    from failures import _refusals
    return _refusals(results)


if __name__ == "__main__":
    sys.exit(main())
