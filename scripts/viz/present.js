// Pitch deck viewer. Keys: Right/Space/PageDown next step, Left/PageUp back, Home/End, N notes, F fullscreen.
// URL hash #N is the slide number. Slides change with a pixel-block dissolve; steps reveal [data-s] elements.
(function () {
  const stage = document.getElementById("stage");
  const cv = document.getElementById("dissolve"), cx = cv.getContext("2d");
  const notesBox = document.getElementById("notes-box");
  const cells = document.getElementById("bar-cells"), count = document.getElementById("count");
  let slides = [], maxStep = [];
  let cur = -1, step = 0, busy = false, showNotes = false;

  // ---- deck/content.md -> slide objects
  function parse(md) {
    md = md.replace(/<!--[\s\S]*?-->/g, "");
    return md.split(/^---\s*$/m).map(b => b.trim()).filter(Boolean).map(b => {
      const sl = { items: [], notes: "" }, lines = b.split(/\r?\n/);
      for (let i = 0; i < lines.length; i++) {
        const l = lines[i];
        if (/^notes:/i.test(l)) { sl.notes = [l.replace(/^notes:\s*/i, ""), ...lines.slice(i + 1)].join(" ").trim(); break; }
        const kv = l.match(/^(\w+):\s*(.*)$/);
        if (kv && !l.startsWith("- ")) sl[kv[1].toLowerCase()] = kv[2].trim();
        else if (l.startsWith("- ")) { const p = l.slice(2).split("|").map(x => x.trim()); sl.items.push({ a: p[0] || "", b: p[1] || "", c: (p[2] || "grey").toLowerCase() }); }
      }
      return sl;
    });
  }
  const el = (tag, cls, txt, parent) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; if (parent) parent.appendChild(e); return e; };

  function build(sl) {
    const sec = el("section", "slide " + (sl.layout || "cards"));
    if (sl.mascot) sec.classList.add("mascot");
    const L = sl.layout || "cards", stepped = sl.steps === "on";
    const tag = (e, n) => { if (stepped) e.dataset.s = n; return e; };
    if (L === "hero") {
      if (sl.image) { const im = el("img", "pic", null, sec); im.src = sl.image; im.alt = ""; }
      el("h2", "", sl.title, sec); if (sl.tag) el("div", "tag", sl.tag, sec);
    } else {
      if (sl.title) el("h2", "", sl.title, sec);
      const body = el("div", "body", null, sec);
      if (L === "stats") sl.items.forEach((it, i) => { const d = tag(el("div", "stat item c-" + it.c, null, body), i + 1); el("b", "", it.a, d); el("span", "", it.b, d); });
      else if (L === "cards") sl.items.forEach((it, i) => { const d = tag(el("div", "card item c-" + it.c, null, body), i + 1); el("h3", "", it.a, d); el("p", "", it.b, d); });
      else if (L === "flow") sl.items.forEach((it, i) => {
        if (i) tag(el("div", "arrow", "→", body), i + 1);
        const d = tag(el("div", "step item c-" + it.c, null, body), i + 1); el("h3", "", it.a, d); el("p", "", it.b, d);
      });
      else if (L === "bars") sl.items.forEach((it, i) => {
        const d = tag(el("div", "bar item c-" + it.c, null, body), i + 1);
        el("span", "nm", it.a, d); const t = el("span", "trk", null, d); el("i", "", null, t).style.setProperty("--v", it.b); el("span", "val", it.b, d);
      });
      else if (L === "image") { const im = el("img", "fig", null, body); im.src = sl.image; im.alt = ""; }
      else if (L === "big") { el("div", "b1", (sl.items[0] || {}).a, body); el("div", "b2", (sl.items[1] || {}).a, body); }
    }
    const n = el("aside", "notes", sl.notes, sec);
    return sec;
  }

  function load(md) {
    const data = parse(md);
    data.forEach(sl => stage.appendChild(build(sl)));
    slides = [...stage.querySelectorAll(".slide")];
    maxStep = slides.map(s => Math.max(0, ...[...s.querySelectorAll("[data-s]")].map(e => +e.dataset.s)));
    slides.forEach((_, i) => { const a = document.createElement("a"); a.href = "#" + (i + 1); cells.appendChild(a); });
    go((parseInt(location.hash.slice(1), 10) || 1) - 1, 0, true);
  }

  function fit() {
    const k = Math.min(innerWidth / 1280, innerHeight / 720);
    stage.style.transform = "scale(" + k + ")";
  }
  addEventListener("resize", fit); fit();

  function paint() {
    slides.forEach((s, i) => s.classList.toggle("on", i === cur));
    slides[cur].querySelectorAll("[data-s]").forEach(e => e.classList.toggle("shown", +e.dataset.s <= step));
    [...cells.children].forEach((a, i) => { a.className = i === cur ? "on" : i < cur ? "done" : ""; });
    count.textContent = String(cur + 1).padStart(2, "0") + " / " + slides.length;
    const n = slides[cur].querySelector(".notes");
    notesBox.hidden = !showNotes; notesBox.textContent = n ? n.textContent : "";
    history.replaceState(null, "", "#" + (cur + 1));
  }

  // pixel-block dissolve: blocks fill in random order (6 frames), the slide swaps, blocks clear (6 frames).
  const W = cv.width, H = cv.height, order = [...Array(W * H).keys()];
  function shuffle() { for (let i = order.length - 1; i > 0; i--) { const j = Math.random() * (i + 1) | 0; [order[i], order[j]] = [order[j], order[i]]; } }
  function dissolve(swap) {
    busy = true; shuffle();
    const bg = "#16202b";
    const F = 6, per = Math.ceil(order.length / F);
    let f = 0, phase = 0;
    cx.fillStyle = bg.trim();
    const t = setInterval(() => {
      f++;
      const lo = (phase === 0 ? f - 1 : f - 1) * per, hi = Math.min(order.length, f * per);
      for (let k = lo; k < hi; k++) { const p = order[k]; if (phase === 0) cx.fillRect(p % W, (p / W) | 0, 1, 1); else cx.clearRect(p % W, (p / W) | 0, 1, 1); }
      if (f === F) {
        if (phase === 0) { swap(); phase = 1; f = 0; shuffle(); } else { clearInterval(t); cx.clearRect(0, 0, W, H); busy = false; }
      }
    }, 40);
  }

  function go(i, s, instant) {
    i = Math.max(0, Math.min(slides.length - 1, i));
    if (i === cur && !instant) { step = s; paint(); return; }
    if (cur < 0 || instant) { cur = i; step = s; paint(); return; }
    dissolve(() => { cur = i; step = s; paint(); });
  }
  const next = () => { if (busy || !slides.length) return; step < maxStep[cur] ? (step++, paint()) : cur < slides.length - 1 && go(cur + 1, 0); };
  const prev = () => { if (busy) return; step > 0 ? (step--, paint()) : cur > 0 && go(cur - 1, maxStep[cur - 1]); };

  addEventListener("keydown", e => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key;
    if (k === "ArrowRight" || k === " " || k === "PageDown" || k === "Enter") { e.preventDefault(); next(); }
    else if (k === "ArrowLeft" || k === "PageUp" || k === "Backspace") { e.preventDefault(); prev(); }
    else if (k === "Home") go(0, 0);
    else if (k === "End") go(slides.length - 1, 0);
    else if (k === "n" || k === "N") { showNotes = !showNotes; paint(); }
    else if (k === "f" || k === "F") { document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen && document.documentElement.requestFullscreen(); }
  });
  document.addEventListener("click", e => {
    if (e.target.closest("#bar") || e.target.closest("#notes-box")) return;
    e.clientX < innerWidth / 3 ? prev() : next();
  });
  addEventListener("hashchange", () => { const n = (parseInt(location.hash.slice(1), 10) || 1) - 1; if (n !== cur) go(n, 0); });

  fetch("deck/content.md", { cache: "no-store" }).then(r => r.text()).then(load);
})();
