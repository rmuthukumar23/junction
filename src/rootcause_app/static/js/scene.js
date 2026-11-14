// @ts-check
/**
 * The greenhouse, drawn from this morning's observations only: crop condition, solution volume,
 * EC, harvest so far and today's forecast. Nothing here uses hidden state (nutrient and salt split,
 * future weather) or predicts an outcome. It is a picture of what the sensors report.
 *
 *   plant colour   crop condition (green = healthy, yellow-brown = damaged)
 *   plant height   condition too, so a damaged crop visibly droops
 *   fruit          harvest so far, as a share of what full health could have produced to date
 *   tray water     solution volume against capacity, with the "uptake limited" line marked
 *   amber ring     EC above the stress threshold (the label says so in words as well)
 */
import { h, s, fmt } from "./dom.js";

const W = 1000, H = 240;

/** @param {number} c condition 0..1 */
function leafColor(c) {
  const t = Math.max(0, Math.min(1, (c - 0.2) / 0.8));
  return `hsl(${Math.round(42 + 78 * t)}, ${Math.round(38 + 12 * t)}%, ${Math.round(40 - 6 * t)}%)`;
}

/** One tomato plant: stem, leaves, and fruit that ripen with harvest share. */
function plant(x, base, height, condition, ripe, seedShift) {
  const g = s("g", { class: "plant" });
  const top = base - height;
  g.append(s("line", { x1: x, y1: base, x2: x + (1 - condition) * 6, y2: top, class: "stem" }));
  const leaves = 5;
  for (let i = 0; i < leaves; i++) {
    const y = base - 8 - (i / (leaves - 1)) * (height - 14);
    const side = i % 2 ? 1 : -1;
    const droop = (1 - condition) * 10;
    const len = 15 + ((i + seedShift) % 3) * 3;
    g.append(s("path", {
      d: `M${x},${y} q${side * len * 0.6},${-9 + droop} ${side * len},${droop * 0.6}  q${-side * len * 0.4},${6} ${-side * len},${-1}z`,
      style: `fill:${leafColor(condition)}`, class: "leaf",
    }));
  }
  const fruits = 3;
  for (let i = 0; i < fruits; i++) {
    const fx = x + (i - 1) * 9, fy = base - height * (0.32 + 0.14 * i) + 6;
    const ripeness = Math.max(0, Math.min(1, ripe * 1.4 - i * 0.18));
    g.append(s("circle", {
      cx: fx, cy: fy, r: 4.2, class: "fruit",
      style: `fill:hsl(${Math.round(100 - 100 * ripeness)}, ${Math.round(55 + 20 * ripeness)}%, ${Math.round(46 - 4 * ripeness)}%)`,
    }));
  }
  return g;
}

/** @param {any} view the dashboard view: rules, status */
export function greenhouseScene(view) {
  const p = view.rules.parameters, st = view.status;
  const zones = st.zones;
  const hot = st.forecast_today_temp_c >= p.growth_heat_onset_c;
  const warm = st.forecast_today_temp_c >= p.transp_ref_temp_c + 4;
  const left = 10, right = W - 10, bayW = (right - left) / zones.length;
  const floorY = H - 12, trayY = floorY - 30;

  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", class: "scene-svg",
    "aria-label": `Greenhouse with four bays. ${zones.map((/** @type {any} */ z) =>
      `${z.name}: condition ${fmt.pct(z.condition)}, ${fmt.int(z.volume_l)} litres, EC ${fmt.two(z.ec_ds_m)}`).join("; ")}.` });

  // sky, sun and ground
  svg.append(s("rect", { x: 0, y: 0, width: W, height: H, class: `sky${hot ? " hot" : warm ? " warm" : ""}` }));
  svg.append(s("circle", { cx: 46, cy: 30, r: hot ? 22 : 16, class: `sun${hot ? " hot" : ""}` }));
  svg.append(s("text", { x: 80, y: 35, class: "scene-temp" }, `${fmt.one(st.forecast_today_temp_c)}° today${hot ? " · hot" : ""}`));
  svg.append(s("rect", { x: 0, y: floorY, width: W, height: H - floorY, class: "ground" }));

  // glass house: gable roof and walls
  const roofPeak = 30, eave = 84;
  svg.append(s("path", { d: `M${left},${eave} L${W / 2},${roofPeak} L${right},${eave} L${right},${floorY} L${left},${floorY}z`, class: "glass" }));
  for (let i = 1; i < 8; i++) {   // roof ribs
    const x = left + ((right - left + 28) / 8) * i;
    const y = x < W / 2 ? eave - ((x - (left)) / (W / 2 - (left))) * (eave - roofPeak) : eave - (((right) - x) / ((right) - W / 2)) * (eave - roofPeak);
    svg.append(s("line", { x1: x, y1: y, x2: x, y2: eave, class: "rib" }));
  }
  svg.append(s("line", { x1: left, y1: eave, x2: right, y2: eave, class: "frame" }));
  svg.append(s("path", { d: `M${left},${eave} L${W / 2},${roofPeak} L${right},${eave}`, class: "frame roof" }));

  zones.forEach((/** @type {any} */ z, i) => {
    const x0 = left + i * bayW, cx = x0 + bayW / 2;
    if (i > 0) svg.append(s("line", { x1: x0, y1: eave + 6, x2: x0, y2: floorY, class: "partition" }));

    // nutrient tray: water level against capacity; the line marks where water uptake becomes limited
    const trayW = bayW - 40, trayX = x0 + 20, trayH = 22;
    const level = Math.max(0, Math.min(1, z.volume_l / p.capacity_l));
    svg.append(s("rect", { x: trayX, y: trayY, width: trayW, height: trayH, rx: 4, class: "tray" }));
    svg.append(s("rect", { x: trayX + 1.5, y: trayY + trayH - 1.5 - (trayH - 3) * level, width: trayW - 3, height: (trayH - 3) * level, rx: 3,
      class: `water${z.volume_l < p.comfort_volume_l ? " low" : ""}` }));
    const markY = trayY + trayH - 1.5 - (trayH - 3) * (p.comfort_volume_l / p.capacity_l);
    svg.append(s("line", { x1: trayX + 2, y1: markY, x2: trayX + trayW - 2, y2: markY, class: "mark" }));

    // plants: height and colour follow condition; fruit follows harvest to date
    const possibleToDate = z.growth_max_kg_per_day * Math.max(1, st.day);
    const ripe = Math.max(0, Math.min(1, z.harvest_kg / possibleToDate));
    const plants = 5, span = bayW - 56;
    for (let k = 0; k < plants; k++) {
      const px = x0 + 28 + (span / (plants - 1)) * k;
      svg.append(plant(px, trayY - 1, 38 + 52 * Math.max(0.2, z.condition) + (k % 2) * 5, z.condition, ripe, k + i));
    }
  });

  // drip line along the bottom
  svg.append(s("line", { x1: left, y1: floorY - 2, x2: right, y2: floorY - 2, class: "pipe" }));

  return h("div", { class: "scene" }, svg);
}
