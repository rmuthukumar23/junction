"""Export one replayed run as an animated USDZ for iPhone AR Quick Look.

Usage (two steps: the replay needs the repo env, USD needs `pip install usd-core`):
    uv run python scripts/viz/export_usdz.py dump reference 2 /tmp/run.json
    python3 scripts/viz/export_usdz.py build /tmp/run.json greenhouse.usdz [--seconds 45]

Open the .usdz on an iPhone (Files, AirDrop, Messages or a Safari link) and tap "AR" to put the
site on a table. The 42-day season plays as a loop: crops grow and are cut, lamps come on at night,
storm-broken roof panes turn red until a contractor fixes them, a red beacon flashes while the
boiler is down, and the gold column beside the site is profit so far.
Everything animated comes from the same frames the viewer draws (`server.run_for`).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HW, HD, WALL, RIDGE, GAP = 10.0, 14.0, 3.4, 2.2, 3.5   # same layout as scene.js
UNIT_M = 0.016                                           # one scene unit = 1.6 cm: the site is ~70 cm wide


def dump(spec: str, seed: int, out: str) -> None:
    sys.path.insert(0, str(Path(__file__).parent))
    from concurrent.futures import ThreadPoolExecutor
    import server
    server.POOL = ThreadPoolExecutor(2)
    if spec.startswith("match:"):                       # pick a recorded trace by substring
        key = spec[6:]
        spec = next(t["id"] for t in server.trace_players() if key in json.dumps(t))
    d = server.run_for(spec, seed)
    Path(out).write_text(json.dumps(d))
    print(f"{spec} seed {seed}: {len(d['frames'])} frames, profit {d['profit']:.0f}, score {d.get('score')}")


def build(src: str, out: str, seconds: float = 45.0) -> None:
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, UsdUtils

    d = json.loads(Path(src).read_text())
    F = d["frames"]
    ids = sorted(d["compartments"])
    n = len(F)
    fps = max(1.0, n / seconds)
    usdc = str(Path(out).with_suffix(".usdc"))
    st = Usd.Stage.CreateNew(usdc)
    UsdGeom.SetStageUpAxis(st, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(st, 1.0)
    st.SetStartTimeCode(0)
    st.SetEndTimeCode(n - 1)
    st.SetTimeCodesPerSecond(fps)
    st.SetFramesPerSecond(fps)
    root = UsdGeom.Xform.Define(st, "/Site")
    st.SetDefaultPrim(root.GetPrim())
    span = len(ids) * HW + (len(ids) - 1) * GAP
    ec_x = span / 2 + 9.0
    cx = (-span / 2 + ec_x + 6) / 2
    UsdGeom.XformCommonAPI(root).SetScale(Gf.Vec3f(UNIT_M, UNIT_M, UNIT_M))
    UsdGeom.XformCommonAPI(root).SetTranslate(Gf.Vec3d(-cx * UNIT_M, 0, 0))

    mats: dict[tuple, UsdShade.Material] = {}

    def mat(rgb, opacity=1.0, emissive=None, rough=0.8):
        key = (rgb, opacity, emissive)
        if key in mats:
            return mats[key]
        p = f"/Site/Mat/m{len(mats)}"
        m = UsdShade.Material.Define(st, p)
        sh = UsdShade.Shader.Define(st, p + "/s")
        sh.CreateIdAttr("UsdPreviewSurface")
        sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*rgb))
        sh.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(rough)
        sh.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
        if opacity < 1:
            sh.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(opacity)
        if emissive:
            sh.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*emissive))
        m.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")
        mats[key] = m
        return m

    count = [0]

    def cube(parent, size, at, m, rot=None, name="b"):
        """A box of `size` (x, y, z) centred at `at`, inside its own xform so it can be scaled."""
        count[0] += 1
        xp = f"{parent}/{name}{count[0]}"
        x = UsdGeom.Xform.Define(st, xp)
        api = UsdGeom.XformCommonAPI(x)
        api.SetTranslate(Gf.Vec3d(*at))
        if rot:
            api.SetRotate(Gf.Vec3f(*rot))
        c = UsdGeom.Cube.Define(st, xp + "/g")
        c.CreateSizeAttr(1.0)
        UsdGeom.XformCommonAPI(c).SetScale(Gf.Vec3f(*size))
        UsdShade.MaterialBindingAPI.Apply(c.GetPrim()).Bind(m)
        return x

    def animate(x, values, base=(1, 1, 1), axis=None, hold=True):
        """values[h] in [0, 1] scales the xform (all axes, or one axis). Writes samples only on change."""
        attr = x.AddScaleOp(opSuffix="anim")
        prev = None
        for h, v in enumerate(values):
            v = round(max(0.0, v), 3)
            if v == prev:
                continue
            if hold and prev is not None and h > 0:
                attr.Set(vec(prev, base, axis), h - 1 + 0.95)
            attr.Set(vec(v, base, axis), h)
            prev = v
        if prev is None:
            attr.Set(vec(0, base, axis), 0)

    def vec(v, base, axis):
        e = 1e-4
        if axis is None:
            return Gf.Vec3f(max(v, e), max(v, e), max(v, e))
        s = [1.0, 1.0, 1.0]
        s[axis] = max(v, e)
        return Gf.Vec3f(*s)

    # ground, path, road
    width = span + 40
    cube("/Site", (width, 0.6, HD + 16), (cx, -0.3, 2), mat((0.24, 0.36, 0.23)), name="ground")
    cube("/Site", (width, 0.62, 3.0), (cx, -0.29, HD / 2 + 6), mat((0.33, 0.33, 0.35)), name="road")

    frame_m, glass_m = mat((0.92, 0.93, 0.95), rough=0.5), mat((0.75, 0.88, 0.95), opacity=0.28, rough=0.1)
    broken_m = mat((0.85, 0.12, 0.10), emissive=(0.5, 0.05, 0.03))
    lamp_m = mat((1.0, 0.85, 0.35), emissive=(1.0, 0.78, 0.25))
    soil_m = mat((0.30, 0.22, 0.16))
    crop_m = {"broccoli": mat((0.30, 0.62, 0.25)), "radish": mat((0.62, 0.42, 0.62))}
    ready_m = {"broccoli": mat((0.48, 0.85, 0.32)), "radish": mat((0.86, 0.50, 0.80))}

    for i, cid in enumerate(ids):
        hx = -span / 2 + HW / 2 + i * (HW + GAP)
        hp = f"/Site/House{cid}"
        UsdGeom.Xform.Define(st, hp)
        # frame posts and glass walls
        for sx in (-1, 1):
            for sz in (-1, 1):
                cube(hp, (0.25, WALL, 0.25), (hx + sx * HW / 2, WALL / 2, sz * HD / 2), frame_m)
        cube(hp, (HW, WALL, 0.08), (hx, WALL / 2, -HD / 2), glass_m)
        cube(hp, (HW, WALL, 0.08), (hx, WALL / 2, HD / 2), glass_m)
        cube(hp, (0.08, WALL, HD), (hx - HW / 2, WALL / 2, 0), glass_m)
        cube(hp, (0.08, WALL, HD), (hx + HW / 2, WALL / 2, 0), glass_m)
        slope = math.degrees(math.atan2(RIDGE, HW / 2))
        rl = math.hypot(RIDGE, HW / 2)
        for side in (-1, 1):
            cube(hp, (rl, 0.08, HD), (hx + side * HW / 4, WALL + RIDGE / 2, 0), glass_m, rot=(0, 0, -side * slope))
        cube(hp, (0.25, 0.25, HD + 0.2), (hx, WALL + RIDGE, 0), frame_m)
        # broken panes: 12 tiles across both roof halves, red while broken
        panes = [0] * n
        for h, fr in enumerate(F):
            for dm in fr["dmg"]:
                if dm["eq"] == f"{cid}.glass":
                    panes[h] = dm["panes"]
        for k in range(12):
            side = -1 if k % 2 == 0 else 1
            z = -HD / 2 + 1.2 + (k // 2) * (HD - 2.4) / 5
            t = cube(hp, (rl * 0.42, 0.14, 1.6), (hx + side * HW / 4, WALL + RIDGE / 2 + 0.06, z), broken_m,
                     rot=(0, 0, -side * slope), name="pane")
            animate(t, [1.0 if p > k else 0.0 for p in panes])
        # lamps over the beds, scaled by lamp output
        lmax = max((fr["c"][cid]["lamp"] for fr in F), default=0) or 1
        for z in (-HD / 4, HD / 4):
            l = cube(hp, (HW * 0.8, 0.12, 0.35), (hx, WALL - 0.3, z), lamp_m, name="lamp")
            animate(l, [1.0 if fr["c"][cid]["lamp"] > 0.02 * lmax else 0.0 for fr in F])
        # benches: one slot per batch, in order of first appearance; height = growth, cut to 0 at harvest
        order: list[str] = []
        for fr in F:
            for b in fr["b"]:
                if b["c"] == cid and b["id"] not in order:
                    order.append(b["id"])
        slots = max(1, len(order))
        cols = 2
        rows = math.ceil(min(slots, 8) / cols)
        for j, bid in enumerate(order[:16]):
            col_i, row_i = (j % 8) % cols, (j % 8) // cols
            bx = hx + (-1 if col_i == 0 else 1) * HW / 4
            bz = -HD / 2 + 1.5 + (row_i + 0.5) * (HD - 3) / rows
            bw, bd = HW / 2 - 1.0, (HD - 3) / rows - 0.6
            cube(hp, (bw, 0.5, bd), (bx, 0.25, bz), soil_m, name="bench")
            crop = next(b["crop"] for fr in F for b in fr["b"] if b["id"] == bid).split("_")[0]
            grow, ready = [], []
            for fr in F:
                b = next((b for b in fr["b"] if b["id"] == bid), None)
                if b is None or b["st"] == "harvested":
                    grow.append(0.0); ready.append(0.0)
                    continue
                k = 1.0 if b["ready"] is None or b["st"] == "ready" else b["age"] / max(0.1, b["age"] + b["ready"])
                grow.append(round(0.15 + 0.85 * min(1.0, k), 2))
                ready.append(1.0 if b["st"] == "ready" else 0.0)
            # growing layer anchored at the bench top: scale y about the base via an inner offset
            g = UsdGeom.Xform.Define(st, f"{hp}/crop{j}")
            UsdGeom.XformCommonAPI(g).SetTranslate(Gf.Vec3d(bx, 0.5, bz))
            animate(g, grow, axis=1)
            cube(g.GetPath().pathString, (bw - 0.2, 1.4, bd - 0.2), (0, 0.7, 0), crop_m.get(crop, crop_m["broccoli"]))
            r = UsdGeom.Xform.Define(st, f"{hp}/ready{j}")
            UsdGeom.XformCommonAPI(r).SetTranslate(Gf.Vec3d(bx, 1.95, bz))
            animate(r, ready)
            cube(r.GetPath().pathString, (bw - 0.1, 0.12, bd - 0.1), (0, 0, 0), ready_m.get(crop, ready_m["broccoli"]))

    # energy centre: building, chimney, boiler fault beacon
    ep = "/Site/Energy"
    UsdGeom.Xform.Define(st, ep)
    cube(ep, (8, 5, 7), (ec_x, 2.5, -1), mat((0.55, 0.52, 0.48)))
    cube(ep, (1.0, 6, 1.0), (ec_x + 2.5, 5.5, -2.5), mat((0.40, 0.38, 0.36)))
    cube(ep, (2.6, 4, 2.6), (ec_x + 6.5, 2, -3), mat((0.72, 0.74, 0.78)))   # buffer tank
    down = [1.0 if "boiler" in fr["faults"] else 0.0 for fr in F]
    flash = [v * (1.0 if (h // 2) % 2 == 0 else 0.55) for h, v in enumerate(down)]
    bcn = cube(ep, (1.4, 1.4, 1.4), (ec_x, 5.9, -1), mat((1.0, 0.15, 0.1), emissive=(1.0, 0.1, 0.05)), name="beacon")
    animate(bcn, flash)
    ok = cube(ep, (0.8, 0.8, 0.8), (ec_x, 5.5, -1), mat((0.35, 0.88, 0.42), emissive=(0.2, 0.7, 0.3)), name="ok")
    animate(ok, [1.0 - v for v in down])

    # profit column (height = profit so far / final profit, capped) and a day ticker
    pm = max(1.0, max(fr["money"]["profit_so_far_eur"] for fr in F))
    cube("/Site", (2.2, 0.3, 2.2), (ec_x + 6.5, 0.15, 6), mat((0.2, 0.2, 0.22)))
    col = UsdGeom.Xform.Define(st, "/Site/Profit")
    UsdGeom.XformCommonAPI(col).SetTranslate(Gf.Vec3d(ec_x + 6.5, 0.3, 6))
    animate(col, [min(1.0, max(0.0, fr["money"]["profit_so_far_eur"] / pm)) for fr in F], axis=1)
    cube("/Site/Profit", (1.8, 12, 1.8), (0, 6, 0), mat((0.95, 0.75, 0.2), emissive=(0.35, 0.25, 0.02), rough=0.3))
    for day in range(0, n // 24 + 1, 7):                 # week marks along the road
        cube("/Site", (0.25, 0.2, 1.2), (cx - width / 2 + 2 + day / (n / 24) * (width - 4), 0.1, HD / 2 + 9), frame_m, name="tick")
    tk = UsdGeom.Xform.Define(st, "/Site/Clock")
    UsdGeom.XformCommonAPI(tk).SetTranslate(Gf.Vec3d(0, 0.3, HD / 2 + 9))
    op = tk.AddTranslateOp(opSuffix="anim")
    for h in (0, n - 1):
        op.Set(Gf.Vec3d(cx - width / 2 + 2 + h / n * (width - 4), 0, 0), h)
    cube("/Site/Clock", (0.9, 0.6, 0.9), (0, 0, 0), mat((1.0, 1.0, 1.0), emissive=(0.8, 0.8, 0.8)))

    st.GetRootLayer().Save()
    UsdUtils.CreateNewARKitUsdzPackage(Sdf.AssetPath(usdc), out)
    Path(usdc).unlink(missing_ok=True)
    print(f"{out}: {n} hours over {n / fps:.0f} s, {count[0]} boxes, {Path(out).stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "dump":
        dump(a[1], int(a[2]), a[3])
    elif a and a[0] == "build":
        secs = float(a[a.index("--seconds") + 1]) if "--seconds" in a else 45.0
        build(a[1], a[2], secs)
    else:
        print(__doc__)
