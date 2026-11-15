// Six growers side by side on one shared clock. Each panel is one real game; every decision it
// makes (each action of each daily turn, with the simulator's answer) fires at the hour it was
// made: the panel's decision strip shows it, the buildings it acts on are outlined, and the
// selected panel's feed, cards and detail drawer follow it.
(() => {
  const $ = (id) => document.getElementById(id);
  const css = getComputedStyle(document.documentElement), C = {};
  for (const k of ["orange", "green", "blue", "yellow", "purple", "grey", "red", "grid", "grid2", "cursor", "band"]) C[k] = css.getPropertyValue(`--c-${k}`).trim();
  const HOURS_PER_SEC = 1008 / 180;           // 1x plays 42 days in about 3 minutes
  const COLORS = { fault: C.red, fixed: C.green, delivery: C.blue, ready: C.yellow, sale: C.green,
                   order: C.blue, grower: C.purple, refused: C.red, low: C.yellow, info: C.grey };
  const SLOT_COLORS = ["#8fe3a6", "#6cb8ff", "#ffd84a", "#ff8a5c", "#c9a8ff", "#8d97a8"];
  let PLAYERS = null, panels = [], focus = 0, hf = 0, speed = 1, playing = false, last = 0, hours = 1008, lastClock = -1;
  let tab = "money", range = "all", drawerOpen = false, lastDrawer = 0, built = "", doneShown = false;
  let layout = "grid", big = [0, 1];          // speaker: big[0]; compare: big[0] left, big[1] right
  // The panel the shared helpers below work on (set with use(p)).
  let D = null, M = null, events = [], IDS = [];
  const use = (p) => { D = p.D; M = p.M; events = p.events; IDS = p.IDS; };

  const eur = (v, sign = false) => (v < 0 ? "-" : sign && v > 0 ? "+" : "") + "€" + Math.abs(Math.round(v)).toLocaleString("en-US");
  const num = (v, d = 0) => (v == null ? "–" : Number(v).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d }));
  const when = (h) => `Day ${Math.floor(h / 24) + 1} · ${String(h % 24).padStart(2, "0")}:00`;
  const cropName = (id) => (D.crops[id] || {}).name || id;
  const houseName = (c) => `House ${c} · ${cropName(D.compartments[c].crop)}`;
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const label = (spec) => { const all = [...PLAYERS.builtin, ...PLAYERS.traces]; return (all.find((p) => p.id === spec) || {}).label || spec; };

  // ---------------- players and panels ----------------
  async function loadPlayers() {
    const r = await fetch("/api/players"); PLAYERS = await r.json();
    $("subtitle").textContent = `${PLAYERS.title} · the real simulator, six growers on the same weather, prices and breakdowns`;
  }
  function options(selected) {
    const opt = (p) => `<option value="${esc(p.id)}"${p.id === selected ? " selected" : ""}>${esc(p.label)}</option>`;
    const models = PLAYERS.traces.filter((t) => t.kind === "model"), recorded = PLAYERS.traces.filter((t) => t.kind !== "model");
    return `<optgroup label="Model runs (replayed from their trace)">${models.length ? models.map(opt).join("") :
        `<option value="model:none"${selected === "model:none" ? " selected" : ""}>No model run found yet</option>`}</optgroup>` +
      `<optgroup label="Scripted growers">${PLAYERS.builtin.filter((p) => p.kind === "scripted").map(opt).join("")}</optgroup>` +
      `<optgroup label="Exploits (should score ~0)">${PLAYERS.builtin.filter((p) => p.kind === "exploit").map(opt).join("")}</optgroup>` +
      (recorded.length ? `<optgroup label="Other recorded runs">${recorded.map(opt).join("")}</optgroup>` : "");
  }
  function buildPanels() {
    const grid = $("grid"); grid.innerHTML = ""; panels = [];
    PLAYERS.slots.forEach((spec, i) => {
      const el = $("panel-tpl").content.firstElementChild.cloneNode(true);
      el.style.setProperty("--slot", SLOT_COLORS[i]); el.querySelector(".p-num").textContent = i + 1;
      grid.appendChild(el);
      const p = { i, el, spec, D: null, M: null, events: [], IDS: [], turns: [], lastHour: -1, scene: makeScene({ pix: 2, zoom: 1.15 }),
                  q: (s) => el.querySelector(s) };
      p.scene.init(p.q("canvas"));
      p.q(".p-pick").innerHTML = options(spec);
      p.q(".p-pick").onchange = (e) => { p.spec = e.target.value; loadPanel(p); };
      const pick = (e) => p.el.classList.contains("thumb") ? promote(i, e.shiftKey) : select(i);
      p.q(".p-head").onclick = p.q(".p-decision").onclick = p.q(".p-money").onclick = pick;
      p.q(".p-big").onclick = (e) => { e.stopPropagation(); setLayout(layout === "focus" && big[0] === i ? "grid" : "focus", i); };
      p.q(".p-cmp").onclick = (e) => { e.stopPropagation(); layout === "compare" ? promote(i, false) : setLayout("compare", focus === i ? i : focus, focus === i ? undefined : i); };
      p.q("canvas").addEventListener("scenepick", (e) => { if (!p.D) return;
        if (p.el.classList.contains("thumb")) { promote(i, false); return; } select(i); openDrawer(e.detail); });
      p.q("canvas").addEventListener("dblclick", () => setLayout(layout === "focus" && big[0] === i ? "grid" : "focus", i));
      panels.push(p);
    });
  }
  async function loadPanel(p) {
    const seed = Math.max(1, Math.min(9999, +$("seed").value || 1));
    p.D = null; p.el.classList.remove("empty"); p.q(".p-loading").hidden = false; p.q(".p-loading p").textContent = "Simulating 42 days…";
    p.q(".p-name").textContent = label(p.spec); p.q(".p-sub").textContent = ""; p.q(".p-profit").textContent = ""; p.q(".p-score").textContent = "";
    if (p.spec === "model:none") {
      p.q(".p-loading").hidden = true; p.el.classList.add("empty"); p.q(".p-name").textContent = "Model (no run yet)";
      p.q(".p-when").innerHTML = "Run <code>bash scripts/model-smoke.sh</code> or <code>bash scripts/judge.sh</code>, then press ↻ Model runs. Each run's trace is replayed here, decision by decision.";
      p.q(".p-acts").innerHTML = ""; renderStandings(); return;
    }
    try {
      const r = await fetch(`/api/run?player=${encodeURIComponent(p.spec)}&seed=${seed}`);
      const j = await r.json(); if (!r.ok) throw new Error(j.error || r.status);
      if (p.spec !== j.policy) return;               // the panel was switched while this was loading
      p.D = j; prepare(p); p.q(".p-loading").hidden = true;
      hours = Math.max(...panels.filter((x) => x.D).map((x) => x.D.hours));
      syncPanel(p); if (p.i === focus) select(focus);
      renderStandings();
    } catch (e) { p.q(".p-loading p").innerHTML = `<span class="err">Could not run: ${esc(e.message)}</span>`; }
  }
  async function loadAll() {
    hf = 0; doneShown = false; $("done").hidden = true; playing = false; setPlayIcon();
    await Promise.all(panels.map(loadPanel));
    const q = new URLSearchParams(location.search);    // ?at=400&focus=2&open=A jump straight to a moment
    if (q.get("focus")) select(Math.max(0, Math.min(5, +q.get("focus") - 1)));
    if (q.get("layout")) setLayout(q.get("layout"), focus, q.get("with") ? +q.get("with") - 1 : undefined);
    if (q.get("at")) seek(+q.get("at"));
    if (q.get("open")) openDrawer(q.get("open"));
    playing = !q.get("pause"); setPlayIcon();
  }

  function prepare(p) {
    const F = p.D.frames, max = (fn) => Math.max(1e-6, ...F.map(fn));
    p.IDS = Object.keys(p.D.compartments).sort();
    const maxW = {};
    for (const f of F) for (const b of f.b) if (b.st !== "harvested") maxW[b.crop] = Math.max(maxW[b.crop] || 0, b.w);
    const temps = F.map((f) => f.out.t), snowAt = temps.map((_, i) => {
      const s = temps.slice(Math.max(0, i - 24), i + 1); return s.reduce((a, b) => a + b, 0) / s.length < 0.5 ? 1 : 0; });
    const sh = (p.D.shift || "07:00-15:00").split("-").map((s) => parseInt(s, 10));
    p.M = { compartments: p.D.compartments, maxW, snowAt, shift: sh,
            maxLamp: Object.fromEntries(p.IDS.map((id) => [id, max((f) => f.c[id].lamp)])),
            maxHeat: Object.fromEntries(p.IDS.map((id) => [id, max((f) => f.c[id].heat)])),
            maxBuffer: max((f) => f.ec.buffer), maxCO2: max((f) => f.ec.co2), maxHeatAll: max((f) => f.ec.heat),
            maxHD: max((f) => Math.max(0, ...Object.values(f.hd || {}))),
            targets: Object.fromEntries(p.IDS.map((id) => { const ct = (p.D.crops[p.D.compartments[id].crop] || {}).climate_targets || {};
              return [id, { day: ct.day_temp_c, night: ct.night_temp_c || ct.day_temp_c, rh: ct.rh_pct }]; })),
            deliveries: p.D.alarms.filter((a) => a.kind === "delivery").map((a) => a.h) };
    p.scene.setData(p.M);
    use(p); p.events = buildEvents(); p.turns = buildTurns(p.events);
    const rep = p.D.replay, trace = p.spec.startsWith("trace:");
    p.q(".p-name").textContent = label(p.spec);
    p.q(".p-sub").innerHTML = `seed ${p.D.seed} · ${p.D.turns} of ${p.D.max_calls} calls` +
      (trace && rep ? ` · <span class="${rep.matched === rep.calls ? "good" : "bad"}" title="Each recorded call was sent to a fresh simulator; this many responses matched the recording byte for byte">replay ${rep.matched === rep.calls ? "verified" : "MISMATCH"} ${rep.matched}/${rep.calls}</span>` : "");
  }

  const SETTING = { heat_day_c: ["day heating", "°C"], heat_night_c: ["night heating", "°C"], co2_ppm: ["CO2 target", " ppm"],
    vent_min_pct: ["vents at least", "%"], vent_max_pct: ["vents at most", "%"], screen: ["screen", ""], lamp_intensity_pct: ["lamps", "%"] };
  const setting = (k, v) => k === "lamp_hours" ? `lamps on ${v.length} h a day` : SETTING[k] ? `${SETTING[k][0]} ${v}${SETTING[k][1]}` : `${k.replace(/_/g, " ")} ${v}`;
  const houseFault = (x) => (x.includes(".") && IDS.includes(x.split(".")[0]) ? x.split(".")[0] : null);
  const comp = (target) => (IDS.includes(target) ? target : IDS.includes(String(target)[0]) ? String(target)[0] : null);

  // Alarms, the grower's decisions and sales, in plain language. A decision carries `turn`
  // (the tool call it was part of), `ok` and `wheres` (the buildings it acts on).
  function buildEvents() {
    const ev = [];
    for (const a of D.alarms) {
      const tgt = a.target || "";
      if (a.kind === "equipment" && /working again/.test(a.text)) ev.push({ h: a.h, type: "fixed", where: "energy", text: `The ${tgt} works again`, bubble: `${tgt} fixed` });
      else if (a.kind === "equipment") ev.push({ h: a.h, type: "fault", where: "energy", text: `The ${tgt} broke down. ${a.text.split(". ").slice(1).join(". ")}`, bubble: `${tgt} broke!` });
      else if (a.kind === "delivery") ev.push({ h: a.h, type: "delivery", where: "road", text: a.text.replace(/arrived: ([\d.e+-]+)/, (_, n) => `arrived: ${num(+n)}`).replace("co2_kg", "kg of CO2").replace(/seedlings:(\w+)/, (_, c) => `${cropName(c)} seedlings`), bubble: "delivery" });
      else if (a.kind === "batch_ready") ev.push({ h: a.h, type: "ready", where: comp(tgt), text: `Batch ${tgt} is ready to harvest`, bubble: `${tgt} ready` });
      else if (a.kind === "stock_low") ev.push({ h: a.h, type: "low", where: "co2", text: a.text.replace("co2_store", "CO2 tank"), bubble: "CO2 low" });
      else if (a.kind === "storm" || a.kind === "bankrupt") ev.push({ h: a.h, type: "fault", where: comp(tgt) || "energy", text: a.text, bubble: a.kind });
      else ev.push({ h: a.h, type: "info", where: comp(tgt) || "energy", text: a.text, bubble: a.kind.replace(/_/g, " ") });
    }
    const item = (k) => k === "co2_kg" ? "kg of CO2" : k.startsWith("seedlings:") ? `${cropName(k.slice(10))} seedlings` : k.startsWith("part:") ? `spare ${k.slice(5).replace(/_/g, " ")}` : k;
    const houses = (list) => (list && list.length ? list : IDS).join(", ");
    const listed = (list) => (list && list.length ? list.filter((x) => IDS.includes(x)) : IDS);
    for (const c of D.calls) {
      const a = c.args, fail = c.ok ? "" : ` (refused${c.err ? `: ${c.err}` : ""})`;
      const push = (o) => ev.push({ h: c.h, type: c.ok ? "grower" : "refused", dec: true, turn: c.turn, ok: c.ok, err: c.err, tool: c.tool,
                                    fx: c.fx || [], wheres: o.wheres || [o.where], ...o });
      if (c.tool === "advance") continue;
      if (c.tool === "submit_day") { ev.push({ h: c.h, type: "turn", turn: c.turn, ok: c.ok, err: c.err, n: a.actions }); continue; }
      if (c.tool === "set_climate") {
        const w = a.compartment ? [a.compartment] : listed(a.compartments);
        push({ where: w[0], wheres: w, bubble: "new settings", short: `Climate ${w.join("")}: ` + Object.entries(a).filter(([k]) => !["compartment", "compartments"].includes(k)).map(([k, v]) => setting(k, v)).join(", "),
          text: `Changed ${a.compartment ? houseName(a.compartment) : `houses ${houses(a.compartments)}`}: ` +
          Object.entries(a).filter(([k]) => !["compartment", "compartments"].includes(k)).map(([k, v]) => setting(k, v)).join(", ") + fail });
      } else if (c.tool === "set_night_schedule") { const w = listed(a.compartments);
        push({ where: w[0], wheres: w, bubble: "night plan", short: `Night plan from ${a.from_hour ?? "?"}:00${a.copy_day ? ", same as day" : ""}`,
          text: `Set the night schedule${a.compartments ? ` for houses ${houses(a.compartments)}` : ""}: ${Object.entries(a).filter(([k]) => k !== "compartments").map(([k, v]) => `${k.replace(/_/g, " ")} ${JSON.stringify(v)}`).join(", ")}${fail}` }); }
      else if (c.tool === "place_order") push({ type: c.ok ? "order" : "refused", where: "road", wheres: ["road", "energy"], bubble: "order placed", short: `Order ${num(a.quantity)} ${item(a.item)}`, text: `Ordered ${num(a.quantity)} ${item(a.item)}${fail}` });
      else if (c.tool === "place_orders") { const o = Object.entries(a.orders || {}).map(([k, q]) => `${num(q)} ${item(k)}`).join(" and ");
        push({ type: c.ok ? "order" : "refused", where: "road", wheres: ["road", "energy"], bubble: "order placed", short: `Order ${o}`, text: `Ordered ${o}${fail}` }); }
      else if (c.tool === "harvest") { const ids = a.batch_ids || [a.batch_id], w = [...new Set(ids.map(comp).filter(Boolean))];
        push({ where: w[0], wheres: w, bubble: `harvest ${ids.join(" ")}`.slice(0, 24), short: `Harvest ${ids.join(", ")}`, text: `Started harvesting ${ids.join(", ")}${fail}` }); }
      else if (c.tool === "plant") { const areas = a.areas_m2 || { [a.compartment]: a.area_m2 };
        push({ where: Object.keys(areas)[0], wheres: Object.keys(areas), bubble: "planting", short: `Plant ${Object.entries(areas).map(([k, v]) => `${num(v)} m² in ${k}`).join(", ")}`,
          text: `Planted ${Object.entries(areas).map(([k, v]) => `${num(v)} m² in ${houseName(k)}`).join(", ")}${fail}` }); }
      else if (c.tool === "book_contractor") { const w = comp(a.target) || "energy";
        push({ where: w, bubble: "contractor", short: `Book ${String(a.trade || "contractor").replace(/_/g, " ")}${a.target ? ` for ${a.target}` : ""}`, text: `Booked a ${String(a.trade || "contractor").replace(/_/g, " ")}${a.target ? ` for ${a.target}` : ""}${fail}` }); }
      else if (c.tool === "hire") push({ where: "energy", bubble: "hiring", short: `Hire ${a.workers}`, text: `Hired ${a.workers} worker(s)${fail}` });
      else if (c.tool === "release") push({ where: "energy", bubble: "release", short: `Release ${a.workers}`, text: `Released ${a.workers} worker(s)${fail}` });
      else if (c.tool === "set_energy") { const s = Object.entries(a).map(([k, v]) => `${k.replace(/_/g, " ")} ${JSON.stringify(v)}`).join(", ");
        push({ where: "energy", bubble: "energy settings", short: `Energy: ${s}`, text: `Set the energy centre: ${s}${fail}` }); }
      else push({ where: comp(a.compartment) || "energy", bubble: c.tool.replace(/_/g, " "), short: `${c.tool.replace(/_/g, " ")} ${JSON.stringify(a)}`, text: `${c.tool.replace(/_/g, " ")} ${JSON.stringify(a)}${fail}` });
    }
    const pending = D.calls.filter((c) => c.tool === "harvest" && c.ok).flatMap((c) => c.args.batch_ids || [c.args.batch_id]);
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
    return ev.sort((a, b) => a.h - b.h || (a.turn || 0) - (b.turn || 0));
  }
  // One entry per tool call (a daily turn) with the actions inside it.
  function buildTurns(ev) {
    const turns = new Map();
    for (const e of ev) {
      if (e.type === "turn") turns.set(e.turn, { h: e.h, turn: e.turn, ok: e.ok, err: e.err, acts: [] });
      else if (e.dec) { if (!turns.has(e.turn)) turns.set(e.turn, { h: e.h, turn: e.turn, ok: true, acts: [] }); turns.get(e.turn).acts.push(e); }
    }
    return [...turns.values()].sort((a, b) => a.turn - b.turn);
  }

  // ---------------- the decision strip and outlines ----------------
  function showTurn(p, t, animate) {
    if (!t) { p.q(".p-when").textContent = "No decision yet"; p.q(".p-acts").innerHTML = ""; return; }
    const head = `<b>Turn ${t.turn}</b> · ${when(t.h)}` + (t.ok ? "" : ` · <span class="bad">turn refused${t.err ? `: ${esc(t.err)}` : ""}</span>`);
    p.q(".p-when").innerHTML = head;
    const isBig = p.el.classList.contains("big"), isThumb = p.el.classList.contains("thumb");
    const shown = t.acts.slice(0, isBig ? 8 : isThumb ? 1 : 3), more = t.acts.length - shown.length;
    p.q(".p-acts").innerHTML = t.acts.length ? shown.map((a) => `<li class="${a.ok ? "" : "bad"}" title="${esc([a.text, ...a.fx].join("\n"))}"><i>${a.ok ? "✓" : "✗"}</i>` +
        (a.ok ? (a.fx.length ? (isBig ? `<span class="fx">${a.fx.map(esc).join(" · ")}</span>` : `<span class="fx">${esc(a.fx[0])}</span>${a.fx.length > 1 ? `<span class="more"> +${a.fx.length - 1}</span>` : ""}`)
                             : `${esc(a.short || a.text)} <span class="muted">· no change, already in force</span>`)
              : `${esc(a.short || a.text)}${esc(a.err ? ` — ${a.err}` : "")}`) + `</li>`).join("") +
        (more ? `<li class="muted"><i>+</i>${more} more action(s) this turn (Full log)</li>` : "")
      : `<li class="muted"><i>·</i>No changes: kept the current plan</li>`;
    if (animate) {
      p.el.classList.remove("decided"); void p.el.offsetWidth; p.el.classList.add("decided");
      if (outlines) for (const a of t.acts) p.scene.flash(a.wheres.filter(Boolean), a.ok ? 0xc9a8ff : 0xff6b5e);
    }
  }
  function syncPanel(p) {          // after a seek or a reload: show the state at the current hour
    const h = Math.floor(hf); p.lastHour = h; p.scene.reset();
    showTurn(p, [...p.turns].reverse().find((t) => t.h <= h), false); panelHud(p);
  }

  // ---------------- playback ----------------
  const frameAt = (p, h) => p.D.frames[Math.max(0, Math.min(p.D.frames.length - 1, Math.floor(h)))];
  function loop(now) {
    const dt = Math.min(0.1, (now - (last || now)) / 1000); last = now; perf(dt);
    const live = panels.filter((p) => p.D);
    if (live.length) {
      if (playing) { hf = Math.min(hours, hf + dt * HOURS_PER_SEC * speed); if (hf >= hours) { playing = false; setPlayIcon(); showDone(); } }
      const h = Math.floor(hf);
      for (const p of live) {
        if (h !== p.lastHour) { const from = p.lastHour; p.lastHour = h; fireEvents(p, from, h); panelHud(p); }
        p.scene.render(frameAt(p, hf), hf, dt, playing ? speed : 0.2);
      }
      if (h !== lastClock) { lastClock = h; clockHud(); if (panels[focus].D) { use(panels[focus]); updateCards(); } renderStandings(); }
      if (drawerOpen && panels[focus].D && now - lastDrawer > 250) { lastDrawer = now; renderDrawer(); }
    }
    requestAnimationFrame(loop);
  }
  function fireEvents(p, from, to, force = false) {
    if (to < from) { syncPanel(p); if (p.i === focus) rebuildFeed(); return; }
    const fresh = p.events.filter((e) => e.h > from && e.h <= to);
    const jump = !force && to - from >= 30;
    if (!jump) for (const e of fresh.filter((e) => !e.dec && e.type !== "turn").slice(-3)) p.scene.bubble(e.where, e.bubble, COLORS[e.type]);
    const turns = p.turns.filter((t) => t.h > from && t.h <= to);
    if (turns.length) {
      showTurn(p, turns[turns.length - 1], !jump);
      if (!jump) for (const a of turns[turns.length - 1].acts.slice(0, 3)) p.scene.bubble(a.where, a.bubble, a.ok ? C.purple : C.red);
      if (p.i === focus && $("stop-at-dec").checked && playing && !jump) { playing = false; setPlayIcon(); hf = Math.floor(hf); }
    }
    if (p.i === focus && fresh.length) { use(p); addFeed(fresh.filter((e) => e.type !== "turn"), true); }
  }
  function addFeed(list, animate) {
    const ol = $("feed"), html = list.map((e) => `<li class="${animate ? "new" : ""}${e.dec ? " dec" : ""}" data-h="${e.h}"><span class="dot" style="background:${COLORS[e.type]}"></span>` +
      `<span><span class="when">${when(e.h)}${e.dec ? ` · turn ${e.turn}` : ""}</span>${esc(e.dec ? `Grower: ${e.text}` : e.text)}` +
      (e.dec && e.ok ? `<span class="fxs">${e.fx.length ? e.fx.map((x) => `→ ${esc(x)}`).join("<br>") : "→ no change: already in force"}</span>` : "") + `</span></li>`).reverse().join("");
    ol.insertAdjacentHTML("afterbegin", html);
    while (ol.children.length > 120) ol.lastElementChild.remove();
  }
  function rebuildFeed() {
    $("feed").innerHTML = ""; const p = panels[focus]; if (!p.D) return; use(p);
    const past = p.events.filter((e) => e.h <= Math.floor(hf) && e.type !== "turn").slice(-120); if (past.length) addFeed(past, false);
  }
  function seek(h) {
    hf = Math.max(0, Math.min(hours, h)); $("done").hidden = true; doneShown = false;
    for (const p of panels) if (p.D) syncPanel(p);
    rebuildFeed(); lastClock = -1;
  }
  function nextDecision() {         // jump to the selected grower's next turn and play it out
    const p = panels[focus]; if (!p.D) return;
    const t = p.turns.find((t) => t.h > Math.floor(hf)); if (!t) return;
    playing = false; setPlayIcon(); $("done").hidden = true; hf = t.h;
    for (const x of panels) if (x.D) { const from = x.lastHour; x.lastHour = t.h; fireEvents(x, from, t.h, true); panelHud(x); }
    lastClock = -1;
  }
  function setPlayIcon() { $("play").textContent = playing ? "❚❚" : "▶"; $("play").setAttribute("aria-label", playing ? "Pause" : "Play"); }

  // ---------------- selection, HUDs, cards, standings ----------------
  function select(i) {
    focus = i; panels.forEach((p) => p.el.classList.toggle("focus", p.i === i));
    const p = panels[i]; $("sel-name").innerHTML = `<span class="swatch" style="background:${SLOT_COLORS[i]}"></span>${esc(p.D ? label(p.spec) : p.q(".p-name").textContent)}`;
    if (!p.D) { $("feed").innerHTML = ""; $("tl-marks").innerHTML = ""; return; }
    use(p); buildHouseUI(); rebuildFeed(); updateCards(); built = "";
    $("tl-marks").innerHTML = p.events.filter((e) => ["fault", "delivery", "sale", "ready"].includes(e.type)).map((e) =>
      `<i style="left:${(e.h / hours) * 100}%;background:${COLORS[e.type]}" title="${esc(when(e.h) + " " + e.text)}"></i>`).join("") +
      p.turns.map((t) => `<i class="tick" style="left:${(t.h / hours) * 100}%;background:${t.acts.some((a) => !a.ok) || !t.ok ? C.red : C.purple}" title="${esc(`${when(t.h)} turn ${t.turn}: ${t.acts.length} action(s)`)}"></i>`).join("");
    if (drawerOpen) openDrawer(tab);
  }
  function clockHud() {
    const p = panels.find((x) => x.D); if (!p) return;
    const h = Math.min(Math.floor(hf), hours), f = frameAt(p, hf);
    $("hud-day").textContent = Math.min(Math.ceil(hours / 24), Math.floor(h / 24) + 1); $("hud-time").textContent = `${String(h % 24).padStart(2, "0")}:00`;
    $("hud-temp").textContent = `${f.out.t.toFixed(1)}°C`;
    $("tl-fill").style.width = $("tl-head").style.left = `${(hf / hours) * 100}%`;
    $("tl-time").textContent = `${(hf / 24).toFixed(1)} / ${Math.round(hours / 24)} d`;
  }
  function panelHud(p) {
    const f = frameAt(p, hf), v = f.money.profit_so_far_eur, el = p.q(".p-profit");
    el.textContent = eur(v); el.className = "p-profit " + (v >= 0 ? "good" : "bad");
    const end = Math.floor(hf) >= p.D.hours;
    p.q(".p-score").innerHTML = end && p.D.score != null ? `score <b>${p.D.score.toFixed(3)}</b>` : `${p.turns.filter((t) => t.h <= Math.floor(hf)).length} turns`;
    const broke = f.faults.length;
    p.el.classList.toggle("faulty", broke > 0);
  }
  function renderStandings() {
    const rows = panels.map((p) => {
      if (!p.D) return { p, v: null };
      return { p, v: frameAt(p, hf).money.profit_so_far_eur };
    });
    const vals = rows.filter((r) => r.v != null).map((r) => Math.abs(r.v)), big = Math.max(1, ...vals);
    const sorted = [...rows].sort((a, b) => (b.v ?? -Infinity) - (a.v ?? -Infinity));
    $("standings").innerHTML = sorted.map(({ p, v }) => `<li data-i="${p.i}" class="${p.i === focus ? "on" : ""}"><span class="swatch" style="background:${SLOT_COLORS[p.i]}"></span>` +
      `<span class="nm">${esc(p.D ? label(p.spec) : p.q(".p-name").textContent)}</span>` +
      `<span class="bar"><i style="width:${v == null ? 0 : (Math.abs(v) / big) * 100}%;background:${v >= 0 ? C.green : C.red}"></i></span>` +
      `<span class="num ${v == null ? "" : v >= 0 ? "good" : "bad"}">${v == null ? "–" : eur(v)}</span></li>`).join("");
    document.querySelectorAll("#standings li").forEach((li) => li.onclick = () => select(+li.dataset.i));
  }
  function weatherWord(o) {
    const w = o.t <= 0.5 && o.rh >= 82 ? "Snowing" : o.rh >= 94 ? "Raining" : o.sun > 150 ? "Sunny" : o.sun > 10 ? "Cloudy" : "Dark";
    return `${w} · wind ${num(o.wind)} m/s · sun ${num(o.sun)} W/m²`;
  }
  function houseState(c) { return c.t < c.sp_night - 1 ? ["Too cold", "info"] : c.t > c.sp_day + 3 ? ["Too warm", "bad"] : ["On target", "good"]; }
  function updateCards() {
    const f = frameAt(panels[focus], hf), m = f.money, p = m.profit_so_far_eur;
    $("c-money").textContent = eur(p); $("c-money").className = "big " + (p >= 0 ? "good" : "bad");
    $("c-money-sub").textContent = `Cash ${eur(m.cash_eur)} · sales ${eur(m.harvest_revenue_eur)}`;
    $("c-out").textContent = `${f.out.t.toFixed(1)}°C`; $("c-out-sub").textContent = weatherWord(f.out);
    for (const id of IDS) {
      const c = f.c[id], [word, cls] = houseState(c), bs = f.b.filter((b) => b.c === id && b.st !== "harvested");
      const ready = bs.filter((b) => b.st === "ready").length, el = $(`c-${id}`); if (!el) continue;
      const dmg = f.faults.filter((x) => houseFault(x) === id).map((x) => x.split(".")[1].replace(/_/g, " "));
      el.innerHTML = `${c.t.toFixed(1)}°C <span class="pill ${cls}">${word}</span>${dmg.length ? ` <span class="pill bad">${esc(dmg.join(", "))} broken</span>` : ""}`;
      $(`c-${id}-sub`).textContent = `Target ${c.sp_night}–${c.sp_day}° · ${bs.length} beds${ready ? ` · ${ready} ready` : ""}${c.free > 1 ? ` · ${num(c.free)} m² empty` : ""}`;
    }
    const plant = f.faults.filter((x) => !houseFault(x));
    $("c-en").innerHTML = plant.length ? `<span class="bad">${esc(plant.join(", ").replace(/_/g, " "))} down</span>` : `<span class="good">All running</span>`;
    $("c-en-sub").textContent = `CO2 tank ${num((f.ec.co2 / M.maxCO2) * 100)}% · ${f.ec.imp > 0.5 ? `buying ${num(f.ec.imp)} kWh` : f.ec.exp > 0.5 ? `selling ${num(f.ec.exp)} kWh` : "grid idle"} · gas ${num(f.ec.gas, 1)} m³/h`;
  }
  function buildHouseUI() {
    document.querySelectorAll(".card.house, #tabs .house").forEach((el) => el.remove());
    const energyCard = document.querySelector('.card[data-open="energy"]'), energyTab = document.querySelector('#tabs [data-tab="energy"]');
    for (const id of IDS) {
      TABS[id] = houseTab(id);
      energyCard.insertAdjacentHTML("beforebegin", `<article class="card house" data-open="${id}"><h3>${esc(houseName(id))}</h3>` +
        `<div class="big" id="c-${id}">–</div><p class="small" id="c-${id}-sub">–</p></article>`);
      energyTab.insertAdjacentHTML("beforebegin", `<button class="house" data-tab="${id}">${esc(houseName(id))}</button>`);
    }
    document.querySelectorAll(".card.house").forEach((el) => el.onclick = () => openDrawer(el.dataset.open));
    document.querySelectorAll("#tabs .house").forEach((b) => b.onclick = () => openDrawer(b.dataset.tab));
    if (!TABS[tab]) tab = "money";
  }
  function showDone() {
    if (doneShown) return; doneShown = true;
    const live = panels.filter((p) => p.D), nobody = live.length ? live[0].D.anchors : {};
    const zero = Math.max(...Object.entries(nobody).filter(([k]) => k !== "reference").map(([, v]) => v));
    $("done-title").textContent = `${Math.round(hours / 24)} days done`;
    $("done-note").textContent = `Score is the benchmark's: 0 = the profit of doing nothing (${eur(zero)}), 0.80 = the reference solution, recomputed on each run's seed.`;
    const rows = [...live].sort((a, b) => (b.D.score ?? -1) - (a.D.score ?? -1) || b.D.profit - a.D.profit).map((p) => {
      const decs = p.events.filter((e) => e.dec), bad = decs.filter((e) => !e.ok).length;
      return `<tr data-i="${p.i}"><td><span class="swatch" style="background:${SLOT_COLORS[p.i]}"></span>${esc(label(p.spec))}</td>` +
        `<td class="num ${p.D.profit >= 0 ? "good" : "bad"}">${eur(p.D.profit)}</td><td class="num"><b>${p.D.score == null ? "–" : p.D.score.toFixed(3)}</b></td>` +
        `<td class="num">${p.events.filter((e) => e.type === "sale").length}</td><td class="num">${p.D.turns}</td><td class="num">${decs.length}${bad ? ` <span class="bad">(${bad} refused)</span>` : ""}</td>` +
        `<td>${p.D.bankrupt ? '<span class="bad">bankrupt</span>' : esc(p.D.end_reason || "")}${p.D.replay ? ` · replay ${p.D.replay.matched}/${p.D.replay.calls}` : ""}</td></tr>`;
    }).join("");
    $("done-table").innerHTML = `<tr><th>Grower</th><th class="num">Profit</th><th class="num">Score</th><th class="num">Sales</th><th class="num">Turns</th><th class="num">Actions</th><th>Ended</th></tr>${rows}`;
    document.querySelectorAll("#done-table tr[data-i]").forEach((tr) => tr.onclick = () => { $("done").hidden = true; select(+tr.dataset.i); openDrawer("log"); });
    $("done").hidden = false;
  }

  // ---------------- charts ----------------
  function series(fn) { return D.frames.map(fn); }
  function chart(id, lines, opts = {}) {
    const cv = document.getElementById(id); if (!cv) return;
    const dpr = devicePixelRatio || 1, w = cv.clientWidth * dpr, h = cv.clientHeight * dpr;
    if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
    const x = cv.getContext("2d"); x.clearRect(0, 0, w, h);
    const now = Math.min(Math.floor(hf), D.hours), a = range === "all" ? 0 : Math.max(0, now - 72), b = range === "all" ? D.hours : Math.max(now, 72);
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
    for (const tt of (opts.turns || [])) if (tt.h >= a && tt.h <= Math.min(b, now)) { x.fillStyle = tt.ok ? C.purple : C.red; x.globalAlpha = 0.45; x.fillRect(Math.round(X(tt.h)), 0, dpr, h); x.globalAlpha = 1; }
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
  const decTurns = () => panels[focus].turns.map((t) => ({ h: t.h, ok: t.ok && t.acts.every((a) => a.ok) }));
  const DEC_NOTE = " Purple lines: the grower's decisions (red: refused).";

  // ---------------- drawer tabs ----------------
  function renderDrawer() {
    use(panels[focus]); const f = frameAt(panels[focus], hf), key = focus + tab + range + panels[focus].spec;
    if (built !== key) { $("drawer-body").innerHTML = TABS[tab].html(f); built = key; }
    TABS[tab].update(f);
  }
  const TABS = {};
  function houseTab(id) { return {
    html: () => {
      const crop = D.crops[D.compartments[id].crop] || {}, ct = crop.climate_targets || {};
      return sec("Temperature", `Inside vs the grower's heating setpoints. Green band: the crop's ideal day range (${(ct.day_temp_c || []).join("–")}°C).` + DEC_NOTE,
          legend([[C.orange, "inside"], [C.green, "day setpoint"], [C.blue, "night setpoint"], [C.grey, "outside"]]) + `<canvas class="chart" id="ch-t"></canvas>`) +
        sec("CO2", `Plants grow faster with more CO2. Green band: ideal ${(ct.co2_ppm || []).join("–")} ppm. Dosing uses the CO2 tank.`, `<canvas class="chart" id="ch-co2"></canvas>`) +
        sec("Humidity", `Green band: ideal ${(ct.rh_pct || []).join("–")}%. Too humid invites disease.`, `<canvas class="chart" id="ch-rh"></canvas>`) +
        sec("Light", "Light at the plants (PAR) and lamp power. Winter sun is weak, so lamps do most of the work.",
          legend([[C.yellow, "PAR µmol/m²/s"], [C.purple, "lamps kW"]]) + `<canvas class="chart" id="ch-par"></canvas>`) +
        sec("Right now", "", `<div id="now-kv"></div>`) +
        sec("Beds", `Each batch of ${crop.name || "plants"} from planting to harvest. Sale price depends on grade (quality) and weight.`, `<div id="beds"></div>`);
    },
    update: (f) => {
      const c = f.c[id], ct = (D.crops[D.compartments[id].crop] || {}).climate_targets || {}, turns = decTurns();
      chart("ch-t", [{ v: series((x) => x.out.t), c: C.grey, thin: 1 }, { v: series((x) => x.c[id].sp_day), c: C.green, thin: 1 },
        { v: series((x) => x.c[id].sp_night), c: C.blue, thin: 1 }, { v: series((x) => x.c[id].t), c: C.orange }], { band: ct.day_temp_c, turns });
      chart("ch-co2", [{ v: series((x) => x.c[id].co2), c: C.blue }], { band: ct.co2_ppm, turns });
      chart("ch-rh", [{ v: series((x) => x.c[id].rh), c: C.blue }], { band: ct.rh_pct, turns });
      chart("ch-par", [{ v: series((x) => x.c[id].par), c: C.yellow }, { v: series((x) => x.c[id].lamp), c: C.purple, thin: 1 }], { zero: 1, turns });
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
    html: () => sec("Heat", "Heat made by the boiler and CHP each hour, and gas burnt to make it." + DEC_NOTE, legend([[C.orange, "heat kWh"], [C.grey, "gas m³ ×10"]]) + `<canvas class="chart" id="ch-heat"></canvas>`) +
      sec("Electricity", "Lamps need lots of power. Bought from the grid, or made by the CHP (which can also sell the surplus).", legend([[C.yellow, "bought kWh"], [C.green, "sold kWh"]]) + `<canvas class="chart" id="ch-el"></canvas>`) +
      sec("Prices", "Hourly prices from recorded Dutch winter data. Buying at peaks costs more.", legend([[C.yellow, "electricity €/kWh"], [C.orange, "gas €/m³"]]) + `<canvas class="chart" id="ch-price"></canvas>`) +
      sec("Tanks", "The hot-water buffer stores heat for later. The CO2 tank feeds the houses and must be reordered in time (deliveries take days).", legend([[C.orange, "buffer kWh"], [C.blue, "CO2 kg"]]) + `<canvas class="chart" id="ch-tank"></canvas>`) +
      sec("Settings and orders", "", `<div id="en-kv"></div>`),
    update: (f) => {
      const turns = decTurns();
      chart("ch-heat", [{ v: series((x) => x.ec.gas * 10), c: C.grey, thin: 1 }, { v: series((x) => x.ec.heat), c: C.orange }], { zero: 1, turns });
      chart("ch-el", [{ v: series((x) => x.ec.imp), c: C.yellow }, { v: series((x) => x.ec.exp), c: C.green }], { zero: 1, turns });
      chart("ch-price", [{ v: series((x) => x.ec.p_imp), c: C.yellow }, { v: series((x) => x.ec.p_gas), c: C.orange }], { zero: 1 });
      chart("ch-tank", [{ v: series((x) => x.ec.buffer), c: C.orange }, { v: series((x) => x.ec.co2), c: C.blue }], { zero: 1, turns });
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
    html: () => sec("Profit over time", "Profit = sales minus every cost so far. Thin lines: the other five growers on the same seed." + DEC_NOTE,
        legend([[C.green, "this grower"], [C.grey, "doing nothing (end)"], ...panels.filter((p) => p.D && p.i !== focus).map((p) => [SLOT_COLORS[p.i], esc(label(p.spec))])]) + `<canvas class="chart" id="ch-profit"></canvas>`) +
      sec("Where the money went", "", `<div id="money-tab"></div>`) + sec("Staff and work queue", "", `<div id="staff"></div>`),
    update: (f) => {
      const zero = D.anchors ? D.anchors["do-nothing"] : 0;
      const others = panels.filter((p) => p.D && p.i !== focus).map((p) => ({ v: D.frames.map((_, i) => frameAt(p, i).money.profit_so_far_eur), c: SLOT_COLORS[p.i], thin: 1 }));
      chart("ch-profit", [{ v: series(() => zero), c: C.grey, thin: 1 }, ...others, { v: series((x) => x.money.profit_so_far_eur), c: C.green }], { zero: 1, turns: decTurns() });
      const items = Object.entries(f.money).filter(([k]) => !["cash_eur", "profit_so_far_eur"].includes(k));
      const big = Math.max(1, ...items.map(([, v]) => Math.abs(v)));
      $("money-tab").innerHTML = `<table>${items.map(([k, v]) => `<tr><td>${k.replace(/_eur$/, "").replace(/_/g, " ")}</td><td style="width:45%"><div class="bar"><i style="left:0;width:${(Math.abs(v) / big) * 100}%;background:${v >= 0 ? C.green : C.red}"></i></div></td><td class="num ${v > 0 ? "good" : v < 0 ? "bad" : ""}">${eur(v, true)}</td></tr>`).join("")}` +
        `<tr><th>Profit so far</th><td></td><th class="num">${eur(f.money.profit_so_far_eur)}</th></tr><tr><td>Cash in the bank</td><td></td><td class="num">${eur(f.money.cash_eur)}</td></tr></table>`;
      $("staff").innerHTML = kv([["Crew", `${f.staff} workers`], ["Shift", D.shift]]) + (f.tasks.length ?
        `<table style="margin-top:10px"><tr><th>Task</th><th>Target</th><th class="num">Work done</th><th>Status</th></tr>${f.tasks.map((k) => `<tr><td>${k.kind}</td><td>${k.target}</td><td class="num">${num(k.done)} / ${num(k.need)} h</td><td>${k.st}</td></tr>`).join("")}</table>` : '<p class="note" style="margin-top:8px">No work queued.</p>');
    },
  };
  TABS.log = {
    html: () => sec("Every decision so far", `Exactly what the grower sent: one "submit_day" call per day (a turn, counted against the budget of ${D.max_calls} calls), holding that day's actions, each with the simulator's answer. Click a row to jump there.`,
      `<div id="log"></div>`) + sec("Every event so far", "", `<div id="evlog"></div>`),
    update: (f) => {
      const now = Math.floor(hf), turns = panels[focus].turns.filter((t) => t.h <= now), raw = D.calls.filter((c) => c.h <= now && c.tool !== "submit_day");
      const byTurn = new Map(); for (const c of raw) { if (!byTurn.has(c.turn)) byTurn.set(c.turn, []); byTurn.get(c.turn).push(c); }
      const html = `<p class="note">Turns used: ${turns.length} of ${D.max_calls}</p><table><tr><th>When</th><th>Turn</th><th>Action</th><th>Arguments</th><th>Result</th><th>Measured change in the simulator</th></tr>${turns.slice(-120).reverse().map((t) =>
        (byTurn.get(t.turn) || [null]).map((c, j) => `<tr class="jump" data-h="${t.h}"><td>${j ? "" : when(t.h)}</td><td>${j ? "" : t.turn}</td><td>${c ? c.tool : "<i>no changes</i>"}</td><td><code>${c ? esc(JSON.stringify(c.args)) : ""}</code></td>` +
          `<td>${c ? (c.ok ? "✓" : `<span class="err">${esc(c.err || "refused")}</span>`) : (t.ok ? "✓" : `<span class="err">${esc(t.err || "refused")}</span>`)}</td>` +
          `<td class="fxcell">${c ? (c.fx && c.fx.length ? c.fx.map(esc).join("<br>") : c.ok ? '<span class="muted">none: already in force</span>' : '<span class="muted">none</span>') : ""}</td></tr>`).join("")).join("")}</table>`;
      if ($("log").dataset.n !== String(turns.length)) { $("log").innerHTML = html; $("log").dataset.n = String(turns.length);
        $("log").querySelectorAll("tr.jump").forEach((tr) => tr.onclick = () => { seek(+tr.dataset.h); playing = false; setPlayIcon(); }); }
      $("evlog").innerHTML = `<table>${events.filter((e) => e.h <= now && e.type !== "turn" && !e.dec).reverse().map((e) => `<tr><td>${when(e.h)}</td><td><span class="pill" style="color:${COLORS[e.type]}">${e.type}</span></td><td>${esc(e.text)}</td></tr>`).join("")}</table>`;
    },
  };
  TABS.incidents = {
    html: () => sec("Damage and repairs", "Every breakdown in this game, from the simulator's own records: when it happened, the grower's response, when the repair crew was on site, and what it cost. Costs are the ledger's entries, not estimates.", `<div id="inc"></div>`),
    update: (f) => {
      const now = Math.floor(hf), map = new Map();
      for (const fr of D.frames) { if (fr.h > now) break;
        for (const d of fr.dmg || []) { const key = `${d.eq}@${d.since}`;
          if (!map.has(key)) map.set(key, { eq: d.eq, since: d.since, panes: d.panes, maxPanes: d.panes, last: fr.h, rep: d.rep, onsite: null });
          const x = map.get(key); x.last = fr.h; x.maxPanes = Math.max(x.maxPanes, d.panes || 0); x.rep = d.rep; }
        for (const b of fr.crew_on || []) for (const x of map.values()) if (b.target === x.eq && b.st === "on_site" && x.onsite == null && fr.h >= x.since) x.onsite = fr.h; }
      const rows = [...map.values()].map((x) => {
        const fixed = x.last < Math.min(now, D.hours) - 1, books = D.calls.filter((c) => c.tool === "book_contractor" && c.ok && c.args.target === x.eq && c.h >= x.since && c.h <= x.last + 1);
        const cost = D.entries.filter((e) => e.h >= x.since && e.h <= x.last + 1 && e.note.includes(x.eq)).reduce((a, e) => a + e.eur, 0);
        const pane = x.eq.endsWith("glass") ? ` · ${x.maxPanes} pane(s) broken` : "";
        const resp = books.length ? `booked ${when(books[0].h)} (turn ${books[0].turn}, ${Math.round((books[0].h - x.since))} h after)` : '<span class="bad">never booked</span>';
        return `<tr><td><b>${esc(x.eq)}</b>${pane}</td><td>${when(x.since)}</td><td>${resp}</td><td>${x.onsite != null ? when(x.onsite) : x.rep ? esc(x.rep.replace(/_/g, " ")) : "–"}</td>` +
          `<td>${fixed ? `<span class="good">${when(x.last + 1)}</span> (${Math.round((x.last + 1 - x.since) / 24 * 10) / 10} d down)` : '<span class="bad">still broken</span>'}</td><td class="num">${eur(cost)}</td></tr>`;
      }).join("");
      const parts = D.entries.filter((e) => e.h <= now && (e.cat === "parts" || e.cat === "contractors"));
      const byCat = (c) => parts.filter((e) => e.cat === c).reduce((a, e) => a + e.eur, 0);
      $("inc").innerHTML = rows ? `<table><tr><th>Equipment</th><th>Broke</th><th>Grower's response</th><th>Crew on site</th><th>Working again</th><th class="num">Contractor cost</th></tr>${rows}</table>` +
        `<p class="note" style="margin-top:10px">Totals so far: contractors ${eur(byCat("contractors"))}, parts ${eur(byCat("parts"))}. Broken glass leaks heat (more gas and power to hold temperature) until it is repaired; the Energy tab shows the heat bill.</p>` +
        `<table style="margin-top:6px"><tr><th>When</th><th>Ledger entry</th><th class="num">€</th></tr>${parts.slice(-40).reverse().map((e) => `<tr><td>${when(e.h)}</td><td>${esc(e.cat)}: ${esc(e.note)}</td><td class="num bad">${eur(e.eur)}</td></tr>`).join("")}</table>`
        : '<p class="note">No damage so far.</p>';
    },
  };
  TABS.raw = { html: () => sec("This hour, exactly as the simulator reports it", "", `<pre id="raw"></pre>`), update: (f) => { $("raw").textContent = JSON.stringify(f, null, 1); } };
  TABS.about = {
    html: () => sec("What you're watching", "", `<p class="note">Six real games of the Greenhouse Bench simulator (<code>src/greenhouse</code>), not animations, on one shared clock. Each grower plays through the same tool an AI agent gets: each morning one turn (<code>submit_day</code>) holding that day's actions. Every simulated hour is recorded and drawn from the numbers: lamps glow when lamp power is on, smoke follows gas burnt, plants grow with their real weight, the red light flashes when equipment is broken.</p>`) +
      sec("How a decision is linked", "", `<p class="note">When a grower's turn happens, its panel's strip lists that turn's actions with the simulator's verdict (✓ accepted, ✗ refused, with the reason), the buildings each action acts on are outlined (purple, or red if refused), and from that hour on the picture shows the result. A model run is not re-generated: its recorded calls are sent to a fresh simulator in order and every response is checked against the recording ("replay verified 42/42").</p>`) +
      sec("Damage, repairs and the field", "", `<p class="note">Storms break roof panes (the count is the simulator's): they shatter, stay dark and leak heat while the house is warmer than outside, until a contractor the grower booked is on site; the crew, its trade and its hours worked come from the booking, and the Damage & repairs tab lists the ledger's charges. The coloured field inside each house shows one real reading per house (pick it under ⚙ Controls → View).</p>`) +
      sec("The goal", "", `<p class="note">${esc(D.objective)}</p>`) +
      sec("Score", "", `<p class="note">The benchmark's own score: 0 is the profit of doing nothing, 0.80 is the reference solution, on the same seed. Shown on each panel when its game ends.</p>`),
    update: () => {},
  };

  function openDrawer(t) {
    if (!panels[focus] || !panels[focus].D) return;
    if (t && TABS[t]) tab = t; built = "";
    $("drawer-title").innerHTML = `<span class="swatch" style="background:${SLOT_COLORS[focus]}"></span>Panel ${focus + 1} · ${esc(label(panels[focus].spec))}`;
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
    drawerOpen = true; $("drawer").classList.add("open"); $("drawer").setAttribute("aria-hidden", "false"); $("scrim").hidden = false; renderDrawer();
  }
  function closeDrawer() { drawerOpen = false; $("drawer").classList.remove("open"); $("drawer").setAttribute("aria-hidden", "true"); $("scrim").hidden = true; }


  // ---------------- layouts ----------------
  function setLayout(lay, a = focus, b) {
    layout = lay;
    if (lay === "focus") big = [a, big[1]];
    if (lay === "compare") { const bb = b ?? (big[1] !== a ? big[1] : (a + 1) % 6); big = [a, bb === a ? (a + 1) % 6 : bb]; }
    $("grid").className = `grid6 lay-${lay}`;
    for (const p of panels) {
      const isBig = lay === "focus" ? p.i === big[0] : lay === "compare" ? big.includes(p.i) : false;
      p.el.classList.toggle("big", isBig); p.el.classList.toggle("thumb", lay !== "grid" && !isBig);
      p.el.classList.toggle("b", lay === "compare" && p.i === big[1]);
      if (p.D) showTurn(p, [...p.turns].reverse().find((t) => t.h <= Math.floor(hf)), false);
    }
    document.querySelectorAll("#layout button").forEach((x) => x.classList.toggle("on", x.dataset.lay === lay));
    if (lay !== "grid") select(big[0]);
  }
  function promote(i, shift) {               // a thumbnail was clicked
    if (layout === "focus") setLayout("focus", i);
    else if (layout === "compare") shift ? setLayout("compare", i, big[1]) : setLayout("compare", big[0], i);
  }

  // ---------------- control windows ----------------
  let fps = 0, frames = 0, fpsT = 0, outlines = false, jobPanel = {}, assigned = new Set();
  function applyView() {
    const kind = $("v-field").value, op = +$("v-op").value;
    for (const p of panels) p.scene.settings({ field: { kind, opacity: kind === "none" ? 0 : op }, fog: $("v-fog").checked, pix: +$("v-pix").value,
                                               crisp: $("v-crisp").checked, shadows: $("v-shadow").checked });
    outlines = $("v-outline").checked;
    const F = panels[0] && panels[0].scene.FIELDS[kind];
    $("v-cbar").innerHTML = ""; if (!F) { $("v-cbar").style.background = "none"; return; }
    $("v-cbar").style.background = F.div ? "linear-gradient(90deg,#2673ff,#000 50%,#ff3f1a)" : "linear-gradient(90deg,#000004,#280b54,#65156e,#9f2a63,#d44842,#f57d15,#fac127,#fcffa4)";
    const hi = F.hi ?? (panels.find((x) => x.M) || { M: {} }).M.maxHD;
    $("v-cbar").innerHTML = F.div ? `<span style="left:0">${F.lo}${F.unit}</span><span style="left:42%">in range</span><span style="right:0">+${F.hi}${F.unit}</span>`
      : `<span style="left:0">${F.lo}${F.unit}</span><span style="right:0">${Math.round(hi || 0)}${F.unit}</span>`;
  }
  function perf(dt) {
    frames++; fpsT += dt; if (fpsT < 0.5) return;
    fps = frames / fpsT; frames = 0; fpsT = 0;
    if ($("wins").hidden) return;
    const live = panels.filter((p) => p.D), h = Math.min(Math.floor(hf), hours);
    $("pf-fps").textContent = `${fps.toFixed(0)} fps · ${(1000 / Math.max(1, fps)).toFixed(1)} ms`;
    $("pf-games").textContent = `${live.length} of 6`;
    $("pf-hours").textContent = `${(h * live.length).toLocaleString("en-US")} / ${live.reduce((a, p) => a + p.D.hours, 0).toLocaleString("en-US")}`;
    $("pf-steps").textContent = live.reduce((a, p) => a + p.D.hours * (p.D.substeps || 1), 0).toLocaleString("en-US");
    $("pf-dec").textContent = live.reduce((a, p) => a + p.events.filter((e) => e.dec).length, 0).toLocaleString("en-US");
    $("pf-sim").textContent = `${live.reduce((a, p) => a + p.D.elapsed_s, 0).toFixed(1)} s of compute`;
    const ok = live.filter((p) => p.D.checks && p.D.checks.ok).length;
    $("pf-ledger").innerHTML = `<span class="${ok === live.length ? "good" : "bad"}">${ok}/${live.length} exact</span>`;
  }
  async function pollJobs() {
    try {
      const j = await (await fetch("/api/jobs")).json();
      const dl = $("m-models"); if (j.env_model && !dl.children.length) { dl.innerHTML = `<option value="${esc(j.env_model)}">`; if (!$("m-model").value) $("m-model").value = j.env_model; }
      if (!pollJobs.backendSet) { $("m-backend").value = j.backend; pollJobs.backendSet = true; }
      $("m-jobs").innerHTML = j.jobs.map((x) => `<li><b>${esc(x.model)}</b> · seed ${x.seed} · ${esc(x.scenario)} · <span class="${x.status === "failed" ? "bad" : x.status === "finished" ? "good" : "warn"}">${x.status}</span> · ${Math.floor(x.elapsed_s / 60)}m${x.elapsed_s % 60}s` +
        (x.log.length ? `<pre>${esc(x.log.join("\n"))}</pre>` : "") + `</li>`).join("");
      for (const x of j.jobs) if (x.status === "finished" && x.traces.length && !assigned.has(x.id)) {
        assigned.add(x.id); await loadPlayers(); const p = panels[(jobPanel[x.id] || 2) - 1];
        p.spec = x.traces[0]; p.q(".p-pick").innerHTML = options(p.spec); loadPanel(p);
      }
    } catch (e) { /* server restarting */ }
  }
  $("toggle-win").onclick = () => { $("wins").hidden = !$("wins").hidden; };
  document.querySelectorAll(".win-title").forEach((t) => t.onclick = () => t.parentElement.classList.toggle("closed"));
  ["v-field", "v-op", "v-pix", "v-fog", "v-outline", "v-crisp", "v-shadow"].forEach((id) => $(id).oninput = applyView);
  document.querySelectorAll("#layout button").forEach((b) => b.onclick = () => setLayout(b.dataset.lay));
  $("m-go").onclick = async () => {
    const body = { model: $("m-model").value.trim(), seed: +$("m-seed").value, scenario: $("m-scn").value, backend: $("m-backend").value };
    const r = await fetch("/api/launch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json(); if (!r.ok) { alert(j.error); return; }
    jobPanel[j.id] = +$("m-panel").value; pollJobs();
  };
  setInterval(pollJobs, 5000);
  // ---------------- wiring ----------------
  $("play").onclick = () => { if (!panels.some((p) => p.D)) return; if (hf >= hours) seek(0); playing = !playing; setPlayIcon(); };
  $("next").onclick = nextDecision;
  document.querySelectorAll(".speeds button").forEach((b) => b.onclick = () => {
    speed = +b.dataset.speed; document.querySelectorAll(".speeds button").forEach((x) => x.classList.toggle("on", x === b)); });
  const tl = $("timeline"); let drag = false;
  const tlSeek = (e) => { const r = tl.getBoundingClientRect(); seek(((e.clientX - r.left) / r.width) * hours); };
  tl.onpointerdown = (e) => { drag = true; tl.setPointerCapture(e.pointerId); tlSeek(e); };
  tl.onpointermove = (e) => drag && tlSeek(e);
  tl.onpointerup = () => { drag = false; };
  document.querySelectorAll("[data-open]").forEach((el) => el.onclick = (e) => { e.stopPropagation(); openDrawer(el.dataset.open); });
  document.querySelectorAll("#tabs button").forEach((b) => b.onclick = () => openDrawer(b.dataset.tab));
  document.querySelectorAll("#range button").forEach((b) => b.onclick = () => { range = b.dataset.range; built = "";
    document.querySelectorAll("#range button").forEach((x) => x.classList.toggle("on", x === b)); renderDrawer(); });
  $("close").onclick = closeDrawer; $("scrim").onclick = closeDrawer;
  $("feed").onclick = (e) => { const li = e.target.closest("li[data-h]"); if (li) { seek(+li.dataset.h); playing = false; setPlayIcon(); } };
  $("replay").onclick = () => { seek(0); playing = true; setPlayIcon(); };
  $("done-close").onclick = () => { $("done").hidden = true; };
  $("newrun").onsubmit = (e) => { e.preventDefault(); loadAll(); };
  $("rescan").onclick = async () => { await loadPlayers(); for (const p of panels) p.q(".p-pick").innerHTML = options(p.spec === "model:none" ? (PLAYERS.slots[1]) : p.spec);
    const m = panels.find((p) => p.spec === "model:none"); if (m && PLAYERS.slots[1] !== "model:none") { m.spec = PLAYERS.slots[1]; loadPanel(m); } };
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, select")) return;
    if (e.key === " ") { e.preventDefault(); $("play").click(); }
    else if (e.key === "Escape") { if (drawerOpen) closeDrawer(); else if (layout !== "grid") setLayout("grid"); }
    else if (e.key === "f" || e.key === "F") setLayout(layout === "focus" ? "grid" : "focus", focus);
    else if (e.key === "c" || e.key === "C") setLayout(layout === "compare" ? "grid" : "compare", focus);
    else if (e.key === "n" || e.key === "N") nextDecision();
    else if (e.key === "g" || e.key === "G") $("toggle-win").click();
    else if (e.key >= "1" && e.key <= "6") { const i = +e.key - 1; layout === "grid" ? select(i) : promote(i, e.shiftKey); }
    else if (e.key === "ArrowRight") seek(hf + 24); else if (e.key === "ArrowLeft") seek(hf - 24);
  });
  (async () => { await loadPlayers(); buildPanels(); applyView(); select(0); pollJobs(); await loadAll(); applyView(); })();
  requestAnimationFrame(loop);
})();
