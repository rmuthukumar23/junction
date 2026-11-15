// One playable day on a phone, against a model. A real morning from a recorded model run: you get
// the model's briefing and its 5 actions (the same submit_day tool), the day plays out from morning
// to evening on the viewer's 3D site, and meanwhile the server replays the model's own morning on a
// copy from the same state. Then both are checked for the same failure patterns
// (scripts/viz/failures.py), and the reference planner finishes both seasons so each morning also
// gets a season score. Endpoints: /api/challenges, /api/challenge/start, /api/challenge/day,
// /api/challenge/report.
(() => {
  const $ = (s) => document.querySelector(s);
  const eur = (v) => (v < 0 ? "−" : "") + "€" + Math.round(Math.abs(v)).toLocaleString("en-US");
  const keur = (v) => (v < 0 ? "−" : "") + "€" + (Math.abs(v) >= 1e6 ? (Math.abs(v) / 1e6).toFixed(2) + "M" : Math.abs(v) >= 1e3 ? Math.round(Math.abs(v) / 1e3) + "k" : Math.round(Math.abs(v)));
  const kfmt = (v) => (Math.abs(v) >= 1e6 ? (v / 1e6).toFixed(1) + "M" : Math.abs(v) >= 1e3 ? (v / 1e3).toFixed(v >= 1e4 ? 0 : 1) + "k" : Math.round(v));
  const DAY_RATE = 2.4, NIGHT_RATE = 14;          // simulated hours per second: 06-18 in ~5 s, the night in ~1 s
  const LEVEL = { first: "hard", radish: "medium", broccoli: "medium" };

  let G = null, R = null, B = null, F = [], ids = [], seed = 0, final = null, result = null;
  let hf = 0, target = 0, playing = false, last = 0, lastH = -1, zoom = 1.05, phase = "intro", lampsOn = true;
  let plan = freshPlan(), viewing = "you";
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
  const sheet = (open) => { $("#sheet").classList.toggle("min", !open); document.body.classList.toggle("min", !open); };

  // ---------------- choosing a morning ----------------
  fetch("/api/challenges").then((r) => r.json()).then((d) => {
    const box = $("#picks"); box.innerHTML = "";
    for (const c of d.challenges) {
      const b = document.createElement("button"); b.className = "pick";
      b.innerHTML = `<span class="lvl">${LEVEL[c.id] || ""}</span><span class="t">${c.title}</span><br><span class="vs">Day ${c.day} · against ${c.model}</span><span class="d">${c.blurb}</span>`;
      b.onclick = () => start(c.id, b); box.appendChild(b);
    }
  }).catch(() => ($("#picks").innerHTML = '<span class="bad">Could not reach the game server.</span>'));

  async function start(cid, btn) {
    document.querySelectorAll(".pick").forEach((b) => (b.disabled = true));
    btn.insertAdjacentHTML("beforeend", '<span class="d warn"><span class="spin"></span> replaying the AI\'s run up to this morning…</span>');
    try { G = await post("/api/challenge/start", { challenge: cid }); }
    catch (e) { btn.insertAdjacentHTML("beforeend", `<span class="d bad">${e.message}</span>`); document.querySelectorAll(".pick").forEach((b) => (b.disabled = false)); return; }
    R = G.rules; B = G.briefing; ids = Object.keys(G.compartments).sort(); seed = G.seed;
    meta.compartments = G.compartments;
    meta.shift = (B.status.business.staff.shift || "07:00-15:00").split("-").map((x) => parseInt(x, 10));
    for (const id of ids) {
      const ct = (G.crops[G.compartments[id].crop] || {}).climate_targets || {};
      const mid = (r) => (Array.isArray(r) ? (r[0] + r[1]) / 2 : r);
      meta.targets[id] = { day: mid(ct.day_temp_c), night: mid(ct.night_temp_c || ct.day_temp_c), rh: mid(ct.rh_pct) };
    }
    addFrames(G.frames);
    for (let h = 0; h < G.first_hour; h++) F[h] = { ...G.frames[0], h };
    hf = target = G.frames[G.frames.length - 1].h; lastH = Math.floor(hf);
    scene.setData(meta);
    $("#intro").style.display = "none"; $("#tools").style.display = "flex"; $("#money").style.display = "block";
    phase = "morning"; renderSheet(); hud(); sheet(true);
  }

  function addFrames(frames) {
    for (const f of frames) {
      F[f.h] = f;
      for (const b of f.b) if (b.st !== "harvested") meta.maxW[b.crop] = Math.max(meta.maxW[b.crop] || 1e-6, b.w);
      for (const id of Object.keys(f.c)) {
        meta.maxLamp[id] = Math.max(meta.maxLamp[id] || 1e-6, f.c[id].lamp);
        meta.maxHeat[id] = Math.max(meta.maxHeat[id] || 1e-6, f.c[id].heat);
      }
      meta.maxBuffer = Math.max(meta.maxBuffer, f.ec.buffer); meta.maxCO2 = Math.max(meta.maxCO2, f.ec.co2);
      meta.maxHeatAll = Math.max(meta.maxHeatAll, f.ec.heat);
      const t = F.slice(Math.max(0, f.h - 24), f.h + 1).filter(Boolean).map((x) => x.out.t);
      meta.snowAt[f.h] = t.length && t.reduce((a, b) => a + b, 0) / t.length < 0.5 ? 1 : 0;
    }
  }

  // ---------------- the morning ----------------
  const st = () => B.status, biz = () => B.status.business, hour = () => B.clock.hour, day = () => B.clock.day;
  const density = (crop) => ((G.crops[crop] || {}).planting || {}).density_per_m2 || ((R.crops[crop] || {}).planting || {}).density_per_m2 || 1;
  const cname = (c) => (c || "").split("_")[0];
  const price = (crop) => R.business.crop_prices_eur_per_unit[crop] || 0;
  const units = (v) => (v && typeof v === "object" ? v.units || 0 : v || 0);
  const est = (b) => b.estimate || {};
  const isReady = (b) => b.status === "ready" || (b.status === "growing" && (est(b).days_to_ready ?? 9) <= 0.05);
  function demand(crop, h) { const d = R.business.demand, f = d.week_factors[crop] || [1]; return d.demand_per_week[crop] * f[Math.min(Math.floor(h / 168), f.length - 1)]; }
  const room = (crop) => demand(crop, hour()) - units((biz().sold_last_7_days || {})[crop]);
  function planned(crop) { let u = 0; for (const b of st().batches) if (plan.harvest.has(b.id) && b.crop === crop) u += est(b).units || 0; return u; }
  const limit = () => B.actions_left_today ?? 5;
  function count() {
    return (plan.climate ? 2 : 0) + (plan.harvest.size ? 1 : 0) + (Object.keys(plan.plant).length ? 1 : 0)
      + (Object.keys(orders()).length ? 1 : 0) + (plan.hire ? 1 : 0) + plan.repairs.length;
  }
  function orders() {
    const o = { ...plan.orders };
    for (const r of plan.repairs) for (const [item, n] of Object.entries(r.parts || {})) { const have = biz().stock[item] || 0; if (n > have) o[item] = (o[item] || 0) + (n - have); }
    return o;
  }
  function tryAdd(extra, fn) { if (count() + extra > limit()) return toast(`Only ${limit()} actions a day. Drop one first.`); fn(); renderSheet(); }
  const houseOf = (b) => b.compartment || b.id[0];
  const cropsHere = () => [...new Set(ids.map((id) => G.compartments[id].crop))];

  function briefing() {
    const lines = [], ready = st().batches.filter((b) => isReady(b) && !b.harvest_queued);
    if (ready.length) lines.push(`🌿 <b>Ready to cut:</b> ${ready.map((b) => `${cname(b.crop)} in house ${houseOf(b)} (${kfmt(est(b).units || 0)} units ≈ ${keur((est(b).units || 0) * price(b.crop))})`).join(", ")}.`);
    else lines.push(`🌿 Nothing is ready to cut today. Next: ${(() => { const n = st().batches.filter((b) => b.status === "growing").sort((a, b) => (est(a).days_to_ready ?? 99) - (est(b).days_to_ready ?? 99))[0]; return n ? `${cname(n.crop)} in house ${houseOf(n)} in ${(est(n).days_to_ready ?? 0).toFixed(1)} days` : "–"; })()}.`);
    for (const crop of cropsHere()) {
      const r = room(crop), nx = demand(crop, hour() + 168);
      lines.push(`📈 <b>${cname(crop)} buyers</b> still want <b>${kfmt(Math.max(0, r))}</b> units at full price this week (€${price(crop)} each); next week ${kfmt(nx)}.`);
    }
    const free = Object.entries(st().free_area_m2 || {}).filter(([, a]) => a > 50);
    if (free.length) lines.push(`🪴 <b>Empty benches:</b> ${free.map(([c, a]) => `house ${c} ${Math.round(a)} m²`).join(", ")}.`);
    const stock = cropsHere().map((c) => [c, (biz().stock["seedlings:" + c] || 0) / density(c)]).filter(([, m]) => m > 1);
    const open = (biz().open_orders || []).filter((o) => o.item.startsWith("seedlings:"));
    lines.push(`🌱 <b>Seed:</b> ${stock.length ? stock.map(([c, m]) => `${cname(c)} for ${Math.round(m)} m² in stock`).join(", ") : "none in stock"}${open.length ? `; on the way: ${open.map((o) => `${cname(o.item.split(":")[1])} on day ${Math.floor(o.expected_arrival_hour / 24)}`).join(", ")}` : "; none on order"}. Seed takes 10 days.`);
    const cold = ids.filter((c) => (st().settings.climate[c] || {}).heat_day_c < 12);
    if (cold.length) lines.push(`🌡 <b class="warn">Houses ${cold.join(", ")} are heated to only ${st().settings.climate[cold[0]].heat_day_c} °C.</b> The crops want about 20 °C.`);
    const outs = biz().outages || [];
    if (outs.length) lines.push(`⚠ <b>Damage:</b> ${outs.map((o) => o.equipment === "boiler" ? "boiler down" : `${o.panes_broken} panes broken in house ${o.equipment[0]}`).join(", ")}.`);
    const news = (B.news_last_3_days || []).slice(-1)[0];
    if (news) lines.push(`📰 ${news.headline}`);
    return lines;
  }

  function renderSheet() {
    const body = $("#body"); body.innerHTML = "";
    const sec = (title, tag = "") => { const h = document.createElement("h3"); h.innerHTML = `<span>${title}</span><span class="tag">${tag}</span>`; body.appendChild(h); const r = document.createElement("div"); r.className = "row"; body.appendChild(r); return r; };
    const chip = (html, on, fn, cls = "") => { const b = document.createElement("button"); b.className = "chip " + cls + (on ? " on" : ""); b.innerHTML = html; b.onclick = fn; return b; };

    const bf = document.createElement("div"); bf.className = "brief";
    bf.innerHTML = `<div class="note">Day ${day()} · 06:00 · morning briefing</div>` + briefing().map((l) => `<div>${l}</div>`).join("");
    body.appendChild(bf);

    // sell
    const growing = st().batches.filter((b) => b.status !== "harvested" && !b.harvest_queued)
      .sort((a, b) => (est(a).days_to_ready ?? 99) - (est(b).days_to_ready ?? 99)).slice(0, 8);
    const sell = sec("Sell: cut a crop", "sold the same day at this week's price");
    for (const b of growing) {
      const ready = isReady(b), u = est(b).units || 0, on = plan.harvest.has(b.id);
      const left = room(b.crop) - planned(b.crop) + (on ? u : 0);
      const fit = !ready ? `<span class="note">not ready: ${(est(b).days_to_ready ?? 0).toFixed(1)} days to go, sells for little</span>`
        : left >= u ? `<span class="ok">fits this week's demand</span>` : left > 0 ? `<span class="warn">only ${kfmt(left)} of it at full price</span>` : `<span class="bad">this week is full: price crashes</span>`;
      sell.appendChild(chip(`${ready ? "✂️" : "🌱"} House ${houseOf(b)} · ${cname(b.crop)} <span class="note num">${b.id}</span><small>${kfmt(u)} units ≈ ${keur(u * price(b.crop))} · ${fit}</small>`, on,
        () => on ? (plan.harvest.delete(b.id), renderSheet()) : tryAdd(plan.harvest.size ? 0 : 1, () => plan.harvest.add(b.id)), ready ? "" : "dimmed"));
    }
    if (!growing.length) sell.innerHTML = '<span class="note">Nothing growing.</span>';

    // plant
    const free = Object.entries(st().free_area_m2 || {}).filter(([, a]) => a > 1);
    if (free.length) {
      const pl = sec("Grow: sow an empty bench", "uses seed in stock");
      for (const [id, a] of free) {
        const crop = G.compartments[id].crop, have = (biz().stock["seedlings:" + crop] || 0) / density(crop), area = Math.floor(Math.min(a, have) * 10) / 10, on = id in plan.plant;
        pl.appendChild(chip(`🪴 House ${id} · ${cname(crop)}<small>${area >= 1 ? `sow ${Math.round(area)} of ${Math.round(a)} m²` : '<span class="bad">no seed in stock: order it first (10 days)</span>'}</small>`, on,
          () => { if (area < 1) return toast("No seed in stock for this crop. Order it: it takes 10 days.");
            on ? (delete plan.plant[id], renderSheet()) : tryAdd(Object.keys(plan.plant).length ? 0 : 1, () => (plan.plant[id] = area)); }));
      }
    }

    // seed
    const sd = sec("Stock: order seed", `arrives day ${day() + 10}`);
    for (const crop of cropsHere()) {
      const it = R.business.items["seedlings:" + crop];
      for (const m2 of [800, 1600, 3200]) {
        const qty = Math.max(it.min_quantity, Math.ceil(m2 * density(crop))), key = "seedlings:" + crop, on = plan.orders[key] === qty;
        sd.appendChild(chip(`🚚 ${cname(crop)} for ${m2} m²<small>${eur(qty * it.price_eur_per_unit)} · ≈ ${Math.round(m2 / 400)} bench${m2 > 400 ? "es" : ""}</small>`, on,
          () => on ? (delete plan.orders[key], renderSheet()) : tryAdd(Object.keys(orders()).length ? 0 : 1, () => (plan.orders[key] = qty))));
      }
    }

    // climate
    const cold = ids.some((c) => (st().settings.climate[c] || {}).heat_day_c < 12);
    const cl = sec("Climate", cold ? '<span class="warn">houses are cold</span>' : "currently " + (st().settings.climate[ids[0]] || {}).heat_day_c + " °C by day");
    cl.appendChild(chip(`🌡 Growing climate, all houses<small>crop targets day and night, CO₂ · uses 2 actions</small>`, plan.climate,
      () => plan.climate ? (plan.climate = false, renderSheet()) : tryAdd(2, () => (plan.climate = true)), "wide"));
    if (plan.climate) cl.appendChild(chip(`💡 Grow lamps ${lampsOn ? "ON" : "OFF"}<small>06:00-18:00 · faster growth, costs power</small>`, false, () => { lampsOn = !lampsOn; renderSheet(); }, "wide"));

    // repairs
    const outs = biz().outages || [];
    if (outs.length) {
      const rp = sec("Repair", "contractor comes once the parts are on site");
      for (const o of outs) {
        const booked = (biz().contractor_bookings || []).some((b) => b.target === o.equipment), on = plan.repairs.some((r) => r.target === o.equipment);
        const trade = Object.entries(R.business.contractors || {}).find(([, s]) => (s.fixes || []).some((x) => o.equipment.endsWith(x)));
        rp.appendChild(chip(`🔧 ${o.equipment === "boiler" ? "Boiler" : "Glass, house " + o.equipment[0]}${o.panes_broken ? ` (${o.panes_broken} panes)` : ""}<small>${booked ? "already booked" : "book " + (trade ? trade[0].replace("_", " ") : "contractor") + " + order parts"}</small>`, on,
          () => { if (booked) return toast("Already booked: it comes when the parts are on site.");
            on ? (plan.repairs = plan.repairs.filter((r) => r.target !== o.equipment), renderSheet())
               : tryAdd(1 + (Object.keys(orders()).length ? 0 : 1), () => plan.repairs.push({ target: o.equipment, trade: trade && trade[0], parts: o.parts_needed || {} })); }));
      }
    }

    // crew
    const sf = biz().staff, tq = biz().task_queue || [];
    const cr = sec("Crew", `${sf.crew} workers, ${sf.shift}${tq.length ? ` · ${tq.length} jobs waiting` : ""}`);
    cr.appendChild(chip(`👷 Hire a worker<small>starts in 3 days · €400 + wages</small>`, plan.hire > 0,
      () => plan.hire ? (plan.hire = 0, renderSheet()) : tryAdd(1, () => (plan.hire = 1)), "wide"));

    // market picture with what is planned
    const mk = sec("Buyers this week", "rolling 7 days; above demand the price falls to 0 at 1.25x");
    const grid = document.createElement("div"); grid.className = "mk"; mk.appendChild(grid);
    for (const crop of cropsHere()) {
      const dm = demand(crop, hour()), sold = units((biz().sold_last_7_days || {})[crop]), pl = planned(crop), cap = dm * 1.3;
      const w = (v) => Math.max(0, Math.min(100, (v / cap) * 100));
      grid.insertAdjacentHTML("beforeend", `<span>${cname(crop)}</span><div><div class="bar">
        <i style="left:0;width:${w(Math.min(sold, cap))}%;background:#6b7aa6"></i>
        <i style="left:${w(sold)}%;width:${w(Math.min(pl, cap - sold))}%;background:${sold + pl > dm ? "var(--bad)" : "var(--acc)"}"></i>
        <i style="left:${w(dm)}%;width:2px;background:var(--ink)"></i></div>
        <span class="note">sold ${kfmt(sold)} · today ${kfmt(pl)} · demand ${kfmt(dm)}</span></div>`);
    }
    planBar();
  }
  function planBar() {
    const a = actions(), n = count();
    $("#plan").innerHTML = n ? `<b>${n} / ${limit()}</b> · ${a.map(describe).join(" · ")}` : `<b>0 / ${limit()}</b> actions · tap cards to plan your morning`;
    $("#go").textContent = n ? "Start the day ▶" : "Do nothing ▶";
  }

  function actions() {
    const a = [];
    if (plan.climate) {
      const mid = (r, d) => (Array.isArray(r) ? (r[0] + r[1]) / 2 : r ?? d);
      const ts = ids.map((id) => (G.crops[G.compartments[id].crop] || {}).climate_targets || {});
      const avg = (k, d) => Math.round(ts.reduce((s, t) => s + mid(t[k], d), 0) / ts.length * 10) / 10;
      a.push({ tool: "set_climate", heat_day_c: avg("day_temp_c", 20), heat_night_c: avg("night_temp_c", 17), co2_ppm: avg("co2_ppm", 900),
               lamp_hours: lampsOn ? [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17] : [], lamp_intensity_pct: lampsOn ? 100 : 0 });
      a.push({ tool: "set_night_schedule", from_hour: 18, copy_day: true });
    }
    for (const r of plan.repairs) a.push({ tool: "book_contractor", target: r.target, trade: r.trade });
    if (plan.harvest.size) a.push({ tool: "harvest", batch_ids: [...plan.harvest] });
    if (Object.keys(plan.plant).length) a.push({ tool: "plant", areas_m2: plan.plant });
    const o = orders(); if (Object.keys(o).length) a.push({ tool: "place_orders", orders: o });
    if (plan.hire) a.push({ tool: "hire", workers: plan.hire });
    return a.slice(0, limit());
  }
  function describe(a) {
    const t = a.tool;
    if (t === "harvest") return "cut " + (a.batch_ids || []).join(", ");
    if (t === "plant") return "sow " + Object.entries(a.areas_m2 || {}).map(([k, v]) => `${k} ${Math.round(v)} m²`).join(", ");
    if (t === "place_orders" || t === "place_order") { const o = a.orders || Object.fromEntries((a.order_list || []).map((x) => [x.item, x.quantity])) || {};
      return "order " + Object.entries(o).map(([k, v]) => `${k.split(":").pop().split("_")[0]} ${kfmt(v)}`).join(", "); }
    if (t === "book_contractor") return `book ${String(a.trade || "").replace("_", " ")} for ${a.target}`;
    if (t === "set_climate") return `climate ${a.heat_day_c ?? "–"}/${a.heat_night_c ?? "–"} °C${a.co2_ppm != null ? ", CO₂ " + a.co2_ppm : ""}`;
    if (t === "set_night_schedule") return `night settings from ${a.from_hour}:00`;
    if (t === "set_energy") return "energy settings";
    if (t === "hire") return `hire ${a.workers}`;
    return t.replace("_", " ");
  }
  function refusals(res) {
    return (res || []).flatMap((x) => (!x.ok ? [`${x.tool}: ${String(x.error || "").slice(0, 100)}`] :
      Object.entries((x.result || {}).refused || {}).map(([k, v]) => `${x.tool} ${k}: ${String(typeof v === "string" ? v : JSON.stringify(v)).slice(0, 100)}`)));
  }

  $("#bHint").onclick = () => {
    if (phase !== "morning") return;
    const ready = st().batches.filter((b) => isReady(b) && !b.harvest_queued && room(b.crop) > 0.3 * (est(b).units || 0));
    const cold = ids.some((c) => (st().settings.climate[c] || {}).heat_day_c < 12);
    const free = Object.entries(st().free_area_m2 || {}).filter(([c, a]) => a > 50 && (biz().stock["seedlings:" + G.compartments[c].crop] || 0) > density(G.compartments[c].crop) * 50);
    const soon = cropsHere().filter((c) => st().batches.some((b) => b.crop === c && b.status !== "harvested" && (est(b).days_to_ready ?? 99) <= 10)
      && !(biz().stock["seedlings:" + c] > 0) && !(biz().open_orders || []).some((o) => o.item === "seedlings:" + c));
    const tip = cold ? "The houses are far too cold for the crops. Climate first."
      : ready.length ? `Something is ready and buyers still want it this week: ${ready.map((b) => b.id).join(", ")}.`
      : free.length ? "You have empty benches and seed to sow them."
      : soon.length ? `Benches will free up within 10 days, and no ${soon.map(cname).join("/")} seed is coming. Seed takes 10 days.`
      : "Nothing urgent. Check what next week's buyers want before you cut.";
    toast("💡 " + tip, 6000);
  };

  // ---------------- the day ----------------
  $("#go").onclick = async () => {
    if (!G || phase !== "morning") return;
    const acts = actions();
    $("#go").disabled = true; $("#go").innerHTML = '<span class="spin"></span> running';
    let r;
    try { r = await post("/api/challenge/day", { id: G.id, actions: acts }); }
    catch (e) { toast('<span class="bad">' + e.message + "</span>"); $("#go").disabled = false; planBar(); return; }
    phase = "day"; result = r;
    addFrames(r.frames || []);
    const rf = refusals(r.results);
    $("#toast").style.display = "none";
    if (rf.length) toast(rf.map((x) => `<div class="bad">✗ ${x}</div>`).join(""), 7000);
    G.alarmList = r.alarms || [];
    target = r.frames && r.frames.length ? r.frames[r.frames.length - 1].h : target;
    playing = true; sheet(false); $("#skip").style.display = "block";
    pollReport();
  };
  $("#skip").onclick = () => { hf = target - 0.01; };
  async function pollReport() {
    while (!final) {
      try { const r = await fetch(`/api/challenge/report?id=${G.id}`).then((x) => x.json()); if (r.error) throw new Error(r.error); if (r.ready) final = r.final; }
      catch (e) { final = { error: e.message }; }
      if (!final) await new Promise((s) => setTimeout(s, 900));
    }
    if (phase === "waiting") showReport();
  }
  function bubbles(prev, f) {
    if (!prev) return;
    const before = Object.fromEntries(prev.b.map((b) => [b.id, b.st]));
    const dRev = f.money.harvest_revenue_eur - prev.money.harvest_revenue_eur;
    for (const b of f.b) if (b.st === "harvested" && before[b.id] && before[b.id] !== "harvested")
      scene.bubble(b.c, `✂ ${b.id} cut`, "#f4c24f");
    if (dRev > 1) { const h = (f.b.find((b) => b.st === "harvested" && before[b.id] !== "harvested") || {}).c || ids[0]; scene.bubble(h, `+${keur(dRev)} sold`, "#7bd88f"); }
    for (const a of (G.alarmList || []).filter((x) => x.h === f.h)) scene.bubble("energy", a.kind === "storm" ? "⛈ storm: glass broken" : a.text.slice(0, 34), "#ff6b5b");
  }

  // ---------------- HUD and loop ----------------
  function hud() {
    const h = Math.min(Math.floor(hf), F.length - 1), f = F[h];
    if (!f) return;
    const hh = String(h % 24).padStart(2, "0"), dark = h % 24 < 7 || h % 24 >= 17;
    $("#clock").innerHTML = `<div class="t">${viewing === "model" ? "🤖 " : ""}Day ${Math.floor(h / 24)} · <span class="num">${hh}:00</span> ${dark ? "🌙" : "☀️"}</div><div class="s">${f.out.t.toFixed(1)} °C outside · wind ${f.out.wind.toFixed(0)} m/s</div>`;
    $("#money").innerHTML = `<div class="v num">${eur(f.money.profit_so_far_eur)}</div><div class="s">${viewing === "model" ? (G ? G.model + "'s" : "AI's") + " day" : "profit so far"}</div>`;
    const al = [];
    if ((f.faults || []).length) al.push(`<span class="bad">⚠ ${f.faults.map((x) => (x === "boiler" ? "boiler down" : "glass " + x[0])).join(", ")}</span>`);
    $("#alerts").innerHTML = al.map((x) => `<div>${x}</div>`).join("");
  }
  function loop(now) {
    const dt = Math.min(0.1, (now - (last || now)) / 1000); last = now;
    if (F.length && ids.length) {
      if (playing) {
        const hod = hf % 24; hf = Math.min(target, hf + dt * (hod >= 6 && hod < 18 ? DAY_RATE : NIGHT_RATE));
        if (hf >= target) { playing = false; $("#skip").style.display = "none"; afterDay(); }
      }
      const h = Math.floor(hf);
      if (h !== lastH) { if (h === lastH + 1) bubbles(F[lastH], F[h]); lastH = h; hud(); }
      const f = F[Math.min(h, F.length - 1)];
      if (f) scene.render(f, hf, dt, playing ? DAY_RATE / 2 : 0.2);
    }
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
  function afterDay() {
    if (viewing === "model") { viewing = "you"; restoreYou(); return showReport(); }
    phase = "waiting";
    if (final) return showReport();
    $("#endbox").innerHTML = `<h2>Day done</h2><p><span class="spin"></span> Now replaying ${G.model}'s own morning from the same state and checking both for mistakes…</p>`;
    $("#end").style.display = "flex";
  }

  // ---------------- the report ----------------
  function showReport() {
    phase = "report";
    if (final.error) { $("#endbox").innerHTML = `<h2 class="bad">Could not compare</h2><p>${final.error}</p><button onclick="location.reload()">Start again</button>`; $("#end").style.display = "flex"; return; }
    const you = final.you, m = final.model, name = final.challenge.model;
    const pname = { constraints: "Missing interacting constraints", revising: "Not revising after new information",
                    tracking: "Losing track of unfinished work", mechanics: "Action mechanics" };
    const nY = you.failures.length, nM = m.failures.length;
    const head = nY === 0 && nM === 0 ? "A clean morning, for both of you" : nY === 0 ? `Clean morning. ${name} slipped ${nM}×.`
      : nY < nM ? `${nY} slip${nY > 1 ? "s" : ""}, ${name} made ${nM}` : nY === nM ? `${nY} slip${nY > 1 ? "s" : ""} each` : `${nY} slip${nY > 1 ? "s" : ""}. ${name} made ${nM || "none"}.`;
    const col = nY === 0 ? "ok" : nY <= nM ? "warn" : "bad";
    const cell = (arr, cls) => arr.length ? arr.map((x) => `<div class="${cls}">${typeof x === "string" ? x : x.text}</div>`).join("") : '<div class="note">none</div>';
    const groups = Object.keys(pname).filter((g) => you.failures.some((x) => x.pattern === g) || m.failures.some((x) => x.pattern === g));
    const failHtml = groups.map((g) => `<div class="pat"><div class="pn">${pname[g]}</div><div class="two">
        <div><div class="who">You</div>${cell(you.failures.filter((x) => x.pattern === g), "fl")}</div>
        <div><div class="who">${name}</div>${cell(m.failures.filter((x) => x.pattern === g), "fl")}</div></div></div>`).join("");
    const goodHtml = (you.good.length || m.good.length) ? `<div class="pat"><div class="pn ok">Good calls</div><div class="two">
        <div><div class="who">You</div>${cell(you.good, "gd")}</div><div><div class="who">${name}</div>${cell(m.good, "gd")}</div></div></div>` : "";
    const diff = you.profit - m.profit;
    const list = (acts) => acts && acts.length ? acts.map((a) => `<div>· ${describe(a)}</div>`).join("") : '<div class="note">· nothing</div>';
    $("#endbox").innerHTML = `<h2 class="${col}">${head}</h2>
      <p class="note">${final.challenge.title} · day ${final.challenge.day} · same briefing, same 5 actions, same simulator as ${name}.</p>
      <table><tr><td></td><td class="note">today's profit</td></tr>
        <tr class="you"><td>You</td><td class="num">${eur(you.day_profit)}</td></tr><tr><td>${name}</td><td class="num">${eur(m.day_profit)}</td></tr></table>
      ${goodHtml}${failHtml || '<p class="note">Neither morning tripped a failure check.</p>'}
      <h4>If the season went on</h4>
      <p class="note">The reference planner finished the season after your morning and after ${name}'s: your morning is worth
        <b class="${Math.abs(diff) < 500 ? "" : diff > 0 ? "ok" : "bad"}">${Math.abs(diff) < 500 ? "about the same" : eur(Math.abs(diff)) + (diff > 0 ? " more" : " less")}</b> (benchmark score <span class="num">${(you.score ?? 0).toFixed(3)}</span> vs <span class="num">${(m.score ?? 0).toFixed(3)}</span>).
        ${name}'s whole real run scored <span class="num">${(final.model_real.score ?? 0).toFixed(3)}</span>; the planner's own season <span class="num">0.800</span>.</p>
      <div class="two"><div><h4>You did</h4>${list(you.days[0].actions)}</div><div><h4>${name} did</h4>${list(m.days[0].actions)}</div></div>
      <div class="row" style="margin-top:14px"><button class="primary" onclick="location.reload()">Play another morning</button>
        <button id="watchAI">🤖 Watch ${name}'s day</button><button id="share">Share</button></div>`;
    $("#end").style.display = "flex";
    $("#watchAI").onclick = watchModel;
    $("#share").onclick = async () => {
      const txt = `Lettuce Bench, "${final.challenge.title}": I made ${nY} mistake${nY === 1 ? "" : "s"}, ${name} made ${nM}. Season score ${(you.score ?? 0).toFixed(3)} vs ${(m.score ?? 0).toFixed(3)}.`;
      try { if (navigator.share) await navigator.share({ text: txt, url: location.href }); else { await navigator.clipboard.writeText(txt + " " + location.href); toast("Copied"); } } catch (e) { /* dismissed */ }
    };
  }
  let youFrames = null;
  function watchModel() {
    if (!final.model_frames || !final.model_frames.length) return toast("No frames for the AI's day.");
    $("#end").style.display = "none";
    youFrames = final.model_frames.map((f) => F[f.h]);
    for (const f of final.model_frames) F[f.h] = f;
    viewing = "model"; scene.reset();
    hf = final.model_frames[0].h - 1; lastH = Math.floor(hf); target = final.model_frames[final.model_frames.length - 1].h;
    G.alarmList = []; playing = true; $("#skip").style.display = "block";
    toast(`🤖 ${final.challenge.model}'s day: ${final.model.days[0].actions.map(describe).join(" · ") || "it did nothing"}`, 6000);
  }
  function restoreYou() { if (youFrames) youFrames.forEach((f) => f && (F[f.h] = f)); hf = target; lastH = -1; }

  // ---------------- camera, zoom, pinch ----------------
  let camOn = false;
  $("#bAR").onclick = async () => {
    const v = $("#cam");
    if (camOn) { v.srcObject && v.srcObject.getTracks().forEach((t) => t.stop()); v.style.display = "none"; camOn = false; scene.settings({ see: false }); return; }
    try { v.srcObject = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
      v.style.display = "block"; camOn = true; scene.settings({ see: true }); toast("The greenhouse is now standing in your room.", 2500); }
    catch (e) { toast("The camera needs the https link and your permission.", 5000); }
  };
  $("#bZin").onclick = () => { zoom = scene.settings({ zoom: zoom * 1.2 }).zoom; };
  $("#bZout").onclick = () => { zoom = scene.settings({ zoom: zoom / 1.2 }).zoom; };
  let pinch = null;
  const cv = $("#cv");
  cv.addEventListener("touchstart", (e) => { if (e.touches.length === 2) pinch = { d: Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY), z: zoom }; }, { passive: true });
  cv.addEventListener("touchmove", (e) => { if (pinch && e.touches.length === 2) { const d = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY); zoom = scene.settings({ zoom: pinch.z * d / pinch.d }).zoom; } }, { passive: true });
  cv.addEventListener("touchend", () => (pinch = null), { passive: true });
  $("#grab").onclick = () => phase === "morning" && sheet($("#sheet").classList.contains("min"));
})();
