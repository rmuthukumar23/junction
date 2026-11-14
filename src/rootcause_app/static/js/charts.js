// @ts-check
/**
 * Charts, drawn as plain SVG and HTML.
 *
 * One y-axis per chart, always: measures with different units get separate small charts.
 * Marks are thin (2px lines, 8px end dots with a surface ring), grid and axes are hairlines,
 * and text uses ink tokens, never a series color. Every line chart has a crosshair that
 * snaps to the nearest day and one tooltip listing every series; arrow keys move it too.
 * Callers put the same numbers in a table, so nothing is reachable only by hovering.
 */
import { h, s, fmt } from "./dom.js";

/** @typedef {{name: string, color: string, values: (number|null)[], dashed?: boolean}} Series */
/** @typedef {{value: number, label: string}} RefLine */

/** @param {number} lo @param {number} hi @param {number} count */
function niceTicks(lo, hi, count) {
  if (!(hi > lo)) hi = lo + 1;
  const raw = (hi - lo) / Math.max(1, count);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((m) => m >= raw) || 10 * mag;
  const first = Math.floor(lo / step) * step;
  const ticks = [];
  for (let v = first; v <= hi + step * 0.999; v += step) ticks.push(Number(v.toFixed(10)));
  return ticks;
}

/**
 * @param {{
 *   title: string, unit?: string, xs: number[], series: Series[], refs?: RefLine[],
 *   width?: number, height?: number, yMin?: number, yMax?: number, xLabel?: string,
 *   format?: (v: number) => string, marker?: number | null, onPick?: (x: number) => void,
 *   xMax?: number,
 * }} o
 */
export function lineChart(o) {
  const width = o.width || 300, height = o.height || 132;
  const format = o.format || fmt.two;
  const multi = o.series.length > 1;
  const pad = { l: 38, r: multi ? 58 : 14, t: 8, b: 20 };
  const xs = o.xs;
  const x0 = xs.length ? xs[0] : 0;
  const x1 = Math.max(o.xMax ?? x0, xs.length ? xs[xs.length - 1] : x0, x0 + 1);
  const all = o.series.flatMap((se) => se.values.filter((v) => v !== null && v !== undefined)).map(Number);
  const refs = o.refs || [];
  let lo = Math.min(...all, ...refs.map((r) => r.value)), hi = Math.max(...all, ...refs.map((r) => r.value));
  if (!Number.isFinite(lo)) { lo = 0; hi = 1; }
  if (o.yMin !== undefined) lo = Math.min(lo, o.yMin);
  if (o.yMax !== undefined) hi = Math.max(hi, o.yMax);
  const ticks = niceTicks(lo, hi, 3);
  lo = ticks[0]; hi = ticks[ticks.length - 1];
  const px = (/** @type {number} */ x) => pad.l + ((x - x0) / (x1 - x0)) * (width - pad.l - pad.r);
  const py = (/** @type {number} */ y) => height - pad.b - ((y - lo) / (hi - lo)) * (height - pad.t - pad.b);

  const svg = s("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": `${o.title}${o.unit ? `, ${o.unit}` : ""}. Use left and right arrow keys to read values.`, tabindex: "0", class: "chart-svg" });
  for (const t of ticks) {
    svg.append(s("line", { x1: pad.l, x2: width - pad.r, y1: py(t), y2: py(t), class: t === lo ? "axis" : "grid" }));
    svg.append(s("text", { x: pad.l - 6, y: py(t) + 3.5, class: "tick", "text-anchor": "end" }, format(t)));
  }
  const xStep = x1 - x0 > 8 ? 2 : 1;
  for (let x = Math.ceil(x0); x <= x1; x += xStep) {
    svg.append(s("text", { x: px(x), y: height - 5, class: "tick", "text-anchor": "middle" }, String(x)));
  }
  for (const r of refs) {
    svg.append(s("line", { x1: pad.l, x2: width - pad.r, y1: py(r.value), y2: py(r.value), class: "ref" }));
    svg.append(s("text", { x: pad.l + 4, y: py(r.value) - 4, class: "ref-label" }, r.label));
  }
  if (o.marker !== null && o.marker !== undefined && o.marker >= x0 && o.marker <= x1) {
    svg.append(s("line", { x1: px(o.marker), x2: px(o.marker), y1: pad.t, y2: height - pad.b, class: "marker" }));
  }

  /** @type {{y: number, name: string}[]} */
  const ends = [];
  for (const se of o.series) {
    const pts = se.values.map((v, i) => (v === null || v === undefined ? null : [px(xs[i]), py(v)]));
    let d = "", pen = false;
    for (const p of pts) {
      if (!p) { pen = false; continue; }
      d += `${pen ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`;
      pen = true;
    }
    svg.append(s("path", { d, class: "series", style: `stroke:${se.color}`, "stroke-dasharray": se.dashed ? "4 3" : null }));
    const last = [...pts].reverse().find(Boolean);
    if (last) {
      svg.append(s("circle", { cx: last[0], cy: last[1], r: 4, class: "end-dot", style: `fill:${se.color}` }));
      ends.push({ y: last[1], name: se.name });
    }
  }
  // Direct end labels only where they will not collide; the legend carries identity either way.
  if (multi && ends.length <= 4) {
    const sorted = [...ends].sort((a, b) => a.y - b.y);
    const clear = sorted.every((e, i) => i === 0 || e.y - sorted[i - 1].y >= 12);
    if (clear) for (const e of ends) svg.append(s("text", { x: width - pad.r + 8, y: e.y + 3.5, class: "end-label" }, e.name));
  }

  const hair = s("line", { y1: pad.t, y2: height - pad.b, class: "crosshair", visibility: "hidden" });
  const dots = o.series.map((se) => s("circle", { r: 4, class: "end-dot", style: `fill:${se.color}`, visibility: "hidden" }));
  svg.append(hair, ...dots);
  const tip = h("div", { class: "chart-tip", hidden: true, role: "status" });
  const plot = h("div", { class: "chart-plot" }, svg, tip);

  let index = -1;
  /** @param {number} i */
  const show = (i) => {
    index = Math.max(0, Math.min(xs.length - 1, i));
    const x = px(xs[index]);
    hair.setAttribute("x1", String(x)); hair.setAttribute("x2", String(x)); hair.setAttribute("visibility", "visible");
    const rows = [];
    o.series.forEach((se, k) => {
      const v = se.values[index];
      if (v === null || v === undefined) { dots[k].setAttribute("visibility", "hidden"); return; }
      dots[k].setAttribute("cx", String(x)); dots[k].setAttribute("cy", String(py(v))); dots[k].setAttribute("visibility", "visible");
      rows.push(h("div", { class: "tip-row" }, h("i", { class: "key", style: `background:${se.color}` }),
        h("b", {}, format(v) + (o.unit ? ` ${o.unit}` : "")), multi ? h("span", {}, se.name) : null));
    });
    tip.replaceChildren(h("div", { class: "tip-head" }, `${o.xLabel || "Day"} ${xs[index]}`), ...rows);
    tip.hidden = false;
    const frac = x / width;
    tip.style.left = frac > 0.55 ? "" : `calc(${(frac * 100).toFixed(1)}% + 10px)`;
    tip.style.right = frac > 0.55 ? `calc(${((1 - frac) * 100).toFixed(1)}% + 10px)` : "";
  };
  const hide = () => {
    index = -1; tip.hidden = true; hair.setAttribute("visibility", "hidden");
    dots.forEach((d) => d.setAttribute("visibility", "hidden"));
  };
  /** @param {PointerEvent} ev */
  const nearest = (ev) => {
    const box = svg.getBoundingClientRect();
    const x = ((ev.clientX - box.left) / box.width) * width;
    let best = 0;
    xs.forEach((v, i) => { if (Math.abs(px(v) - x) < Math.abs(px(xs[best]) - x)) best = i; });
    return best;
  };
  if (xs.length) {
    svg.addEventListener("pointermove", (ev) => show(nearest(/** @type {PointerEvent} */ (ev))));
    svg.addEventListener("pointerleave", hide);
    svg.addEventListener("blur", hide);
    svg.addEventListener("click", (ev) => { if (o.onPick) o.onPick(xs[nearest(/** @type {PointerEvent} */ (ev))]); });
    svg.addEventListener("keydown", (ev) => {
      const key = /** @type {KeyboardEvent} */ (ev).key;
      if (key === "ArrowRight" || key === "ArrowLeft") {
        ev.preventDefault();
        show(index < 0 ? xs.length - 1 : index + (key === "ArrowRight" ? 1 : -1));
      } else if (key === "Enter" && o.onPick && index >= 0) o.onPick(xs[index]);
      else if (key === "Escape") hide();
    });
  }

  const legend = multi
    ? h("div", { class: "legend" }, o.series.map((se) => h("span", {}, h("i", { class: "line", style: `background:${se.color}` }), se.name)))
    : null;
  return h("figure", { class: "chart" },
    h("figcaption", {}, h("b", {}, o.title), o.unit ? h("span", { class: "muted" }, ` ${o.unit}`) : null), legend, plot);
}

/**
 * A word-sized trend line. Decorative: the caller states the values in text.
 * Pass `domain` so sparklines that sit side by side share one scale and a small
 * wobble is not drawn as a cliff.
 * @param {number[]} values @param {{width?: number, height?: number, domain?: [number, number]}} [o]
 */
export function sparkline(values, o = {}) {
  const width = o.width || 56, height = o.height || 22, m = 4;
  const svg = s("svg", { viewBox: `0 0 ${width} ${height}`, width, height, class: "spark", "aria-hidden": "true" });
  if (values.length < 2) return svg;
  const lo = Math.min(...values, ...(o.domain || [])), hi = Math.max(...values, ...(o.domain || []));
  const px = (/** @type {number} */ i) => m + (i / (values.length - 1)) * (width - 2 * m);
  const py = (/** @type {number} */ v) => (hi > lo ? height - m - ((v - lo) / (hi - lo)) * (height - 2 * m) : height / 2);
  svg.append(s("path", { d: values.map((v, i) => `${i ? "L" : "M"}${px(i).toFixed(1)},${py(v).toFixed(1)}`).join(""), class: "series spark-line" }));
  svg.append(s("circle", { cx: px(values.length - 1), cy: py(values[values.length - 1]), r: 3, class: "end-dot spark-dot" }));
  return svg;
}

/**
 * Ranked horizontal bars with the value at the tip. One series, one color; one row can be emphasized.
 * @param {{label: string, value: number, note?: string, emphasis?: boolean, detail?: string}[]} rows
 * @param {{format?: (v: number) => string, max?: number}} [o]
 */
export function barRows(rows, o = {}) {
  const format = o.format || fmt.eur0;
  const max = Math.max(o.max || 0, ...rows.map((r) => r.value), 1);
  return h("div", { class: "bars", role: "list" }, rows.map((r) => {
    const share = Math.max(0, r.value) / max;
    return h("div", { class: `bar-row${r.emphasis ? " emphasis" : ""}`, role: "listitem", title: r.detail || null, tabindex: r.detail ? "0" : null },
      h("div", { class: "bar-label" }, h("b", {}, r.label), r.note ? h("span", { class: "muted small" }, r.note) : null),
      h("div", { class: "bar-track" },
        h("div", { class: "bar-fill", style: `width:${(share * 100).toFixed(2)}%` }),
        h("span", { class: "bar-value num" }, format(r.value))));
  }));
}

/**
 * A level meter with labelled marks, for a quantity against a capacity.
 * @param {{value: number, max: number, marks?: {at: number, label: string}[], state?: "ok"|"warn"|"bad", label: string}} o
 */
export function meter(o) {
  const share = Math.max(0, Math.min(1, o.value / o.max));
  return h("div", { class: `meter ${o.state || "ok"}`, role: "meter", "aria-valuemin": "0", "aria-valuemax": String(o.max), "aria-valuenow": String(Math.round(o.value)), "aria-label": o.label },
    h("div", { class: "meter-fill", style: `width:${(share * 100).toFixed(1)}%` }),
    (o.marks || []).map((mk) => h("span", { class: "meter-mark", style: `left:${((mk.at / o.max) * 100).toFixed(1)}%`, title: mk.label })));
}
