// @ts-check
/** One bay's controls, sitting directly under its plants: what the sensor shows, and three sliders. */
import { h, fmt, actionButton } from "./dom.js";

const EC_SCALE = 6.5;   // dS/m shown across the full width of the bar

/**
 * The EC bar. Before a test it is one grey block with a question mark: the sensor cannot say
 * what it is made of. After a test it is split into nutrients and salts as measured on the sample day.
 * @param {any} p @param {any} zone
 */
function ecBar(p, zone) {
  const t = zone.latest_test;
  const pct = (/** @type {number} */ v) => `${Math.min(100, (v / EC_SCALE) * 100).toFixed(1)}%`;
  const parts = t
    ? [h("span", { class: "nut", style: `width:${pct(p.ec_per_g_l * t.result.nutrient_g_l)}`, title: `nutrients ${fmt.two(t.result.nutrient_g_l)} g/L` }),
       h("span", { class: "salt", style: `width:${pct(p.ec_per_g_l * t.result.salt_g_l)}`, title: `salts ${fmt.two(t.result.salt_g_l)} g/L` })]
    : [h("span", { class: "unknown", style: `width:${pct(zone.ec_ds_m)}` }, "?")];
  return h("div", { class: "ecbar", role: "img",
    "aria-label": t ? `EC ${fmt.two(zone.ec_ds_m)}. Tested day ${t.sampled_day}: nutrients ${fmt.two(t.result.nutrient_g_l)}, salts ${fmt.two(t.result.salt_g_l)} grams per litre`
      : `EC ${fmt.two(zone.ec_ds_m)}, make-up unknown` },
    parts, h("i", { class: "limit", style: `left:${pct(p.ec_threshold_ds_m)}`, title: `stress above EC ${p.ec_threshold_ds_m}` }));
}

/**
 * @param {any} view @param {any} zone @param {Record<string, number>} plan
 * @param {{onPlan: (zone: string, key: string, value: number) => void, onTest: (zone: string) => Promise<void>}} on
 */
export function bay(view, zone, plan, on) {
  const p = view.rules.parameters, id = zone.zone_id, day = view.status.day, t = zone.latest_test;
  const atLab = view.tests.pending.some((/** @type {any} */ x) => x.zone_id === id);
  const sampledToday = view.tests.pending.some((/** @type {any} */ x) => x.zone_id === id && x.sampled_day === day);
  const y = zone.yesterday;
  const high = zone.ec_ds_m > p.ec_threshold_ds_m;

  /** @param {string} key @param {string} label @param {string} unit @param {number} max @param {number} step */
  const slider = (key, label, unit, max, step) => {
    const out = h("output", { class: "num" }, `${fmt.int(plan[key])} ${unit}`);
    const input = /** @type {HTMLInputElement} */ (h("input", { type: "range", id: `${id}-${key}`, min: "0", max: String(max), step: String(step),
      value: String(Math.min(plan[key], max)), "aria-label": `${zone.name} ${label}`,
      oninput: () => { out.textContent = `${fmt.int(Number(input.value))} ${unit}`; on.onPlan(id, key, Number(input.value)); } }));
    return h("div", { class: `sl ${key}` }, h("span", {}, label), input, out);
  };

  return h("section", { class: "bay", "aria-label": zone.name },
    h("div", { class: "bay-head" }, h("b", {}, zone.name),
      h("span", { class: `chip ${zone.condition >= 0.9 ? "ok" : zone.condition >= 0.7 ? "warn" : "bad"}` }, `health ${fmt.pct(zone.condition)}`)),
    h("div", { class: "bay-ec" },
      h("span", { class: "num" }, "EC ", h("b", {}, fmt.two(zone.ec_ds_m)), high ? h("span", { class: "hi" }, " ▲ high") : null),
      atLab ? h("span", { class: "muted" }, "result tomorrow")
        : actionButton(t ? "Re-test €25" : `Test €${p.test_price}`, () => on.onTest(id), { class: "btn tiny", disabled: sampledToday })),
    ecBar(p, zone),
    h("div", { class: "bay-cap muted" }, t ? `nutrients ${fmt.two(t.result.nutrient_g_l)} · salts ${fmt.two(t.result.salt_g_l)} g/L, as of day ${t.sampled_day}` : "nutrients or salts? the sensor can't tell"),
    y ? h("div", { class: "grew", title: `Day ${y.day}: grew ${fmt.one(y.growth_kg)} kg of ${fmt.one(zone.growth_max_kg_per_day)} kg possible` },
      h("span", { class: "muted" }, "grew"), h("div", { class: "grew-track" }, h("div", { style: `width:${Math.min(100, (y.growth_kg / zone.growth_max_kg_per_day) * 100).toFixed(0)}%` })),
      h("span", { class: "num" }, `${fmt.int(y.growth_kg)}/${fmt.int(zone.growth_max_kg_per_day)} kg`)) : null,
    slider("irrigation_l", "Water", "L", p.irrigation_max_l, 10),
    slider("fertilizer_g", "Feed", "g", p.fertilizer_max_g, 20),
    slider("flush_l", "Flush", "L", Math.floor(zone.pumpable_l / 10) * 10, 10));
}
