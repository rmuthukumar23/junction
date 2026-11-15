// "Beat the AI": the phone demo for peer review. AR first: the greenhouse stands over the camera
// image and tilting the phone walks around it. Two mornings, three big choices each (heat, harvest,
// order seed), each mapped to the real submit_day actions the AI models used. Afterwards: how you did
// against the 7 recorded AI runs on the same seed. Same server endpoints as play.html (the full
// version): /api/challenges, /api/challenge/start, /api/challenge/day, /api/challenge/report.
(() => {
  const $ = (s) => document.querySelector(s);
  const eur = (v) => (v < 0 ? "−" : "") + "€" + Math.round(Math.abs(v)).toLocaleString("en-US");
  const kfmt = (v) => (v >= 1e3 ? (v / 1e3).toFixed(1) + "k" : Math.round(v));
  const DAY_RATE = 2.6, NIGHT_RATE = 16;
  const SEED_M2 = 1600;                       // "order seed" = seed for 1600 m² of each crop (about 4 benches)

  let G = null, R = null, B = null, F = [], ids = [], final = null, last = 0, lastH = -1, hf = 0, target = 0;
  let playing = false, phase = "intro", dayNo = 1, result = null, zoom = 0.95, camOn = false, wantCam = true;
  let pick = { heat: false, cut: false, seed: false };
  const scene = makeScene({ pix: 2, zoom, transparent: true });
  scene.init($("#cv"));
  const meta = { compartments: {}, maxW: {}, snowAt: [], shift: [7, 15], maxLamp: {}, maxHeat: {}, maxBuffer: 1,
                 maxCO2: 1, maxHeatAll: 1, maxHD: 1, targets: {}, deliveries: [] };
  const toast = (html, ms = 3500) => { const t = $("#toast"); t.innerHTML = html; t.style.display = "block"; clearTimeout(t._h); t._h = setTimeout(() => (t.style.display = "none"), ms); };
  const post = async (path, body) => { const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json(); if (!r.ok) throw new Error(j.error || r.statusText); return j; };

  // ---------------- start: camera and motion need a tap, so both are asked for on Start ----------------
  let challenge = null;
  fetch("/api/challenges").then((r) => r.json()).then((d) => { challenge = d.challenges[0]; const b = $("#start"); b.disabled = false; b.textContent = "Start ▶"; })
    .catch(() => ($("#start").textContent = "Can't reach the game server"));
  $("#noCam").onclick = (e) => { e.preventDefault(); wantCam = false; $("#start").click(); };
  $("#start").onclick = async () => {
    if (!challenge) return;
    const b = $("#start"); b.disabled = true; b.innerHTML = '<span class="spin"></span> opening the greenhouse…';
    const motion = wantCam ? askMotion() : Promise.resolve(false);           // must start inside the tap on iOS
    const cam = wantCam ? openCam() : Promise.resolve(false);
    try { G = await post("/api/challenge/start", { challenge: challenge.id }); }
    catch (e) { b.disabled = false; b.textContent = "Try again: " + e.message; return; }
    R = G.rules; B = G.briefing; ids = Object.keys(G.compartments).sort();
    meta.compartments = G.compartments;
    for (const id of ids) { const ct = (G.crops[G.compartments[id].crop] || {}).climate_targets || {}; const mid = (r) => (Array.isArray(r) ? (r[0] + r[1]) / 2 : r);
      meta.targets[id] = { day: mid(ct.day_temp_c), night: mid(ct.night_temp_c || ct.day_temp_c), rh: mid(ct.rh_pct) }; }
    addFrames(G.frames); for (let h = 0; h < G.first_hour; h++) F[h] = { ...G.frames[0], h };
    hf = target = G.frames[G.frames.length - 1].h; lastH = Math.floor(hf);
    scene.setData(meta);
    $("#intro").style.display = "none"; $("#money").style.display = "block"; $("#rail").style.display = "flex"; $("#mini").style.display = "flex";
    if (await motion) startTilt();
    await cam;
    morning();
  };
  async function openCam() {
    try { const v = $("#cam"); v.srcObject = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
      v.style.display = "block"; camOn = true; scene.settings({ see: true }); return true; }
    catch (e) { camOn = false; scene.settings({ see: false }); return false; }
  }
  function askMotion() {
    try { if (typeof DeviceOrientationEvent !== "undefined" && DeviceOrientationEvent.requestPermission)
      return DeviceOrientationEvent.requestPermission().then((p) => p === "granted").catch(() => false); }
    catch (e) { return Promise.resolve(false); }
    return Promise.resolve(typeof DeviceOrientationEvent !== "undefined");
  }
  function startTilt() {
    let base = null;
    window.addEventListener("deviceorientation", (e) => {
      if (e.gamma == null) return;
      if (!base) base = { g: e.gamma, b: e.beta, v: scene.settings({}) };
      scene.settings({ az: base.v.az - (e.gamma - base.g) * 0.035, el: base.v.el + (e.beta - base.b) * 0.018 });
    });
  }
  $("#bCam").onclick = async () => { if (camOn) { const v = $("#cam"); v.srcObject && v.srcObject.getTracks().forEach((t) => t.stop()); v.style.display = "none"; camOn = false; scene.settings({ see: false }); }
    else if (!(await openCam())) toast("The camera needs the https link and your permission (aA → Website Settings → Camera)."); };
  $("#bZin").onclick = () => { zoom = scene.settings({ zoom: zoom * 1.2 }).zoom; };
  $("#bZout").onclick = () => { zoom = scene.settings({ zoom: zoom / 1.2 }).zoom; };

  function addFrames(frames) {
    for (const f of frames) {
      F[f.h] = f;
      for (const b of f.b) if (b.st !== "harvested") meta.maxW[b.crop] = Math.max(meta.maxW[b.crop] || 1e-6, b.w);
      for (const id of Object.keys(f.c)) { meta.maxLamp[id] = Math.max(meta.maxLamp[id] || 1e-6, f.c[id].lamp); meta.maxHeat[id] = Math.max(meta.maxHeat[id] || 1e-6, f.c[id].heat); }
      meta.maxBuffer = Math.max(meta.maxBuffer, f.ec.buffer); meta.maxCO2 = Math.max(meta.maxCO2, f.ec.co2); meta.maxHeatAll = Math.max(meta.maxHeatAll, f.ec.heat);
      meta.snowAt[f.h] = 0;
    }
  }

  // ---------------- the morning: three choices ----------------
  const st = () => B.status, biz = () => B.status.business;
  const est = (b) => b.estimate || {};
  const ready = () => st().batches.filter((b) => !b.harvest_queued && (b.status === "ready" || (b.status === "growing" && (est(b).days_to_ready ?? 9) <= 0.05)));
  const cold = () => ids.some((c) => (st().settings.climate[c] || {}).heat_day_c < 12);
  const crops = () => [...new Set(ids.map((id) => G.compartments[id].crop))];
  const density = (crop) => ((G.crops[crop] || {}).planting || {}).density_per_m2 || 1;
  const price = (crop) => R.business.crop_prices_eur_per_unit[crop] || 0;
  const seedComing = () => (biz().open_orders || []).some((o) => o.item.startsWith("seedlings:"));

  function morning() {
    phase = "morning"; pick = { heat: false, cut: false, seed: false }; $("#rail").style.opacity = "1";
    const r = ready(), val = r.reduce((s, b) => s + (est(b).units || 0) * price(b.crop), 0);
    const bits = [];
    bits.push(cold() ? `🥶 The houses are at <b>${st().settings.climate[ids[0]].heat_day_c} °C</b>; the crops want ~20 °C.` : "🌡️ The houses are warm.");
    bits.push(r.length ? `✂️ <b>${r.length} crop${r.length > 1 ? "s" : ""} ready</b>, worth about <b>${eur(val)}</b>.` : "🌱 Nothing is ready to harvest yet.");
    bits.push(seedComing() ? "🚚 Seed is on the way." : "📦 No seed on order, and it takes <b>10 days</b> to arrive.");
    const news = (B.news_last_3_days || []).slice(-1)[0]; if (news) bits.push("📰 " + news.headline);
    $("#tip").innerHTML = `<b>Morning ${dayNo} of 2</b> · ${bits.join(" ")}<div class="small" style="margin-top:4px">Tap the choices on the right, then GO.</div>`;
    $("#tip").style.display = "block";
    $("#aCut").classList.toggle("off", !r.length);
    paint(); $("#go").disabled = false;
  }
  function paint() { for (const [k, id] of [["heat", "#aHeat"], ["cut", "#aCut"], ["seed", "#aSeed"]]) $(id).classList.toggle("on", pick[k]); }
  $("#aHeat").onclick = () => { if (phase !== "morning") return; pick.heat = !pick.heat; paint(); if (pick.heat) toast("🌡️ Heat all three houses to the crops' targets, day and night."); };
  $("#aCut").onclick = () => { if (phase !== "morning") return; if (!ready().length) return toast("Nothing is ready to harvest yet."); pick.cut = !pick.cut; paint();
    if (pick.cut) toast(`✂️ Harvest ${ready().map((b) => b.id).join(", ")} and sell it today.`); };
  $("#aSeed").onclick = () => { if (phase !== "morning") return; pick.seed = !pick.seed; paint(); if (pick.seed) toast("🌱 Order seed for about 8 benches. It arrives in 10 days."); };

  function actions() {
    const a = [];
    if (pick.heat) {
      const ts = ids.map((id) => (G.crops[G.compartments[id].crop] || {}).climate_targets || {}), mid = (r, d) => (Array.isArray(r) ? (r[0] + r[1]) / 2 : r ?? d);
      const avg = (k, d) => Math.round(ts.reduce((s, t) => s + mid(t[k], d), 0) / ts.length * 10) / 10;
      a.push({ tool: "set_climate", heat_day_c: avg("day_temp_c", 20), heat_night_c: avg("night_temp_c", 17), co2_ppm: avg("co2_ppm", 900),
               lamp_hours: [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17], lamp_intensity_pct: 100 });
      a.push({ tool: "set_night_schedule", from_hour: 18, copy_day: true });
    }
    if (pick.cut && ready().length) a.push({ tool: "harvest", batch_ids: ready().map((b) => b.id) });
    if (pick.seed) {
      const orders = {};
      for (const c of crops()) { const it = R.business.items["seedlings:" + c]; orders["seedlings:" + c] = Math.max(it.min_quantity, Math.ceil(SEED_M2 * density(c))); }
      a.push({ tool: "place_orders", orders });
    }
    return a;
  }

  // ---------------- the day ----------------
  $("#go").onclick = async () => {
    if (phase !== "morning") return;
    $("#go").disabled = true; $("#go").innerHTML = '<span class="spin"></span>';
    let r;
    try { r = await post("/api/challenge/day", { id: G.id, actions: actions() }); }
    catch (e) { toast(`<span class="bad">${e.message}</span>`, 6000); $("#go").disabled = false; $("#go").textContent = "GO ▶"; return; }
    $("#go").textContent = "GO ▶";
    result = r; phase = "day"; $("#tip").style.display = "none";
    pick = { heat: false, cut: false, seed: false }; paint(); $("#rail").style.opacity = ".35";
    addFrames(r.frames || []); G.alarms = r.alarms || [];
    target = r.frames.length ? r.frames[r.frames.length - 1].h : target; playing = true;
    toast(`Day ${dayNo}: watch it play out ☀️`, 2000);
    if (r.day >= r.days_to_play) pollReport();
  };
  function bubbles(prev, f) {
    if (!prev) return;
    const before = Object.fromEntries(prev.b.map((b) => [b.id, b.st]));
    const cut = f.b.filter((b) => b.st === "harvested" && before[b.id] && before[b.id] !== "harvested");
    const dRev = f.money.harvest_revenue_eur - prev.money.harvest_revenue_eur;
    if (dRev > 1) scene.bubble((cut[0] || {}).c || ids[0], `+${eur(dRev)} sold`, "#7bd88f");
    for (const a of (G.alarms || []).filter((x) => x.h === f.h)) scene.bubble("energy", a.kind === "storm" ? "⛈ storm! glass broken" : a.text.slice(0, 30), "#ff6b5b");
    const hod = f.h % 24;
    if (hod === 18 && f.c[ids[0]]) { const t = ids.map((c) => f.c[c].t); scene.bubble(ids[1] || ids[0], `${Math.min(...t).toFixed(0)}–${Math.max(...t).toFixed(0)} °C inside`, Math.min(...t) < 12 ? "#6cc4ff" : "#7bd88f"); }
  }
  function hud() {
    const h = Math.min(Math.floor(hf), F.length - 1), f = F[h]; if (!f) return;
    const hod = h % 24, sun = hod >= 8 && hod < 17;
    $("#clock").innerHTML = `<b>Day ${dayNo} · ${String(hod).padStart(2, "0")}:00 ${sun ? "☀️" : "🌙"}</b><div class="s">${f.out.t.toFixed(0)} °C outside${(f.faults || []).length ? ' · <span class="bad">⚠ damage</span>' : ""}</div>`;
    $("#money").innerHTML = `<b>${eur(f.money.profit_so_far_eur)}</b><div class="s">profit</div>`;
  }
  function loop(now) {
    const dt = Math.min(0.1, (now - (last || now)) / 1000); last = now;
    if (F.length && ids.length) {
      if (playing) { const hod = hf % 24; hf = Math.min(target, hf + dt * (hod >= 6 && hod < 18 ? DAY_RATE : NIGHT_RATE)); if (hf >= target) { playing = false; afterDay(); } }
      const h = Math.floor(hf);
      if (h !== lastH) { if (h === lastH + 1) bubbles(F[lastH], F[h]); lastH = h; hud(); }
      const f = F[Math.min(h, F.length - 1)]; if (f) scene.render(f, hf, dt, playing ? DAY_RATE / 2 : 0.2);
    }
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
  function afterDay() {
    if (result.day < result.days_to_play) { B = result.briefing; dayNo = result.day + 1; morning(); return; }
    phase = "waiting"; $("#rail").style.display = "none";
    if (final) return report();
    $("#endcard").innerHTML = `<h2>Done!</h2><p><span class="spin"></span> Comparing you with the 7 AI runs…</p>`; $("#end").style.display = "flex";
  }
  async function pollReport() {
    while (!final) {
      try { const r = await fetch(`/api/challenge/report?id=${G.id}`).then((x) => x.json()); if (r.error) throw new Error(r.error); if (r.ready) final = r.final; }
      catch (e) { final = { error: e.message }; }
      if (!final) await new Promise((s) => setTimeout(s, 900));
    }
    if (phase === "waiting") report();
  }

  // ---------------- the result ----------------
  function report() {
    phase = "report";
    if (final.error) { $("#endcard").innerHTML = `<h2 class="bad">Something went wrong</h2><p>${final.error}</p><button class="big" onclick="location.reload()">Play again</button>`; $("#end").style.display = "flex"; return; }
    const you = final.you, ais = final.ais.filter((a) => a.kind === "model"), planner = final.ais.find((a) => a.kind === "planner");
    const all = [you, ...final.ais].sort((a, b) => b.checks_passed - a.checks_passed || b.two_day_profit - a.two_day_profit);
    const place = all.indexOf(you) + 1, beat = ais.filter((a) => all.indexOf(a) > all.indexOf(you)).length;
    const head = beat === ais.length ? "🏆 You beat every AI!" : beat > 0 ? `🎉 You beat ${beat} of ${ais.length} AI runs` : "🤖 The AIs win this time";
    const slips = you.failures.slice(0, 2).map((x) => `<p class="bad">✗ ${x.text}</p>`).join("");
    const aiSlip = ais.flatMap((a) => a.failures.map((x) => `${a.name}: ${x.text}`))[0];
    const name = (e) => e.kind === "you" ? "You" : e.kind === "planner" ? "Scripted planner" : e.name.replace("Claude ", "").replace("Gemini 4 Hydrogen", "Gemini");
    const rows = all.map((e, i) => `<div class="${e.kind === "you" ? "you" : ""}"><span>${i + 1}. ${name(e)}</span><span>${e.checks_passed}/${e.checks_total} ✓</span></div>`).join("");
    $("#endcard").innerHTML = `<h2>${head}</h2>
      <p>You passed <b>${you.checks_passed} of ${you.checks_total}</b> good-grower checks and finished <b>#${place} of ${all.length}</b>.</p>
      ${slips || '<p class="ok">✓ No mistakes in your two mornings.</p>'}
      <div class="rank">${rows}</div>
      ${aiSlip ? `<p class="small">An AI slip from the same morning: ${aiSlip}</p>` : ""}
      <p class="small">The AIs played the full 42-day season in our benchmark, LettuceBench; here you both played its first two days. Ties are broken by profit over the two days.</p>
      <button class="big" onclick="location.reload()">Play again</button>`;
    $("#end").style.display = "flex";
  }
})();
