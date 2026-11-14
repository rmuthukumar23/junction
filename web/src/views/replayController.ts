// Replay screen controller, ported as is from scripts/pixel/app.js (startReplay). It renders into a
// host element and returns a teardown. Step 4 of the pixel-site plan replaces it with React components.
import { Sprites as S } from "../legacy/sprites";
import { PixelScene } from "../legacy/scene";
import { rafLoop } from "../lib/loop";
import { clamp, esc, eur, lowerBound as lb, num, when } from "../lib/format";
import { query as Q } from "../lib/route";
import type { Replay, SimEvent } from "../lib/types";

const P = S.P;

export function mountReplay(root: HTMLElement, D: Replay): () => void {
  D.frames.forEach((f) => { if (f.day == null) f.day = Math.floor(f.h / 24) + 1; if (f.hod == null) f.hod = f.h % 24; });
  D.actions = D.actions || []; D.events = (D.events || []).slice().sort((a, b) => a.h - b.h); D.alarms = D.alarms || []; D.daily = D.daily || [];
  const meta = D.meta, last = D.frames.length - 1, mas = S.mascotFor(meta);
  root.innerHTML = `<div class="replay"><div class="stagebox">
    <div class="hud" id="hud"></div>
    <div class="stage" id="stage"><canvas id="cv"></canvas><div class="toasts" id="toasts"></div><div class="done" id="done" hidden></div></div>
    <div class="controls"><div class="scrub" id="scrub"><div class="fill" id="fill"></div></div>
      <div class="ctl" id="ctl"><button class="px-btn" id="play">PLAY</button><button class="px-btn sm" data-s="-24">-1D</button><button class="px-btn sm" data-s="-1">-1H</button><button class="px-btn sm" data-s="1">+1H</button><button class="px-btn sm" data-s="24">+1D</button>
      <button class="px-btn sm" id="pe">[ PREV EVT</button><button class="px-btn sm" id="ne">NEXT EVT ]</button><span class="grow"></span><span class="dim">H/S</span>
      ${[1, 4, 12, 48].map((s) => `<button class="px-btn sm spd" data-v="${s}">${s}x</button>`).join("")}</div></div></div>
    <div class="side"><div class="px-panel"><div style="display:flex;gap:10px;align-items:center" id="who"></div></div>
      <div class="px-panel insp" id="insp"><h3 class="px-title">Inspector</h3><div class="dim">Click a greenhouse or the energy centre.</div></div>
      <div class="px-panel"><div class="tabs" id="tabs"><button class="px-btn sm on" data-t="actions">Actions</button><button class="px-btn sm" data-t="events">Events</button><button class="px-btn sm" data-t="alarms">Alarms</button></div><div class="list" id="list"></div></div></div></div>`;
  const $ = (i: string) => root.querySelector("#" + i) as HTMLElement;
  const all = (sel: string) => root.querySelectorAll<HTMLElement>(sel);
  const tip = document.getElementById("tip") as HTMLElement;
  const tipShow = (x: number, y: number, html: string) => { tip.hidden = false; tip.innerHTML = html; tip.style.left = Math.min(innerWidth - 340, x + 12) + "px"; tip.style.top = y + 14 + "px"; };
  const tipHide = () => { tip.hidden = true; };
  const cv = $("cv") as HTMLCanvasElement, stage = $("stage");
  const sc = PixelScene.create(cv, {}); sc.setData(D);
  $("who").append(S.mascotCanvas(mas, 4), Object.assign(document.createElement("div"), { innerHTML: `<div class="px-title" style="margin:0">${esc(meta.label || meta.model || meta.id)}</div><div class="dim">${esc(meta.kind)} / seed ${esc(meta.seed)} / ${esc(meta.scenario)}</div><div><span class="px-tag ${meta.status === "complete" ? "good" : "warn"}">${esc(meta.status)}</span> <span class="px-tag">${meta.replay_verified ? "replay verified" : "unverified"}</span></div>` }));
  const R = { hf: 0, playing: true, speed: 4, lastH: 0, tab: "actions", insp: null as string | null, listAt: 0, done: false, force: true };

  let tk = "";
  for (let d = 1; d < 42; d++) tk += `<i class="day" style="left:${((d * 24) / last) * 100}%"></i>`;
  D.events.forEach((e) => (tk += `<i class="tick ${e.severity || "info"}" style="left:${(e.h / last) * 100}%"></i>`));
  $("scrub").insertAdjacentHTML("beforeend", tk + '<div class="head" id="head"></div>');

  function fit() { const avail = ($("hud").parentElement as HTMLElement).clientWidth - 8, s = Math.floor(avail / 480), w = s >= 1 ? 480 * s : avail; cv.style.width = w + "px"; cv.style.height = (w * 270) / 480 + "px"; stage.style.width = w + 8 + "px"; }
  fit(); window.addEventListener("resize", fit);

  const frameNow = () => D.frames[clamp(Math.floor(R.hf), 0, last)];
  const timers = new Set<number>();
  const later = (fn: () => void, ms: number) => { const t = window.setTimeout(() => { timers.delete(t); fn(); }, ms); timers.add(t); };
  function toast(e: { h: number; text?: string; kind: string; severity?: string }) {
    const sev = e.severity || (e.kind === "alarm" ? "bad" : "info"); if (R.speed > 12 && sev === "info") return;
    const t = $("toasts"), d = document.createElement("div"); d.className = "toast " + sev; d.textContent = when(e.h) + "  " + (e.text || e.kind);
    t.appendChild(d); while (t.children.length > 4) (t.firstChild as ChildNode).remove(); later(() => d.remove(), 4200);
  }
  function fire(from: number, to: number) {
    if (to < from || to - from > 60) { sc.reset(to); R.force = true; return; }
    for (let i = lb(D.events, from + 1); i < D.events.length && D.events[i].h <= to; i++) { sc.trigger(D.events[i]); toast(D.events[i]); }
    for (let i = lb(D.alarms, from + 1); i < D.alarms.length && D.alarms[i].h <= to; i++) { const a = D.alarms[i]; toast({ h: a.h, text: a.text, kind: "alarm", severity: "bad" }); sc.flash(a.target, P.bad); }
    const a0 = lb(D.actions, from + 1), a1 = lb(D.actions, to + 1), n = Math.min(3, a1 - a0);
    for (let k = 0; k < n; k++) {
      const a = D.actions[a1 - n + k], args = (a.args || {}) as Record<string, unknown>, arg = args.compartment || args.target || args.batch_id || args.item || "";
      later(() => sc.bubble("worker", a.tool.replace(/_/g, " ") + (arg ? " " + arg : ""), a.ok ? P.white : P.bad), k * 700);
    }
  }
  function seek(h: number) { R.hf = clamp(h, 0, last); R.done = false; $("done").hidden = true; R.force = true; }
  function nextEvent(dir: number) {
    const h = Math.floor(R.hf);
    if (dir > 0) { for (const e of D.events) if (e.h > h) return seek(e.h); }
    else for (let i = D.events.length - 1; i >= 0; i--) if (D.events[i].h < h) return seek(D.events[i].h);
  }
  function hud() {
    const f = frameNow(), m = f.money || {}, p = m.profit_so_far_eur, base = meta.baseline_profit_eur, calls = lb(D.actions, f.h + 1);
    $("hud").innerHTML = `<div class="cell"><div class="k">Day</div><div class="v">${f.day}/42</div></div><div class="cell"><div class="k">Clock</div><div class="v">${String(f.hod).padStart(2, "0")}:00</div></div>
      <div class="cell"><div class="k">Outside</div><div class="v">${f.out.t.toFixed(1)}C</div></div><div class="cell"><div class="k">Cash</div><div class="v">${eur(m.cash_eur)}</div></div>
      <div class="cell"><div class="k">Profit</div><div class="v ${(p ?? 0) >= 0 ? "good" : "bad"}">${eur(p)}</div></div><div class="cell"><div class="k">Do-nothing final</div><div class="v dim">${eur(base)}</div></div>
      <div class="cell"><div class="k">Actions</div><div class="v">${calls}</div></div>`;
  }
  function lists() {
    const f = frameNow(), now = f.h, host = $("list"); let html = "";
    if (R.tab === "actions") {
      for (let i = lb(D.actions, now + 1) - 1, n = 0; i >= 0 && n < 70; i--, n++) {
        const a = D.actions[i]; if (a.day < f.day - 1) break;
        html += `<div class="it ${a.day === f.day ? "cur" : ""} ${a.ok ? "" : "err"}"><span class="when">${when(a.h)}</span><b>${esc(a.tool)}</b> ${esc(JSON.stringify(a.args || {}))} ${a.ok ? "" : "ERR " + esc(a.err)}</div>`;
      }
    } else if (R.tab === "events") {
      for (let i = lb(D.events, now + 1) - 1, n = 0; i >= 0 && n < 60; i--, n++) {
        const e: SimEvent = D.events[i];
        html += `<div class="it ${e.severity === "bad" ? "err" : ""}"><span class="when">${when(e.h)}</span><span class="px-tag ${e.severity === "warn" ? "warn" : e.severity === "bad" ? "bad" : "info"}">${esc(e.kind)}</span> ${esc(e.text)}</div>`;
      }
    } else for (let i = lb(D.alarms, now + 1) - 1, n = 0; i >= 0 && n < 60; i--, n++) { const a = D.alarms[i]; html += `<div class="it err"><span class="when">${when(a.h)}</span>${esc(a.text)}</div>`; }
    host.innerHTML = html || '<div class="dim">Nothing yet.</div>';
  }
  function inspector() {
    const id = R.insp, host = $("insp"), f = frameNow(); if (!id) return;
    let h = `<h3 class="px-title">${id === "energy" ? "Energy centre" : "House " + esc(id) + " / " + esc((meta.compartments || {})[id]?.crop)}</h3>`;
    if (id === "energy") {
      const e = f.ec;
      h += `<table><tr><td>Heat buffer</td><td class="n">${num(e.buffer)} kWh</td></tr><tr><td>CO2 tank</td><td class="n">${num(e.co2)} kg</td></tr><tr><td>CHP load</td><td class="n">${num((e.chp || 0) * 100)}%</td></tr><tr><td>Boiler</td><td class="n">${esc(e.boiler)}</td></tr><tr><td>Grid</td><td class="n">${(e.imp ?? 0) > 0.5 ? "buy " + num(e.imp) : (e.exp ?? 0) > 0.5 ? "sell " + num(e.exp) : "idle"} kWh</td></tr><tr><td>Gas</td><td class="n">${num(e.gas, 1)} m3/h</td></tr><tr><td>Faults</td><td class="n ${f.faults.length ? "bad" : "good"}">${f.faults.length ? esc(f.faults.join(", ")) : "none"}</td></tr></table>`;
    } else {
      const c = f.c[id]; if (!c) return;
      h += `<table><tr><td>Temp</td><td class="n">${c.t}C (set ${c.sp_night}-${c.sp_day})</td></tr><tr><td>Humidity</td><td class="n">${num(c.rh)}%</td></tr><tr><td>CO2</td><td class="n">${num(c.co2)} ppm (set ${c.sp_co2})</td></tr><tr><td>PAR</td><td class="n">${num(c.par)}</td></tr><tr><td>Vent</td><td class="n">${num(c.vent)}%</td></tr><tr><td>Screen</td><td class="n">${c.screen ? "closed" : "open"}</td></tr><tr><td>Lamps</td><td class="n">${num(c.lamp, 1)} kW</td></tr><tr><td>Heat</td><td class="n">${num(c.heat, 1)} kW</td></tr></table>`;
      h += `<table style="margin-top:6px"><tr><th>Batch</th><th>State</th><th class="n">Age</th><th class="n">Q</th></tr>${f.b.filter((b) => b.c === id && b.st !== "harvested").map((b) => `<tr><td>${esc(b.id)}</td><td>${esc(b.st)}</td><td class="n">${num(b.age, 1)}d</td><td class="n">${num(b.qual * 100)}%</td></tr>`).join("")}</table>`;
    }
    host.innerHTML = h;
  }
  function showDone() {
    const f = D.frames[last], p = f.money.profit_so_far_eur ?? null, base = meta.baseline_profit_eur, d = $("done");
    d.innerHTML = `<div class="px-panel"><h2 class="px-title">42 days done</h2><div class="big ${(p ?? 0) >= 0 ? "good" : "bad"}" style="font-size:22px">${eur(p)}</div><p>Do-nothing baseline ${eur(base)}${p != null && base != null ? `<br><span class="${p - base >= 0 ? "good" : "bad"}">${eur(p - base, true)} vs baseline</span>` : ""}${meta.score != null ? `<br>SCORE ${num(meta.score, 2)}` : ""}</p><button class="px-btn primary" id="again">Watch again</button></div>`;
    d.hidden = false;
    $("again").onclick = () => { seek(0); sc.reset(0); R.playing = true; setPlay(); R.lastH = 0; };
  }
  function setPlay() { $("play").textContent = R.playing ? "PAUSE" : "PLAY"; }
  function setSpeed() { all(".spd").forEach((b) => b.classList.toggle("on", +(b.dataset.v as string) === R.speed)); }
  setPlay(); setSpeed();

  $("play").onclick = () => { if (R.hf >= last) seek(0); R.playing = !R.playing; setPlay(); };
  all("#ctl [data-s]").forEach((b) => (b.onclick = () => { R.playing = false; setPlay(); seek(Math.floor(R.hf) + +(b.dataset.s as string)); }));
  all(".spd").forEach((b) => (b.onclick = () => { R.speed = +(b.dataset.v as string); setSpeed(); }));
  $("pe").onclick = () => nextEvent(-1); $("ne").onclick = () => nextEvent(1);
  all("#tabs [data-t]").forEach((b) => (b.onclick = () => { R.tab = b.dataset.t as string; all("#tabs [data-t]").forEach((x) => x.classList.toggle("on", x === b)); R.force = true; }));
  const sb = $("scrub"); let drag = false;
  const sbH = (e: PointerEvent) => clamp(((e.clientX - sb.getBoundingClientRect().left) / sb.clientWidth) * last, 0, last);
  sb.onpointerdown = (e) => { drag = true; sb.setPointerCapture(e.pointerId); seek(sbH(e)); };
  sb.onpointermove = (e) => {
    if (drag) seek(sbH(e));
    const h = sbH(e), i = lb(D.events, h), px = sb.clientWidth / last; let best: SimEvent | null = null, bd = 9;
    for (let k = Math.max(0, i - 3); k < Math.min(D.events.length, i + 3); k++) { const d = Math.abs(D.events[k].h - h) * px; if (d < bd) { bd = d; best = D.events[k]; } }
    tipShow(e.clientX, e.clientY - 60, best ? `<b>${when(best.h)}</b> ${esc(best.kind)}<br>${esc(best.text)}` : when(Math.round(h)));
  };
  sb.onpointerup = () => (drag = false); sb.onpointerleave = tipHide;
  const toScene = (e: PointerEvent) => { const r = cv.getBoundingClientRect(); return sc.hit(((e.clientX - r.left) / r.width) * 480, ((e.clientY - r.top) / r.height) * 270); };
  cv.addEventListener("pointerdown", (e) => { const id = toScene(e); R.insp = id; R.force = true; if (!id) $("insp").innerHTML = '<h3 class="px-title">Inspector</h3><div class="dim">Click a greenhouse or the energy centre.</div>'; });
  cv.addEventListener("pointermove", (e) => sc.setHover(toScene(e)));
  cv.addEventListener("pointerleave", () => sc.setHover(null));
  const onKey = (e: KeyboardEvent) => {
    if (/INPUT|SELECT|TEXTAREA/.test((e.target as HTMLElement).tagName)) return;
    if (e.key === " ") { e.preventDefault(); $("play").click(); }
    else if (e.key === "ArrowRight" || e.key === "ArrowLeft") { R.playing = false; setPlay(); seek(Math.floor(R.hf) + (e.key === "ArrowRight" ? 1 : -1) * (e.shiftKey ? 24 : 1)); }
    else if (e.key === "[") nextEvent(-1); else if (e.key === "]") nextEvent(1); else if (e.key === "Escape") R.insp = null;
  };
  document.addEventListener("keydown", onKey);
  if (Q.get("at")) seek(+(Q.get("at") as string));
  if (Q.get("pause")) { R.playing = false; setPlay(); }
  if (Q.get("speed")) { R.speed = +(Q.get("speed") as string); setSpeed(); }
  if (Q.get("open")) R.insp = Q.get("open");
  R.lastH = Math.floor(R.hf); sc.reset(R.hf);

  const stop = rafLoop((dt, now) => {
    if (R.playing) { R.hf = Math.min(last, R.hf + dt * R.speed); if (R.hf >= last && !R.done) { R.done = true; R.playing = false; setPlay(); showDone(); } }
    const h = Math.floor(R.hf); let changed = R.force;
    if (h !== R.lastH) { fire(R.lastH, h); R.lastH = h; changed = true; }
    sc.render(R.hf, dt, R.speed, R.playing);
    if (changed || (R.playing && now - R.listAt > 250)) { R.listAt = now; hud(); if (changed) lists(); if (R.insp) inspector(); R.force = false; }
    $("fill").style.width = $("head").style.left = (R.hf / last) * 100 + "%";
  });
  return () => {
    stop(); timers.forEach((t) => clearTimeout(t)); document.removeEventListener("keydown", onKey);
    window.removeEventListener("resize", fit); tipHide(); root.innerHTML = "";
  };
}
