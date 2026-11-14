// Playback, cards, event feed, timeline and the detail drawer.
(() => {
  const $ = (id) => document.getElementById(id);
  const css = getComputedStyle(document.documentElement), C = {};
  for (const k of ["orange", "green", "blue", "yellow", "purple", "grey", "red", "grid", "grid2", "cursor", "band"]) C[k] = css.getPropertyValue(`--c-${k}`).trim();
  const HOURS_PER_SEC = 1008 / 180;           // 1x plays the 42 days in about 3 minutes
  const COLORS = { fault: C.red, fixed: C.green, delivery: C.blue, ready: C.yellow, sale: C.green,
                   order: C.blue, grower: C.purple, low: C.yellow, info: C.grey };
  let D = null, M = null, events = [], hf = 0, speed = 1, playing = true, lastHour = -1, last = 0, feedShown = 0;
  let tab = "money", range = "all", drawerOpen = false, lastDrawer = 0, IDS = [];

  const eur = (v, sign = false) => (v < 0 ? "-" : sign && v > 0 ? "+" : "") + "€" + Math.abs(Math.round(v)).toLocaleString("en-US");
  const num = (v, d = 0) => (v == null ? "–" : Number(v).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d }));
  const when = (h) => `Day ${Math.floor(h / 24) + 1} · ${String(h % 24).padStart(2, "0")}:00`;
  const cropName = (id) => (D.crops[id] || {}).name || id;
  const houseName = (c) => `House ${c} · ${cropName(D.compartments[c].crop)}`;
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

  // ---------------- loading a run ----------------
  async function load(policy, seed) {
    $("loading").hidden = false; $("done").hidden = true; $("loading-text").textContent = "Simulating 42 days of the real greenhouse…";
    try {
      const r = await fetch(`/api/run?policy=${encodeURIComponent(policy)}&seed=${seed}`);
      const j = await r.json(); if (!r.ok) throw new Error(j.error || r.status);
      D = j; prepare(); hf = 0; lastHour = -1; feedShown = 0; $("feed").innerHTML = ""; playing = true; setPlayIcon();
      $("loading").hidden = true;
      const q = new URLSearchParams(location.search);   // ?at=400&open=A&pause=1 jump straight to a moment
      if (q.get("at")) { seek(+q.get("at")); }
      if (q.get("pause")) { playing = false; setPlayIcon(); }
      if (q.get("open")) openDrawer(q.get("open"));
    } catch (e) { $("loading-text").innerHTML = `<span class="err">Could not run the simulator: ${esc(e.message)}</span>`; }
  }

  function prepare() {
    const F = D.frames, max = (fn) => Math.max(1e-6, ...F.map(fn));
    IDS = Object.keys(D.compartments).sort();
    const maxW = {};
    for (const f of F) for (const b of f.b) if (b.st !== "harvested") maxW[b.crop] = Math.max(maxW[b.crop] || 0, b.w);
    const temps = F.map((f) => f.out.t), snowAt = temps.map((_, i) => {
      const s = temps.slice(Math.max(0, i - 24), i + 1); return s.reduce((a, b) => a + b, 0) / s.length < 0.5 ? 1 : 0; });
    const sh = (D.shift || "07:00-15:00").split("-").map((s) => parseInt(s, 10));
    M = { compartments: D.compartments, maxW, snowAt, shift: sh,
          maxLamp: Object.fromEntries(IDS.map((id) => [id, max((f) => f.c[id].lamp)])),
          maxHeat: Object.fromEntries(IDS.map((id) => [id, max((f) => f.c[id].heat)])),
          maxBuffer: max((f) => f.ec.buffer), maxCO2: max((f) => f.ec.co2), maxHeatAll: max((f) => f.ec.heat),
          deliveries: D.alarms.filter((a) => a.kind === "delivery").map((a) => a.h) };
    Scene.setData(M);
    events = buildEvents();
    const who = { reference: "The expert planner", "rule-based": "A rule-based grower", naive: "A naive grower", "do-nothing": "Nobody" }[D.policy] || D.policy;
    $("subtitle").textContent = `${who} runs the real simulator for 42 winter days · seed ${D.seed} · ${D.calls.length} decisions`;
    buildHouseUI();
    // timeline markers
    $("tl-marks").innerHTML = events.filter((e) => ["fault", "delivery", "sale", "ready"].includes(e.type))
      .map((e) => `<i style="left:${(e.h / D.hours) * 100}%;background:${COLORS[e.type]}" title="${esc(when(e.h) + " " + e.text)}"></i>`).join("");
  }

  const SETTING = { heat_day_c: ["day heating", "°C"], heat_night_c: ["night heating", "°C"], co2_ppm: ["CO2 target", " ppm"],
    vent_min_pct: ["vents at least", "%"], vent_max_pct: ["vents at most", "%"], screen: ["screen", ""], lamp_intensity_pct: ["lamps", "%"] };
  const setting = (k, v) => k === "lamp_hours" ? `lamps on ${v.length} h a day` : SETTING[k] ? `${SETTING[k][0]} ${v}${SETTING[k][1]}` : `${k.replace(/_/g, " ")} ${v}`;

  const comp = (target) => (IDS.includes(target) ? target : IDS.includes(String(target)[0]) ? String(target)[0] : null);

  // One card and one details tab per compartment, however many the scenario has.
  function buildHouseUI() {
    document.querySelectorAll(".card.house, #tabs .house").forEach((el) => el.remove());
    const energyCard = document.querySelector('.card[data-open="energy"]'), energyTab = document.querySelector('#tabs [data-tab="energy"]');
    for (const id of IDS) {
      TABS[id] = houseTab(id);
      energyCard.insertAdjacentHTML("beforebegin", `<article class="card house" data-open="${id}"><h3>${esc(houseName(id))}</h3>` +
        `<div class="big" id="c-${id}">–</div><p class="small" id="c-${id}-sub">–</p><button class="link">Details →</button></article>`);
      energyTab.insertAdjacentHTML("beforebegin", `<button class="house" data-tab="${id}">${esc(houseName(id))}</button>`);
    }
    document.querySelectorAll(".card.house").forEach((el) => el.onclick = () => openDrawer(el.dataset.open));
    document.querySelectorAll("#tabs .house").forEach((b) => b.onclick = () => openDrawer(b.dataset.tab));
    if (!TABS[tab]) tab = "money";
  }

  // Turn alarms, grower decisions and sales into plain-language events.
  function buildEvents() {
    const ev = [];
    for (const a of D.alarms) {
      const tgt = a.target || "";
      if (a.kind === "equipment" && /working again/.test(a.text)) ev.push({ h: a.h, type: "fixed", where: "energy", text: `The ${tgt} works again`, bubble: `${tgt} fixed` });
      else if (a.kind === "equipment") ev.push({ h: a.h, type: "fault", where: "energy", text: `The ${tgt} broke down. ${a.text.split(". ").slice(1).join(". ")}`, bubble: `${tgt} broke!` });
      else if (a.kind === "delivery") ev.push({ h: a.h, type: "delivery", where: "road", text: a.text.replace(/([\d.]+e[+-]?\d+|\d+(\.\d+)?)/, (n) => num(+n)).replace("co2_kg", "kg of CO2").replace(/seedlings:(\w+)/, (_, c) => `${cropName(c)} seedlings`), bubble: "delivery" });
      else if (a.kind === "batch_ready") ev.push({ h: a.h, type: "ready", where: comp(tgt), text: `Batch ${tgt} is ready to harvest`, bubble: `${tgt} ready` });
      else if (a.kind === "stock_low") ev.push({ h: a.h, type: "low", where: "co2", text: a.text.replace("co2_store", "CO2 tank"), bubble: "CO2 low" });
      else ev.push({ h: a.h, type: "info", where: comp(tgt) || "energy", text: a.text, bubble: a.kind.replace(/_/g, " ") });
    }
    for (const c of D.calls) {
      const a = c.args, fail = c.ok ? "" : " (refused)";
      if (c.tool === "advance") continue;
      if (c.tool === "set_climate") ev.push({ h: c.h, type: "grower", where: a.compartment, text: `Grower changed ${houseName(a.compartment)}: ` +
        Object.entries(a).filter(([k]) => k !== "compartment").map(([k, v]) => setting(k, v)).join(", ") + fail, bubble: "new settings" });
      else if (c.tool === "place_order") ev.push({ h: c.h, type: "order", where: "energy", text: `Grower ordered ${num(a.quantity)} ${a.item === "co2_kg" ? "kg of CO2" : `${cropName(a.item.replace("seedlings:", ""))} seedlings`}${fail}`, bubble: "order placed" });
      else if (c.tool === "harvest") ev.push({ h: c.h, type: "grower", where: comp(a.batch_id), text: `Grower started harvesting ${a.batch_id}${fail}`, bubble: `harvest ${a.batch_id}` });
      else if (c.tool === "plant") ev.push({ h: c.h, type: "grower", where: a.compartment, text: `Grower planted ${num(a.area_m2)} m² in ${houseName(a.compartment)}${fail}`, bubble: "planting" });
      else if (c.tool === "hire") ev.push({ h: c.h, type: "grower", where: "energy", text: `Grower hired ${a.workers} worker(s)${fail}`, bubble: "hiring" });
      else if (c.tool === "set_energy") ev.push({ h: c.h, type: "grower", where: "energy", text: `Grower set the energy centre: ${Object.entries(a).map(([k, v]) => `${k.replace(/_/g, " ")} ${JSON.stringify(v)}`).join(", ")}${fail}`, bubble: "energy settings" });
      else ev.push({ h: c.h, type: "grower", where: (a.compartment || "energy"), text: `Grower: ${c.tool.replace(/_/g, " ")} ${JSON.stringify(a)}${fail}`, bubble: c.tool.replace(/_/g, " ") });
    }
    const pending = D.calls.filter((c) => c.tool === "harvest" && c.ok).map((c) => c.args.batch_id);
    for (let i = 1; i < D.frames.length; i++) {
      const p = D.frames[i - 1], f = D.frames[i], gain = f.money.harvest_revenue_eur - p.money.harvest_revenue_eur;
      if (gain > 1) {
        let sold = f.b.filter((b) => b.st === "harvested" && (p.b.find((x) => x.id === b.id) || {}).st !== "harvested").map((b) => b.id);
        sold.forEach((id) => { const k = pending.indexOf(id); if (k >= 0) pending.splice(k, 1); });
        if (!sold.length && pending.length) sold = [pending.shift()];
        const where = sold.length ? comp(sold[0]) : IDS[0];
        ev.push({ h: f.h, type: "sale", where, text: `Sold ${sold.join(", ") || "a harvest"} for ${eur(gain)}`, bubble: `+${eur(gain)}` });
      }
    }
    return ev.sort((a, b) => a.h - b.h);
  }

  // ---------------- playback ----------------
  function frameAt(h) { return D.frames[Math.max(0, Math.min(D.frames.length - 1, Math.floor(h)))]; }
  function loop(now) {
    const dt = Math.min(0.1, (now - (last || now)) / 1000); last = now;
    if (D) {
      if (playing) { hf = Math.min(D.hours, hf + dt * HOURS_PER_SEC * speed); if (hf >= D.hours) { playing = false; setPlayIcon(); showDone(); } }
      const h = Math.floor(hf);
      if (h !== lastHour) { fireEvents(lastHour, h); lastHour = h; updateHud(); }
      Scene.render(frameAt(hf), hf, dt, playing ? speed : 0.2);
      if (drawerOpen && now - lastDrawer > 250) { lastDrawer = now; renderDrawer(); }
    }
    requestAnimationFrame(loop);
  }
  function fireEvents(from, to) {
    const fresh = events.filter((e) => e.h > from && e.h <= to);
    if (to < from) { rebuildFeed(to); return; }
    if (to - from < 30) for (const e of fresh.slice(-3)) Scene.bubble(e.where, e.bubble, COLORS[e.type]);
    if (fresh.length) addFeed(fresh, true);
  }
  function addFeed(list, animate) {
    const ol = $("feed"), html = list.map((e) => `<li class="${animate ? "new" : ""}"><span class="dot" style="background:${COLORS[e.type]}"></span>` +
      `<span><span class="when">${when(e.h)}</span>${esc(e.text)}</span></li>`).reverse().join("");
    ol.insertAdjacentHTML("afterbegin", html); feedShown += list.length;
    while (ol.children.length > 80) ol.lastElementChild.remove();
  }
  function rebuildFeed(h) {
    $("feed").innerHTML = ""; feedShown = 0;
    const past = events.filter((e) => e.h <= h).slice(-80); if (past.length) addFeed(past, false);
    Scene.reset();
  }
  function seek(h) { const prev = Math.floor(hf); hf = Math.max(0, Math.min(D.hours, h)); $("done").hidden = true;
    const now = Math.floor(hf); if (now < prev || now - prev > 30) { rebuildFeed(now); lastHour = now; updateHud(); } }

  function setPlayIcon() { $("play").textContent = playing ? "❚❚" : "▶"; $("play").setAttribute("aria-label", playing ? "Pause" : "Play"); }

  // ---------------- HUD and cards ----------------
  function weatherWord(o) {
    const w = o.t <= 0.5 && o.rh >= 82 ? "Snowing" : o.rh >= 94 ? "Raining" : o.sun > 150 ? "Sunny" : o.sun > 10 ? "Cloudy" : "Dark";
    return `${w} · wind ${num(o.wind)} m/s · sun ${num(o.sun)} W/m²`;
  }
  function houseState(c) { return c.t < c.sp_night - 1 ? ["Too cold", "info"] : c.t > c.sp_day + 3 ? ["Too warm", "bad"] : ["On target", "good"]; }
  function updateHud() {
    const f = frameAt(hf), h = Math.min(Math.floor(hf), D.hours), m = f.money;
    $("hud-day").textContent = Math.min(42, Math.floor(h / 24) + 1); $("hud-time").textContent = `${String(h % 24).padStart(2, "0")}:00`;
    $("hud-temp").textContent = `${f.out.t.toFixed(1)}°C`;
    const p = m.profit_so_far_eur; $("hud-profit").textContent = eur(p); $("hud-profit").className = p >= 0 ? "good" : "bad";
    $("tl-fill").style.width = $("tl-head").style.left = `${(hf / D.hours) * 100}%`;
    $("tl-time").textContent = `${(hf / 24).toFixed(1)} / 42 d`;
    $("c-money").textContent = eur(p); $("c-money").className = "big " + (p >= 0 ? "good" : "bad");
    $("c-money-sub").textContent = `Cash ${eur(m.cash_eur)} · sales ${eur(m.harvest_revenue_eur)}`;
    $("c-out").textContent = `${f.out.t.toFixed(1)}°C`; $("c-out-sub").textContent = weatherWord(f.out);
    for (const id of IDS) {
      const c = f.c[id], [word, cls] = houseState(c), bs = f.b.filter((b) => b.c === id && b.st !== "harvested");
      const ready = bs.filter((b) => b.st === "ready").length;
      $(`c-${id}`).innerHTML = `${c.t.toFixed(1)}°C <span class="pill ${cls}">${word}</span>`;
      $(`c-${id}-sub`).textContent = `Target ${c.sp_night}–${c.sp_day}° · ${bs.length} beds growing${ready ? ` · ${ready} ready` : ""}${c.free > 1 ? ` · ${num(c.free)} m² empty` : ""}`;
    }
    const broken = f.faults.length;
    $("c-en").innerHTML = broken ? `<span class="bad">${esc(f.faults.join(", "))} down</span>` : `<span class="good">All running</span>`;
    const co2pct = (f.ec.co2 / M.maxCO2) * 100;
    $("c-en-sub").textContent = `CO2 tank ${num(co2pct)}% · ${f.ec.imp > 0.5 ? `buying ${num(f.ec.imp)} kWh` : f.ec.exp > 0.5 ? `selling ${num(f.ec.exp)} kWh` : "grid idle"} · gas ${num(f.ec.gas, 1)} m³/h`;
  }
  function showDone() {
    const f = D.frames[D.frames.length - 1], p = f.money.profit_so_far_eur, base = D.baseline_profit;
    $("done-profit").textContent = eur(p); $("done-profit").className = "v " + (p >= 0 ? "good" : "bad");
    $("done-base").textContent = eur(base);
    $("done-harv").textContent = events.filter((e) => e.type === "sale").length;
    $("done-faults").textContent = events.filter((e) => e.type === "fault").length;
    const diff = p - base;
    $("done-verdict").textContent = D.policy === "do-nothing" ? "Nobody touched anything. This is the number any grower, human or AI, has to beat." :
      `The grower ended ${eur(Math.abs(diff))} ${diff >= 0 ? "better" : "worse"} than leaving the greenhouse alone. The benchmark scores an AI agent between doing nothing (0) and the expert planner (0.8).`;
    $("done").hidden = false;
  }

  // ---------------- charts ----------------
  function series(fn) { return D.frames.map(fn); }
  function chart(id, lines, opts = {}) {
    const cv = document.getElementById(id); if (!cv) return;
    const dpr = devicePixelRatio || 1, w = cv.clientWidth * dpr, h = cv.clientHeight * dpr;
    if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
    const x = cv.getContext("2d"); x.clearRect(0, 0, w, h);
    const now = Math.floor(hf), a = range === "all" ? 0 : Math.max(0, now - 72), b = range === "all" ? D.hours : Math.max(now, 72);
    let lo = Infinity, hi = -Infinity;
    for (const l of lines) for (let i = a; i <= Math.min(b, now); i++) { const v = l.v[i]; if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }
    if (opts.band) { lo = Math.min(lo, opts.band[0]); hi = Math.max(hi, opts.band[1]); }
    if (opts.zero) lo = Math.min(lo, 0);
    if (!isFinite(lo)) { lo = 0; hi = 1; } if (hi - lo < 1e-6) hi = lo + 1;
    const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
    const L = 46 * dpr, X = (i) => L + ((i - a) / (b - a)) * (w - L - 6 * dpr), Y = (v) => h - 6 * dpr - ((v - lo) / (hi - lo)) * (h - 12 * dpr);
    x.font = `${11 * dpr}px Silkscreen, monospace`; x.fillStyle = C.grey;
    for (const v of [lo + pad, hi - pad]) { x.fillText(fmtAxis(v), 4 * dpr, Y(v) + 4 * dpr); x.fillStyle = C.grid; x.fillRect(L, Math.round(Y(v)), w - L, dpr); x.fillStyle = C.grey; }
    if (opts.band) { x.fillStyle = C.band; x.fillRect(L, Y(opts.band[1]), w - L, Y(opts.band[0]) - Y(opts.band[1])); }
    for (let d = Math.ceil(a / 24) * 24; d <= b; d += range === "all" ? 168 : 24) { x.fillStyle = C.grid2; x.fillRect(Math.round(X(d)), 0, dpr, h); }
    for (const l of lines) {
      x.strokeStyle = l.c; x.lineWidth = (l.thin ? 1 : 2) * dpr; x.beginPath(); let started = false;
      for (let i = a; i <= Math.min(b, now); i++) { const v = l.v[i]; if (v == null) { started = false; continue; }
        const px = Math.round(X(i)), py = Math.round(Y(v)); if (!started) { x.moveTo(px, py); started = true; } else { x.lineTo(px, x.__py ?? py); x.lineTo(px, py); } x.__py = py; }
      x.stroke(); x.__py = undefined;
    }
    x.fillStyle = C.cursor; x.fillRect(Math.round(X(now)), 0, 2 * dpr, h);
  }
  const fmtAxis = (v) => Math.abs(v) >= 10000 ? `${Math.round(v / 1000)}k` : Math.abs(v) >= 100 ? Math.round(v) : v.toFixed(1);
  const legend = (items) => `<div class="legend">${items.map(([c, t]) => `<span><i style="background:${c}"></i>${t}</span>`).join("")}</div>`;
  const sec = (title, note, body) => `<section class="sec"><h4>${title}</h4>${note ? `<p class="note">${note}</p>` : ""}${body}</section>`;
  const kv = (pairs) => `<div class="kv">${pairs.map(([k, v]) => `<div><span class="k">${k}</span><span>${v}</span></div>`).join("")}</div>`;

  // ---------------- drawer tabs ----------------
  let built = "";
  function renderDrawer() {
    const f = frameAt(hf), key = tab + range;
    if (built !== key) { $("drawer-body").innerHTML = TABS[tab].html(f); built = key; }
    TABS[tab].update(f);
  }
  const TABS = {};
  function houseTab(id) { return {
    html: () => {
      const crop = D.crops[D.compartments[id].crop] || {}, ct = crop.climate_targets || {};
      return sec("Temperature", `Inside vs the grower's heating setpoints. Green band: the crop's ideal day range (${(ct.day_temp_c || []).join("–")}°C).`,
          legend([[C.orange, "inside"], [C.green, "day setpoint"], [C.blue, "night setpoint"], [C.grey, "outside"]]) + `<canvas class="chart" id="ch-t"></canvas>`) +
        sec("CO2", `Plants grow faster with more CO2. Green band: ideal ${(ct.co2_ppm || []).join("–")} ppm. Dosing uses the CO2 tank.`, `<canvas class="chart" id="ch-co2"></canvas>`) +
        sec("Humidity", `Green band: ideal ${(ct.rh_pct || []).join("–")}%. Too humid invites disease.`, `<canvas class="chart" id="ch-rh"></canvas>`) +
        sec("Light", "Light at the plants (PAR) and lamp power. Winter sun is weak, so lamps do most of the work.",
          legend([[C.yellow, "PAR µmol/m²/s"], [C.purple, "lamps kW"]]) + `<canvas class="chart" id="ch-par"></canvas>`) +
        sec("Right now", "", `<div id="now-kv"></div>`) +
        sec("Beds", `Each batch of ${crop.name || "plants"} from planting to harvest. Sale price depends on grade (quality) and weight.`, `<div id="beds"></div>`);
    },
    update: (f) => {
      const c = f.c[id], ct = (D.crops[D.compartments[id].crop] || {}).climate_targets || {};
      chart("ch-t", [{ v: series((x) => x.out.t), c: C.grey, thin: 1 }, { v: series((x) => x.c[id].sp_day), c: C.green, thin: 1 },
        { v: series((x) => x.c[id].sp_night), c: C.blue, thin: 1 }, { v: series((x) => x.c[id].t), c: C.orange }], { band: ct.day_temp_c });
      chart("ch-co2", [{ v: series((x) => x.c[id].co2), c: C.blue }], { band: ct.co2_ppm });
      chart("ch-rh", [{ v: series((x) => x.c[id].rh), c: C.blue }], { band: ct.rh_pct });
      chart("ch-par", [{ v: series((x) => x.c[id].par), c: C.yellow }, { v: series((x) => x.c[id].lamp), c: C.purple, thin: 1 }], { zero: 1 });
      $("now-kv").innerHTML = kv([["Inside", `${c.t.toFixed(1)}°C`], ["Setpoints", `${c.sp_day}° day / ${c.sp_night}° night`], ["Humidity", `${num(c.rh)}%`],
        ["CO2", `${num(c.co2)} ppm (target ${c.sp_co2})`], ["CO2 dosing", `${num(c.co2req, 2)} kg/h`], ["Heating", `${num(c.heat)} kW`],
        ["Vents", `${num(c.vent)}% open`], ["Energy screen", c.screen ? "closed" : "open"], ["Lamps", `${num(c.lamp)} kW`], ["Light today", `${num(c.dli, 1)} mol/m²`]]);
      const grades = ((D.crops[D.compartments[id].crop] || {}).market || {}).grades || [];
      const grade = (q) => (grades.find((g) => q >= g.min_quality) || { name: "?" }).name;
      const rows = f.b.filter((b) => b.c === id).map((b) => {
        const st = b.st === "ready" ? '<span class="pill warn">ready</span>' : b.st === "harvested" ? '<span class="pill">sold</span>' : '<span class="pill good">growing</span>';
        return `<tr><td>${b.id}</td><td>${st}${b.q ? ' <span class="pill info">harvesting</span>' : ""}</td><td class="num">${num(b.age, 1)} d</td>` +
          `<td class="num">${num(b.w)} g</td><td class="num">${num(b.qual * 100)}% (${grade(b.qual)})</td><td class="num">${b.ready == null ? "–" : num(b.ready, 1) + " d"}</td><td class="num">${num(b.units)}</td></tr>`;
      }).join("");
      $("beds").innerHTML = `<table><tr><th>Batch</th><th>Status</th><th class="num">Age</th><th class="num">Weight</th><th class="num">Quality</th><th class="num">Ready in</th><th class="num">Plants</th></tr>${rows}</table>`;
    },
  }; }
  TABS.energy = {
    html: () => sec("Heat", "Heat made by the boiler and CHP each hour, and gas burnt to make it.", legend([[C.orange, "heat kWh"], [C.grey, "gas m³ ×10"]]) + `<canvas class="chart" id="ch-heat"></canvas>`) +
      sec("Electricity", "Lamps need lots of power. Bought from the grid, or made by the CHP (which can also sell the surplus).", legend([[C.yellow, "bought kWh"], [C.green, "sold kWh"]]) + `<canvas class="chart" id="ch-el"></canvas>`) +
      sec("Prices", "Hourly prices from recorded Dutch winter data. Buying at peaks costs more.", legend([[C.yellow, "electricity €/kWh"], [C.orange, "gas €/m³"]]) + `<canvas class="chart" id="ch-price"></canvas>`) +
      sec("Tanks", "The hot-water buffer stores heat for later. The CO2 tank feeds the houses and must be reordered in time (deliveries take days).", legend([[C.orange, "buffer kWh"], [C.blue, "CO2 kg"]]) + `<canvas class="chart" id="ch-tank"></canvas>`) +
      sec("Settings and orders", "", `<div id="en-kv"></div>`),
    update: (f) => {
      chart("ch-heat", [{ v: series((x) => x.ec.gas * 10), c: C.grey, thin: 1 }, { v: series((x) => x.ec.heat), c: C.orange }], { zero: 1 });
      chart("ch-el", [{ v: series((x) => x.ec.imp), c: C.yellow }, { v: series((x) => x.ec.exp), c: C.green }], { zero: 1 });
      chart("ch-price", [{ v: series((x) => x.ec.p_imp), c: C.yellow }, { v: series((x) => x.ec.p_gas), c: C.orange }], { zero: 1 });
      chart("ch-tank", [{ v: series((x) => x.ec.buffer), c: C.orange }, { v: series((x) => x.ec.co2), c: C.blue }], { zero: 1 });
      const e = f.ec;
      $("en-kv").innerHTML = kv([["Broken", f.faults.length ? `<span class="bad">${esc(f.faults.join(", "))}</span>` : '<span class="good">nothing</span>'],
        ["CHP load", e.chp ? `${num(e.chp * 100)}%` : "off"], ["Boiler", e.boiler], ["Buffer mode", e.bufmode], ["External CO2", `${num(e.extco2, 1)} kg/h`],
        ["Heat lost", `${num(e.lost, 1)} kWh`], ["Electricity price", `€${num(e.p_imp, 3)} buy / €${num(e.p_exp, 3)} sell`], ["Gas price", `€${num(e.p_gas, 2)}/m³`]]) +
        (f.orders.length ? `<table style="margin-top:10px"><tr><th>Order</th><th>Item</th><th class="num">Qty</th><th class="num">Arrives</th><th>Status</th></tr>${f.orders.map((o) =>
          `<tr><td>${o.id}</td><td>${esc(o.item)}</td><td class="num">${num(o.qty)}</td><td class="num">${when(o.eta)}</td><td>${o.st}</td></tr>`).join("")}</table>` : '<p class="note" style="margin-top:8px">No open orders.</p>');
    },
  };
  TABS.weather = {
    html: () => sec("Outside temperature", "Recorded Dutch January weather. Every grower on the same seed gets the same weather.", `<canvas class="chart" id="ch-ot"></canvas>`) +
      sec("Sun", "Solar radiation in W/m². Short, dark winter days.", `<canvas class="chart" id="ch-sun"></canvas>`) +
      sec("Wind and humidity", "", legend([[C.blue, "humidity %"], [C.purple, "wind m/s ×10"]]) + `<canvas class="chart" id="ch-wind"></canvas>`),
    update: () => {
      chart("ch-ot", [{ v: series((x) => x.out.t), c: C.blue }], { band: [-30, 0] });
      chart("ch-sun", [{ v: series((x) => x.out.sun), c: C.yellow }], { zero: 1 });
      chart("ch-wind", [{ v: series((x) => x.out.rh), c: C.blue }, { v: series((x) => x.out.wind * 10), c: C.purple, thin: 1 }], { zero: 1 });
    },
  };
  TABS.money = {
    html: () => sec("Profit over time", "Profit = sales minus every cost so far. Wages and energy are paid every hour; money comes in only at harvests.",
        legend([[C.green, "profit"], [C.grey, "doing nothing (end)"]]) + `<canvas class="chart" id="ch-profit"></canvas>`) +
      sec("Where the money went", "", `<div id="money-tab"></div>`) + sec("Staff and work queue", "", `<div id="staff"></div>`),
    update: (f) => {
      chart("ch-profit", [{ v: series(() => D.baseline_profit), c: C.grey, thin: 1 }, { v: series((x) => x.money.profit_so_far_eur), c: C.green }], { zero: 1 });
      const items = Object.entries(f.money).filter(([k]) => !["cash_eur", "profit_so_far_eur"].includes(k));
      const big = Math.max(1, ...items.map(([, v]) => Math.abs(v)));
      $("money-tab").innerHTML = `<table>${items.map(([k, v]) => `<tr><td>${k.replace(/_eur$/, "").replace(/_/g, " ")}</td><td style="width:45%"><div class="bar"><i style="left:0;width:${(Math.abs(v) / big) * 100}%;background:${v >= 0 ? C.green : C.red}"></i></div></td><td class="num ${v > 0 ? "good" : v < 0 ? "bad" : ""}">${eur(v, true)}</td></tr>`).join("")}` +
        `<tr><th>Profit so far</th><td></td><th class="num">${eur(f.money.profit_so_far_eur)}</th></tr><tr><td>Cash in the bank</td><td></td><td class="num">${eur(f.money.cash_eur)}</td></tr></table>`;
      $("staff").innerHTML = kv([["Crew", `${f.staff} workers`], ["Shift", D.shift]]) + (f.tasks.length ?
        `<table style="margin-top:10px"><tr><th>Task</th><th>Target</th><th class="num">Work done</th><th>Status</th></tr>${f.tasks.map((k) => `<tr><td>${k.kind}</td><td>${k.target}</td><td class="num">${num(k.done)} / ${num(k.need)} h</td><td>${k.st}</td></tr>`).join("")}</table>` : '<p class="note" style="margin-top:8px">No work queued.</p>');
    },
  };
  TABS.log = {
    html: () => sec("Every decision so far", `The grower plays through the same tools an AI agent gets. "advance" moves time forward and is the only call that counts against the budget of ${D.max_calls}.`,
      `<label class="note"><input type="checkbox" id="hide-adv" checked> hide "advance"</label><div id="log"></div>`) + sec("Every event so far", "", `<div id="evlog"></div>`),
    update: (f) => {
      const hide = $("hide-adv") ? $("hide-adv").checked : true, now = f.h;
      const calls = D.calls.filter((c) => c.h <= now && !(hide && c.tool === "advance"));
      const used = D.calls.filter((c) => c.h <= now && c.tool === "advance").length;
      $("log").innerHTML = `<p class="note">Time steps used: ${used} of ${D.max_calls}</p><table><tr><th>When</th><th>Tool</th><th>Arguments</th><th>OK</th></tr>${calls.slice(-200).reverse().map((c) =>
        `<tr><td>${when(c.h)}</td><td>${c.tool}</td><td><code>${esc(JSON.stringify(c.args))}</code></td><td>${c.ok ? "✓" : `<span class="err">${esc(c.err || "no")}</span>`}</td></tr>`).join("")}</table>`;
      $("evlog").innerHTML = `<table>${events.filter((e) => e.h <= now).reverse().map((e) => `<tr><td>${when(e.h)}</td><td><span class="pill" style="color:${COLORS[e.type]}">${e.type}</span></td><td>${esc(e.text)}</td></tr>`).join("")}</table>`;
    },
  };
  TABS.raw = { html: () => sec("This hour, exactly as the simulator reports it", "", `<pre id="raw"></pre>`), update: (f) => { $("raw").textContent = JSON.stringify(f, null, 1); } };
  TABS.about = {
    html: () => sec("What you're watching", "", `<p class="note">This is the real Greenhouse Bench simulator from <code>src/greenhouse</code>, not an animation. A grower plays 42 winter days through the same tools an AI agent gets (read status, change heating and CO2, order stock, harvest, advance time). Every simulated hour is recorded and replayed here. The picture is drawn from those numbers: lamps glow when lamp power is on, smoke follows gas burnt, plants grow with their real weight, the red light flashes when equipment is broken.</p>`) +
      sec("The goal", "", `<p class="note">${esc(D.objective)}</p>`) +
      sec("Growers you can pick", "", `<p class="note"><b>Expert planner</b>: the hand-written reference the benchmark is calibrated against. <b>Rule-based</b>: a sensible grower following fixed rules. <b>Naive</b>: crop-file targets, reorders CO2 only when the tank is empty, harvests when ready. <b>Nobody</b>: the starting settings run untouched; the baseline every grower must beat. A different seed gives different weather windows, breakdowns and hidden parameters.</p>`) +
      sec("Scenario", "", `<p class="note">The benchmark scenario <code>scenarios/normal-winter.toml</code>: 42 days, 400 tool calls. Profit here is the raw EUR figure; the official score maps it so doing nothing is 0 and the expert planner is 0.8.</p>`),
    update: () => {},
  };

  function openDrawer(t) {
    if (t && TABS[t]) tab = t; built = "";
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
    drawerOpen = true; $("drawer").classList.add("open"); $("drawer").setAttribute("aria-hidden", "false"); $("scrim").hidden = false; renderDrawer();
  }
  function closeDrawer() { drawerOpen = false; $("drawer").classList.remove("open"); $("drawer").setAttribute("aria-hidden", "true"); $("scrim").hidden = true; }

  // ---------------- wiring ----------------
  Scene.init($("scene"));
  $("play").onclick = () => { if (!D) return; if (hf >= D.hours) seek(0); playing = !playing; setPlayIcon(); };
  document.querySelectorAll(".speeds button").forEach((b) => b.onclick = () => {
    speed = +b.dataset.speed; document.querySelectorAll(".speeds button").forEach((x) => x.classList.toggle("on", x === b)); });
  const tl = $("timeline"); let drag = false;
  const tlSeek = (e) => { const r = tl.getBoundingClientRect(); seek(((e.clientX - r.left) / r.width) * D.hours); };
  tl.onpointerdown = (e) => { if (!D) return; drag = true; tl.setPointerCapture(e.pointerId); tlSeek(e); };
  tl.onpointermove = (e) => drag && tlSeek(e);
  tl.onpointerup = () => { drag = false; };
  document.querySelectorAll("[data-open]").forEach((el) => el.onclick = () => D && openDrawer(el.dataset.open));
  document.querySelectorAll("#tabs button").forEach((b) => b.onclick = () => openDrawer(b.dataset.tab));
  document.querySelectorAll("#range button").forEach((b) => b.onclick = () => { range = b.dataset.range; built = "";
    document.querySelectorAll("#range button").forEach((x) => x.classList.toggle("on", x === b)); renderDrawer(); });
  $("close").onclick = closeDrawer; $("scrim").onclick = closeDrawer;
  $("scene").addEventListener("scenepick", (e) => { if (D && e.detail) openDrawer(e.detail); });
  $("replay").onclick = () => { seek(0); rebuildFeed(0); playing = true; setPlayIcon(); };
  $("done-details").onclick = () => openDrawer("money");
  $("newrun").onsubmit = (e) => { e.preventDefault(); load($("policy").value, Math.max(1, Math.min(9999, +$("seed").value || 1))); };
  document.addEventListener("keydown", (e) => {
    if (!D || e.target.matches("input, select")) return;
    if (e.key === " ") { e.preventDefault(); $("play").click(); }
    else if (e.key === "Escape") closeDrawer();
    else if (e.key === "ArrowRight") seek(hf + 24); else if (e.key === "ArrowLeft") seek(hf - 24);
  });
  load($("policy").value, 1);
  requestAnimationFrame(loop);
})();
