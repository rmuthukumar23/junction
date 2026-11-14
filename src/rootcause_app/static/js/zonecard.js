// @ts-check
/** One zone: this morning's readings, the latest lab result, today's plan inputs and the history. */
import { h, fmt, badge, actionButton } from "./dom.js";
import { lineChart, sparkline, meter } from "./charts.js";

export const PLAN_FIELDS = [
  { key: "irrigation_l", label: "Irrigation", unit: "L", step: 10, help: "fresh water added" },
  { key: "fertilizer_g", label: "Fertilizer", unit: "g", step: 10, help: "adds nutrients, raises EC" },
  { key: "flush_l", label: "Flush", unit: "L", step: 10, help: "bleed to waste, refill with fresh water" },
];

/**
 * Water the crop is expected to ask for today, from the published formula and today's forecast.
 * @param {any} p rules.parameters @param {any} zone @param {number} temp
 */
export function estimatedDemand(p, zone, temp) {
  const d = temp - p.transp_ref_temp_c;
  const factor = d >= 0 ? 1 + p.transp_heat_slope * d : Math.max(p.transp_min_factor, 1 + p.transp_cool_slope * d);
  return zone.transpiration_base_l_per_day * factor * (p.canopy_floor + (1 - p.canopy_floor) * zone.condition);
}

/** @param {number} condition */
function conditionBadge(condition) {
  if (condition >= 0.9) return badge("good", `Condition ${fmt.pct(condition)}`);
  if (condition >= 0.7) return badge("warn", `Condition ${fmt.pct(condition)}`);
  return badge("bad", `Condition ${fmt.pct(condition)}`);
}

/**
 * @param {any} view @param {any} zone @param {Record<string, number>} plan
 * @param {{onPlan: (zone: string, key: string, value: number) => void, onTest: (zone: string) => Promise<void>, open: Set<string>}} handlers
 */
export function zoneCard(view, zone, plan, handlers) {
  const p = view.rules.parameters;
  const id = zone.zone_id;
  const day = view.status.day;
  const days = view.history[id].days;
  const ecSeries = days.map((/** @type {any} */ d) => d.morning.ec_ds_m);
  const pending = view.tests.pending.filter((/** @type {any} */ t) => t.zone_id === id);
  const sampledToday = pending.some((/** @type {any} */ t) => t.sampled_day === day);
  const test = zone.latest_test;
  const y = zone.yesterday;

  const readings = h("div", { class: "readings" },
    h("div", { class: "reading" },
      h("span", { class: "label" }, "EC ", h("span", { class: "muted" }, "dS/m")),
      h("div", { class: "row tight" }, h("span", { class: "value num" }, fmt.two(zone.ec_ds_m)), sparkline(ecSeries, { domain: [1.5, 6] })),
      zone.ec_ds_m > p.ec_threshold_ds_m
        ? badge("warn", `above ${p.ec_threshold_ds_m}: salinity stress`)
        : h("span", { class: "note" }, "nutrients + salts, not split")),
    h("div", { class: "reading" },
      h("span", { class: "label" }, "Solution volume"),
      h("span", { class: "value num" }, fmt.litres(zone.volume_l)),
      meter({ value: zone.volume_l, max: p.capacity_l, label: `Solution volume of zone ${id}`,
        state: zone.volume_l < p.comfort_volume_l ? "warn" : "ok",
        marks: [{ at: p.dead_volume_l, label: `${p.dead_volume_l} L cannot be used` }, { at: p.comfort_volume_l, label: `below ${p.comfort_volume_l} L water uptake is limited` }] }),
      zone.volume_l < p.comfort_volume_l
        ? badge("warn", `below ${fmt.int(p.comfort_volume_l)} L: uptake limited`)
        : h("span", { class: "note" }, `capacity ${fmt.int(p.capacity_l)} L`)),
    h("div", { class: "reading" },
      h("span", { class: "label" }, "Harvest so far"),
      h("span", { class: "value num" }, fmt.kg(zone.harvest_kg)),
      y ? h("span", { class: "note" }, `day ${y.day}: +${fmt.one(y.growth_kg)} kg of ${fmt.one(zone.growth_max_kg_per_day)} kg possible at full health`)
        : h("span", { class: "note" }, `up to ${fmt.one(zone.growth_max_kg_per_day)} kg a day at full health`)));

  const lab = h("div", { class: "lab" },
    test
      ? h("p", {}, h("b", {}, "Lab result "), h("span", { class: "muted" }, `sampled day ${test.sampled_day}, ${test.sample_time}${day - test.sampled_day > 0 ? ` (${day - test.sampled_day} day${day - test.sampled_day > 1 ? "s" : ""} ago)` : ""}: `),
          h("span", { class: "num" }, `nutrients ${fmt.two(test.result.nutrient_g_l)} g/L · salts ${fmt.two(test.result.salt_g_l)} g/L · in ${fmt.int(test.result.volume_l)} L`))
      : h("p", { class: "muted" }, "No lab result yet: the split between nutrients and salts is unknown."),
    pending.map((/** @type {any} */ t) => h("p", { class: "small" }, badge("plain", "at the lab"), ` sample from day ${t.sampled_day}; result on day ${t.delivery_day}`)),
    actionButton(sampledToday ? "Sample taken today" : `Order test · ${fmt.eur0(p.test_price)}`, () => handlers.onTest(id),
      { class: "btn small", disabled: sampledToday, title: "Sampled now, before today's plan. Result tomorrow morning." }));

  const demand = estimatedDemand(p, zone, view.status.forecast_today_temp_c);
  const inputs = h("fieldset", { class: "plan-inputs" },
    h("legend", {}, `Plan for day ${day}`),
    PLAN_FIELDS.map((f) => {
      const input = /** @type {HTMLInputElement} */ (h("input", {
        type: "number", min: "0", step: String(f.step), inputmode: "decimal", id: `${id}-${f.key}`, value: String(plan[f.key]),
        "aria-describedby": `${id}-${f.key}-help`,
        oninput: () => handlers.onPlan(id, f.key, input.value === "" ? 0 : Number(input.value)),
      }));
      const limit = f.key === "irrigation_l" ? `max ${fmt.int(p.irrigation_max_l)}` : f.key === "fertilizer_g" ? `max ${fmt.int(p.fertilizer_max_g)}` : `max ${fmt.int(zone.pumpable_l)} (pumpable)`;
      return h("div", { class: "plan-field" },
        h("label", { for: input.id }, f.label),
        h("div", { class: "input-unit" }, input, h("span", { "aria-hidden": "true" }, f.unit)),
        h("span", { class: "note", id: `${id}-${f.key}-help` }, `${f.help}; ${limit}`));
    }),
    h("p", { class: "note estimate" }, `Estimate: the crop will ask for about ${fmt.int(demand)} L today (from today's forecast of ${fmt.temp(view.status.forecast_today_temp_c)}).`));

  const history = h("details", { class: "history", open: handlers.open.has(id),
    ontoggle: (/** @type {Event} */ ev) => { if (/** @type {HTMLDetailsElement} */ (ev.currentTarget).open) handlers.open.add(id); else handlers.open.delete(id); } },
    h("summary", {}, "History and charts"), historyPanel(view, id));

  return h("article", { class: "card zone", "aria-label": zone.name },
    h("header", { class: "spread" }, h("h3", {}, zone.name), conditionBadge(zone.condition)),
    readings,
    h("p", { class: "observed" }, `Sensors read on the morning of day ${zone.observed_day}. EC sensor error about ±${p.ec_sensor_sigma_ds_m} dS/m; volume, condition and harvest are exact.`),
    lab, inputs, history);
}

/** @param {any} view @param {string} id */
export function historyPanel(view, id) {
  const p = view.rules.parameters;
  const days = view.history[id].days;
  const xs = days.map((/** @type {any} */ d) => d.day);
  const played = days.filter((/** @type {any} */ d) => d.outcome);
  const common = { xs, xMax: p.horizon_days, width: 250, height: 140 };
  const charts = h("div", { class: "chart-grid" },
    lineChart({ ...common, title: "EC at the morning reading", unit: "dS/m", series: [{ name: "EC", color: "var(--series-1)", values: days.map((/** @type {any} */ d) => d.morning.ec_ds_m) }],
      refs: [{ value: p.ec_threshold_ds_m, label: `stress above ${p.ec_threshold_ds_m}` }], yMin: 1 }),
    lineChart({ ...common, title: "Solution volume", unit: "L", format: fmt.int, series: [{ name: "Volume", color: "var(--series-1)", values: days.map((/** @type {any} */ d) => d.morning.volume_l) }],
      refs: [{ value: p.comfort_volume_l, label: "uptake limited below" }], yMin: p.dead_volume_l, yMax: p.capacity_l }),
    lineChart({ ...common, xs: played.map((/** @type {any} */ d) => d.day), title: "Growth per day", unit: "kg", format: fmt.one, series: [{ name: "Growth", color: "var(--series-1)", values: played.map((/** @type {any} */ d) => d.outcome.growth_kg) }], yMin: 0 }),
    lineChart({ ...common, title: "Crop condition", unit: "0–1", series: [{ name: "Condition", color: "var(--series-1)", values: days.map((/** @type {any} */ d) => d.morning.condition) }], yMin: 0, yMax: 1 }));
  const table = h("div", { class: "table-wrap" }, h("table", { class: "data" },
    h("thead", {}, h("tr", {}, ["Day", "°C", "EC", "Volume L", "Condition", "Irrig. L", "Fert. g", "Flush L", "Growth kg", "Transpired L"].map((c) => h("th", {}, c)))),
    h("tbody", {}, days.map((/** @type {any} */ d) => h("tr", {},
      h("td", {}, d.outcome ? String(d.day) : `${d.day} (today)`),
      h("td", { class: "num" }, d.outcome ? fmt.one(d.temp_c) : "–"),
      h("td", { class: "num" }, fmt.two(d.morning.ec_ds_m)),
      h("td", { class: "num" }, fmt.int(d.morning.volume_l)),
      h("td", { class: "num" }, fmt.two(d.morning.condition)),
      h("td", { class: "num" }, d.plan ? fmt.int(d.plan.irrigation_l) : "–"),
      h("td", { class: "num" }, d.plan ? fmt.int(d.plan.fertilizer_g) : "–"),
      h("td", { class: "num" }, d.plan ? fmt.int(d.plan.flush_l) : "–"),
      h("td", { class: "num" }, d.outcome ? fmt.one(d.outcome.growth_kg) : "–"),
      h("td", { class: "num" }, d.outcome ? fmt.int(d.outcome.transpired_l) : "–"))))));
  return h("div", { class: "stack" }, charts,
    h("p", { class: "note" }, "Readings are taken each morning before that day's plan. Temperatures shown are the ones that occurred."), table);
}
