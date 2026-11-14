// Greenhouse Bench pixel site: router, runs picker, replay controller, ?mock=1 fabricated run.
(function () {
  "use strict";
  const S = window.Sprites, P = S.P;
  const Q = new URLSearchParams(location.search), MOCK = Q.get("mock") === "1";
  const app = document.getElementById("app"), tip = document.getElementById("tip");
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const eur = (v, sign) => (v == null || isNaN(v) ? "-" : (v < 0 ? "-" : sign && v > 0 ? "+" : "") + "EUR " + Math.abs(Math.round(v)).toLocaleString("en-US"));
  const num = (v, d) => (v == null || isNaN(v) ? "-" : Number(v).toLocaleString("en-US", { maximumFractionDigits: d || 0, minimumFractionDigits: d || 0 }));
  const when = (h) => "D" + (Math.floor(h / 24) + 1) + " " + String(h % 24).padStart(2, "0") + ":00";
  const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);

  // ============================================================== mock run
  function rng(seed) { let s = (seed >>> 0) || 1; return () => { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; }; }
  const MOCK_RUNS = [
    ["mock", "Agent: scout-1", "agent", "scout-1", null, 3, 0.71, 9120],
    ["mock-2", "Agent: northwind-large", "agent", "northwind-large", null, 3, 0.55, 6400],
    ["mock-3", "Agent: opencode-mini", "agent", "opencode-mini", null, 5, 0.18, 1800],
    ["mock-4", "Reference planner", "policy", "reference", "reference", 3, 0.8, 11200],
    ["mock-5", "Do nothing", "policy", "do-nothing", "do-nothing", 3, 0, 0],
    ["mock-6", "Agent: scout-1", "agent", "scout-1", null, 101, null, null],
  ];
  function mockList() {
    return { runs: MOCK_RUNS.map((r, i) => ({ id: r[0], label: r[1], kind: r[2], model: r[3], policy: r[4], scenario: "normal-winter", seed: r[5], score: r[6], profit_eur: r[7], baseline_profit_eur: 0,
      days: 42, status: r[6] == null ? "partial" : "complete", failure: r[6] == null ? "ran out of tool calls on day 30" : null, started: "2026-11-1" + (i + 1) + "T10:00:00Z", source: "mock" })) };
  }
  const mockCache = {};
  function buildMock(id) {
    if (mockCache[id]) return mockCache[id];
    const seed = S.hashStr(id), R = rng(seed), HOURS = 1008, cids = ["A", "B", "C"], crops = { A: "lettuce_butterhead", B: "lettuce_butterhead", C: "broccoli_micro" };
    const dur = { A: 21, B: 21, C: 11 }, events = [], actions = [], alarms = [], daily = [], frames = [], tasks = [];
    const add = (h, kind, target, text, severity) => events.push({ h, day: Math.floor(h / 24) + 1, kind, target, text, severity: severity || "info" });
    const act = (h, tool, args, ok, err, resp) => actions.push({ h, day: Math.floor(h / 24) + 1, tool, args, ok: ok !== false, err: err || null, resp_summary: resp || "ok" });
    const task = (h0, h1, kind, target) => tasks.push({ h0, h1, kind, target });
    // cycles: harvest + plant at 06:00
    for (const c of cids) for (let j = 0; j < 2; j++) {
      const period = dur[c] * 24, phase = j * dur[c] * 12;
      for (let h = 6; h < HOURS; h += 24) if (h > 6 && ((h - 6 + phase) % period) === 0) {
        add(h, "harvest", c, "Harvested bed " + c + j + " (" + (40 + j * 6) + " kg)", "info"); add(h, "plant", c, "Planted bed " + c + j, "info");
        act(h, "harvest", { batch_id: c + j + "-" + Math.floor((h - 6 + phase) / period - 1) }); act(h, "plant", { compartment: c, area_m2: 40 }); task(h, h + 3, "harvest", c); task(h + 3, h + 6, "plant", c);
      }
    }
    const BRK = 17 * 24 + 9, REP = 19 * 24 + 11, TRIP = 12 * 24 + 4, FIX = 12 * 24 + 15;
    add(17 * 24 + 3, "storm", "", "Storm warning: gusts up to 18 m/s", "warn"); add(17 * 24 + 8, "storm_damage", "B", "Wind damage to roof of B", "bad");
    add(BRK, "window_break", "B", "A window in B broke in the storm", "bad"); add(BRK + 3, "alarm", "B", "B is cooling fast: 9.1 C", "bad"); alarms.push({ h: BRK + 3, kind: "temp", target: "B", text: "B is cooling fast: 9.1 C" });
    add(REP, "window_repaired", "B", "Window in B repaired", "info"); task(19 * 24 + 6, REP, "repair", "B"); act(19 * 24 + 6, "repair", { target: "B" }, true, null, "contractor not needed");
    add(TRIP, "equipment", "boiler", "boiler tripped. Needs a manual restart", "bad"); alarms.push({ h: TRIP, kind: "equipment", target: "boiler", text: "boiler tripped" });
    add(FIX, "equipment", "boiler", "boiler working again", "info"); task(13 * 24 + 6 - 24 + 0, 12 * 24 + 15, "repair", "boiler"); act(12 * 24 + 6, "repair", { target: "boiler" });
    add(7 * 24 + 6, "order_placed", "", "Ordered 800 kg CO2", "info"); act(7 * 24 + 6, "place_order", { item: "co2_kg", quantity: 800 });
    add(8 * 24 + 10, "late_delivery", "", "CO2 delivery is late", "warn"); add(8 * 24 + 13, "order_arrived", "", "Order arrived: 800 kg CO2", "info");
    add(3 * 24 + 6, "hire", "", "Hired 1 worker", "info"); act(3 * 24 + 6, "hire", { workers: 1 }); add(30 * 24 + 6, "release", "", "Released 1 worker", "info"); act(30 * 24 + 6, "release", { workers: 1 });
    for (let d = 0; d < 42; d++) {
      const h = d * 24 + 6, c = cids[Math.floor(R() * 3)]; act(h, "set_climate", { compartment: c, heat_day_c: 19 + Math.floor(R() * 3), co2_ppm: 700 + 50 * Math.floor(R() * 4) });
      if (R() < 0.12) act(h, "plant", { compartment: c, area_m2: 400 }, false, "area exceeds free space");
      act(h, "submit_day", {}, true, null, "day " + (d + 1) + " submitted");
    }
    events.sort((a, b) => a.h - b.h); actions.sort((a, b) => a.h - b.h);
    let rev = 0, costs = 0, kg = 0, ai = 0, evi = 0; const baseline = -1500, outT = [];
    for (let h = 0; h < HOURS; h++) {
      const hod = h % 24, d = Math.floor(h / 24), storm = h >= 410 && h <= 432, snow = d >= 20 && d <= 23;
      const t = -2 + 4 * Math.sin(((hod - 14) / 24) * 6.283) + 3 * Math.sin(d / 5) + (storm ? 3 : 0) - (snow ? 3 : 0), sunBase = hod >= 8 && hod <= 16 ? 95 * Math.sin(Math.PI * (hod - 8) / 8) : 0;
      const out = { t: +t.toFixed(1), rh: storm ? 96 : snow ? 90 : 78 + 8 * Math.sin(h / 9), sun: +(sunBase * (storm || snow ? 0.2 : 0.4 + 0.6 * Math.abs(Math.sin(d * 1.7)))).toFixed(1), wind: storm ? 16 + 2 * Math.sin(h) : 3 + 2 * Math.sin(h / 7) };
      const trip = h >= TRIP && h < FIX, c = {}, b = [];
      let lampTot = 0, heatTot = 0, co2req = 0;
      for (const id of cids) {
        const broken = id === "B" && h >= BRK && h < REP, since = id === "B" && h >= BRK ? Math.min(h - BRK, 20) : 0;
        let ti = 18.5 + 1.5 * Math.sin(((hod - 14) / 24) * 6.283) + R() * 0.2; if (broken) ti = ti - (ti - out.t) * (since / 28); if (id === "B" && h >= REP && h < REP + 10) ti -= (REP + 10 - h) * 0.5;
        if (trip) ti -= 0.4 * Math.min(h - TRIP, 6);
        const lamp = id === "C" ? 0 : (hod < 7 || hod >= 16) && hod !== 15 ? 8 : 0, heat = Math.max(0, (19 - out.t) * 1.6) * (broken ? 1.6 : 1) * (trip ? 0.3 : 1);
        lampTot += lamp; heatTot += heat; const cr = hod >= 8 && hod < 16 ? 0.6 : 0; co2req += cr;
        c[id] = { t: +ti.toFixed(1), rh: +(72 + 8 * Math.sin(h / 6) + (broken ? 8 : 0)).toFixed(1), co2: Math.round(700 + 140 * Math.sin(h / 11) + (hod >= 8 && hod < 16 ? 100 : 0)), par: +(lamp * 6 + out.sun * 0.9).toFixed(1), dli: +((h % 24) * 0.8).toFixed(1),
          vent: broken ? 0 : sunBase > 60 && out.t > -2 ? 35 : out.t > 3 ? 15 : 0, screen: hod < 7 || hod >= 17, lamp, heat: +heat.toFixed(1), co2req: cr, sp_day: 20, sp_night: 16, sp_co2: 800, free: 6 };
        for (let j = 0; j < 2; j++) {
          const period = dur[id] * 24, tt = h - 6 + j * dur[id] * 12 + period * 4, cyc = Math.floor(tt / period), age = (tt % period) / 24, g = clamp(age / dur[id], 0.03, 1), ready = age >= dur[id] - 2;
          const dmg = id === "B" && h > REP && h < REP + 300 ? 0.42 : 0.94 - 0.02 * (j);
          b.push({ id: id + j + "-" + cyc, crop: crops[id], c: id, area: 40 - j * 4, age: +age.toFixed(1), st: ready ? "ready" : "growing", q: false, w: +(8 + 130 * g * g).toFixed(1), qual: +dmg.toFixed(3), ready: ready ? 0 : +(dur[id] - age).toFixed(1), units: 240 });
        }
      }
      while (evi < events.length && events[evi].h <= h) { const e = events[evi++]; if (e.kind === "harvest") { const gain = 160 + R() * 120; rev += gain; kg += 42; } }
      costs += 3 + lampTot * 0.1 + heatTot * 0.06; while (ai < actions.length && actions[ai].h <= h) ai++;
      const imp = lampTot > 0 ? Math.round(lampTot * 0.7) : 0, tk = tasks.filter((x) => h >= x.h0 && h < x.h1).map((x) => ({ kind: x.kind, target: x.target, done: h - x.h0, need: x.h1 - x.h0, st: "active" }));
      const co2tank = 900 - (h % 190) * 3.5 + (h >= 205 ? 400 : 0);
      frames.push({ h, day: d + 1, hod, out, c, ec: { buffer: Math.round(220 + 150 * Math.sin(h / 14) + (trip ? -120 : 0)), co2: Math.max(60, Math.round(co2tank)), chp: trip ? 0.6 : hod >= 7 && hod < 22 ? 0.8 : 0, boiler: trip ? 0 : heatTot > 22 ? 1 : 0, bufmode: "charge", extco2: 0, gas: +(1 + heatTot * 0.1).toFixed(1), imp, exp: hod >= 7 && hod < 22 && !lampTot ? 40 : 0, heat: +heatTot.toFixed(1), lost: 4, p_gas: 0.4, p_imp: 0.2, p_exp: 0.1 },
        faults: trip ? ["boiler"] : [], money: { cash_eur: +(20000 + rev - costs).toFixed(0), profit_so_far_eur: +(rev - costs).toFixed(0), harvest_revenue_eur: +rev.toFixed(0) }, staff: 2, tasks: tk, orders: [], stock: {}, b, damage: { B: c.B && h >= BRK && h < REP + 24 ? 0.7 : 0 } });
      if (hod === 23) daily.push({ day: d + 1, cash: +(20000 + rev - costs).toFixed(0), profit: +(rev - costs).toFixed(0), revenue: +rev.toFixed(0), costs: +costs.toFixed(0), harvested_kg: kg, alarms: alarms.filter((a) => a.h >= d * 24 && a.h < d * 24 + 24).length });
    }
    const final = frames[HOURS - 1].money.profit_so_far_eur, row = MOCK_RUNS.find((r) => r[0] === id) || MOCK_RUNS[0];
    const meta = { id, label: row[1], kind: row[2], model: row[3], policy: row[4], scenario: "normal-winter", seed: row[5], score: row[6], profit_eur: final, baseline_profit_eur: baseline, days: 42, status: "complete", failure: null, started: "2026-11-10T10:00:00Z", source: "mock",
      shift: "07:00-15:00", max_calls: 400, compartments: { A: { crop: crops.A }, B: { crop: crops.B }, C: { crop: crops.C } }, crops: {}, objective: "Maximise net profit over 42 simulated days.", hours: HOURS, replay_verified: true };
    return (mockCache[id] = { meta, frames, actions, events, alarms, daily });
  }

  // ============================================================== helpers
  function fetchJson(url) {
    if (MOCK) {
      if (url.indexOf("/api/runs") === 0) { const rest = url.slice(9).replace(/^\//, ""); return Promise.resolve(rest ? buildMock(decodeURIComponent(rest)) : mockList()); }
      return Promise.reject(new Error("mock mode: no backend for " + url));
    }
    return fetch(url).then((r) => { if (!r.ok) throw new Error(url + " -> HTTP " + r.status); return r.json(); });
  }
  let teardown = null, rafId = 0;
  function loop(fn) { let last = 0, on = true; const step = (now) => { if (!on) return; const dt = Math.min(0.1, (now - (last || now)) / 1000); last = now; fn(dt); rafId = requestAnimationFrame(step); }; rafId = requestAnimationFrame(step); return () => { on = false; cancelAnimationFrame(rafId); }; }
  function bigText(txt, scale, w) {
    const c = document.createElement("canvas"), tw = S.textWidth(txt, scale) + 4 * scale; c.width = w || tw; c.height = 7 * scale + 2 * scale; c.className = "bigtitle";
    const x = c.getContext("2d"), ox = ((c.width - S.textWidth(txt, scale)) / 2) | 0;
    S.text(x, txt, ox + scale, scale * 2, "#05080e", scale); S.text(x, txt, ox, scale, "#ffc247", scale); c.style.width = c.width * 2 + "px"; c.style.maxWidth = "100%"; return c;
  }
  function topbar(active) {
    const l = (h, t) => `<a class="px-btn sm ${active === h ? "on" : ""}" href="#/${h}">${t}</a>`;
    return `<div class="topbar"><a class="brand" href="#/">GREENHOUSE BENCH</a><nav>${l("runs", "Runs")}${l("stats", "Stats")}${l("how", "How it works")}</nav></div>`;
  }
  function tipShow(x, y, html) { tip.hidden = false; tip.innerHTML = html; tip.style.left = Math.min(innerWidth - 340, x + 12) + "px"; tip.style.top = y + 14 + "px"; }
  function tipHide() { tip.hidden = true; }

  // ============================================================== views
  function viewIntro() {
    app.innerHTML = `<div class="intro"><canvas class="bg"></canvas><div class="content"></div></div>`;
    const cv = app.querySelector("canvas.bg"), content = app.querySelector(".content");
    content.appendChild(bigText("GREENHOUSE BENCH", 6, 400));
    content.insertAdjacentHTML("beforeend", `<img class="hero" src="assets/hero.png" alt="Two pixel fighters with icon heads clash a shovel and a pitchfork in a greenhouse">
      <div class="px-panel lines"><div>An AI agent runs a 3-compartment winter greenhouse and its energy centre for 42 simulated days.</div>
      <div>It reads sensors, sets heating, light and CO2, orders stock, plants, harvests and fixes breakdowns through tools.</div>
      <div>It is scored on net profit against doing nothing. Watch any recorded run as a living pixel greenhouse.</div></div>
      <div class="btns"><a class="px-btn primary" href="#/runs">Watch a run</a><a class="px-btn" href="#/stats">Stats</a><a class="px-btn" href="#/how">How it works</a></div>`);
    const sc = window.PixelScene.create(cv), scale = Math.max(1, Math.ceil(innerWidth / 480)); cv.style.width = 480 * scale + "px"; cv.style.height = 270 * scale + "px";
    const D = buildMock("intro"); sc.setData(D); let hf = 380;
    const stop = loop((dt) => { hf += dt * 12; if (hf > 1000) { hf = 0; sc.reset(0); } sc.render(hf, dt, 12, true); });
    teardown = stop;
  }

  function viewRuns() {
    app.innerHTML = topbar("runs") + `<div class="page"><h2 class="px-title">Recorded runs</h2><div class="filters" id="f"></div><div class="cards" id="cards"><div class="msg dim">Loading runs...</div></div></div>`;
    fetchJson("/api/runs").then((j) => {
      const runs = j.runs || [], seeds = [...new Set(runs.map((r) => r.seed))].sort((a, b) => a - b);
      const f = document.getElementById("f");
      f.innerHTML = `<label>KIND <select id="fk"><option value="">all</option><option>agent</option><option>policy</option></select></label><label>SEED <select id="fs"><option value="">all</option>${seeds.map((s) => `<option>${s}</option>`).join("")}</select></label><span class="dim" id="fc"></span>`;
      const draw = () => {
        const k = document.getElementById("fk").value, s = document.getElementById("fs").value, host = document.getElementById("cards");
        const list = runs.filter((r) => (!k || r.kind === k) && (!s || String(r.seed) === s)).sort((a, b) => (b.score == null) - (a.score == null) || b.score - a.score);
        document.getElementById("fc").textContent = list.length + " / " + runs.length;
        host.innerHTML = ""; if (!list.length) host.innerHTML = '<div class="msg dim">No runs match.</div>';
        for (const r of list) {
          const a = document.createElement("a"); a.className = "card px-panel"; a.href = "#/run/" + encodeURIComponent(r.id);
          const face = document.createElement("div"); face.className = "face"; face.appendChild(S.mascotCanvas(S.mascotFor(r), 5));
          const base = r.baseline_profit_eur, d = r.profit_eur != null && base != null ? r.profit_eur - base : null, st = r.status === "complete" ? "good" : r.status === "partial" ? "warn" : "bad";
          const body = document.createElement("div");
          body.innerHTML = `<h3>${esc(r.label || r.model || r.id)}</h3><div class="row"><span class="px-tag ${r.kind === "agent" ? "info" : ""}">${esc(r.kind)}</span><span class="px-tag">seed ${esc(r.seed)}</span><span class="px-tag ${st}">${esc(r.status)}</span></div>
            <div class="big">${r.score == null ? "-" : "SCORE " + num(r.score, 2)}</div><div class="dim">PROFIT ${eur(r.profit_eur)}</div><div class="dim">BASELINE ${eur(base)}</div>
            ${d == null ? "" : `<div class="${d >= 0 ? "good" : "bad"}">${eur(d, true)} vs do-nothing</div>`}${r.failure ? `<div class="bad">${esc(r.failure)}</div>` : ""}`;
          a.append(face, body); host.appendChild(a);
        }
      };
      f.querySelectorAll("select").forEach((e) => (e.onchange = draw)); draw();
    }).catch((e) => { document.getElementById("cards").innerHTML = `<div class="px-panel msg bad">Could not load runs: ${esc(e.message)}. Try <a href="?mock=1#/runs">?mock=1</a>.</div>`; });
  }

  function viewStats() {
    app.innerHTML = topbar("stats") + `<div class="page" id="statsroot"></div>`;
    const root = document.getElementById("statsroot");
    if (window.PixelStats && PixelStats.mount) { try { PixelStats.mount(root, { fetchJson }); } catch (e) { root.innerHTML = `<div class="px-panel msg bad">Stats failed: ${esc(e.message)}</div>`; } }
    else root.innerHTML = '<div class="px-panel msg">Stats not built yet.</div>';
  }

  function viewHow() {
    app.innerHTML = topbar("how") + `<div class="page how"><div class="px-panel"><h2 class="px-title">How it works</h2>
      <p>Greenhouse Bench is an interactive environment. An agent runs three glass greenhouse compartments and a shared energy centre (CHP, boiler, heat buffer, CO2 tank, grid connection) for 42 simulated days. It sees sensor readings and acts through tools: climate setpoints, energy settings, orders, planting, harvesting, hiring, repairs. The score is net profit, compared with doing nothing.</p>
      <h2 class="px-title">What you see</h2><ul>
      <li>Sky, sun and moon follow the hour; clouds, rain, snow and wind follow the weather data.</li>
      <li>Energy building: CHP and BOILER windows glow when running, chimney smoke follows the load, tanks show heat buffer and CO2 stock. Grid arrows show import or export.</li>
      <li>Each greenhouse tints with its temperature, lights its lamps, opens roof vents and closes the thermal screen exactly as recorded. Underground pipes flow with the heat (red) and CO2 (teal) requests.</li>
      <li>Crops grow with age, wilt at low quality and sparkle when ready. The little worker wears the agent's icon head and walks to wherever the current task is.</li>
      <li>A broken window cracks, drops glass and lets cold air and frost in until it is repaired.</li></ul>
      <h2 class="px-title">Controls</h2><p>Space play/pause. Left/Right step one hour (Shift: one day). [ and ] jump to the previous or next event. Click a greenhouse or the energy centre to inspect it. Drag the scrub bar; coloured ticks are events (red bad, yellow warning, blue info).</p>
      <h2 class="px-title">Honesty note</h2><p>Replays are recordings of real simulator hours; with ?mock=1 the data are fabricated for UI testing only.</p></div></div>`;
  }

  // ============================================================== replay
  function viewRun(id) {
    app.innerHTML = topbar("") + `<div class="msg dim" id="ld">Loading run...</div>`;
    fetchJson("/api/runs/" + encodeURIComponent(id)).then(startReplay).catch((e) => { app.innerHTML = topbar("") + `<div class="page"><div class="px-panel msg bad">Could not load run: ${esc(e.message)}</div></div>`; });
  }
  function lb(arr, h) { let lo = 0, hi = arr.length; while (lo < hi) { const m = (lo + hi) >> 1; if (arr[m].h < h) lo = m + 1; else hi = m; } return lo; }

  function startReplay(D) {
    D.frames.forEach((f, i) => { if (f.day == null) f.day = Math.floor(f.h / 24) + 1; if (f.hod == null) f.hod = f.h % 24; });
    D.actions = D.actions || []; D.events = (D.events || []).slice().sort((a, b) => a.h - b.h); D.alarms = D.alarms || []; D.daily = D.daily || [];
    const meta = D.meta, last = D.frames.length - 1, mas = S.mascotFor(meta), cids = Object.keys(D.frames[0].c).sort();
    app.innerHTML = topbar("") + `<div class="replay"><div class="stagebox">
      <div class="hud" id="hud"></div>
      <div class="stage" id="stage"><canvas id="cv"></canvas><div class="toasts" id="toasts"></div><div class="done" id="done" hidden></div></div>
      <div class="controls"><div class="scrub" id="scrub"><div class="fill" id="fill"></div></div>
        <div class="ctl" id="ctl"><button class="px-btn" id="play">PLAY</button><button class="px-btn sm" data-s="-24">-1D</button><button class="px-btn sm" data-s="-1">-1H</button><button class="px-btn sm" data-s="1">+1H</button><button class="px-btn sm" data-s="24">+1D</button>
        <button class="px-btn sm" id="pe">[ PREV EVT</button><button class="px-btn sm" id="ne">NEXT EVT ]</button><span class="grow"></span><span class="dim">H/S</span>
        ${[1, 4, 12, 48].map((s) => `<button class="px-btn sm spd" data-v="${s}">${s}x</button>`).join("")}</div></div></div>
      <div class="side"><div class="px-panel"><div style="display:flex;gap:10px;align-items:center" id="who"></div></div>
        <div class="px-panel insp" id="insp"><h3 class="px-title">Inspector</h3><div class="dim">Click a greenhouse or the energy centre.</div></div>
        <div class="px-panel"><div class="tabs" id="tabs"><button class="px-btn sm on" data-t="actions">Actions</button><button class="px-btn sm" data-t="events">Events</button><button class="px-btn sm" data-t="alarms">Alarms</button></div><div class="list" id="list"></div></div></div></div>`;
    const $ = (i) => document.getElementById(i), cv = $("cv"), stage = $("stage");
    const sc = window.PixelScene.create(cv); sc.setData(D);
    const m = document.createElement("canvas"); $("who").append(S.mascotCanvas(mas, 4), Object.assign(document.createElement("div"), { innerHTML: `<div class="px-title" style="margin:0">${esc(meta.label || meta.model || meta.id)}</div><div class="dim">${esc(meta.kind)} / seed ${esc(meta.seed)} / ${esc(meta.scenario)}</div><div><span class="px-tag ${meta.status === "complete" ? "good" : "warn"}">${esc(meta.status)}</span> <span class="px-tag">${meta.replay_verified ? "replay verified" : "unverified"}</span></div>` }));
    const R = { hf: 0, playing: true, speed: 4, lastH: 0, tab: "actions", insp: null, listAt: 0, inspAt: 0, done: false, force: true };
    const evT = D.events.map((e) => e.h);
    // scrub ticks
    let tk = ""; for (let d = 1; d < 42; d++) tk += `<i class="day" style="left:${(d * 24 / last) * 100}%"></i>`;
    D.events.forEach((e) => (tk += `<i class="tick ${e.severity || "info"}" style="left:${(e.h / last) * 100}%"></i>`));
    $("scrub").insertAdjacentHTML("beforeend", tk + '<div class="head" id="head"></div>'); $("scrub").querySelectorAll("i.day").forEach((e) => (e.className = "day"));
    $("scrub").querySelectorAll("i.tick, i.day").forEach((e) => { e.style.position = "absolute"; });

    function fit() { const avail = $("hud").parentElement.clientWidth - 8, s = Math.floor(avail / 480), w = s >= 1 ? 480 * s : avail; cv.style.width = w + "px"; cv.style.height = (w * 270) / 480 + "px"; stage.style.width = w + 8 + "px"; }
    fit(); window.addEventListener("resize", fit);

    function frameNow() { return D.frames[clamp(Math.floor(R.hf), 0, last)]; }
    function toast(e) {
      const sev = e.severity || (e.kind === "alarm" ? "bad" : "info"); if (R.speed > 12 && sev === "info") return;
      const t = $("toasts"), d = document.createElement("div"); d.className = "toast " + sev; d.textContent = when(e.h) + "  " + (e.text || e.kind); t.appendChild(d); while (t.children.length > 4) t.firstChild.remove(); setTimeout(() => d.remove(), 4200);
    }
    function fire(from, to) {
      if (to < from || to - from > 60) { sc.reset(to); R.force = true; return; }
      for (let i = lb(D.events, from + 1); i < D.events.length && D.events[i].h <= to; i++) { sc.trigger(D.events[i]); toast(D.events[i]); }
      for (let i = lb(D.alarms, from + 1); i < D.alarms.length && D.alarms[i].h <= to; i++) { const a = D.alarms[i]; toast({ h: a.h, text: a.text, kind: "alarm", severity: "bad" }); sc.flash(a.target, P.bad); }
      const a0 = lb(D.actions, from + 1), a1 = lb(D.actions, to + 1), n = Math.min(3, a1 - a0);
      for (let k = 0; k < n; k++) { const a = D.actions[a1 - n + k], arg = a.args && (a.args.compartment || a.args.target || a.args.batch_id || a.args.item || ""); setTimeout(() => sc.bubble("worker", a.tool.replace(/_/g, " ") + (arg ? " " + arg : ""), a.ok ? P.white : P.bad), k * 700); }
    }
    function seek(h) { R.hf = clamp(h, 0, last); R.done = false; $("done").hidden = true; R.force = true; }
    function nextEvent(dir) {
      const h = Math.floor(R.hf);
      if (dir > 0) { for (const e of D.events) if (e.h > h) return seek(e.h); } else for (let i = D.events.length - 1; i >= 0; i--) if (D.events[i].h < h) return seek(D.events[i].h);
    }
    function hud() {
      const f = frameNow(), m = f.money || {}, p = m.profit_so_far_eur, base = meta.baseline_profit_eur, calls = lb(D.actions, f.h + 1);
      $("hud").innerHTML = `<div class="cell"><div class="k">Day</div><div class="v">${f.day}/42</div></div><div class="cell"><div class="k">Clock</div><div class="v">${String(f.hod).padStart(2, "0")}:00</div></div>
        <div class="cell"><div class="k">Outside</div><div class="v">${f.out.t.toFixed(1)}C</div></div><div class="cell"><div class="k">Cash</div><div class="v">${eur(m.cash_eur)}</div></div>
        <div class="cell"><div class="k">Profit</div><div class="v ${p >= 0 ? "good" : "bad"}">${eur(p)}</div></div><div class="cell"><div class="k">Do-nothing final</div><div class="v dim">${eur(base)}</div></div>
        <div class="cell"><div class="k">Actions</div><div class="v">${calls}</div></div>`;
      $("fill").style.width = $("head").style.left = (R.hf / last) * 100 + "%";
    }
    function lists() {
      const f = frameNow(), now = f.h, host = $("list"); let html = "";
      if (R.tab === "actions") {
        for (let i = lb(D.actions, now + 1) - 1, n = 0; i >= 0 && n < 70; i--, n++) { const a = D.actions[i]; if (a.day < f.day - 1) break;
          html += `<div class="it ${a.day === f.day ? "cur" : ""} ${a.ok ? "" : "err"}"><span class="when">${when(a.h)}</span><b>${esc(a.tool)}</b> ${esc(JSON.stringify(a.args || {}))} ${a.ok ? "" : "ERR " + esc(a.err)}</div>`; }
      } else if (R.tab === "events") {
        for (let i = lb(D.events, now + 1) - 1, n = 0; i >= 0 && n < 60; i--, n++) { const e = D.events[i]; html += `<div class="it ${e.severity === "bad" ? "err" : ""}"><span class="when">${when(e.h)}</span><span class="px-tag ${e.severity === "warn" ? "warn" : e.severity === "bad" ? "bad" : "info"}">${esc(e.kind)}</span> ${esc(e.text)}</div>`; }
      } else for (let i = lb(D.alarms, now + 1) - 1, n = 0; i >= 0 && n < 60; i--, n++) { const a = D.alarms[i]; html += `<div class="it err"><span class="when">${when(a.h)}</span>${esc(a.text)}</div>`; }
      host.innerHTML = html || '<div class="dim">Nothing yet.</div>';
    }
    function inspector() {
      const id = R.insp, host = $("insp"), f = frameNow(); if (!id) return;
      let h = `<h3 class="px-title">${id === "energy" ? "Energy centre" : "House " + esc(id) + " / " + esc(((meta.compartments || {})[id] || {}).crop)}</h3>`;
      if (id === "energy") { const e = f.ec; h += `<table><tr><td>Heat buffer</td><td class="n">${num(e.buffer)} kWh</td></tr><tr><td>CO2 tank</td><td class="n">${num(e.co2)} kg</td></tr><tr><td>CHP load</td><td class="n">${num((e.chp || 0) * 100)}%</td></tr><tr><td>Boiler</td><td class="n">${esc(e.boiler)}</td></tr><tr><td>Grid</td><td class="n">${e.imp > 0.5 ? "buy " + num(e.imp) : e.exp > 0.5 ? "sell " + num(e.exp) : "idle"} kWh</td></tr><tr><td>Gas</td><td class="n">${num(e.gas, 1)} m3/h</td></tr><tr><td>Faults</td><td class="n ${f.faults.length ? "bad" : "good"}">${f.faults.length ? esc(f.faults.join(", ")) : "none"}</td></tr></table>`; }
      else { const c = f.c[id]; h += `<table><tr><td>Temp</td><td class="n">${c.t}C (set ${c.sp_night}-${c.sp_day})</td></tr><tr><td>Humidity</td><td class="n">${num(c.rh)}%</td></tr><tr><td>CO2</td><td class="n">${num(c.co2)} ppm (set ${c.sp_co2})</td></tr><tr><td>PAR</td><td class="n">${num(c.par)}</td></tr><tr><td>Vent</td><td class="n">${num(c.vent)}%</td></tr><tr><td>Screen</td><td class="n">${c.screen ? "closed" : "open"}</td></tr><tr><td>Lamps</td><td class="n">${num(c.lamp, 1)} kW</td></tr><tr><td>Heat</td><td class="n">${num(c.heat, 1)} kW</td></tr></table>`;
        h += `<table style="margin-top:6px"><tr><th>Batch</th><th>State</th><th class="n">Age</th><th class="n">Q</th></tr>${f.b.filter((b) => b.c === id && b.st !== "harvested").map((b) => `<tr><td>${esc(b.id)}</td><td>${esc(b.st)}</td><td class="n">${num(b.age, 1)}d</td><td class="n">${num(b.qual * 100)}%</td></tr>`).join("")}</table>`; }
      host.innerHTML = h;
    }
    function showDone() {
      const f = D.frames[last], p = f.money.profit_so_far_eur, base = meta.baseline_profit_eur, d = $("done");
      d.innerHTML = `<div class="px-panel"><h2 class="px-title">42 days done</h2><div class="big ${p >= 0 ? "good" : "bad"}" style="font-size:22px">${eur(p)}</div><p>Do-nothing baseline ${eur(base)}${p != null && base != null ? `<br><span class="${p - base >= 0 ? "good" : "bad"}">${eur(p - base, true)} vs baseline</span>` : ""}${meta.score != null ? `<br>SCORE ${num(meta.score, 2)}` : ""}</p><button class="px-btn primary" id="again">Watch again</button></div>`; d.hidden = false;
      $("again").onclick = () => { seek(0); sc.reset(0); R.playing = true; setPlay(); R.lastH = 0; };
    }
    function setPlay() { $("play").textContent = R.playing ? "PAUSE" : "PLAY"; }
    function setSpeed() { document.querySelectorAll(".spd").forEach((b) => b.classList.toggle("on", +b.dataset.v === R.speed)); }
    setPlay(); setSpeed();

    // controls
    $("play").onclick = () => { if (R.hf >= last) seek(0); R.playing = !R.playing; setPlay(); };
    document.querySelectorAll("#ctl [data-s]").forEach((b) => (b.onclick = () => { R.playing = false; setPlay(); seek(Math.floor(R.hf) + +b.dataset.s); }));
    document.querySelectorAll(".spd").forEach((b) => (b.onclick = () => { R.speed = +b.dataset.v; setSpeed(); }));
    $("pe").onclick = () => nextEvent(-1); $("ne").onclick = () => nextEvent(1);
    document.querySelectorAll("#tabs [data-t]").forEach((b) => (b.onclick = () => { R.tab = b.dataset.t; document.querySelectorAll("#tabs [data-t]").forEach((x) => x.classList.toggle("on", x === b)); R.force = true; }));
    const sb = $("scrub"); let drag = false;
    const sbH = (e) => clamp(((e.clientX - sb.getBoundingClientRect().left) / sb.clientWidth) * last, 0, last);
    sb.onpointerdown = (e) => { drag = true; sb.setPointerCapture(e.pointerId); seek(sbH(e)); };
    sb.onpointermove = (e) => {
      if (drag) seek(sbH(e)); const h = sbH(e), i = lb(D.events, h), px = sb.clientWidth / last; let best = null, bd = 9;
      for (let k = Math.max(0, i - 3); k < Math.min(D.events.length, i + 3); k++) { const d = Math.abs(D.events[k].h - h) * px; if (d < bd) { bd = d; best = D.events[k]; } }
      tipShow(e.clientX, e.clientY - 60, best ? `<b>${when(best.h)}</b> ${esc(best.kind)}<br>${esc(best.text)}` : when(Math.round(h)));
    };
    sb.onpointerup = () => (drag = false); sb.onpointerleave = tipHide;
    cv.addEventListener("pointerdown", (e) => { const r = cv.getBoundingClientRect(), id = sc.hit(((e.clientX - r.left) / r.width) * 480, ((e.clientY - r.top) / r.height) * 270); R.insp = id; R.force = true; if (!id) $("insp").innerHTML = '<h3 class="px-title">Inspector</h3><div class="dim">Click a greenhouse or the energy centre.</div>'; });
    cv.addEventListener("pointermove", (e) => { const r = cv.getBoundingClientRect(); sc.setHover(sc.hit(((e.clientX - r.left) / r.width) * 480, ((e.clientY - r.top) / r.height) * 270)); });
    cv.addEventListener("pointerleave", () => sc.setHover(null));
    const onKey = (e) => {
      if (/INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return;
      if (e.key === " ") { e.preventDefault(); $("play").click(); } else if (e.key === "ArrowRight" || e.key === "ArrowLeft") { R.playing = false; setPlay(); seek(Math.floor(R.hf) + (e.key === "ArrowRight" ? 1 : -1) * (e.shiftKey ? 24 : 1)); }
      else if (e.key === "[") nextEvent(-1); else if (e.key === "]") nextEvent(1); else if (e.key === "Escape") { R.insp = null; }
    };
    document.addEventListener("keydown", onKey);
    if (Q.get("at")) seek(+Q.get("at")); if (Q.get("pause")) { R.playing = false; setPlay(); } if (Q.get("speed")) { R.speed = +Q.get("speed"); setSpeed(); } if (Q.get("open")) { R.insp = Q.get("open"); }
    R.lastH = Math.floor(R.hf); sc.reset(R.hf);

    const stop = loop((dt) => {
      if (R.playing) { R.hf = Math.min(last, R.hf + dt * R.speed); if (R.hf >= last && !R.done) { R.done = true; R.playing = false; setPlay(); showDone(); } }
      const h = Math.floor(R.hf); let changed = R.force;
      if (h !== R.lastH) { fire(R.lastH, h); R.lastH = h; changed = true; }
      sc.render(R.hf, dt, R.speed, R.playing);
      const now = performance.now();
      if (changed || (R.playing && now - R.listAt > 250)) { R.listAt = now; hud(); if (R.force || changed) { lists(); } if (R.insp) inspector(); R.force = false; }
      $("fill").style.width = $("head").style.left = (R.hf / last) * 100 + "%";
    });
    teardown = () => { stop(); document.removeEventListener("keydown", onKey); window.removeEventListener("resize", fit); tipHide(); };
  }

  // ============================================================== router
  function route() {
    if (teardown) { teardown(); teardown = null; } tipHide(); window.scrollTo(0, 0);
    const h = location.hash.replace(/^#\/?/, ""), parts = h.split("/");
    if (!h) viewIntro(); else if (parts[0] === "runs") viewRuns(); else if (parts[0] === "run" && parts[1]) viewRun(decodeURIComponent(parts[1])); else if (parts[0] === "stats") viewStats(); else if (parts[0] === "how") viewHow(); else viewIntro();
  }
  window.addEventListener("hashchange", route); route();
})();
