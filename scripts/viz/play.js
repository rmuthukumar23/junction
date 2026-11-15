// One morning, you against a model. A real morning from a recorded model run: you pick up to 5
// actions, the server copies the game (POST /api/challenge/play), plays your morning and the
// model's actual morning from the same state, and then lets the model carry on exactly as it did in
// its run. Both seasons get the official score; the reference planner's own season is the bar.
(() => {
  const $ = (s) => document.querySelector(s);
  const eur = (v) => (v < 0 ? "−" : "") + "€" + Math.round(Math.abs(v)).toLocaleString("en-US");
  const kfmt = (v) => (Math.abs(v) >= 1e6 ? (v / 1e6).toFixed(1) + "M" : Math.abs(v) >= 1e3 ? Math.round(v / 1e3) + "k" : Math.round(v));
  const HOURS_PER_SEC = 7;                 // a day plays in about 3.5 s
  const BOARD = [["Reference planner (scripted)", 0.80], ["Gemini 4 Hydrogen (mean of 7)", 0.781],
                 ["Claude Sonnet 5.5 (mean of 7)", 0.695], ["Claude Haiku 5.5 (mean of 3)", 0.622],
                 ["Stop-early baseline", 0.24], ["Nobody acts", 0]];
  const COLORS = { alarm: "#ff6b5b", delivery: "#7bd88f", contractor: "#6cc4ff", harvest: "#f4c24f", news: "#ffd166" };

  let seed = +(new URLSearchParams(location.search).get("seed") || 2);
  let G = null, R = null, B = null, F = [], ids = [];
  let hf = 0, target = 0, playing = false, last = 0, lastH = -1, zoom = 1.05, done = false, dayResults = null;
  let plan = freshPlan(), lampsOn = true, climateDone = false;
  const scene = makeScene({ pix: 2, zoom, transparent: true });
  scene.init($("#cv"));
  const meta = { compartments: {}, maxW: {}, snowAt: [], shift: [7, 15], maxLamp: {}, maxHeat: {}, maxBuffer: 1,
                 maxCO2: 1, maxHeatAll: 1, maxHD: 1, targets: {}, deliveries: [] };

  function freshPlan() { return { harvest: new Set(), plant: {}, orders: {}, repairs: [], climate: false, hire: 0 }; }
  function toast(html, ms = 3800) { const t = $("#toast"); t.innerHTML = html; t.style.display = "block"; clearTimeout(t._h); t._h = setTimeout(() => (t.style.display = "none"), ms); }
  async function post(path, body) {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json(); if (!r.ok) throw new Error(j.error || r.statusText); return j;
  }

  // ---------------- game ----------------
  fetch("/api/challenges").then((r) => r.json()).then((d) => {
    const box = $("#picks"); box.innerHTML = "";
    for (const c of d.challenges) {
      const b = document.createElement("button"); b.className = "pick";
      b.innerHTML = `<b>${c.title}</b> <span class="note">· day ${c.day} · vs ${c.model}</span><br><span>${c.blurb}</span>`;
      b.onclick = () => start(c.id, b); box.appendChild(b);
    }
  }).catch(() => ($("#picks").textContent = "Could not reach the server."));

  async function start(cid, btn) {
    btn.disabled = true; btn.insertAdjacentHTML("beforeend", '<br><span class="warn">replaying the model run to this morning…</span>');
    try { G = await post("/api/challenge/start", { challenge: cid }); } catch (e) { btn.innerHTML += `<br><span class="bad">${e.message}</span>`; return; }
    R = G.rules; B = G.briefing; ids = Object.keys(G.compartments).sort(); seed = G.seed;
    climateDone = B.clock.day > 0;
    meta.compartments = G.compartments;
    meta.shift = (B.status.business.staff.shift || "07:00-15:00").split("-").map((x) => parseInt(x, 10));
    for (const id of ids) {
      const ct = (G.crops[G.compartments[id].crop] || {}).climate_targets || {};
      const mid = (r) => (Array.isArray(r) ? (r[0] + r[1]) / 2 : r);
      meta.targets[id] = { day: mid(ct.day_temp_c), night: mid(ct.night_temp_c || ct.day_temp_c), rh: mid(ct.rh_pct) };
    }
    addFrames(G.frames, G.alarms);
    for (let h = 0; h < G.first_hour; h++) F[h] = { ...G.frames[0], h };
    hf = target = G.frames[G.frames.length - 1].h; lastH = Math.floor(hf);
    scene.setData(meta);
    $("#intro").style.display = "none";
    renderSheet(); hud();
    toast(`<b>${G.challenge.title}</b>: ${G.challenge.blurb}`, 7000);
  }

  function addFrames(frames, alarms) {
    for (const f of frames) {
      F[f.h] = f;
      for (const b of f.b) if (b.st !== "harvested") meta.maxW[b.crop] = Math.max(meta.maxW[b.crop] || 1e-6, b.w);
      for (const id of Object.keys(f.c)) {
        meta.maxLamp[id] = Math.max(meta.maxLamp[id] || 1e-6, f.c[id].lamp);
        meta.maxHeat[id] = Math.max(meta.maxHeat[id] || 1e-6, f.c[id].heat);
      }
      meta.maxBuffer = Math.max(meta.maxBuffer, f.ec.buffer); meta.maxCO2 = Math.max(meta.maxCO2, f.ec.co2);
      meta.maxHeatAll = Math.max(meta.maxHeatAll, f.ec.heat);
    }
    for (const a of alarms || []) {
      (G.alarmList = G.alarmList || []).push(a);
      if (a.kind === "delivery") meta.deliveries.push(a.h);
    }
  }

  // ---------------- the morning sheet ----------------
  const st = () => B.status, biz = () => B.status.business, day = () => B.clock.day, hour = () => B.clock.hour;
  const items = () => R.business.items;
  const density = (crop) => ((R.crops[crop] || {}).planting || {}).density_per_m2 || 1;
  const cropName = (c) => c.split("_")[0];
  function count() {
    let n = 0;
    if (plan.climate) n += 2;
    if (plan.harvest.size) n++;
    if (Object.keys(plan.plant).length) n++;
    if (Object.keys(plan.orders).length) n++;
    if (plan.hire) n++;
    n += plan.repairs.length;
    return n;
  }
  const limit = () => B.actions_left_today ?? 5;
  function can(extra) { return count() + extra <= limit(); }

  function renderSheet() {
    const body = $("#body"); body.innerHTML = "";
    const add = (html) => { const d = document.createElement("div"); d.innerHTML = html; body.appendChild(d); return d; };
    const h = hour(), w = Math.floor(h / 168), dem = R.business.demand;
    $("#slots").textContent = `${count()} / ${limit()} actions`;
    $("#go").textContent = count() ? `Lock in ${count()} ▶` : "Do nothing ▶";

    // market: the planning problem in one look
    const sold = biz().sold_last_7_days || {};
    const mk = add(`<h4>Market · week ${w + 1} of 6 (demand counted over the last 7 days)</h4><div class="mk"></div>`).querySelector(".mk");
    for (const crop of Object.keys(dem.demand_per_week)) {
      const f = dem.week_factors[crop], now = dem.demand_per_week[crop] * f[Math.min(w, f.length - 1)],
            next = dem.demand_per_week[crop] * f[Math.min(w + 1, f.length - 1)];
      const s = typeof sold[crop] === "object" ? (sold[crop].units ?? 0) : (sold[crop] || 0), k = Math.min(1, s / Math.max(1, now));
      mk.insertAdjacentHTML("beforeend", `<span>${cropName(crop)}</span><div><div class="bar"><i class="${s > now ? "over" : ""}" style="width:${k * 100}%"></i></div>
        <span class="note">sold ${kfmt(s)} of ${kfmt(now)} this week · next week ${kfmt(next)} · €${R.business.crop_prices_eur_per_unit[crop]}/unit</span></div>`);
    }

    // climate
    const cl = add(`<h4>Climate ${climateDone ? "" : '<span class="warn">· recommended now</span>'}</h4><div class="row"></div>`).querySelector(".row");
    const ch = chip(`Growing climate, all houses<small>crop targets day & night, CO₂, lamps ${lampsOn ? "on" : "off"} · 2 actions</small>`, plan.climate,
      () => { if (!plan.climate && !can(2)) return full(); plan.climate = !plan.climate; renderSheet(); });
    cl.appendChild(ch);
    cl.appendChild(chip(`Lamps ${lampsOn ? "ON" : "OFF"}<small>06:00–22:00, costs power</small>`, false, () => { lampsOn = !lampsOn; renderSheet(); }));

    // harvest
    const bs = (st().batches || []).filter((b) => b.status !== "harvested" && !b.harvest_queued);
    const hv = add(`<h4>Harvest (sold when the crew cuts it; grade drops ~2 days after ready)</h4><div class="row"></div>`).querySelector(".row");
    if (!bs.length) hv.innerHTML = '<span class="note">nothing growing</span>';
    for (const b of bs) {
      const e = b.estimate || {}, ready = b.status === "ready" || (e.days_to_ready ?? 9) <= 0;
      const c = chip(`${b.id} ${cropName(b.crop)}<small>${ready ? "READY" : "ready in " + (e.days_to_ready ?? "?") + " d"} · ${kfmt(e.units || 0)} u · q ${(e.quality ?? 0).toFixed(2)}</small>`,
        plan.harvest.has(b.id), () => { if (!plan.harvest.size && !plan.harvest.has(b.id) && !can(1)) return full();
          plan.harvest.has(b.id) ? plan.harvest.delete(b.id) : plan.harvest.add(b.id); renderSheet(); });
      c.classList.add(ready ? "ready" : "x"); hv.appendChild(c);
    }

    // plant
    const pl = add(`<h4>Plant (uses seed in stock)</h4><div class="row"></div>`).querySelector(".row");
    let any = false;
    for (const id of ids) {
      const free = (st().free_area_m2 || {})[id] || 0, crop = G.compartments[id].crop, stock = biz().stock["seedlings:" + crop] || 0;
      if (free <= 0.5) continue; any = true;
      const area = Math.min(free, stock / density(crop));
      const c = chip(`House ${id}: ${Math.round(area)} of ${Math.round(free)} m²<small>${cropName(crop)} · seed for ${Math.round(stock / density(crop))} m² in stock</small>`,
        id in plan.plant, () => { if (area < 1) return toast("No seed in stock for this crop: order it (10-day lead time)."); if (!Object.keys(plan.plant).length && !(id in plan.plant) && !can(1)) return full();
          id in plan.plant ? delete plan.plant[id] : (plan.plant[id] = Math.floor(area * 10) / 10); renderSheet(); });
      if (area < 1) c.classList.add("late"); pl.appendChild(c);
    }
    if (!any) pl.innerHTML = '<span class="note">no free bench space (harvest to free it)</span>';

    // orders
    const od = add(`<h4>Order seed (arrives in 10 days, day ${day() + 10})</h4><div class="row"></div>`).querySelector(".row");
    for (const crop of [...new Set(ids.map((id) => G.compartments[id].crop))]) {
      const it = items()["seedlings:" + crop];
      for (const m2 of [800, 1600, 3200]) {
        const qty = Math.max(it.min_quantity, Math.ceil(m2 * density(crop))), key = "seedlings:" + crop;
        const on = plan.orders[key] === qty;
        od.appendChild(chip(`${cropName(crop)} ${m2} m²<small>${kfmt(qty)} seed · ${eur(qty * it.price_eur_per_unit)}</small>`, on, () => {
          if (!Object.keys(plan.orders).length && !can(1)) return full();
          if (on) delete plan.orders[key]; else plan.orders[key] = qty; renderSheet(); }));
      }
    }
    const open = biz().open_orders || [];
    if (open.length) add(`<div class="note">on the way: ${open.map((o) => `${o.item.replace("seedlings:", "")} ${kfmt(o.quantity)} → day ${Math.floor(o.expected_arrival_hour / 24)}`).join(" · ")}</div>`);

    // repairs
    const outs = biz().outages || [];
    const rp = add(`<h4>Damage ${outs.length ? '<span class="bad">· ' + outs.length + " open</span>" : ""}</h4><div class="row"></div>`).querySelector(".row");
    if (!outs.length) rp.innerHTML = '<span class="note">nothing broken</span>';
    for (const o of outs) {
      const booked = (biz().contractor_bookings || []).some((b) => b.target === o.equipment);
      const trade = Object.entries(R.business.contractors || R.repairs || {}).find(([, s]) => (s.fixes || []).some((x) => o.equipment.endsWith(x)));
      const parts = o.parts_needed || {}, on = plan.repairs.some((r) => r.target === o.equipment);
      const c = chip(`Fix ${o.equipment}${o.panes_broken ? " (" + o.panes_broken + " panes)" : ""}<small>${booked ? "contractor booked" : "book " + (trade ? trade[0].replace("_", " ") : "?") + " + order parts"}</small>`, on, () => {
        if (booked && !on) return toast("Already booked: it comes when the parts are on site.");
        if (!on && !can(1 + (Object.keys(plan.orders).length || !Object.keys(parts).length ? 0 : 1))) return full();
        if (on) plan.repairs = plan.repairs.filter((r) => r.target !== o.equipment);
        else { plan.repairs.push({ target: o.equipment, trade: trade && trade[0], parts }); }
        renderSheet(); });
      c.classList.add("late"); rp.appendChild(c);
    }

    // crew
    const sf = biz().staff, tq = biz().task_queue || [];
    const cr = add(`<h4>Crew · ${sf.crew} workers, ${sf.shift}${tq.length ? ` · <span class="warn">${tq.length} jobs waiting</span>` : ""}</h4><div class="row"></div>`).querySelector(".row");
    cr.appendChild(chip(`Hire 1 worker<small>starts in 3 days · €400 + wages</small>`, plan.hire > 0, () => { if (!plan.hire && !can(1)) return full(); plan.hire = plan.hire ? 0 : 1; renderSheet(); }));
  }
  function chip(html, on, fn) { const b = document.createElement("button"); b.className = "chip" + (on ? " on" : ""); b.innerHTML = html; b.onclick = fn; return b; }
  function full() { toast(`Only ${limit()} actions a day.`); }

  function actions() {
    const a = [];
    if (plan.climate) {
      const mid = (r, d) => (Array.isArray(r) ? Math.round((r[0] + r[1]) / 2 * 10) / 10 : r ?? d);
      const ts = ids.map((id) => (G.crops[G.compartments[id].crop] || {}).climate_targets || {});
      const avg = (k, d) => Math.round(ts.reduce((s, t) => s + mid(t[k], d), 0) / ts.length * 10) / 10;
      a.push({ tool: "set_climate", heat_day_c: avg("day_temp_c", 20), heat_night_c: avg("night_temp_c", 17), co2_ppm: avg("co2_ppm", 900),
               lamp_hours: lampsOn ? [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17] : [], lamp_intensity_pct: lampsOn ? 100 : 0 });
      a.push({ tool: "set_night_schedule", from_hour: 18, copy_day: true, lamps_on: lampsOn });
    }
    const orders = { ...plan.orders };
    for (const r of plan.repairs) for (const [item, n] of Object.entries(r.parts || {})) {
      const have = biz().stock[item] || 0; if (n > have) orders[item] = (orders[item] || 0) + (n - have); }
    for (const r of plan.repairs) a.push({ tool: "book_contractor", target: r.target, trade: r.trade });
    if (plan.harvest.size) a.push({ tool: "harvest", batch_ids: [...plan.harvest] });
    if (Object.keys(plan.plant).length) a.push({ tool: "plant", areas_m2: plan.plant });
    if (Object.keys(orders).length) a.push({ tool: "place_orders", orders });
    if (plan.hire) a.push({ tool: "hire", workers: plan.hire });
    return a.slice(0, limit());
  }

  let result = null;
  $("#go").onclick = async () => {
    if (!G || playing || done) return;
    const acts = actions();
    $("#go").disabled = true; $("#go").textContent = "playing both seasons…";
    let r;
    try { r = await post("/api/challenge/play", { id: G.id, actions: acts }); }
    catch (e) { toast('<span class="bad">' + e.message + "</span>"); $("#go").disabled = false; renderSheet(); return; }
    result = r; done = true;
    addFrames(r.you.frames || [], []);
    target = r.you.frames && r.you.frames.length ? r.you.frames[r.you.frames.length - 1].h : target;
    playing = true; $("#sheet").classList.add("min");
    toast("Your day is playing out…", 2500);
  };
  $("#grab").onclick = $("#sheethead").querySelector(".t").onclick = () => $("#sheet").classList.toggle("min");
  new MutationObserver(() => document.body.classList.toggle("min", $("#sheet").classList.contains("min"))).observe($("#sheet"), { attributes: true });

  // ---------------- HUD, loop ----------------
  function hud() {
    if (!F.length) return;
    const h = Math.min(Math.floor(hf), F.length - 1), f = F[h] || F[F.length - 1];
    if (!f) return;
    const d = Math.floor(h / 24), hh = String(h % 24).padStart(2, "0");
    $("#clock").innerHTML = `<b>Day ${d}</b> / 42 · ${hh}:00<div class="note">${f.out.t.toFixed(1)} °C out · wind ${f.out.wind.toFixed(0)} m/s</div>`;
    $("#money").innerHTML = `<div class="you">${eur(f.money.profit_so_far_eur)}</div><div class="ref">profit so far · vs ${G ? G.model : ""}</div>`;
    const news = (B && B.news_last_3_days || []).slice(-2);
    $("#news").innerHTML = news.map((n) => `<div>📰 ${n.headline}</div>`).join("") +
      ((f.faults || []).length ? `<div class="bad" style="color:#ff6b5b">⚠ ${f.faults.join(", ")}</div>` : "");
  }
  function alarmsBetween(a, b) {
    for (const x of (G.alarmList || []).filter((x) => x.h > a && x.h <= b).slice(-3)) {
      const where = ids.includes((x.target || "")[0]) && (x.target || "").length <= 8 ? x.target[0] : x.kind === "delivery" ? "road" : "energy";
      scene.bubble(where, (x.text || x.kind).slice(0, 38), COLORS[x.kind] || "#ffffff");
    }
  }
  function loop(now) {
    const dt = Math.min(0.1, (now - (last || now)) / 1000); last = now;
    if (F.length && ids.length) {
      if (playing) {
        hf = Math.min(target, hf + dt * HOURS_PER_SEC);
        if (hf >= target) { playing = false; onMorning(); }
      }
      const h = Math.floor(hf);
      if (h !== lastH) { if (h > lastH) alarmsBetween(lastH, h); lastH = h; hud(); }
      const f = F[Math.min(h, F.length - 1)];
      if (f) scene.render(f, hf, dt, playing ? HOURS_PER_SEC / 3 : 0.2);
    }
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
  function onMorning() {
    hud();
    if (done && result) return finish(result);
    $("#go").disabled = false; renderSheet(); $("#sheet").classList.remove("min");
  }
  function describe(a) {
    const t = a.tool;
    if (t === "harvest") return "harvest " + (a.batch_ids || []).join(", ");
    if (t === "plant") return "plant " + Object.entries(a.areas_m2 || {}).map(([k, v]) => `${k} ${Math.round(v)} m²`).join(", ");
    if (t === "place_orders") { const o = a.orders || Object.fromEntries((a.order_list || []).map((x) => [x.item, x.quantity]));
      return "order " + Object.entries(o).map(([k, v]) => `${k.replace("seedlings:", "").replace("part:", "")} ${kfmt(v)}`).join(", "); }
    if (t === "book_contractor") return `book ${String(a.trade || "").replace("_", " ")} → ${a.target}`;
    if (t === "set_climate") return `climate ${a.heat_day_c ?? "–"}/${a.heat_night_c ?? "–"} °C${a.co2_ppm != null ? ", CO₂ " + a.co2_ppm : ""}`;
    if (t === "set_night_schedule") return `night from ${a.from_hour}:00`;
    if (t === "set_energy") return "energy " + Object.entries(a).filter(([k]) => k !== "tool").map(([k, v]) => `${k}=${v}`).join(" ");
    if (t === "hire") return `hire ${a.workers}`;
    return t;
  }
  function refused(res) {
    return (res || []).flatMap((x) => (!x.ok ? [`${x.tool}: ${String(x.error || "").slice(0, 90)}`] :
      Object.entries((x.result || {}).refused || {}).map(([k, v]) => `${x.tool} ${k}: ${String(typeof v === "string" ? v : JSON.stringify(v)).slice(0, 90)}`)));
  }
  function finish(r) {
    const you = r.you, m = r.model, pl = r.planner, diff = you.profit - m.profit;
    const verdict = Math.abs(diff) < 500 ? "Same season as the model" : diff > 0 ? `You beat ${r.challenge.model} by ${eur(diff)}` : `${r.challenge.model} beat you by ${eur(-diff)}`;
    const col = Math.abs(diff) < 500 ? "warn" : diff > 0 ? "ok" : "bad";
    const list = (acts) => acts && acts.length ? acts.map((a) => `<div>· ${describe(a)}</div>`).join("") : '<div class="note">· nothing</div>';
    const rf = refused(you.results);
    const rows = [["You (your morning, then the model's run)", you.score, you.profit, true],
                  [`${r.challenge.model} (its real run)`, m.score, m.profit, false],
                  ["Reference planner (its own season)", pl.score, pl.profit, false]].sort((a, b) => b[1] - a[1]);
    $("#endbox").innerHTML = `<h2 class="${col}">${verdict}</h2>
      <p class="note">${r.challenge.title} · day ${r.challenge.day} · seed ${seed}. Your morning replaced the model's; after it, the model carried on exactly as it did in its run.</p>
      <table>${rows.map((x) => `<tr class="${x[3] ? "you" : ""}"><td>${x[0]}</td><td>${(x[1] ?? 0).toFixed(3)}<div class="note">${eur(x[2])}</div></td></tr>`).join("")}</table>
      <div class="cmp"><div><h4>You did</h4>${list(you.actions)}${rf.length ? `<div class="bad" style="font-size:11px">${rf.map((x) => "✗ " + x).join("<br>")}</div>` : ""}</div>
        <div><h4>${r.challenge.model} did</h4>${list(m.actions)}</div></div>
      <div class="row"><button onclick="location.reload()">Another morning</button></div>`;
    $("#end").style.display = "flex"; $("#sheet").classList.add("min");
  }

  // ---------------- camera behind the site, tilt to look around, zoom ----------------
  let camOn = false;
  $("#bAR").onclick = async () => {
    const v = $("#cam");
    if (camOn) { (v.srcObject && v.srcObject.getTracks().forEach((t) => t.stop())); v.style.display = "none"; camOn = false; scene.settings({ see: false }); return; }
    try {
      v.srcObject = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
      v.style.display = "block"; camOn = true; scene.settings({ see: true });
    } catch (e) { toast("Camera needs the https link (and permission): " + e.message, 5000); }
  };
  let tilt = null;
  $("#bTilt").onclick = async () => {
    if (tilt) { window.removeEventListener("deviceorientation", tilt); tilt = null; toast("tilt off", 1200); return; }
    try { if (typeof DeviceOrientationEvent !== "undefined" && DeviceOrientationEvent.requestPermission) {
      const p = await DeviceOrientationEvent.requestPermission(); if (p !== "granted") throw new Error(p); } }
    catch (e) { return toast("Motion needs the https link and permission: " + e.message, 5000); }
    let base = null;
    tilt = (e) => { if (e.gamma == null) return; if (!base) base = { g: e.gamma, b: e.beta, a: scene.settings({}) };
      scene.settings({ az: base.a.az - (e.gamma - base.g) * 0.03, el: base.a.el + (e.beta - base.b) * 0.015 }); };
    window.addEventListener("deviceorientation", tilt); toast("tilt the phone to walk around the site", 2200);
  };
  $("#bZin").onclick = () => { zoom = scene.settings({ zoom: zoom * 1.2 }).zoom; };
  $("#bZout").onclick = () => { zoom = scene.settings({ zoom: zoom / 1.2 }).zoom; };
})();
