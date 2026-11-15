// "Beat the AI": the phone demo for peer review. AR first: the greenhouse stands in the room over the
// camera image, anchored by the phone's own orientation (pitch and roll from gravity, heading from the
// first reading), so turning or tilting the phone looks around it. Two mornings, three choices each
// (heat, harvest, order seed), each mapped to the real submit_day actions the AI models used; then how
// you did against the 7 recorded AI runs on the same morning.
// Two data sources: the live server (scripts/viz/server.py, /api/challenge/*), or, when the page sets
// window.STATIC_DATA, the files scripts/build_phone_demo.py precomputed for every one of the 64 plans,
// so the page runs from a static host on any device.
(() => {
  const $ = (s) => document.querySelector(s);
  const eur = (v) => (v < 0 ? "−" : "") + "€" + Math.round(Math.abs(v)).toLocaleString("en-US");
  const DAY_RATE = 2.6, NIGHT_RATE = 16, STATIC = window.STATIC_DATA || null;
  const store = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } } };

  let G = null, M = null, F = [], ids = [], final = null, last = 0, lastH = -1, hf = 0, target = 0, codes = [];
  let playing = false, phase = "intro", dayNo = 1, zoom = 0.95, arDist = 1, camOn = false, arOn = false, wantCam = true, aiList = null, pendingDay = null;
  let pick = { heat: false, cut: false, seed: false };
  const scene = makeScene({ pix: 2, zoom, transparent: true });
  scene.init($("#cv"));
  const meta = { compartments: {}, maxW: {}, snowAt: [], shift: [7, 15], maxLamp: {}, maxHeat: {}, maxBuffer: 1,
                 maxCO2: 1, maxHeatAll: 1, maxHD: 1, targets: {}, deliveries: [] };
  const toast = (html, ms = 3500) => { const t = $("#toast"); t.innerHTML = html; t.style.display = "block"; clearTimeout(t._h); t._h = setTimeout(() => (t.style.display = "none"), ms); };
  const getJSON = async (url) => { const r = await fetch(url); if (!r.ok) throw new Error(r.status + " " + url); return r.json(); };
  const post = async (path, body) => { const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json(); if (!r.ok) throw new Error(j.error || r.statusText); return j; };

  // ---------------- data: live server or precomputed files ----------------
  const api = STATIC ? {
    ready: () => Promise.resolve(true),
    async start() { const d = await getJSON(STATIC + "start.json"); aiList = d.ai; return d; },
    async day(code) { codes.push(code); return getJSON(STATIC + (codes.length === 1 ? `d1_${codes[0]}.json` : `d2_${codes[0]}${codes[1]}.json`)); },
    async report(d2) { return { you: d2.you, ais: aiList }; },
  } : {
    ready: () => getJSON("/api/challenges").then((d) => (api._ch = d.challenges[0])),
    async start() { const g = await post("/api/challenge/start", { challenge: api._ch.id }); api._g = g;
      return { frames: g.frames, first_hour: g.first_hour, compartments: g.compartments, crops: g.crops, morning: summary(g.briefing, g.rules) }; },
    async day(code) { const r = await post("/api/challenge/day", { id: api._g.id, actions: actions(code) }); api._b = r.briefing;
      return { frames: r.frames, morning: r.briefing ? summary(r.briefing, api._g.rules) : null, refused: [] }; },
    async report() { for (;;) { const r = await getJSON(`/api/challenge/report?id=${api._g.id}`); if (r.error) throw new Error(r.error); if (r.ready) return r.final; await new Promise((s) => setTimeout(s, 900)); } },
  };
  // live mode only: the same summary and action mapping scripts/build_phone_demo.py uses
  let liveB = null;
  function summary(b, rules) {
    liveB = b; const st = b.status, prices = rules.business.crop_prices_eur_per_unit;
    const heat = Math.min(...Object.values(st.settings.climate).map((v) => v.heat_day_c));
    const r = readyOf(st), news = (b.news_last_3_days || []).slice(-1)[0];
    return { day: b.clock.day, cold: heat < 12, heat_c: heat, seed_coming: (st.business.open_orders || []).some((o) => o.item.startsWith("seedlings:")),
             ready: r.map((x) => ({ id: x.id, crop: x.crop, units: Math.round((x.estimate || {}).units || 0), value: Math.round(((x.estimate || {}).units || 0) * (prices[x.crop] || 0)) })),
             news: news ? news.headline : null };
  }
  function readyOf(st) { return st.batches.filter((b) => !b.harvest_queued && (b.status === "ready" || (b.status === "growing" && ((b.estimate || {}).days_to_ready ?? 9) <= 0.05))); }
  function actions(code) {
    const g = api._g, a = [], idz = Object.keys(g.compartments).sort();
    if (code & 1) { const ts = idz.map((i) => (g.crops[g.compartments[i].crop] || {}).climate_targets || {}), mid = (r, d) => (Array.isArray(r) ? (r[0] + r[1]) / 2 : r ?? d);
      const avg = (k, d) => Math.round(ts.reduce((s, t) => s + mid(t[k], d), 0) / ts.length * 10) / 10;
      a.push({ tool: "set_climate", heat_day_c: avg("day_temp_c", 20), heat_night_c: avg("night_temp_c", 17), co2_ppm: avg("co2_ppm", 900), lamp_hours: [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17], lamp_intensity_pct: 100 });
      a.push({ tool: "set_night_schedule", from_hour: 18, copy_day: true }); }
    const r = readyOf((api._b || liveB).status); if (code & 2 && r.length) a.push({ tool: "harvest", batch_ids: r.map((b) => b.id) });
    if (code & 4) { const orders = {}; for (const c of [...new Set(idz.map((i) => g.compartments[i].crop))]) { const it = g.rules.business.items["seedlings:" + c];
      orders["seedlings:" + c] = Math.max(it.min_quantity, Math.ceil(1600 * (((g.crops[c] || {}).planting || {}).density_per_m2 || 1))); } a.push({ tool: "place_orders", orders }); }
    return a;
  }

  // ---------------- start: camera and motion are asked for inside the tap (iOS requires it) ----------------
  api.ready().then(() => { const b = $("#start"); b.disabled = false; b.textContent = "Start ▶"; }).catch(() => ($("#start").textContent = "Can't load the game"));
  $("#noCam").onclick = (e) => { e.preventDefault(); wantCam = false; $("#start").click(); };
  $("#start").onclick = async () => {
    const b = $("#start"); b.disabled = true; b.innerHTML = '<span class="spin"></span> opening the greenhouse…';
    const motion = wantCam ? askMotion() : Promise.resolve(false);
    const cam = wantCam ? openCam() : Promise.resolve(false);
    let d;
    try { d = await api.start(); } catch (e) { b.disabled = false; b.textContent = "Try again (" + e.message + ")"; return; }
    G = d; M = d.morning; ids = Object.keys(d.compartments).sort(); meta.compartments = d.compartments;
    for (const id of ids) { const ct = (d.crops[d.compartments[id].crop] || {}).climate_targets || {}; const mid = (r) => (Array.isArray(r) ? (r[0] + r[1]) / 2 : r);
      meta.targets[id] = { day: mid(ct.day_temp_c), night: mid(ct.night_temp_c || ct.day_temp_c), rh: mid(ct.rh_pct) }; }
    addFrames(d.frames); for (let h = 0; h < d.first_hour; h++) F[h] = { ...d.frames[0], h };
    hf = target = d.frames[d.frames.length - 1].h; lastH = Math.floor(hf);
    scene.setData(meta);
    $("#intro").style.display = "none"; $("#money").style.display = "block"; $("#rail").style.display = "flex"; $("#mini").style.display = "flex";
    const [m, c] = await Promise.all([motion, cam]);
    if (m && c) startAR(); else if (c) toast("Camera on. Motion sensors are off, so drag to turn the greenhouse.", 4000);
    if (!store.get("lb-tutorial")) tutorial(0); else morning();
  };
  async function openCam() {
    try { const v = $("#cam"); v.srcObject = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment", width: { ideal: 1280 } }, audio: false });
      v.style.display = "block"; camOn = true; scene.settings({ see: true }); sampleLight(); return true; }
    catch (e) { camOn = false; scene.settings({ see: false }); return false; }
  }
  function askMotion() {
    try { if (typeof DeviceOrientationEvent !== "undefined" && DeviceOrientationEvent.requestPermission)
      return DeviceOrientationEvent.requestPermission().then((p) => p === "granted").catch(() => false); }
    catch (e) { return Promise.resolve(false); }
    return Promise.resolve(typeof DeviceOrientationEvent !== "undefined");   // AR switches on only when real readings arrive
  }
  // the phone's orientation as a camera quaternion (the standard DeviceOrientation mapping)
  const zee = new THREE.Vector3(0, 0, 1), eul = new THREE.Euler(), q0 = new THREE.Quaternion(), q1 = new THREE.Quaternion(-Math.sqrt(0.5), 0, 0, Math.sqrt(0.5));
  let arListening = false;
  window.__lbStartAR = () => { camOn = true; startAR(); };   // for automated tests (headless browsers deny motion)
  function startAR() {
    if (arListening) { scene.settings({ ar: true }); arOn = true; return; }
    arListening = true;
    let got = false;
    window.addEventListener("deviceorientation", (e) => {
      if (e.alpha == null || !camOn) return;
      const d = Math.PI / 180, q = new THREE.Quaternion();
      eul.set(e.beta * d, e.alpha * d, -e.gamma * d, "YXZ"); q.setFromEuler(eul); q.multiply(q1);
      const o = ((screen.orientation && screen.orientation.angle) || window.orientation || 0) * d; q.multiply(q0.setFromAxisAngle(zee, -o));
      scene.settings({ arq: q });
      if (!got || !arOn) { got = true; arOn = true; scene.settings({ ar: true, crisp: false, pix: 1 / Math.min(2, window.devicePixelRatio || 1), shadows: true }); }
    });
  }
  // the room's brightness from the camera, so the greenhouse is lit like the room around it
  let sampling = false;
  function sampleLight() {
    if (sampling) return; sampling = true;
    const v = $("#cam"), c = document.createElement("canvas"); c.width = c.height = 16; const g = c.getContext("2d", { willReadFrequently: true });
    setInterval(() => { if (!camOn || !v.videoWidth) return; g.drawImage(v, 0, 0, 16, 16); const px = g.getImageData(0, 0, 16, 16).data; let l = 0;
      for (let i = 0; i < px.length; i += 4) l += 0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2]; l /= (px.length / 4) * 255;
      scene.settings({ env: 0.55 + l * 1.1 }); }, 800);
  }
  $("#bCam").onclick = async () => { if (camOn) { const v = $("#cam"); v.srcObject && v.srcObject.getTracks().forEach((t) => t.stop()); v.style.display = "none"; camOn = false; arOn = false; scene.settings({ see: false, ar: false, crisp: true, pix: 2 }); }
    else if (await openCam()) { if (await askMotion()) startAR(); } else toast("The camera needs permission: in Safari tap aA → Website Settings → Camera → Allow.", 5000); };
  $("#bZin").onclick = () => { if (arOn) arDist = scene.settings({ arDist: arDist / 1.25 }).arDist; else zoom = scene.settings({ zoom: zoom * 1.2 }).zoom; };
  $("#bZout").onclick = () => { if (arOn) arDist = scene.settings({ arDist: arDist * 1.25 }).arDist; else zoom = scene.settings({ zoom: zoom / 1.2 }).zoom; };
  $("#bRe").onclick = () => { if (arOn) { scene.settings({ ar: true }); toast("Re-centred where the phone points.", 1600); } else toast("Turn on the camera (📷) for AR.", 1600); };

  function addFrames(frames) {
    for (const f of frames) {
      F[f.h] = f;
      for (const b of f.b) if (b.st !== "harvested") meta.maxW[b.crop] = Math.max(meta.maxW[b.crop] || 1e-6, b.w);
      for (const id of Object.keys(f.c)) { meta.maxLamp[id] = Math.max(meta.maxLamp[id] || 1e-6, f.c[id].lamp); meta.maxHeat[id] = Math.max(meta.maxHeat[id] || 1e-6, f.c[id].heat); }
      meta.maxBuffer = Math.max(meta.maxBuffer, f.ec.buffer); meta.maxCO2 = Math.max(meta.maxCO2, f.ec.co2); meta.maxHeatAll = Math.max(meta.maxHeatAll, f.ec.heat);
      meta.snowAt[f.h] = 0;
    }
  }

  // ---------------- a short tutorial, the first time ----------------
  const STEPS = [
    { el: null, text: "🌱 <b>This is your greenhouse.</b> Three houses of microgreens on a winter morning. Turn or tilt your phone to look around it, or drag to spin it." },
    { el: "#tip", text: "📋 <b>Every morning</b> this card tells you what's going on: how warm the houses are, what's ready, whether seed is on its way." },
    { el: "#rail", text: "👉 <b>Pick your moves here.</b> 🌡️ Heat the houses, ✂️ harvest what's ready, 🌱 order seed (it takes 10 days). Tap to switch each on." },
    { el: "#go", text: "▶ <b>Tap GO</b> and watch the day play out. You get 2 mornings. Then see how you did against 7 AI runs that faced this exact morning." },
  ];
  function tutorial(i) {
    phase = "tutorial"; morning(true);
    document.querySelectorAll(".hl").forEach((x) => x.classList.remove("hl"));
    const s = STEPS[i]; if (s.el) $(s.el).classList.add("hl");
    $("#coach").innerHTML = `<div>${s.text}</div><div class="coachnav"><span class="small">${i + 1} / ${STEPS.length}</span>
      <span><a href="#" id="cSkip">skip</a> <button id="cNext">${i + 1 < STEPS.length ? "Next" : "Let's play"}</button></span></div>`;
    $("#coach").style.display = "block";
    $("#cNext").onclick = () => (i + 1 < STEPS.length ? tutorial(i + 1) : endTutorial());
    $("#cSkip").onclick = (e) => { e.preventDefault(); endTutorial(); };
  }
  function endTutorial() { store.set("lb-tutorial", "1"); $("#coach").style.display = "none"; document.querySelectorAll(".hl").forEach((x) => x.classList.remove("hl")); morning(); }
  $("#help").onclick = () => { if (phase === "morning") tutorial(0); };

  // ---------------- the morning: three choices ----------------
  function morning(quiet) {
    if (!quiet) phase = "morning";
    pick = { heat: false, cut: false, seed: false }; $("#rail").style.opacity = "1";
    const r = M.ready, val = r.reduce((s, b) => s + b.value, 0), bits = [];
    bits.push(M.cold ? `🥶 The houses are at <b>${M.heat_c} °C</b>; the crops want about 20 °C.` : "🌡️ The houses are warm.");
    bits.push(r.length ? `✂️ <b>${r.length} crop${r.length > 1 ? "s" : ""} ready</b>, worth about <b>${eur(val)}</b>.` : "🌱 Nothing is ready to harvest yet.");
    bits.push(M.seed_coming ? "🚚 Seed is on the way." : "📦 No seed on order, and it takes <b>10 days</b> to arrive.");
    if (M.news) bits.push("📰 " + M.news);
    $("#tip").innerHTML = `<b>Morning ${dayNo} of 2</b> · ${bits.join(" ")}`;
    $("#tip").style.display = "block";
    $("#aCut").classList.toggle("off", !r.length);
    paint(); $("#go").disabled = false;
  }
  function paint() { for (const [k, id] of [["heat", "#aHeat"], ["cut", "#aCut"], ["seed", "#aSeed"]]) $(id).classList.toggle("on", pick[k]); }
  const can = () => phase === "morning";
  $("#aHeat").onclick = () => { if (!can()) return; pick.heat = !pick.heat; paint(); if (pick.heat) toast("🌡️ Heat all three houses to the crops' targets, day and night."); };
  $("#aCut").onclick = () => { if (!can()) return; if (!M.ready.length) return toast("Nothing is ready to harvest yet."); pick.cut = !pick.cut; paint();
    if (pick.cut) toast(`✂️ Harvest ${M.ready.map((b) => b.id).join(", ")} and sell it today.`); };
  $("#aSeed").onclick = () => { if (!can()) return; pick.seed = !pick.seed; paint(); if (pick.seed) toast("🌱 Order seed for about 8 benches. It arrives in 10 days."); };

  // ---------------- the day ----------------
  $("#go").onclick = async () => {
    if (!can()) return;
    const code = (pick.heat ? 1 : 0) + (pick.cut && M.ready.length ? 2 : 0) + (pick.seed ? 4 : 0);
    $("#go").disabled = true; $("#go").innerHTML = '<span class="spin"></span>';
    let r;
    try { r = await api.day(code); } catch (e) { toast(`<span class="bad">${e.message}</span>`, 6000); $("#go").disabled = false; $("#go").textContent = "GO ▶"; return; }
    $("#go").textContent = "GO ▶";
    pendingDay = r; phase = "day"; $("#tip").style.display = "none";
    pick = { heat: false, cut: false, seed: false }; paint(); $("#rail").style.opacity = ".35";
    addFrames(r.frames || []);
    target = r.frames.length ? r.frames[r.frames.length - 1].h : target; playing = true;
    if ((r.refused || []).length) toast(r.refused.map((x) => `<div class="bad">✗ ${x}</div>`).join(""), 5000); else toast(`Day ${dayNo}: watch it play out ☀️`, 2000);
    if (dayNo === 2) api.report(r).then((f) => (final = f)).catch((e) => (final = { error: e.message })).then(() => phase === "waiting" && report());
  };
  function bubbles(prev, f) {
    if (!prev) return;
    const before = Object.fromEntries(prev.b.map((b) => [b.id, b.st]));
    const cut = f.b.filter((b) => b.st === "harvested" && before[b.id] && before[b.id] !== "harvested");
    const dRev = f.money.harvest_revenue_eur - prev.money.harvest_revenue_eur;
    if (dRev > 1) scene.bubble((cut[0] || {}).c || ids[0], `+${eur(dRev)} sold`, "#7bd88f");
    const nf = (f.faults || []).filter((x) => !(prev.faults || []).includes(x));
    if (nf.length) scene.bubble("energy", nf.some((x) => x.endsWith("glass")) ? "⛈ storm! glass broken" : "⚠ " + nf[0] + " down", "#ff6b5b");
    if (f.h % 24 === 13 && f.c[ids[0]]) { const t = ids.map((c) => f.c[c].t); scene.bubble(ids[1] || ids[0], `${Math.min(...t).toFixed(0)}–${Math.max(...t).toFixed(0)} °C inside`, Math.min(...t) < 12 ? "#6cc4ff" : "#7bd88f"); }
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
    if (dayNo === 1) { M = pendingDay.morning; dayNo = 2; morning(); toast("☀️ Morning 2: check what changed overnight.", 3000); return; }
    phase = "waiting"; $("#rail").style.display = "none";
    if (final) return report();
    $("#endcard").innerHTML = `<h2>Done!</h2><p><span class="spin"></span> Comparing you with the 7 AI runs…</p>`; $("#end").style.display = "flex";
  }

  // ---------------- the result ----------------
  function report() {
    phase = "report";
    if (final.error) { $("#endcard").innerHTML = `<h2 class="bad">Something went wrong</h2><p>${final.error}</p><button class="big" onclick="location.reload()">Play again</button>`; $("#end").style.display = "flex"; return; }
    const you = { ...final.you, kind: "you", name: "You" }, ais = final.ais.filter((a) => a.kind === "model");
    const all = [you, ...final.ais].sort((a, b) => b.checks_passed - a.checks_passed || b.two_day_profit - a.two_day_profit);
    const place = all.indexOf(you) + 1, beat = ais.filter((a) => all.indexOf(a) > all.indexOf(you)).length;
    const head = beat === ais.length ? "🏆 You beat every AI!" : beat > 0 ? `🎉 You beat ${beat} of ${ais.length} AI runs` : "🤖 The AIs win this time";
    const slips = you.failures.slice(0, 2).map((x) => `<p class="bad">✗ ${x.text}</p>`).join("");
    const aiSlip = ais.flatMap((a) => a.failures.map((x) => `${a.name}: ${x.text}`))[0];
    const name = (e) => e.kind === "you" ? "You" : e.kind === "planner" ? "Scripted planner" : e.name.replace("Claude ", "").replace("Gemini 4 Hydrogen", "Gemini");
    const rows = all.map((e, i) => `<div class="${e.kind === "you" ? "you" : ""}"><span>${i + 1}. ${name(e)}</span><span>${e.checks_passed}/${e.checks_total} ✓ · ${eur(e.two_day_profit)}</span></div>`).join("");
    $("#endcard").innerHTML = `<h2>${head}</h2>
      <p>You passed <b>${you.checks_passed} of ${you.checks_total}</b> good-grower checks and finished <b>#${place} of ${all.length}</b>.</p>
      ${slips || '<p class="ok">✓ No mistakes in your two mornings.</p>'}
      <div class="rank">${rows}</div>
      ${aiSlip ? `<p class="small">An AI slip from the same morning: ${aiSlip}</p>` : ""}
      <p class="small">Ranked by checks passed, then by profit over the two days. The AIs played the full 42-day season in our benchmark, LettuceBench; here you both played its first two days, in the same simulator.</p>
      <button class="big" onclick="location.reload()">Play again</button>`;
    $("#end").style.display = "flex";
  }
})();
