// The pixel-art greenhouse. Everything is drawn on a 320x180 grid, then scaled up with no smoothing.
const Scene = (() => {
  const W = 320, H = 180, WALL = 90, FLOOR = 132, APEX = 64;
  const HOUSE = { A: { x: 6, w: 116 }, B: { x: 128, w: 116 } };
  const EC = { x: 252, y: 100, w: 38 };
  const buf = document.createElement("canvas"); buf.width = W; buf.height = H;
  const g = buf.getContext("2d");
  let out, octx, meta = {}, t = 0;

  // ---------- tiny 3x5 bitmap font ----------
  const GL = {
    A:"010101111101101",B:"110101110101110",C:"011100100100011",D:"110101101101110",E:"111100110100111",
    F:"111100110100100",G:"011100101101011",H:"101101111101101",I:"111010010010111",J:"001001001101010",
    K:"101101110101101",L:"100100100100111",M:"101111111101101",N:"110101101101101",O:"010101101101010",
    P:"110101110100100",Q:"010101101110011",R:"110101110101101",S:"011100010001110",T:"111010010010010",
    U:"101101101101111",V:"101101101101010",W:"101101111111101",X:"101101010101101",Y:"101101010010010",
    Z:"111001010100111","0":"111101101101111","1":"010110010010111","2":"110001010100111","3":"110001010001110",
    "4":"101101111001001","5":"111100110001110","6":"011100111101111","7":"111001010010010","8":"111101111101111",
    "9":"111101111001110"," ":"000000000000000",":":"000010000010000",".":"000000000000010","-":"000000111000000",
    "+":"000010111010000","%":"101001010100101","!":"010010010000010","/":"001001010100100","€":"011100111100011",
    "°":"010101010000000",",":"000000000010100","(":"010100100100010",")":"010001001001010","?":"110001010000010",
  };
  function text(s, x, y, color, shadow = "#000") {
    s = String(s).toUpperCase();
    for (const pass of shadow ? [0, 1] : [1]) {
      g.fillStyle = pass ? color : shadow;
      let cx = x + (pass ? 0 : 1), cy = y + (pass ? 0 : 1);
      for (const ch of s) {
        const gl = GL[ch] || GL["?"];
        for (let i = 0; i < 15; i++) if (gl[i] === "1") g.fillRect(cx + (i % 3), cy + ((i / 3) | 0), 1, 1);
        cx += 4;
      }
    }
  }
  const textW = (s) => String(s).length * 4 - 1;

  // ---------- helpers ----------
  const R = (x, y, w, h, c) => { g.fillStyle = c; g.fillRect(x | 0, y | 0, w | 0, h | 0); };
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const lerp = (a, b, k) => a + (b - a) * k;
  const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const mix = (a, b, k) => { const A = hex(a), B = hex(b);
    return "#" + A.map((v, i) => Math.round(lerp(v, B[i], clamp(k, 0, 1))).toString(16).padStart(2, "0")).join(""); };
  let seed = 7; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);

  const stars = Array.from({ length: 46 }, () => ({ x: (rnd() * W) | 0, y: (rnd() * 70) | 0, p: rnd() * 6.3 }));
  const clouds = Array.from({ length: 7 }, (_, i) => ({ x: rnd() * W, y: 8 + rnd() * 40, w: 16 + ((rnd() * 22) | 0), k: i }));
  let flakes = [], smoke = [], co2 = { A: [], B: [] }, bubbles = [], workers = [], sparks = [];

  function reset() { smoke = []; co2 = { A: [], B: [] }; bubbles = []; sparks = []; workers = []; }

  // ---------- sky, weather, ground ----------
  function sky(f, hd) {
    const day = daylight(f, hd);
    const twi = (hd > 7 && hd < 10) || (hd > 15 && hd < 18) ? clamp(1 - Math.abs(day - 0.12) * 5, 0, 1) : 0;
    const top = mix("#0a1030", "#4f8fd8", day), hor = mix(mix("#1b2550", "#b9dcf2", day), "#f0a060", twi * 0.7);
    for (let i = 0; i < 12; i++) R(0, i * 11, W, 11, mix(top, hor, i / 11));
    const night = 1 - day;
    if (night > 0.3) for (const s of stars) if (Math.sin(t * 2 + s.p) > -0.3) R(s.x, s.y, 1, 1, `rgba(255,255,230,${(night - 0.3) * 1.2})`);
    // sun on a low winter arc, moon at night
    if (hd > 8.3 && hd < 17) {
      const k = (hd - 8.3) / 8.7, sx = lerp(14, 300, k), sy = 58 - Math.sin(Math.PI * k) * 34;
      disc(sx, sy, 6, mix("#ffd27a", "#fff3b0", day)); disc(sx, sy, 4, "#fff8d0");
    } else {
      const k = ((hd + 7) % 24) / 15, mx = lerp(20, 300, clamp(k, 0, 1)), my = 40 - Math.sin(Math.PI * clamp(k, 0, 1)) * 26;
      disc(mx, my, 5, "#e8ecf4"); disc(mx + 2, my - 1, 4, mix(top, hor, 0.3));
    }
    // clouds: more when it's humid, faster in wind
    const n = clamp(Math.round((f.out.rh - 62) / 5), 0, clouds.length);
    const cc = mix("#3a4260", "#f2f5f8", day), cs = mix("#262c44", "#c9d2dc", day);
    for (let i = 0; i < n; i++) {
      const c = clouds[i]; c.x += (0.6 + f.out.wind * 0.35) * 0.016 * (1 + i * 0.1);
      if (c.x > W + 30) c.x = -c.w - 10;
      R(c.x, c.y + 2, c.w, 5, cs); R(c.x + 3, c.y, c.w - 6, 5, cc); R(c.x + 7, c.y - 2, c.w * 0.45, 3, cc);
    }
  }
  // Daylight from the clock (a dull winter day is still day) brightened by measured sun.
  function daylight(f, hd) {
    const clockK = hd > 8.3 && hd < 17 ? Math.sin(Math.PI * (hd - 8.3) / 8.7) : 0;
    return clamp(Math.max(clamp(clockK * 1.6, 0, 1) * 0.7, f.out.sun / 120), 0, 1);
  }
  function disc(cx, cy, r, c) { for (let dy = -r; dy <= r; dy++) { const hw = Math.round(Math.sqrt(r * r - dy * dy)); R(cx - hw, cy + dy, hw * 2 + 1, 1, c); } }

  function ground(f, snowy) {
    R(0, 134, W, 46, snowy ? "#dfe8ee" : "#33503a");
    for (let x = 0; x < W; x += 6) R(x + ((x * 7) % 4), 136 + ((x * 13) % 5), 2, 1, snowy ? "#c5d2db" : "#2a4430");
    R(0, 158, W, 14, "#3c3f48"); for (let x = (-t * 6) % 16; x < W; x += 16) R(x, 164, 7, 1, "#8a8d96");
    R(0, 157, W, 1, snowy ? "#b9c6cf" : "#26392b");
  }

  function weather(f, dt) {
    const snow = f.out.t <= 0.5 && f.out.rh >= 82, rain = !snow && f.out.rh >= 94;
    const want = snow ? 90 : rain ? 70 : 0;
    while (flakes.length < want) flakes.push({ x: rnd() * W, y: rnd() * H, s: 0.6 + rnd() });
    if (flakes.length > want) flakes.length = want;
    for (const p of flakes) {
      if (snow) { p.y += 14 * p.s * dt; p.x += (f.out.wind * 2 + Math.sin(t + p.s * 9) * 4) * dt; R(p.x, p.y, 1, 1, "#ffffff"); }
      else { p.y += 120 * p.s * dt; p.x += f.out.wind * 3 * dt; R(p.x, p.y, 1, 3, "rgba(170,200,255,.55)"); }
      if (p.y > H) { p.y = -2; p.x = rnd() * W; } if (p.x > W) p.x = 0;
    }
  }

  // ---------- greenhouse ----------
  function roofRows(x, w, fn) { const cx = x + w / 2; for (let y = APEX; y < WALL; y++) { const hw = Math.round(((y - APEX) / (WALL - APEX)) * (w / 2)); fn(y, cx - hw, hw * 2); } }

  function house(id, f, dark, dt) {
    const { x, w } = HOUSE[id], c = f.c[id], cx = x + w / 2;
    const lampK = clamp(c.lamp / (meta.maxLamp[id] || 1), 0, 1);
    // interior air
    const inside = mix("#0e1a14", "#2a4a38", clamp(1 - dark + lampK * 0.6, 0, 1));
    roofRows(x, w, (y, rx, rw) => R(rx, y, rw, 1, inside));
    R(x, WALL, w, FLOOR - WALL + 2, inside);
    // temperature tint: blue when below night target, red when far above day target
    const cold = clamp((c.sp_night - 1 - c.t) / 6, 0, 0.35), hot = clamp((c.t - c.sp_day - 3) / 8, 0, 0.3);
    if (cold > 0) R(x, WALL, w, FLOOR - WALL, `rgba(90,160,255,${cold})`);
    if (hot > 0) R(x, WALL, w, FLOOR - WALL, `rgba(255,90,60,${hot})`);
    // lamp cones
    const lamps = 5;
    for (let i = 0; i < lamps; i++) {
      const lx = x + 12 + i * ((w - 24) / (lamps - 1));
      if (lampK > 0.02) {
        for (let y = WALL + 3; y < FLOOR; y += 1) { const hw = 1 + (y - WALL) * 0.28; R(lx - hw, y, hw * 2 + 1, 1, `rgba(255,226,120,${0.07 * lampK})`); }
      }
      R(lx - 2, WALL + 1, 5, 2, "#2b2f38"); R(lx - 1, WALL + 3, 3, 1, lampK > 0.02 ? "#fff1a0" : "#4a4f5a");
    }
    // energy screen (a cloth under the roof)
    if (c.screen) { for (let i = 0; i < w; i++) R(x + i, WALL - 1, 1, 2, i % 4 < 2 ? "#d8c79a" : "#bfae82"); }
    // beds and plants
    beds(id, f, x, w);
    // heating pipe glows with heat demand
    const hk = clamp(c.heat / (meta.maxHeat[id] || 1), 0, 1);
    R(x + 1, FLOOR + 1, w - 2, 1, mix("#3b404b", "#ff5a36", hk * (0.85 + 0.15 * Math.sin(t * 4))));
    // CO2 in the air
    const want = clamp(Math.round((c.co2 - 380) / 35), 0, 24), list = co2[id];
    while (list.length < want) list.push({ x: x + 3 + rnd() * (w - 6), y: WALL + 6 + rnd() * 26, v: rnd() * 6.3 });
    if (list.length > want) list.length = want;
    for (const p of list) { p.v += dt; p.x += Math.sin(p.v) * 0.12; p.y += Math.cos(p.v * 0.7) * 0.08; R(p.x, p.y, 1, 1, "rgba(190,215,255,.75)"); }
    // workers inside are drawn before the glass
    for (const wk of workers) if (wk.inside === id && wk.visible) person(wk);
    // glass and frame
    const glass = "rgba(185,228,255,0.13)", frame = mix("#5f7480", "#d6e6ee", 1 - dark * 0.6);
    roofRows(x, w, (y, rx, rw) => { R(rx, y, rw, 1, glass); R(rx, y, 1, 1, frame); R(rx + rw - 1, y, 1, 1, frame); });
    R(x, WALL, w, FLOOR - WALL + 2, glass);
    R(x, WALL, 1, FLOOR - WALL + 2, frame); R(x + w - 1, WALL, 1, FLOOR - WALL + 2, frame); R(x, WALL, w, 1, frame);
    for (let mx = x + 14; mx < x + w - 4; mx += 14) R(mx, WALL, 1, FLOOR - WALL, "rgba(214,230,238,.35)");
    for (let i = 0; i < 6; i++) R(x + 8 + i * 2, WALL + 4 + i * 3, 1, 2, "rgba(255,255,255,.25)");
    R(cx, APEX, 1, WALL - APEX, frame);
    // roof vents lift open
    const lift = Math.round(clamp(c.vent / 100, 0, 1) * 5);
    for (const vx of [cx - 14, cx + 6]) { R(vx, APEX + 7 - lift, 8, 2, frame); if (lift) R(vx, APEX + 9 - lift, 8, lift, "rgba(10,20,30,.55)"); }
    // sign on the ground
    const crop = (meta.compartments[id] || {}).crop || "";
    text(`${id} ${crop.split("_")[0]}`, x + 2, 140, "#ffffff");
    const tc = c.t < c.sp_night - 1 ? "#7cc4ff" : c.t > c.sp_day + 3 ? "#ff8a70" : "#b8f0a8";
    const tt = `${c.t.toFixed(1)}°`; text(tt, x + w - textW(tt) - 2, 140, tc);
  }

  function beds(id, f, x, w) {
    const list = f.b.filter((b) => b.c === id && b.st !== "harvested");
    const total = list.reduce((s, b) => s + b.area, 0) + f.c[id].free;
    const inner = w - 6; let bx = x + 3;
    const slots = list.map((b) => ({ b, a: b.area })); if (f.c[id].free > 1) slots.push({ b: null, a: f.c[id].free });
    slots.forEach((s, i) => {
      const bw = i === slots.length - 1 ? x + 3 + inner - bx : Math.max(6, Math.round((s.a / total) * inner));
      R(bx, FLOOR - 2, bw - 1, 3, "#5b3a29"); R(bx, FLOOR - 2, bw - 1, 1, "#7a5038");
      if (s.b) plants(s.b, bx, bw - 1);
      else if (bw > 14) text("EMPTY", bx + ((bw - 20) >> 1), FLOOR - 8, "#6b5444", null);
      bx += bw;
    });
  }

  function plants(b, bx, bw) {
    const gr = clamp(b.w / (meta.maxW[b.crop] || 1), 0, 1), q = b.qual;
    const lettuce = b.crop.startsWith("lettuce");
    const base = q >= 0.85 ? (lettuce ? ["#9be05a", "#62a83a"] : ["#4fae4a", "#2f7a32"]) :
      q >= 0.6 ? ["#c8cf5a", "#8f9a3a"] : ["#a88a4a", "#6f5a32"];
    const step = lettuce ? 6 : 4;
    for (const row of [0, 1]) {
      const y0 = FLOOR - 3 - row * 2, light = row ? base[1] : base[0], dark = row ? "#2c5a26" : base[1];
      for (let px = bx + 2 + row * (step >> 1); px < bx + bw - 2; px += step) {
        if (lettuce) {
          const r = gr < 0.08 ? 0 : 1 + Math.round(gr * 2.2);
          if (r === 0) { R(px, y0, 1, 1, light); continue; }
          for (let dy = 0; dy <= r; dy++) { const hw = Math.round(Math.sqrt(r * r - dy * dy) * 1.25); R(px - hw, y0 - dy, hw * 2 + 1, 1, dy === r ? light : dy ? light : dark); }
          R(px, y0 - r + 1, 1, 1, dark);
        } else {
          const h = 1 + Math.round(gr * 8), sway = Math.round(Math.sin(t * 1.5 + px) * 0.4);
          R(px, y0 - h + 1, 1, h, "#2a5a24");
          for (let k = 2; k < h; k += 2) { R(px - 1 + sway, y0 - k, 1, 1, light); R(px + 1 + sway, y0 - k + 1, 1, 1, light); }
          R(px - 1 + sway, y0 - h, 3, 1, light);
        }
      }
    }
    if (b.st === "ready" && Math.sin(t * 6) > 0) { const sx = bx + (bw >> 1); R(sx, FLOOR - 22, 1, 3, "#ffd84a"); R(sx - 1, FLOOR - 21, 3, 1, "#ffd84a"); }
    if (b.q) for (let i = 0; i < Math.min(3, (bw / 9) | 0); i++) { const cx = bx + 3 + i * 8; R(cx, FLOOR - 6, 5, 3, "#a0703c"); R(cx, FLOOR - 6, 5, 1, "#c8925a"); }
  }

  // ---------- energy centre ----------
  function energy(f, dark, dt) {
    const e = f.ec, broken = f.faults.length > 0, { x, y, w } = EC;
    // power line from the pole to the roof; dots show electricity direction
    const px = 314, py = 64, ex = x + w - 4, ey = y;
    R(px, py, 2, 72, "#4a4036"); R(px - 4, py, 10, 2, "#4a4036");
    const pts = []; for (let i = 0; i <= 40; i++) { const k = i / 40; pts.push([lerp(px, ex, k), lerp(py + 1, ey, k) + Math.sin(Math.PI * k) * 8]); }
    for (const [lx, ly] of pts) R(lx, ly, 1, 1, "#22262e");
    const flow = e.imp > 0.5 ? 1 : e.exp > 0.5 ? -1 : 0;
    if (flow) for (let j = 0; j < 4; j++) { let k = ((t * 0.6 + j / 4) % 1); if (flow < 0) k = 1 - k; const [lx, ly] = pts[Math.round(k * 40)]; R(lx - 1, ly - 1, 2, 2, flow > 0 ? "#ffe066" : "#7bd88f"); }
    // chimney and smoke (smoke rate follows gas burnt)
    R(x + 26, y - 26, 6, 26, "#6e3b2e"); R(x + 25, y - 28, 8, 2, "#4a2820");
    if (Math.random() < clamp(e.gas / 40, 0, 1) * dt * 22) smoke.push({ x: x + 28 + rnd() * 2, y: y - 30, r: 1, a: 0.75 });
    for (const s of smoke) { s.y -= 7 * dt; s.x += (f.out.wind * 1.6 + 1) * dt; s.r += 1.1 * dt; s.a -= 0.16 * dt;
      const c = Math.round(s.r); R(s.x - c, s.y - c, c * 2 + 1, c * 2 + 1, `rgba(${dark > 0.5 ? "150,150,160" : "210,212,218"},${Math.max(0, s.a)})`); }
    smoke = smoke.filter((s) => s.a > 0 && s.y > -8);
    // building
    R(x, y, w, 36, "#8a4b3a"); for (let by = y + 3; by < y + 36; by += 4) for (let bx = x + ((by >> 2) % 2) * 3; bx < x + w; bx += 6) R(bx, by, 4, 1, "#7a4032");
    R(x - 2, y - 2, w + 4, 3, "#3a2a26");
    const win = dark > 0.4 ? "#ffd977" : "#9cc8e0"; R(x + 4, y + 6, 6, 5, win); R(x + 14, y + 6, 6, 5, win);
    R(x + 24, y + 22, 8, 14, "#3a2a26");
    // boiler light: green when fine, flashing red when broken
    const lamp = broken ? (Math.sin(t * 10) > 0 ? "#ff3b30" : "#5a1410") : "#5ee06a";
    R(x + 34, y + 4, 2, 2, lamp);
    if (broken) { text("!", x + 16, y - 9, Math.sin(t * 8) > 0 ? "#ff5a4a" : "#ffd84a");
      if (Math.random() < dt * 8) sparks.push({ x: x + 6 + rnd() * 20, y: y + 16, vx: (rnd() - 0.5) * 30, vy: -20 - rnd() * 20, a: 1 }); }
    for (const s of sparks) { s.x += s.vx * dt; s.y += s.vy * dt; s.vy += 60 * dt; s.a -= 1.6 * dt; R(s.x, s.y, 1, 1, `rgba(255,${180 + ((rnd() * 70) | 0)},60,${Math.max(0, s.a)})`); }
    sparks = sparks.filter((s) => s.a > 0);
    // CHP engine box with a fan that spins when running
    R(x + 3, y + 23, 16, 13, "#5a6270"); R(x + 4, y + 24, 14, 1, "#7a8494");
    const fanOn = e.chp > 0; const fp = fanOn ? Math.floor(t * 12) % 2 : 0;
    R(x + 7, y + 27, 7, 7, "#2a2f38"); if (fp) { R(x + 10, y + 28, 1, 5, "#c0c8d4"); } else { R(x + 8, y + 30, 5, 1, "#c0c8d4"); }
    text("CHP", x + 4, y + 17, fanOn ? "#ffffff" : "#9aa3b2", null);
    // tanks: hot-water buffer and CO2
    tank(x + w + 4, y - 4, 9, 40, clamp(e.buffer / (meta.maxBuffer || 1), 0, 1), "#ff8a3c", "HEAT");
    const co2k = clamp(e.co2 / (meta.maxCO2 || 1), 0, 1);
    tank(x + w + 15, y + 6, 9, 30, co2k, co2k < 0.15 ? (Math.sin(t * 6) > 0 ? "#ff5a4a" : "#7a2a24") : "#7cc4ff", "CO2");
    // main heat pipe to the houses
    const heatK = clamp(e.heat / (meta.maxHeatAll || 1), 0, 1);
    R(4, 135, x - 4, 2, mix("#40454f", "#ff6a3c", heatK)); R(4, 135, x - 4, 1, mix("#5a5f6a", "#ffa070", heatK));
    text("ENERGY", x + 4, 142, "#ffffff");
  }
  function tank(x, y, w, h, k, c, label) {
    R(x, y, w, h, "#2b313c"); R(x + 1, y + 1, w - 2, h - 2, "#151a22");
    const fh = Math.round((h - 2) * k); R(x + 1, y + h - 1 - fh, w - 2, fh, c);
    R(x + 1, y + 1, 1, h - 2, "rgba(255,255,255,.18)"); R(x - 1, y - 1, w + 2, 2, "#4a5262");
  }

  // ---------- people and trucks ----------
  function person(wk) {
    const leg = wk.moving ? (Math.floor(t * 8 + wk.id) % 2) : 0, x = Math.round(wk.x), y = Math.round(wk.y);
    R(x, y - 7, 3, 2, "#f0c8a0"); R(x, y - 8, 3, 1, wk.hair); R(x, y - 5, 3, 3, wk.shirt);
    R(x + (leg ? 0 : 0), y - 2, 1, 2, "#2a2f3a"); R(x + 2, y - 2 + (leg ? -1 : 0), 1, 2 - (leg ? 0 : 0), "#2a2f3a");
    if (wk.carry) { const bob = Math.round(Math.sin(t * 5 + wk.id)); R(x - 1, y - 5 + bob, 5, 2, "#a0703c"); R(x - 1, y - 6 + bob, 5, 1, "#62a83a"); }
  }
  const SHIRTS = ["#e85d4a", "#4a90e8", "#f2b33d", "#9b6be0", "#3dbf8a", "#e06aa8", "#ffffff", "#8bc34a"];
  function updateWorkers(f, hd, dt, speed, shift) {
    const n = f.staff;
    while (workers.length < n) { const i = workers.length; workers.push({ id: i, x: -8 - i * 6, y: 152, tx: 0, ty: 152, shirt: SHIRTS[i % 8], hair: i % 2 ? "#3a2418" : "#d8a050", visible: true, inside: null, carry: false, moving: false }); }
    workers.length = n;
    const onShift = hd >= shift[0] && hd < shift[1];
    const task = f.tasks.find((k) => k.st !== "done");
    workers.forEach((wk, i) => {
      let tx, ty, inside = null, carry = false;
      if (!onShift) { tx = -12 - i * 5; ty = 152; }
      else if (task && (task.kind === "harvest" || task.kind === "plant")) {
        const hid = task.target[0] in HOUSE ? task.target[0] : (task.target in HOUSE ? task.target : "A");
        const hx = HOUSE[hid]; tx = hx.x + 10 + ((i * 37) % (hx.w - 20)); ty = FLOOR - 1; inside = hid; carry = task.kind === "harvest";
      } else if (task && task.kind === "repair") { tx = EC.x + 4 + i * 5; ty = 140; }
      else { tx = 60 + i * 18 + Math.sin(t * 0.3 + i) * 14; ty = 152; }
      const dx = tx - wk.x, dy = ty - wk.y, d = Math.hypot(dx, dy), v = 40 * Math.min(speed, 4) * dt;
      wk.moving = d > 0.6;
      if (d > 30 && Math.abs(wk.y - ty) > 4) { wk.x = tx; wk.y = ty; } // teleport between inside and outside paths
      else if (d > 0.6) { wk.x += (dx / d) * Math.min(v, d); wk.y += (dy / d) * Math.min(v, d); }
      wk.inside = Math.abs(wk.y - (FLOOR - 1)) < 1 ? inside : null; wk.carry = carry && !!wk.inside;
      wk.visible = wk.x > -6;
    });
  }

  function truck(f, hf) {
    for (const d of meta.deliveries) {
      const k = (hf - (d - 4)) / 7; if (k < 0 || k > 1) continue;
      const stop = EC.x - 30, x = k < 0.4 ? lerp(-34, stop, k / 0.4) : k < 0.65 ? stop : lerp(stop, W + 40, (k - 0.65) / 0.35);
      const y = 160;
      R(x, y - 10, 22, 10, "#e8eef4"); R(x + 1, y - 9, 20, 1, "#ffffff"); text("CO2", x + 5, y - 7, "#2a6ab8", null);
      R(x + 22, y - 7, 7, 7, "#d84a3a"); R(x + 24, y - 6, 4, 3, "#9cd0f0");
      R(x + 3, y, 4, 3, "#1a1d24"); R(x + 18, y, 4, 3, "#1a1d24"); R(x + 24, y, 4, 3, "#1a1d24");
    }
  }

  // ---------- speech bubbles ----------
  function bubble(where, msg, color) {
    const at = { A: [HOUSE.A.x + 58, 58], B: [HOUSE.B.x + 58, 58], energy: [EC.x + 18, 64], co2: [EC.x + 44, 84], road: [EC.x - 20, 140] }[where] || [160, 50];
    bubbles.push({ x: at[0], y: at[1], msg: msg.toUpperCase().slice(0, 26), color, life: 0 });
    if (bubbles.length > 4) bubbles.shift();
  }
  function drawBubbles(dt) {
    const stacked = {};
    for (const b of bubbles) {
      b.life += dt; const key = `${b.x}`; const lvl = (stacked[key] = (stacked[key] || 0) + 1) - 1;
      const w = textW(b.msg) + 6, bx = clamp(Math.round(b.x - w / 2), 1, W - w - 1), by = Math.round(b.y - lvl * 11 - Math.min(b.life, 0.3) * 10);
      R(bx, by, w, 9, "#0d1016"); R(bx, by, w, 1, b.color); R(bx, by + 8, w, 1, b.color); R(bx, by, 1, 9, b.color); R(bx + w - 1, by, 1, 9, b.color);
      R(Math.round(b.x) - 1, by + 9, 3, 1, b.color); R(Math.round(b.x), by + 10, 1, 1, b.color);
      text(b.msg, bx + 3, by + 2, "#ffffff", null);
    }
    bubbles = bubbles.filter((b) => b.life < 3.2);
  }

  // ---------- public ----------
  function init(canvas) { out = canvas; octx = out.getContext("2d"); }
  function setData(m) { meta = m; reset(); }
  function render(f, hf, dt, speed) {
    t += dt;
    const hd = hf % 24, dark = 1 - daylight(f, hd);
    sky(f, hd);
    ground(f, meta.snowAt[Math.floor(hf)] === 1);
    updateWorkers(f, hd, dt, speed, meta.shift);
    house("A", f, dark, dt); house("B", f, dark, dt);
    energy(f, dark, dt);
    for (const wk of workers) if (!wk.inside && wk.visible) person(wk);
    truck(f, hf);
    weather(f, dt);
    if (dark > 0.3) R(0, 0, W, H, `rgba(5,8,25,${(dark - 0.3) * 0.25})`);
    drawBubbles(dt);
    // scale up crisply
    const s = Math.max(1, Math.floor(Math.min(out.clientWidth * devicePixelRatio / W, out.clientHeight * devicePixelRatio / H)));
    const cw = Math.round(out.clientWidth * devicePixelRatio), ch = Math.round(out.clientHeight * devicePixelRatio);
    if (out.width !== cw || out.height !== ch) { out.width = cw; out.height = ch; }
    octx.imageSmoothingEnabled = false; octx.fillStyle = "#000"; octx.fillRect(0, 0, cw, ch);
    const sw = cw / W, sh = ch / H, k = Math.min(sw, sh) >= s + 1 ? Math.min(sw, sh) : Math.min(sw, sh);
    const dw = W * k, dh = H * k; octx.drawImage(buf, (cw - dw) / 2, (ch - dh) / 2, dw, dh);
  }
  function hit(px, py) {
    const x = (px / out.clientWidth) * W, y = (py / out.clientHeight) * H;
    for (const id of ["A", "B"]) { const h = HOUSE[id]; if (x >= h.x && x <= h.x + h.w && y >= APEX && y <= 146) return id; }
    if (x >= EC.x - 2 && x <= W && y >= 60 && y <= 150) return "energy";
    if (y < 60) return "weather";
    return null;
  }
  return { init, setData, render, bubble, hit, reset };
})();
