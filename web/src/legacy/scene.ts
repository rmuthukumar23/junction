// @ts-nocheck
// Legacy port of scripts/pixel/scene.js (vanilla JS). Untyped on purpose: replaced by the sprite system (web/src/engine).
import { Sprites } from "./sprites";
// Side-view pixel greenhouse world. Draws one logical 480x270 frame from Replay frame data.
// window.PixelScene.create(canvas, {onPick}) -> {setData, render, trigger, bubble, flash, reset, hit, setHover}
  const S = Sprites, P = S.P;
  const W = 480, H = 270, GY = 214, EY = 156, RY = 128, BY = 198, WIRE = 108;
  const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
  const lerp = (a, b, t) => a + (b - a) * t;
  const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
  const num = (v, d) => (v == null || isNaN(v) ? d : +v);
  const isOn = (v) => (typeof v === "number" ? v > 0.01 : !!v && v !== "off" && v !== "idle" && v !== "none" && v !== "0");

  // ---- sky colour table: [level 0..15][grey 0..2][band 0..5], built once
  function hex(c) { return [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)]; }
  function mix(a, b, t) { return "#" + [0, 1, 2].map((i) => ("0" + Math.round(lerp(a[i], b[i], t)).toString(16)).slice(-2)).join(""); }
  const SKY = [];
  (function () {
    const nT = hex("#060b1f"), nB = hex("#16234a"), dT = hex("#3f82c9"), dB = hex("#a4d4f0"), gT = hex("#5d7288"), gB = hex("#a9b8c6"), sB = hex("#e9895a");
    for (let l = 0; l < 16; l++) {
      const d = l / 15, dusk = 4 * d * (1 - d), row = [];
      for (let g = 0; g < 3; g++) {
        const bands = [];
        for (let k = 0; k < 6; k++) {
          const q = k / 5;
          let top = [0, 1, 2].map((i) => lerp(nT[i], lerp(dT[i], gT[i], g * 0.4), d));
          let bot = [0, 1, 2].map((i) => lerp(nB[i], lerp(dB[i], gB[i], g * 0.4), d));
          const c = [0, 1, 2].map((i) => lerp(top[i], bot[i], q));
          const e = [0, 1, 2].map((i) => lerp(c[i], sB[i], dusk * 0.55 * q * q));
          bands.push(mix(e, e, 0));
        }
        row.push(bands);
      }
      SKY.push(row);
    }
  })();

  const PCOL = ["#c9ced8", "#bfe4ff", "#9ad7ff", "#ffd23f", "#ffe27a", "#6fe36f", "#8b5a2b", "#ffffff", "#ff8a4d"];
  const NP = 320;
  const BREAK_DIRS = [[-1, -0.2], [1, -0.1], [0.1, -1], [-0.3, 1], [0.8, 0.8], [-0.9, 0.7], [0.6, -0.8], [-0.7, -0.7]];

  function create(canvas, opts) {
    opts = opts || {};
    const ctx = canvas.getContext("2d");
    canvas.width = W; canvas.height = H; ctx.imageSmoothingEnabled = false;
    const mk = () => { const c = document.createElement("canvas"); c.width = W; c.height = H; const x = c.getContext("2d"); x.imageSmoothingEnabled = false; return [c, x]; };
    let D = null, frames = null, last = 0, cids = [], houses = [], hmap = {}, back = null, front = null, mascot = null, maxW = {}, maxHeat = {}, maxBuf = 1, maxCO2 = 1, maxHeatAll = 1;
    let T = 0, shake = 0, lightning = 0, hover = null, lampPhase = 0;
    const clouds = [], stars = [], cl = { v: 0.5 };
    for (let i = 0; i < 7; i++) clouds.push({ x: S.hash(i + 3) * 540, y: 14 + S.hash(i + 40) * 78, v: 0.5 + S.hash(i + 9) * 0.9, k: i % 3 });
    for (let i = 0; i < 40; i++) stars.push({ x: S.hash(i + 100) * W, y: S.hash(i + 200) * 120, p: S.hash(i + 300) * 6 });
    const cloudW = [S.cloudSprite(0, "#f3f7fb", "#cfd9e6"), S.cloudSprite(1, "#f3f7fb", "#cfd9e6"), S.cloudSprite(2, "#f3f7fb", "#cfd9e6")];
    const cloudG = [S.cloudSprite(0, "#6b7684", "#566070"), S.cloudSprite(1, "#6b7684", "#566070"), S.cloudSprite(2, "#6b7684", "#566070")];

    // particles
    const px = new Float32Array(NP), py = new Float32Array(NP), pvx = new Float32Array(NP), pvy = new Float32Array(NP), pl = new Float32Array(NP), pm = new Float32Array(NP), ps = new Float32Array(NP);
    const pt = new Uint8Array(NP), pc = new Uint8Array(NP); let pcur = 0;
    function spawn(type, x, y, vx, vy, life, col, size) {
      let i = pcur; for (let n = 0; n < NP; n++) { const j = (pcur + n) % NP; if (pl[j] <= 0) { i = j; break; } }
      pcur = (i + 1) % NP; px[i] = x; py[i] = y; pvx[i] = vx; pvy[i] = vy; pl[i] = life; pm[i] = life; pt[i] = type; pc[i] = col; ps[i] = size || 1;
    }
    // weather drops
    const NR = 180, rx = new Float32Array(NR), ry = new Float32Array(NR), rv = new Float32Array(NR);
    for (let i = 0; i < NR; i++) { rx[i] = Math.random() * W; ry[i] = Math.random() * GY; rv[i] = 0.7 + Math.random() * 0.6; }
    // bubbles
    const NB = 8, bt = new Array(NB).fill(""), bx = new Array(NB).fill(null), bl = new Float32Array(NB), bcol = new Array(NB).fill(P.white); let bcur = 0;
    // worker + van
    const wk = { x: 224, face: 1, ph: 0, anim: 0, tx: 224, kind: "", spark: 0 };
    const van = { x: -40, t: -1, tx: 0, wait: 0 };
    // live state
    const cur = { t: 0, rh: 0, sun: 0, wind: 0, buf: 0, co2: 0, imp: 0, exp: 0, gas: 0, chp: 0, boiler: 0, heat: 0, hod: 0, day: 0, precip: 0, snow: false, c: {}, faults: "", heatTot: 0 };
    const en = { flash: 0, flashCol: P.bad, chpFault: false, boilerFault: false, blink: 0 };

    function resolve(target, f) {
      if (target == null) return null; const t = String(target);
      if (hmap[t]) return t; const tl = t.toLowerCase();
      if (/boiler|chp|energy|buffer|pump|grid/.test(tl)) return "energy";
      if (f) for (let i = 0; i < f.b.length; i++) if (f.b[i].id === t) return f.b[i].c;
      if (hmap[t[0]]) return t[0]; if (hmap[t[0] && t[0].toUpperCase()]) return t[0].toUpperCase();
      return null;
    }

    function setData(data) {
      D = data; frames = data.frames; last = frames.length - 1;
      cids = Object.keys(frames[0].c).sort(); houses = []; hmap = {};
      const n = cids.length, avail = 252, gap = 8, w = Math.min(76, Math.floor((avail - (n - 1) * gap) / Math.max(1, n)));
      const x00 = 222 + Math.floor((avail - (n * w + (n - 1) * gap)) / 2);
      maxHeat = {}; maxW = {}; maxBuf = 1; maxCO2 = 1; maxHeatAll = 1;
      for (const f of frames) {
        maxBuf = Math.max(maxBuf, num(f.ec.buffer, 0)); maxCO2 = Math.max(maxCO2, num(f.ec.co2, 0)); maxHeatAll = Math.max(maxHeatAll, num(f.ec.heat, 0));
        for (const c of cids) maxHeat[c] = Math.max(maxHeat[c] || 1e-6, num(f.c[c].heat, 0));
        for (const b of f.b) if (b.st !== "harvested") maxW[b.crop] = Math.max(maxW[b.crop] || 1, num(b.w, 0));
      }
      const timeline = {};
      for (const e of data.events || []) {
        if (e.kind === "window_break" || e.kind === "window_repaired") { const c = resolve(e.target, null) || String(e.target || "")[0]; (timeline[c] = timeline[c] || []).push({ h: e.h, broken: e.kind === "window_break" }); }
      }
      for (let i = 0; i < n; i++) {
        const id = cids[i], x0 = x00 + i * (w + gap), crop = ((data.meta.compartments || {})[id] || {}).crop || "";
        const hs = { id, i, x0, w, cx: x0 + (w >> 1), crop, fam: S.family(crop), side: i % 2 === 0 ? 0 : 1, tl: (timeline[id] || []).sort((a, b) => a.h - b.h),
          broken: false, crackT: 99, flash: 0, frost: 0, repairT: 99, coldAcc: 0, fault: 0, tint: 0, name: String(crop).split("_")[0].toUpperCase() };
        houses.push(hs); hmap[id] = hs; cur.c[id] = { t: 0, rh: 0, co2: 0, vent: 0, lamp: 0, heat: 0, co2req: 0, par: 0, screen: false, spd: 0, spn: 0, sp_co2: 0 };
      }
      mascot = S.mascotFor(data.meta || {});
      buildStatic(); reset(0);
    }

    function reset(hf) {
      for (let i = 0; i < NP; i++) pl[i] = 0; bl.fill(0); shake = 0; lightning = 0; van.t = -1;
      const h = Math.floor(hf);
      for (const hs of houses) {
        hs.broken = false; for (const e of hs.tl) if (e.h <= h) hs.broken = e.broken;
        hs.crackT = hs.broken ? 99 : 99; hs.frost = hs.broken ? 0.6 : 0; hs.repairT = 99; hs.flash = 0;
      }
      en.flash = 0;
    }

    // -------------------------------------------------------------- static layers
    function pane(hs) { const pw = Math.max(10, Math.floor(hs.w / 5)); return { x: hs.side === 0 ? hs.x0 + 2 : hs.x0 + hs.w - pw - 2, y: EY + 5, w: pw, h: 28 }; }
    function buildStatic() {
      const b = mk(), f = mk(); back = b[0]; front = f[0]; const g = b[1], q = f[1];
      // ground
      S.rect(g, P.grass, 0, GY, W, 3); S.rect(g, P.grass2, 0, GY, W, 1);
      S.rect(g, P.soil, 0, GY + 3, W, 33); for (let i = 0; i < 260; i++) { g.fillStyle = i % 3 ? P.soil2 : P.soil3; g.fillRect((S.hash(i) * W) | 0, GY + 4 + ((S.hash(i + 500) * 30) | 0), 2, 1); }
      S.rect(g, P.road2, 0, 248, W, 1); S.rect(g, P.road, 0, 249, W, 15); S.rect(g, P.road2, 0, 264, W, 1); S.rect(g, P.soil2, 0, 265, W, 5);
      for (let x = 6; x < W; x += 28) S.rect(g, P.paint, x, 256, 14, 1);
      // gas meter + pipe
      S.rect(g, P.gas, 20, 200, 14, 14); S.rect(g, "#a88418", 20, 211, 14, 3); S.rect(g, P.ink, 24, 203, 6, 5); S.rect(g, P.gas, 0, 212, 21, 2);
      // pylon
      for (let y = 140; y < GY; y += 2) { const t = (y - 140) / 74, hw = 2 + t * 7; S.rect(g, P.steel, 14 - hw, y, 1, 1); S.rect(g, P.steel, 14 + hw, y, 1, 1); }
      for (let y = 148; y < GY; y += 12) S.line(g, 14 - (2 + (y - 140) / 74 * 7), y, 14 + (2 + (y - 140) / 74 * 7), y + 6, P.steelDk);
      S.rect(g, P.steelHi, 4, 142, 20, 1); S.rect(g, P.steelHi, 7, 150, 14, 1);
      // building shell
      S.rect(g, P.brick, 40, 130, 112, 84);
      for (let y = 130; y < GY; y += 4) { S.rect(g, P.brick2, 40, y, 112, 1); for (let x = 40 + ((y >> 2) & 1) * 4; x < 152; x += 8) S.rect(g, P.brick2, x, y, 1, 4); }
      for (let i = 0; i < 80; i++) S.rect(g, P.brickHi, 40 + ((S.hash(i + 700) * 112) | 0), 132 + ((S.hash(i + 800) * 80) | 0), 2, 1);
      S.rect(g, P.roof, 37, 126, 118, 5); S.rect(g, P.roofHi, 37, 126, 118, 1);
      // chimneys
      S.rect(g, P.chimney, 66, 100, 10, 26); S.rect(g, P.chimneyHi, 66, 100, 2, 26); S.rect(g, P.roof, 64, 98, 14, 3);
      S.rect(g, P.chimney, 126, 110, 8, 16); S.rect(g, P.chimneyHi, 126, 110, 2, 16); S.rect(g, P.roof, 124, 108, 12, 3);
      // windows (dark)
      S.rect(g, P.ink, 49, 139, 42, 50); S.rect(g, "#1b2230", 51, 141, 38, 46); S.rect(g, P.ink, 97, 147, 40, 42); S.rect(g, "#1b2230", 99, 149, 36, 38);
      S.rect(g, P.roof, 49, 189, 42, 2); S.rect(g, P.roof, 97, 189, 40, 2);
      // heat buffer tank
      S.rect(g, P.steelDk, 155, 122, 18, 92); S.rect(g, P.steel, 156, 124, 16, 90); S.rect(g, P.steelDk, 157, 120, 14, 2); S.rect(g, P.steelHi, 157, 125, 2, 86);
      S.rect(g, P.ink, 160, 130, 10, 80);
      // CO2 tank
      S.rect(g, P.steelDk, 178, 194, 40, 16); S.rect(g, "#d8eceb", 179, 195, 38, 14); S.rect(g, "#a9cfcc", 179, 205, 38, 4); S.rect(g, P.ink, 184, 199, 28, 6);
      S.rect(g, P.steelDk, 184, 210, 3, 4); S.rect(g, P.steelDk, 208, 210, 3, 4);
      // houses: bench, posts, wire, signs, frames
      S.rect(g, P.ink, 225, WIRE, W - 225, 1);
      const px0 = houses.length ? houses[0].x0 - 4 : 218;
      for (let i = 0; i <= houses.length; i++) { const x = i === 0 ? px0 : houses[i - 1].x0 + houses[i - 1].w + 3; S.rect(q, P.woodDk, x, WIRE - 2, 3, GY - WIRE + 2); S.rect(q, P.wood, x, WIRE - 2, 1, GY - WIRE + 2); }
      S.rect(q, P.ink, px0, WIRE, houses.length ? houses[houses.length - 1].x0 + houses[houses.length - 1].w + 6 - px0 : 4, 1);
      for (let x = px0 + 10; x < W - 20; x += 22) S.rect(q, P.warn, x, WIRE, 2, 1);
      for (const hs of houses) {
        const x0 = hs.x0, w = hs.w, cx = hs.cx;
        S.rect(g, P.wood, x0 + 2, BY, w - 4, 3); S.rect(g, P.woodHi, x0 + 2, BY, w - 4, 1); S.rect(g, P.woodDk, x0 + 4, BY + 3, 2, GY - BY - 3); S.rect(g, P.woodDk, x0 + w - 6, BY + 3, 2, GY - BY - 3);
        S.rect(g, P.soil2, x0 + 3, BY - 1, w - 6, 1);
        // frame (front layer)
        const fr = P.frame;
        S.rect(q, fr, x0, EY, 1, GY - EY); S.rect(q, fr, x0 + w - 1, EY, 1, GY - EY); S.rect(q, fr, x0, EY, w, 1);
        for (let k = 1; k < 4; k++) S.rect(q, "#9fc0da", x0 + ((w * k / 4) | 0), EY + 1, 1, GY - EY - 1);
        S.line(q, x0, EY, cx, RY, fr); S.line(q, x0 + w - 1, EY, cx, RY, fr);
        S.line(q, x0 + 8, EY, cx, RY + 11, "#9fc0da"); S.line(q, x0 + w - 9, EY, cx, RY + 11, "#9fc0da");
        S.rect(q, fr, cx, RY, 1, 5);
        S.rect(q, P.ink, cx, WIRE, 1, 12); // hanger
        const lab = String(hs.id) + " - " + hs.name, pw = S.textWidth(lab) + 7, sx = cx - (pw >> 1);
        S.plate(q, lab, sx, WIRE + 4, P.white);
        S.rect(q, "#8fd0ff", sx + 2, WIRE + 5, 1, 1);
      }
      // static plates for energy centre
      S.plate(q, "GRID", 3, 124, P.white); S.plate(q, "GAS", 20, 188, P.white); S.plate(q, "CHP", 56, 129 - 8 + 8 - 1, P.white);
      S.plate(q, "BOILER", 100, 137, P.white);
    }

    // -------------------------------------------------------------- trigger API
    function bubble(target, textStr, col) {
      const i = bcur; bcur = (bcur + 1) % NB; bt[i] = String(textStr).toUpperCase().slice(0, 22); bx[i] = target; bl[i] = 3.2; bcol[i] = col || P.white;
    }
    function flash(target, col) {
      const k = resolve(target, frames && frames[Math.floor(frame)]) || target;
      if (hmap[k]) { hmap[k].flash = 1.4; hmap[k].flashCol = col || P.bad; } else { en.flash = 1.4; en.flashCol = col || P.bad; }
    }
    let frame = 0;
    function trigger(ev) {
      const f = frames[clamp(Math.floor(frame), 0, last)], k = ev.kind, tg = resolve(ev.target, f), hs = tg && hmap[tg];
      const col = ev.severity === "bad" ? P.bad : ev.severity === "warn" ? P.warn : P.info;
      if (k === "window_break" && hs) {
        hs.broken = true; hs.crackT = 0.001; hs.flash = 1.2; hs.flashCol = P.white; shake = 0.5;
        const p = pane(hs); for (let i = 0; i < 16; i++) spawn(1, p.x + 3 + Math.random() * (p.w - 6), p.y + 6 + Math.random() * 10, (Math.random() - 0.5) * 34, -10 - Math.random() * 20, 1.6 + Math.random(), 1, 1 + (Math.random() * 2 | 0));
        bubble(tg, "window broke!", P.bad);
      } else if (k === "window_repaired" && hs) { hs.broken = false; hs.repairT = 0.001; hs.flash = 0.8; hs.flashCol = P.good; bubble(tg, "window fixed", P.good);
      } else if (k === "storm") { lightning = 0.5; shake = 0.2; bubble("energy", "storm!", P.warn);
      } else if (k === "storm_damage") { flash(tg || "energy", P.warn); shake = 0.35; if (hs) for (let i = 0; i < 6; i++) spawn(3, hs.cx + (Math.random() - 0.5) * hs.w, EY - 4, (Math.random() - 0.5) * 40, -10, 0.5, 3, 1);
      } else if (k === "equipment") { en.flash = 1.6; en.flashCol = col; const p = String(ev.text || "").toLowerCase(); bubble("energy", /working again|fixed|repaired/.test(p) ? "back online" : "fault!", col);
        if (!/working again|fixed|repaired/.test(p)) for (let i = 0; i < 10; i++) spawn(3, 95 + Math.random() * 30, 150, (Math.random() - 0.5) * 50, -20 + Math.random() * 15, 0.7, 3 + (i & 1), 1);
      } else if (k === "order_arrived" || k === "late_delivery") { if (k === "order_arrived") { van.t = 0; van.x = -30; van.tx = tg === "energy" || !hs ? 196 : hs.cx - 10; van.wait = 0; } bubble(hs ? tg : "road", k === "late_delivery" ? "late delivery" : "delivery", k === "late_delivery" ? P.warn : P.info);
      } else if (k === "harvest") { if (hs) for (let i = 0; i < 8; i++) spawn(5, hs.cx + (Math.random() - 0.5) * hs.w * 0.7, BY - 8, (Math.random() - 0.5) * 10, -14 - Math.random() * 10, 1, 5, 1); bubble(tg || "worker", "harvest", P.good);
      } else if (k === "plant") { if (hs) for (let i = 0; i < 6; i++) spawn(6, hs.cx + (Math.random() - 0.5) * hs.w * 0.7, BY - 2, (Math.random() - 0.5) * 20, -12, 0.6, 6, 1); bubble(tg || "worker", "planted", P.good);
      } else if (k === "alarm") { flash(tg || "energy", P.bad); bubble(tg || "energy", "alarm", P.bad);
      } else if (k === "order_placed") { bubble("worker", "order placed", P.info);
      } else if (k === "hire" || k === "release") { bubble("worker", k, P.info);
      } else { flash(tg || "energy", col); bubble(tg || "energy", String(k).replace(/_/g, " "), col); }
    }

    // -------------------------------------------------------------- per-frame state
    function interp(hf) {
      const i = clamp(Math.floor(hf), 0, last), a = clamp(hf - i, 0, 1), f0 = frames[i], f1 = frames[Math.min(last, i + 1)];
      frame = hf; cur.f = f0; cur.a = a;
      cur.t = lerp(f0.out.t, f1.out.t, a); cur.rh = lerp(f0.out.rh, f1.out.rh, a); cur.sun = lerp(f0.out.sun, f1.out.sun, a); cur.wind = lerp(f0.out.wind, f1.out.wind, a);
      cur.buf = lerp(num(f0.ec.buffer, 0), num(f1.ec.buffer, 0), a) / maxBuf; cur.co2 = lerp(num(f0.ec.co2, 0), num(f1.ec.co2, 0), a) / maxCO2;
      cur.imp = lerp(num(f0.ec.imp, 0), num(f1.ec.imp, 0), a); cur.exp = lerp(num(f0.ec.exp, 0), num(f1.ec.exp, 0), a); cur.gas = lerp(num(f0.ec.gas, 0), num(f1.ec.gas, 0), a);
      cur.heat = lerp(num(f0.ec.heat, 0), num(f1.ec.heat, 0), a);
      cur.chp = isOn(f0.ec.chp) ? (typeof f0.ec.chp === "number" ? f0.ec.chp : 1) : 0; cur.boiler = isOn(f0.ec.boiler) ? (typeof f0.ec.boiler === "number" ? Math.min(1, f0.ec.boiler) : 1) : 0;
      cur.hod = ((hf % 24) + 24) % 24; cur.day = Math.floor(hf / 24) + 1;
      en.chpFault = en.boilerFault = false; const fl = f0.faults || [];
      for (let k = 0; k < fl.length; k++) { const s = String(fl[k]).toLowerCase(); if (s.indexOf("chp") >= 0) en.chpFault = true; else if (s.indexOf("boiler") >= 0) en.boilerFault = true; else { en.chpFault = en.boilerFault = true; } }
      if (en.chpFault) cur.chp = 0; if (en.boilerFault) cur.boiler = 0;
      cur.heatTot = 0;
      for (let k = 0; k < cids.length; k++) {
        const id = cids[k], c0 = f0.c[id], c1 = f1.c[id], o = cur.c[id];
        o.t = lerp(c0.t, c1.t, a); o.rh = lerp(c0.rh, c1.rh, a); o.co2 = lerp(c0.co2, c1.co2, a); o.vent = lerp(num(c0.vent, 0), num(c1.vent, 0), a);
        o.lamp = lerp(num(c0.lamp, 0), num(c1.lamp, 0), a); o.heat = lerp(num(c0.heat, 0), num(c1.heat, 0), a); o.co2req = lerp(num(c0.co2req, 0), num(c1.co2req, 0), a);
        o.par = lerp(num(c0.par, 0), num(c1.par, 0), a); o.screen = !!c0.screen; o.spd = num(c0.sp_day, 20); o.spn = num(c0.sp_night, 16); o.sp_co2 = num(c0.sp_co2, 800); cur.heatTot += o.heat;
        hmap[id].dmg = f0.damage ? num(f0.damage[id], 0) : 0;
      }
    }

    function skyLevel() {
      const hod = cur.hod, day = smooth(7, 9.5, hod) * (1 - smooth(15.5, 18, hod));
      const want = day > 0.05 ? clamp(1 - cur.sun / (Math.max(0.2, day) * 110), 0, 1) : 0.5;
      cl.v += (want - cl.v) * 0.05; cur.day01 = day; return [Math.round(day * 15), clamp(Math.round(cl.v * 2), 0, 2)];
    }

    // -------------------------------------------------------------- drawing helpers
    function drawSky(lvl, grey) {
      const b = SKY[lvl][grey], bh = (GY + 4) / 6;
      for (let k = 0; k < 6; k++) { ctx.fillStyle = b[k]; ctx.fillRect(0, Math.floor(k * bh), W, Math.ceil(bh) + 1); }
      ctx.fillStyle = b[1]; for (let x = 0; x < W; x += 4) ctx.fillRect(x, Math.floor(bh) - 2, 2, 2);
      ctx.fillStyle = b[2]; for (let x = 2; x < W; x += 4) ctx.fillRect(x, Math.floor(2 * bh) - 2, 2, 2);
    }
    function drawCelestial(day) {
      const hod = cur.hod;
      if (day < 0.9) for (let i = 0; i < stars.length; i++) { const s = stars[i], tw = Math.sin(T * 2 + s.p) > 0.3; ctx.globalAlpha = (1 - day) * (tw ? 0.95 : 0.4); ctx.fillStyle = "#e8f0ff"; ctx.fillRect(s.x | 0, s.y | 0, 1, 1); }
      ctx.globalAlpha = 1;
      const ts = (hod - 7.5) / 10.5;
      if (ts >= 0 && ts <= 1) { const x = 50 + ts * 380, y = 104 - Math.sin(Math.PI * ts) * 52 | 0, a = 1 - cl.v * 0.5; ctx.globalAlpha = a;
        S.rect(ctx, "#ffd84a", x - 5 | 0, y - 4, 10, 8); S.rect(ctx, "#ffd84a", x - 4 | 0, y - 5, 8, 10); S.rect(ctx, "#fff3a0", x - 3 | 0, y - 3, 3, 3);
        ctx.fillStyle = "#ffe27a"; const r = (T * 2 | 0) & 1; ctx.fillRect(x - 1 | 0, y - 8 - r, 2, 2); ctx.fillRect(x - 1 | 0, y + 7 + r, 2, 2); ctx.fillRect(x - 9 - r | 0, y - 1, 2, 2); ctx.fillRect(x + 8 + r | 0, y - 1, 2, 2); ctx.globalAlpha = 1; }
      const tn = ((hod - 17 + 24) % 24) / 14.5;
      if (tn >= 0 && tn <= 1) { const x = 60 + tn * 360, y = 100 - Math.sin(Math.PI * tn) * 58 | 0; S.rect(ctx, "#e8eefc", x - 4 | 0, y - 4, 8, 8); S.rect(ctx, "#e8eefc", x - 3 | 0, y - 5, 6, 10); ctx.globalAlpha = 1; S.rect(ctx, SKY[Math.round(cur.day01 * 15)][0][2], x - 1 | 0, y - 4, 4, 7); }
    }
    function drawClouds(dt) {
      const sp = 3 + cur.wind * 1.6;
      for (let i = 0; i < clouds.length; i++) {
        const c = clouds[i]; c.x += dt * sp * c.v; if (c.x > W + 10) c.x = -70;
        const night = cur.day01 < 0.3; ctx.globalAlpha = night ? 0.35 : 1; ctx.drawImage(cloudW[c.k], c.x | 0, c.y | 0);
        if (cl.v > 0.25) { ctx.globalAlpha = (night ? 0.35 : 1) * clamp(cl.v - 0.1, 0, 0.8); ctx.drawImage(cloudG[c.k], c.x | 0, c.y | 0); }
      }
      ctx.globalAlpha = 1;
    }

    function drawEnergy(dt) {
      const blink = (T * 4 | 0) & 1;
      // windows glow handled in emissive pass; here: buffer + co2 fills
      const bh = 80, fill = Math.round(bh * clamp(cur.buf, 0, 1));
      S.rect(ctx, P.heat, 160, 130 + bh - fill, 10, fill); if (fill > 2) S.rect(ctx, "#ff9a7a", 160, 130 + bh - fill, 10, 1);
      for (let y = 134; y < 210; y += 10) S.rect(ctx, "rgba(0,0,0,0.35)", 160, y, 10, 1);
      const cw = Math.round(28 * clamp(cur.co2, 0, 1)); S.rect(ctx, P.co2, 184, 199, cw, 6); S.rect(ctx, "rgba(0,0,0,0.3)", 184, 203, cw, 2);
      // plates (dynamic)
      S.plate(ctx, "HEAT BUFFER " + Math.round(cur.buf * 100) + "%", 120, 109 + 5, P.white);
      S.plate(ctx, "CO2 STOCK " + Math.round(cur.co2 * 100) + "%", 178, 183, P.white);
      const cc = en.chpFault ? (blink ? P.bad : "#601820") : cur.chp > 0 ? P.good : "#46506a", bc = en.boilerFault ? (blink ? P.bad : "#601820") : cur.boiler > 0 ? P.good : "#46506a";
      S.rect(ctx, cc, 86, 143, 3, 3); S.rect(ctx, bc, 132, 151, 3, 3);
      if (en.chpFault || en.boilerFault) { const pl = en.chpFault && en.boilerFault ? "FAULT" : en.chpFault ? "CHP FAULT" : "BOILER FAULT"; S.plate(ctx, pl, 62, 196, blink ? P.white : P.bad, "#5a1018"); }
      // grid wire + packets
      S.line(ctx, 22, 142, 40, 131, P.ink);
      const imp = cur.imp > 0.5, exp = cur.exp > 0.5;
      if (imp || exp) for (let k = 0; k < 3; k++) { let u = ((T * 1.2 + k / 3) % 1); if (exp) u = 1 - u; S.rect(ctx, imp ? P.grid : P.export, (22 + 18 * u) | 0, (142 - 11 * u) | 0, 2, 2); }
      S.plate(ctx, imp ? "IMP " + Math.round(cur.imp) : exp ? "EXP " + Math.round(cur.exp) : "IDLE", 2, 150, imp ? P.grid : exp ? P.export : "#8896ad");
      S.plate(ctx, cur.gas.toFixed(1) + " M3", 2, 216 - 3 - 7 + 8, P.gas);
      if (en.flash > 0) { en.flash -= dt; if ((T * 8 | 0) & 1) { ctx.strokeStyle = en.flashCol; ctx.lineWidth = 1; ctx.strokeRect(38.5, 126.5, 116, 88); } }
      // smoke
      en.sm = (en.sm || 0) - dt;
      if (en.sm <= 0) { en.sm = 0.18; if (cur.chp > 0) spawn(0, 71 + Math.random() * 3, 96, cur.wind * 1.4, -9, 3.2, 0, 2); if (cur.boiler > 0) spawn(0, 129 + Math.random() * 2, 106, cur.wind * 1.4, -8, 2.6, 0, 2); }
      if (en.chpFault || en.boilerFault) { en.sp = (en.sp || 0) - dt; if (en.sp <= 0) { en.sp = 0.25; spawn(3, en.chpFault ? 70 : 118, en.chpFault ? 170 : 175, (Math.random() - 0.5) * 40, -22, 0.5, 3, 1); } }
    }

    function drawPipes() {
      const n = houses.length; if (!n) return; const yH = GY + 11, yC = GY + 19, x1 = houses[n - 1].cx;
      // trunks
      S.rect(ctx, P.heatDim, 162, yH, x1 - 162 + 2, 2); S.rect(ctx, P.heatDim, 162, GY + 3, 2, yH - GY - 1);
      S.rect(ctx, P.co2Dim, 196, yC, x1 - 196 + 2, 2); S.rect(ctx, P.co2Dim, 196, 210, 2, yC - 210);
      const ph = (T * 18) | 0;
      let down = 0;
      for (let i = n - 1; i >= 0; i--) {
        const hs = houses[i], o = cur.c[hs.id], fh = clamp(o.heat / maxHeat[hs.id], 0, 1), fc = clamp(o.co2req / 2, 0, 1);
        S.rect(ctx, P.heatDim, hs.cx - 2, GY + 3, 2, yH - GY - 1); S.rect(ctx, P.co2Dim, hs.cx + 1, GY + 3, 2, yC - GY - 1);
        if (o.heat > 0.05) for (let y = yH - ((ph + i) % 6); y > GY + 2; y -= 6) S.rect(ctx, P.heat, hs.cx - 2, y, 2, 3);
        if (o.co2req > 0.01) for (let y = yC - ((ph + i + 2) % 6); y > GY + 2; y -= 6) S.rect(ctx, P.co2, hs.cx + 1, y, 2, 3);
        down += o.heat; hs._fh = fh; hs._fc = fc;
        const xs = i === 0 ? 162 : houses[i - 1].cx;
        if (down > 0.05) for (let x = xs + ((ph) % 8); x < hs.cx; x += 8) S.rect(ctx, P.heat, x, yH, 4, 2);
        if (down > 0.05 || cur.heat > 0.5) { }
      }
      let dc = 0;
      for (let i = n - 1; i >= 0; i--) { const hs = houses[i], o = cur.c[hs.id]; dc += o.co2req; const xs = i === 0 ? 196 : houses[i - 1].cx; if (dc > 0.01) for (let x = xs + ((ph + 4) % 8); x < hs.cx; x += 8) S.rect(ctx, P.co2, x, yC, 4, 2); }
      if (cur.heatTot > 0.05) for (let y = yH - (ph % 6); y > GY + 2; y -= 6) S.rect(ctx, P.heat, 162, y, 2, 3);
    }

    function crackLines(hs, t) {
      const p = pane(hs), cx = p.x + (p.w >> 1), cy = p.y + 13;
      for (let i = 0; i < BREAK_DIRS.length; i++) {
        const d = BREAK_DIRS[i], len = (p.w * 0.9 + 6 + (i & 1) * 4) * t; let x = cx, y = cy;
        for (let s = 0; s < len; s++) { x += d[0] * (1 + 0.2); y += d[1] * 1.2 + (S.hash(i * 31 + s) - 0.5) * 0.9; if (x < p.x || x > p.x + p.w || y < p.y || y > p.y + p.h) break; ctx.fillRect(x | 0, y | 0, 1, 1); }
      }
    }

    function drawHouse(hs, dt) {
      const o = cur.c[hs.id], x0 = hs.x0, w = hs.w, f = cur.f;
      // glass tint by temperature vs setpoint and humidity haze
      const dev = o.t - (cur.day01 > 0.3 ? o.spd : o.spn);
      if (dev < -1) { ctx.globalAlpha = clamp(-dev / 14, 0, 0.3); ctx.fillStyle = "#4aa3ff"; ctx.fillRect(x0 + 1, EY, w - 2, GY - EY); }
      else if (dev > 2) { ctx.globalAlpha = clamp(dev / 20, 0, 0.25); ctx.fillStyle = "#ffa14a"; ctx.fillRect(x0 + 1, EY, w - 2, GY - EY); }
      ctx.globalAlpha = 1;
      // roof glass faint
      ctx.globalAlpha = 0.12; ctx.fillStyle = P.glass; ctx.fillRect(x0 + 1, EY + 1, w - 2, GY - EY - 1);
      for (let y = RY + 1; y < EY; y++) { const t = (y - RY) / (EY - RY), hw = (w >> 1) * t; ctx.fillRect(hs.cx - hw | 0, y, (hw * 2) | 0, 1); }
      ctx.globalAlpha = 1;
      // crops
      let area = 0, nb = 0; const fam = hs.fam, free = Math.max(0, num((f.c[hs.id] || {}).free, 0));
      for (let k = 0; k < f.b.length; k++) { const b = f.b[k]; if (b.c === hs.id && b.st !== "harvested" && b.st !== "dead") { area += num(b.area, 1); nb++; } }
      const total = area + free || 1, usable = w - 10; let cx = x0 + 5;
      const frost = hs.frost, tierForce = frost > 0.7 ? 1 : 0;
      for (let k = 0; k < f.b.length; k++) {
        const b = f.b[k]; if (b.c !== hs.id || b.st === "harvested" || b.st === "dead") continue;
        const sw = Math.max(4, Math.round((num(b.area, 1) / total) * usable)), bf = S.family(b.crop), sp = S.SPACING[bf];
        const age = num(b.age, 0) + cur.a / 24; let g = b.st === "ready" ? 1 : b.ready != null ? age / (age + Math.max(0, b.ready - cur.a / 24)) : (num(b.w, 0) / (maxW[b.crop] || 1));
        g = clamp(g, 0.05, 1); const q = num(b.qual, 1), tier = Math.max(q >= 0.85 ? 0 : q >= 0.6 ? 1 : 2, tierForce);
        const cnt = Math.max(1, Math.floor(sw / sp));
        for (let c = 0; c < cnt; c++) { const x = cx + ((sw / cnt) * (c + 0.5)) | 0; S.plant(ctx, bf, x, BY - 1, g * (0.92 + 0.08 * S.hash(k * 13 + c)), tier, Math.sin(T * 2 + x * 0.4) * (o.vent > 20 ? 0.6 : 0.2)); }
        if (b.st === "ready") { for (let s = 0; s < 3; s++) { const ph = (T * 2.2 + s * 1.7 + k) % 3; if (ph < 0.4) { ctx.fillStyle = P.white; const sx = cx + ((S.hash(k + s * 7) * sw) | 0), sy = BY - 4 - ((S.hash(k + s * 3) * 22) | 0); ctx.fillRect(sx, sy, 1, 3); ctx.fillRect(sx - 1, sy + 1, 3, 1); } } }
        if (b.q) { S.rect(ctx, P.woodHi, cx + (sw >> 1) - 2, BY - 3, 5, 3); }
        cx += sw;
      }
      if (free > 1) { const fw = x0 + 5 + usable - cx + 0; if (fw > 1) { S.rect(ctx, P.soil2, cx, BY - 1, fw, 1); for (let i = 0; i < fw; i += 3) S.rect(ctx, P.soil3, cx + i, BY - 2, 1, 1); } }
      // frost on plants
      if (frost > 0.02) { ctx.fillStyle = "#eaf6ff"; const n = (frost * 70) | 0; for (let i = 0; i < n; i++) ctx.fillRect(x0 + 5 + ((S.hash(i * 3 + hs.i) * (w - 10)) | 0), BY - 3 - ((S.hash(i * 5 + 1) * 30) | 0), 1 + (i & 1), 1); ctx.globalAlpha = frost * 0.18; ctx.fillStyle = "#bfe4ff"; ctx.fillRect(x0 + 1, EY, w - 2, GY - EY); ctx.globalAlpha = 1; }
      // CO2 shimmer
      if (o.co2req > 0.01 || o.co2 > 900) for (let i = 0; i < 7; i++) { const u = (T * 0.25 + S.hash(i + hs.i * 9)) % 1; ctx.globalAlpha = 0.7 * (1 - u); ctx.fillStyle = P.co2; ctx.fillRect(x0 + 5 + ((S.hash(i * 17 + hs.i) * (w - 10)) | 0) + Math.round(Math.sin(T * 2 + i) * 1), BY - 4 - (u * 34) | 0, 1, 1); ctx.globalAlpha = 1; }
      // thermal screen
      if (o.screen) { ctx.globalAlpha = 0.6; ctx.fillStyle = "#dfe6ee"; ctx.fillRect(x0 + 2, EY + 4, w - 4, 2); ctx.globalAlpha = 0.35; for (let x = x0 + 2; x < x0 + w - 2; x += 2) ctx.fillRect(x, EY + 6, 1, 1); ctx.globalAlpha = 1; }
      // humidity haze (dithered)
      if (o.rh > 85) { ctx.globalAlpha = clamp((o.rh - 85) / 40, 0, 0.3); ctx.fillStyle = "#ffffff"; for (let y = EY + 1; y < GY; y += 2) ctx.fillRect(x0 + 1, y, w - 2, 1); ctx.globalAlpha = 1; }
      // damaged pane
      const p = pane(hs);
      if (hs.broken || hs.crackT < 90) {
        const t = hs.crackT >= 90 ? 1 : clamp(hs.crackT / 0.8, 0, 1);
        if (hs.crackT < 90) hs.crackT += dt;
        ctx.globalAlpha = 0.5; ctx.fillStyle = "#0b1018"; ctx.fillRect(p.x + 2, p.y + 4, p.w - 4, p.h - 12); ctx.globalAlpha = 1;
        ctx.fillStyle = "#ffffff"; crackLines(hs, t);
        ctx.fillStyle = "#9ad7ff"; for (let i = 0; i < 6; i++) ctx.fillRect(p.x + 1 + ((i * 5) % (p.w - 2)), p.y + p.h - 2 - (i & 1), 2, 1);
      }
      if (hs.broken) {
        hs.coldAcc += dt; if (hs.coldAcc > 0.07) { hs.coldAcc = 0; const sx = hs.side === 0 ? x0 - 6 : x0 + w + 6; spawn(2, sx, p.y + 6 + Math.random() * 16, (hs.side === 0 ? 1 : -1) * (35 + Math.random() * 20), 4 + Math.random() * 8, 1.4, 2, 2); }
        hs.frost = Math.min(1, hs.frost + dt * (cur.t < o.t ? 0.12 : 0.05)); hs.broken = true;
      } else if (hs.frost > 0) hs.frost = Math.max(0, hs.frost - dt * 0.2);
      if (hs.repairT < 90) {
        hs.repairT += dt; const u = hs.repairT / 1.2;
        if (u < 1) { ctx.globalAlpha = 0.7 * (1 - u); ctx.fillStyle = "#ffffff"; ctx.fillRect(p.x + ((u * (p.w + 8)) | 0) - 4, p.y, 3, p.h); ctx.globalAlpha = 1; if (Math.random() < 0.3) spawn(5, p.x + Math.random() * p.w, p.y + Math.random() * p.h, 0, -10, 0.7, 5, 1); }
        else hs.repairT = 99;
      }
      // flash outline / lightning white
      if (hs.flash > 0) { hs.flash -= dt; if (hs.flashCol === P.white) { ctx.globalAlpha = clamp(hs.flash / 1.2, 0, 1) * 0.7; ctx.fillStyle = "#fff"; ctx.fillRect(x0, RY, w, GY - RY); ctx.globalAlpha = 1; } else if ((T * 8 | 0) & 1) { ctx.strokeStyle = hs.flashCol; ctx.strokeRect(x0 - 0.5, RY - 0.5, w + 1, GY - RY + 1); } }
      if (hover === hs.id) { ctx.strokeStyle = "#fff"; ctx.globalAlpha = 0.7; ctx.strokeRect(x0 - 1.5, RY - 1.5, w + 3, GY - RY + 3); ctx.globalAlpha = 1; }
    }
    function drawVents(hs) {
      const o = cur.c[hs.id], open = clamp(o.vent / 100, 0, 1), x0 = hs.x0, w = hs.w, cx = hs.cx, slope = (EY - RY) / (w / 2);
      for (let s = 0; s < 2; s++) {
        const dir = s ? 1 : -1, bx = cx + dir * 4, by = RY + 4 * slope + 1, len = 11, ang = Math.atan(slope) + open * 0.65;
        const ex = bx + dir * Math.cos(ang) * len, ey = by + Math.sin(ang) * len * (open > 0.02 ? -1 : 1) * 0;
        // closed flap lies on the slope; open flap lifts about the lower end
        const lx = bx + dir * len, ly = by + len * slope, hx = bx + dir * Math.cos(Math.atan(slope) - open * 0.9) * len * 1, hy = by + Math.sin(Math.atan(slope) - open * 0.9) * len;
        S.line(ctx, lx, ly, hx, hy, open > 0.05 ? "#ffffff" : P.frame); S.line(ctx, lx, ly - 1, hx, hy - 1, "#9fc0da");
        if (open > 0.05) { ctx.globalAlpha = 0.5; S.rect(ctx, "#fff", (hx - 1) | 0, (hy - 4 - ((T * 8 + s * 3) % 5)) | 0, 1, 2); ctx.globalAlpha = 1; }
      }
    }
    function drawLights(hs) {
      const o = cur.c[hs.id]; if (o.lamp <= 0.05) { for (let k = 0; k < 4; k++) S.rect(ctx, "#6b7280", hs.x0 + 6 + (((hs.w - 18) * k / 3) | 0), EY + 12, 6, 2); return; }
      const a = clamp(0.35 + o.lamp / 40, 0.35, 0.9);
      for (let k = 0; k < 4; k++) {
        const lx = hs.x0 + 6 + (((hs.w - 18) * k / 3) | 0);
        ctx.globalAlpha = 0.14 * a; ctx.fillStyle = "#ffa8e0";
        for (let r = 0; r < 28; r += 2) ctx.fillRect(lx + 3 - ((3 + r * 0.45) | 0), EY + 14 + r, ((6 + r * 0.9) | 0), 2);
        ctx.globalAlpha = 1; S.rect(ctx, "#ffe0f4", lx, EY + 12, 6, 2); S.rect(ctx, "#ff7ac8", lx + 1, EY + 14, 4, 1);
      }
    }

    function drawWorker(dt, speed) {
      const f = cur.f; let tgt = null, kind = "", task = null;
      if (f.tasks && f.tasks.length) { for (let i = 0; i < f.tasks.length; i++) { const t = f.tasks[i]; if (t.st === "active" || t.st === "in_progress" || t.st === "working" || t.st === "running") { task = t; break; } } if (!task) task = f.tasks[0]; }
      if (task) { tgt = resolve(task.target, f); kind = String(task.kind || "work"); }
      let tx = 226 + Math.sin(T * 0.4) * 14;
      if (tgt && hmap[tgt]) tx = hmap[tgt].cx + (kind.indexOf("repair") >= 0 ? (hmap[tgt].side === 0 ? -hmap[tgt].w / 2 + 12 : hmap[tgt].w / 2 - 12) : Math.sin(T * 0.7) * 10);
      else if (tgt === "energy") tx = 150;
      wk.tx = tx; const dx = tx - wk.x, k = 2 + Math.min(6, speed * 0.4);
      wk.x += dx * (1 - Math.exp(-dt * k)); const moving = Math.abs(dx) > 1.5; if (Math.abs(dx) > 0.3) wk.face = dx > 0 ? 1 : -1;
      wk.ph += dt * (moving ? 9 : 0); let pose = 0;
      if (moving) pose = 1 + ((wk.ph | 0) & 1);
      else if (task) { const w = (T * 4 | 0) & 1; wk.kind = kind;
        if (kind.indexOf("plant") >= 0) { pose = 4; wk.spark -= dt; if (wk.spark <= 0 && hmap[tgt]) { wk.spark = 0.35; spawn(6, wk.x + 8, BY - 2, (Math.random() - 0.2) * 12, -10, 0.5, 6, 1); } }
        else if (kind.indexOf("repair") >= 0) { pose = w ? 3 : 0; wk.spark -= dt; if (wk.spark <= 0 && tgt && hmap[tgt]) { wk.spark = 0.3; const p = pane(hmap[tgt]); spawn(3, p.x + p.w / 2, p.y + 14, (Math.random() - 0.5) * 30, -16, 0.4, 3, 1); } }
        else if (kind.indexOf("harvest") >= 0) { pose = w ? 3 : 4; wk.spark -= dt; if (wk.spark <= 0 && tgt && hmap[tgt]) { wk.spark = 0.5; spawn(5, wk.x + 4, BY - 10, (Math.random() - 0.5) * 12, -16, 0.8, 5, 1); } }
        else pose = w ? 3 : 0;
      }
      S.mascot(ctx, mascot, (wk.x - 4) | 0, GY - 15 + (moving && ((wk.ph | 0) & 1) ? -0 : 0), 1, pose, wk.face);
      if (pose === 3 && kind.indexOf("repair") >= 0) { const hx = wk.x + wk.face * 8; S.rect(ctx, P.woodHi, hx | 0, GY - 20, 1, 4); S.rect(ctx, P.steel, (hx - 1) | 0, GY - 21, 3, 2); }
      if (pose === 3 && kind.indexOf("harvest") >= 0) S.rect(ctx, P.woodHi, wk.x + wk.face * 7 | 0, GY - 9, 4, 3);
    }
    function drawVan(dt) {
      if (van.t < 0) return; van.t += dt; const target = van.tx;
      if (van.t < 3.2 && van.x < target) van.x = Math.min(target, van.x + dt * 70); else { van.wait += dt; if (van.wait > 1.1) van.x += dt * 90; }
      if (van.wait > 0.2 && van.wait < 0.35) spawn(4, van.x + 12, 246, 0, -16, 0.7, 4, 2);
      if (van.x > W + 30) { van.t = -1; return; }
      const x = van.x | 0, y = 242;
      S.rect(ctx, "#e8eef5", x, y, 20, 7); S.rect(ctx, "#e8eef5", x + 2, y - 3, 11, 3); S.rect(ctx, "#74c0ff", x + 4, y - 2, 4, 2); S.rect(ctx, "#74c0ff", x + 9, y - 2, 3, 2); S.rect(ctx, P.warn, x + 14, y + 1, 5, 2); S.rect(ctx, "#8d98ab", x, y + 5, 20, 1);
      S.rect(ctx, P.ink, x + 3, y + 6, 4, 4); S.rect(ctx, P.ink, x + 13, y + 6, 4, 4); S.rect(ctx, "#8d98ab", x + 4 + (((T * 20) | 0) & 1), y + 7, 2, 1);
    }

    function drawWeather(dt) {
      const wet = cur.rh >= 94 && cur.t > 0.5, snow = cur.t <= 0.5 && cur.rh >= 82, storm = cur.wind > 13;
      const inten = wet || snow ? clamp((cur.rh - 78) / 17, 0.2, 1) : 0, n = (NR * inten) | 0, slant = cur.wind * (snow ? 2 : 4);
      ctx.fillStyle = snow ? "#ffffff" : "#8fc4ff"; ctx.globalAlpha = snow ? 0.9 : 0.7;
      for (let i = 0; i < n; i++) {
        ry[i] += rv[i] * (snow ? 22 : 130) * dt; rx[i] += slant * dt * (snow ? 1 : 1.2) + (snow ? Math.sin(T * 2 + i) * 6 * dt : 0);
        if (ry[i] > GY + 8) { ry[i] = -4; rx[i] = Math.random() * (W + 60) - 30; } if (rx[i] > W + 4) rx[i] -= W + 8; if (rx[i] < -4) rx[i] += W + 8;
        if (snow) ctx.fillRect(rx[i] | 0, ry[i] | 0, 2, 2); else ctx.fillRect(rx[i] | 0, ry[i] | 0, 1, 3);
      }
      ctx.globalAlpha = 1;
      if (storm && Math.random() < dt * 0.25) lightning = 0.18;
      if (lightning > 0) { lightning -= dt; ctx.globalAlpha = clamp(lightning * 2, 0, 0.5); ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, W, H); ctx.globalAlpha = 1; }
    }

    function drawParticles(dt) {
      for (let i = 0; i < NP; i++) {
        if (pl[i] <= 0) continue; pl[i] -= dt; const u = pl[i] / pm[i], ty = pt[i];
        px[i] += pvx[i] * dt; py[i] += pvy[i] * dt;
        if (ty === 1) pvy[i] += 90 * dt; else if (ty === 3) pvy[i] += 60 * dt; else if (ty === 0) { ps[i] += dt * 1.6; pvx[i] += cur.wind * 0.3 * dt; }
        if (ty === 1 && py[i] > GY - 1) { py[i] = GY - 1; pvy[i] = 0; pvx[i] = 0; }
        ctx.globalAlpha = ty === 0 ? clamp(u, 0, 1) * 0.7 : clamp(u * 2, 0, 1); ctx.fillStyle = PCOL[pc[i]];
        const s = ps[i] | 0 || 1;
        if (ty === 2) ctx.fillRect(px[i] | 0, py[i] | 0, 3, 1); else if (ty === 4) { ctx.fillRect(px[i] | 0, py[i] | 0, 3, 1); ctx.fillRect((px[i] + 1) | 0, (py[i] - 1) | 0, 1, 3); } else ctx.fillRect(px[i] | 0, py[i] | 0, s, s);
        if (ty === 1 && ((T * 10 + i) | 0) % 5 === 0) { ctx.fillStyle = "#fff"; ctx.fillRect(px[i] | 0, py[i] | 0, 1, 1); }
      }
      ctx.globalAlpha = 1;
    }

    function bubblePos(t, out) {
      if (t === "worker") { out[0] = wk.x; out[1] = GY - 28; } else if (hmap[t]) { out[0] = hmap[t].cx; out[1] = WIRE - 6; } else if (t === "road") { out[0] = 120; out[1] = 238; } else { out[0] = 100; out[1] = 90; }
    }
    const bp = [0, 0];
    function drawBubbles(dt) {
      for (let i = 0; i < NB; i++) {
        if (bl[i] <= 0) continue; bl[i] -= dt; bubblePos(bx[i], bp);
        let stack = 0; for (let j = 0; j < NB; j++) if (j !== i && bl[j] > 0 && bx[j] === bx[i] && bl[j] > bl[i]) stack++;
        const s = bt[i], w = S.textWidth(s) + 6, x = clamp((bp[0] - (w >> 1)) | 0, 1, W - w - 1), y = (bp[1] - stack * 11 - (bl[i] > 2.8 ? (bl[i] - 2.8) * 20 : 0)) | 0;
        ctx.globalAlpha = clamp(bl[i] * 2, 0, 1);
        S.rect(ctx, P.ink, x, y, w, 9); S.rect(ctx, "#f4f7fb", x + 1, y + 1, w - 2, 7); S.rect(ctx, P.ink, bp[0] | 0, y + 9, 2, 2); S.rect(ctx, "#f4f7fb", bp[0] | 0, y + 9, 1, 1);
        S.text(ctx, s, x + 3, y + 2, bcol[i] === P.white ? P.ink : darken(bcol[i]));
        ctx.globalAlpha = 1;
      }
    }
    function darken(c) { return c === P.good ? "#1c7a2a" : c === P.bad ? "#b01824" : c === P.warn ? "#9a6208" : c === P.info ? "#1d5fa8" : P.ink; }

    function render(hf, dt, speed, playing) {
      if (!D) return; dt = Math.min(dt, 0.1); T += dt * (playing ? 1 : 0.5);
      interp(clamp(hf, 0, last));
      const lv = skyLevel(); ctx.setTransform(1, 0, 0, 1, 0, 0);
      if (shake > 0) { shake -= dt; ctx.translate(((Math.random() - 0.5) * 4) | 0, ((Math.random() - 0.5) * 4) | 0); }
      drawSky(lv[0], lv[1]); drawCelestial(cur.day01); drawClouds(dt);
      ctx.drawImage(back, 0, 0);
      drawEnergy(dt); drawPipes();
      for (let i = 0; i < houses.length; i++) drawHouse(houses[i], dt);
      ctx.drawImage(front, 0, 0);
      for (let i = 0; i < houses.length; i++) drawVents(houses[i]);
      drawWorker(dt, speed); drawVan(dt);
      // night overlay then emissive things
      const night = 1 - cur.day01;
      if (night > 0.02) { ctx.globalAlpha = night * 0.42; ctx.fillStyle = "#06102e"; ctx.fillRect(0, 0, W, H); ctx.globalAlpha = 1; }
      for (let i = 0; i < houses.length; i++) drawLights(houses[i]);
      drawGlow();
      drawParticles(dt); drawWeather(dt); drawBubbles(dt);
      if (cur.day01 < 0.5) { /* sign lights */ }
    }
    function drawGlow() {
      if (cur.chp > 0) { ctx.globalAlpha = 0.35 + 0.35 * cur.chp; S.rect(ctx, "#ffb347", 51, 141, 38, 46); ctx.globalAlpha = 1;
        S.rect(ctx, "#5c6577", 56, 160, 28, 22); S.rect(ctx, "#8d98ab", 56, 160, 28, 2); for (let i = 0; i < 3; i++) S.rect(ctx, "#2a3140", 59 + i * 8, 166, 5, 12); }
      else { S.rect(ctx, "#2a3140", 56, 160, 28, 22); S.rect(ctx, "#3d465a", 56, 160, 28, 2); for (let i = 0; i < 3; i++) S.rect(ctx, "#1b2230", 59 + i * 8, 166, 5, 12); }
      if (cur.boiler > 0) { S.rect(ctx, "#b8362a", 104, 156, 26, 30); const fl = 2 + (((T * 9) | 0) & 3); S.rect(ctx, "#ff9a3d", 108, 182 - fl * 3, 18, fl * 3); S.rect(ctx, "#ffe27a", 112, 182 - fl * 2, 10, fl * 2); ctx.globalAlpha = 0.18 * cur.boiler; S.rect(ctx, "#ff7a3d", 99, 149, 36, 38); ctx.globalAlpha = 1; }
      else S.rect(ctx, "#5a2a28", 104, 156, 26, 30);
    }

    function hit(mx, my) {
      for (const hs of houses) if (mx >= hs.x0 && mx <= hs.x0 + hs.w && my >= RY - 2 && my <= GY) return hs.id;
      if (mx >= 38 && mx <= 220 && my >= 98 && my <= GY) return "energy";
      return null;
    }
    function setHover(id) { hover = id; }
    return { setData, render, trigger, bubble, flash, reset, hit, setHover, resolve, get cids() { return cids; }, get mascot() { return mascot; } };
  }

  export const PixelScene = { create, W, H };
