// @ts-check
/** Side panels of the dashboard: lab tests, the published rules, and the event timeline. */
import { h, fmt, badge } from "./dom.js";

/** @param {any} view */
export function testsPanel(view) {
  const tests = view.tests;
  const rows = [...tests.pending, ...tests.delivered].sort((a, b) => b.sampled_day - a.sampled_day || a.zone_id.localeCompare(b.zone_id));
  return h("section", { class: "card pad stack", "aria-label": "Lab tests" },
    h("div", { class: "spread" }, h("h2", {}, "Lab tests"), h("span", { class: "muted small" }, `${tests.pending.length} at the lab`)),
    rows.length === 0
      ? h("p", { class: "muted small" }, `None ordered. A test costs ${fmt.eur0(view.rules.tests.price_eur)}, is sampled when ordered (before that day's plan), and arrives the next morning.`)
      : h("ul", { class: "tests" }, rows.map((t) => h("li", {},
        h("div", { class: "spread" }, h("b", {}, `Zone ${t.zone_id}`), t.status === "pending" ? badge("plain", `arrives day ${t.delivery_day}`) : badge("good", `delivered day ${t.delivery_day}`)),
        h("p", { class: "small muted" }, `Sampled day ${t.sampled_day}, ${t.sample_time}.`),
        t.result ? h("p", { class: "small num" }, `Nutrients ${fmt.two(t.result.nutrient_g_l)} g/L · salts ${fmt.two(t.result.salt_g_l)} g/L · ${fmt.int(t.result.volume_l)} L · EC ${fmt.two(t.result.ec_ds_m)}`) : null))),
    rows.some((t) => t.result) ? h("p", { class: "note" }, "A result describes the sample day's morning. The zone has changed since by that day's plan and the crop's uptake.") : null);
}

/** @param {any} view */
export function rulesPanel(view) {
  const p = view.rules.parameters;
  /** @type {[string, string][]} */
  const facts = [
    ["Tomatoes sell for", `${fmt.eur(p.price_per_kg)} per kg`],
    ["Fresh water", `${fmt.eur(p.water_price_per_l)} per L, with ${p.source_salt_g_l} g/L of salt in it`],
    ["Fertilizer", `${fmt.eur(p.fertilizer_price_per_g)} per g; ${fmt.pct(p.fertilizer_ballast)} of it is salt`],
    ["Discharge to waste", `${fmt.eur(p.discharge_price_per_l)} per L flushed or overflowed`],
    ["Lab test", `${fmt.eur0(p.test_price)}, result after ${p.test_delay_days} day`],
    ["EC", `${p.ec_per_g_l} dS/m per g/L of nutrients plus salts`],
    ["Nutrition is not limiting at", `${p.nutrient_full_g_l} g/L of nutrients or more`],
    ["Salinity stress starts above", `EC ${p.ec_threshold_ds_m}; growth falls ${fmt.pct(p.ec_slope_per_ds_m)} per dS/m beyond`],
    ["Growth uses", `${p.uptake_g_per_kg} g of nutrient per kg on day 0, +${p.uptake_rise_per_day} g each later day`],
    ["Water uptake is limited below", `${fmt.int(p.comfort_volume_l)} L; ${fmt.int(p.dead_volume_l)} L cannot be used at all`],
    ["Water demand", `+${fmt.pct(p.transp_heat_slope)} per °C above ${p.transp_ref_temp_c} °C`],
    ["Heat slows growth", `above ${p.growth_heat_onset_c} °C, by ${fmt.pct(p.growth_heat_slope)} per °C`],
    ["Crop condition", `falls with stress above ${fmt.pct(p.stress_tolerance)} of a day's growth; regains ${fmt.pct(p.recovery_per_day)} on a calm day`],
    ["Default plan, per zone", `${fmt.int(p.default_irrigation_l)} L irrigation, ${fmt.int(p.default_fertilizer_g)} g fertilizer, no flush`],
  ];
  return h("section", { class: "card pad" },
    h("details", {},
      h("summary", {}, "Rules and numbers"),
      h("dl", { class: "facts-list" }, facts.map(([k, v]) => [h("dt", {}, k), h("dd", {}, v)])),
      h("h3", {}, "Order of a day"),
      h("ol", { class: "day-order small" }, view.rules.day_order.map((/** @type {string} */ line) => h("li", {}, line.replace(/^\d+\.\s*/, "")))),
      h("p", { class: "note" }, "These are the same rules and numbers an AI agent receives. Nothing about the model is hidden; only each zone's current nutrient and salt split and the weather that will actually occur.")));
}

const KIND_LABEL = { day: "Day", plan: "Plan", water: "Resources", overflow: "Overflow", stress: "Crop stress", low_water: "Low water",
  test_ordered: "Test ordered", test_result: "Test result", forecast: "Forecast" };
const KIND_TONE = { stress: "bad", low_water: "warn", overflow: "warn", forecast: "plain", test_result: "good" };

/** @param {any[]} events */
export function timeline(events) {
  const byDay = new Map();
  for (const e of events) {
    if (!byDay.has(e.day)) byDay.set(e.day, []);
    byDay.get(e.day).push(e);
  }
  const days = [...byDay.keys()].sort((a, b) => b - a);
  return h("section", { class: "card pad stack timeline", "aria-label": "Event timeline" },
    h("div", { class: "spread" }, h("h2", {}, "What has happened"), h("span", { class: "muted small" }, "facts only, newest first")),
    days.map((day, i) => h("details", { open: i < 2 },
      h("summary", {}, `Morning of day ${day}`),
      h("ul", { class: "events" }, byDay.get(day).map((/** @type {any} */ e) => h("li", {},
        badge(/** @type {any} */ (KIND_TONE)[e.kind] || "plain", /** @type {any} */ (KIND_LABEL)[e.kind] || e.kind), h("span", {}, e.text)))))));
}
