// First-visit tour for the hosted demo: one highlighted area at a time, an arrow and a line of
// text. ✕ or "Done" hides it for good (remembered in this browser); the "?" button in the header
// replays it. Added to the page by scripts/build_static_demo.py.
(() => {
  const KEY = "lettucebench-tour-done";
  const STEPS = [
    { sel: "#grid .big canvas", title: "A greenhouse, hour by hour", text: "The reference planner's farm, simulated live. Click a greenhouse or the energy centre to see its charts." },
    { sel: "#grid .big .p-pick", title: "Who is playing", text: "Pick who runs this farm: the planner, a simple baseline, or a recorded AI run (Gemini, Sonnet)." },
    { sel: "#grid .big .p-money", title: "Profit so far", text: "Money made since day 1. The game is scored on this alone." },
    { sel: "#grid .big .p-decision", title: "This morning's decisions", text: "What the grower did at 06:00 today. ✓ accepted, ✗ refused." },
    { sel: "#grid .thumb", title: "The other growers", text: "Same weather, same prices. Click one to make it big." },
    { sel: "#standings", title: "Standings", text: "Who is ahead right now. Click a name to select it." },
    { sel: "#cards", title: "The selected farm", text: "Money, weather, each house and the energy centre. Click a card for its charts." },
    { sel: "#feed", title: "Decisions and events", text: "Every decision, sale, delivery and breakdown as it happens." },
    { sel: "#timeline", title: "Timeline", text: "Drag to any of the 42 days. Each tick is a decision." },
    { sel: ".speeds", title: "Speed", text: "Watch at half speed up to 10×." },
    { sel: "#layout", title: "Layout", text: "One big farm, all six, or two side by side." },
  ];
  const seen = () => { try { return localStorage.getItem(KEY) === "1"; } catch { return false; } };
  const remember = () => { try { localStorage.setItem(KEY, "1"); } catch { /* private mode */ } };

  const css = document.createElement("style");
  css.textContent = `
    .tour-spot { position: fixed; z-index: 9998; border: 2px solid #7bd88f; border-radius: 8px;
      box-shadow: 0 0 0 9999px rgba(6, 8, 13, 0.72); pointer-events: none; transition: all .25s ease; }
    .tour-tip { position: fixed; z-index: 9999; width: 300px; background: #161b26; color: #e9edf3;
      border: 2px solid #7bd88f; border-radius: 8px; padding: 14px 16px 12px; font-family: inherit;
      box-shadow: 0 8px 30px rgba(0,0,0,.5); transition: top .25s ease, left .25s ease; }
    .tour-tip h4 { margin: 0 24px 6px 0; font-size: 15px; color: #7bd88f; }
    .tour-tip p { margin: 0 0 12px; font-size: 13px; line-height: 1.45; }
    .tour-tip .tour-x { position: absolute; top: 6px; right: 8px; background: none; border: 0; color: #8d97a8;
      font-size: 18px; cursor: pointer; }
    .tour-tip .tour-x:hover { color: #e9edf3; }
    .tour-tip .tour-row { display: flex; align-items: center; gap: 8px; }
    .tour-tip .tour-n { color: #8d97a8; font-size: 12px; margin-right: auto; }
    .tour-tip button.tb { background: #1d2433; color: #e9edf3; border: 1px solid #2a3242; border-radius: 6px;
      padding: 5px 12px; font-family: inherit; font-size: 13px; cursor: pointer; }
    .tour-tip button.tb.go { background: #7bd88f; color: #0e1119; border-color: #7bd88f; }
    .tour-arrow { position: fixed; z-index: 9999; width: 0; height: 0; border: 10px solid transparent; pointer-events: none;
      transition: top .25s ease, left .25s ease; }
    .tour-help { margin-left: 8px; }`;
  document.head.appendChild(css);

  let i = 0, spot, tip, arrow;
  function close(forever) {
    [spot, tip, arrow].forEach((e) => e && e.remove()); spot = tip = arrow = null;
    window.removeEventListener("resize", place);
    if (forever) remember();
  }
  function place() {
    const step = STEPS[i], el = document.querySelector(step.sel);
    if (!el) { i < STEPS.length - 1 ? (i++, place()) : close(true); return; }
    const r = el.getBoundingClientRect(), pad = 6;
    Object.assign(spot.style, { top: `${r.top - pad}px`, left: `${r.left - pad}px`, width: `${r.width + 2 * pad}px`, height: `${r.height + 2 * pad}px` });
    tip.querySelector("h4").textContent = step.title;
    tip.querySelector("p").textContent = step.text;
    tip.querySelector(".tour-n").textContent = `${i + 1} / ${STEPS.length}`;
    tip.querySelector(".back").style.visibility = i ? "visible" : "hidden";
    tip.querySelector(".go").textContent = i === STEPS.length - 1 ? "Done" : "Next";
    const tw = 300, th = tip.offsetHeight || 140, gap = 16, vw = innerWidth, vh = innerHeight;
    let side = r.bottom + gap + th < vh ? "below" : r.top - gap - th > 0 ? "above" : r.right + gap + tw < vw ? "right" : "left";
    let top, left;
    if (side === "below" || side === "above") {
      top = side === "below" ? r.bottom + gap : r.top - gap - th;
      left = Math.min(Math.max(12, r.left + r.width / 2 - tw / 2), vw - tw - 12);
    } else {
      left = side === "right" ? r.right + gap : r.left - gap - tw;
      top = Math.min(Math.max(12, r.top + r.height / 2 - th / 2), vh - th - 12);
    }
    Object.assign(tip.style, { top: `${top}px`, left: `${left}px` });
    const c = "#7bd88f", a = arrow.style;
    a.borderColor = "transparent";
    if (side === "below") { a.top = `${top - 20}px`; a.left = `${Math.min(Math.max(left + 14, r.left + r.width / 2 - 10), left + tw - 34)}px`; a.borderBottomColor = c; }
    if (side === "above") { a.top = `${top + th}px`; a.left = `${Math.min(Math.max(left + 14, r.left + r.width / 2 - 10), left + tw - 34)}px`; a.borderTopColor = c; }
    if (side === "right") { a.left = `${left - 20}px`; a.top = `${Math.min(Math.max(top + 14, r.top + r.height / 2 - 10), top + th - 34)}px`; a.borderRightColor = c; }
    if (side === "left") { a.left = `${left + tw}px`; a.top = `${Math.min(Math.max(top + 14, r.top + r.height / 2 - 10), top + th - 34)}px`; a.borderLeftColor = c; }
  }
  function open() {
    close(false); i = 0;
    spot = Object.assign(document.createElement("div"), { className: "tour-spot" });
    arrow = Object.assign(document.createElement("div"), { className: "tour-arrow" });
    tip = Object.assign(document.createElement("div"), { className: "tour-tip" });
    tip.innerHTML = `<button class="tour-x" title="Close and don't show again" aria-label="Close tour">✕</button><h4></h4><p></p>
      <div class="tour-row"><span class="tour-n"></span><button class="tb back">Back</button><button class="tb go">Next</button></div>`;
    document.body.append(spot, arrow, tip);
    tip.querySelector(".tour-x").onclick = () => close(true);
    tip.querySelector(".back").onclick = () => { i = Math.max(0, i - 1); place(); };
    tip.querySelector(".go").onclick = () => { if (i === STEPS.length - 1) close(true); else { i++; place(); } };
    window.addEventListener("resize", place);
    requestAnimationFrame(place);
  }
  document.addEventListener("keydown", (e) => { if (tip && e.key === "Escape") { e.stopPropagation(); close(true); } }, true);

  // A "?" button in the header replays the tour.
  const bar = document.getElementById("newrun");
  if (bar) {
    const b = Object.assign(document.createElement("button"), { type: "button", className: "btn tour-help", textContent: "? Tour", title: "Show the tour again" });
    b.onclick = open; bar.appendChild(b);
  }
  // First visit only: wait until the games have loaded and the big panel exists.
  if (!seen()) {
    const t0 = Date.now();
    const wait = setInterval(() => {
      const ready = document.querySelector("#grid .big canvas") && document.querySelector("#standings li");
      if (ready || Date.now() - t0 > 20000) { clearInterval(wait); if (ready) setTimeout(open, 600); }
    }, 300);
  }
})();
