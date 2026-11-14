// @ts-check
/**
 * Replay: the finished season, one day at a time, with what was observed, what was done and
 * what happened. This is a post-episode analysis view: it also shows the hidden state
 * (true nutrient and salt levels, stress factors, the weather that occurred), clearly marked.
 */
import { api, ApiError } from "./api.js";
import { h, replace, fmt, badge } from "./dom.js";
import { lineChart } from "./charts.js";
import { go } from "./nav.js";

/** @param {number} v */
const factor = (v) => (v >= 0.995 ? "none" : `−${fmt.pct(1 - v)}`);

/** @param {any} a analysis @param {number} day @param {(d: number) => void} pick */
function charts(a, day, pick) {
  const xs = a.days.map((/** @type {any} */ d) => d.day);
  return h("div", { class: "chart-grid four" },
    Object.keys(a.zones).map((id) => lineChart({
      title: `${a.zones[id].name}: nutrients and salts`, unit: "g/L", xs, xMax: a.days.length, width: 320, height: 150, marker: day, onPick: pick,
      series: [
        { name: "nutrients", color: "var(--series-1)", values: a.days.map((/** @type {any} */ d) => d.zones[id].hidden_morning.nutrient_g_l) },
        { name: "salts", color: "var(--series-2)", values: a.days.map((/** @type {any} */ d) => d.zones[id].hidden_morning.salt_g_l) },
      ],
      yMin: 0,
    })),
    lineChart({ title: "Temperature that occurred", unit: "°C", xs, xMax: a.days.length, width: 320, height: 150, marker: day, onPick: pick, format: fmt.one,
      series: [{ name: "temperature", color: "var(--series-1)", values: a.realized_temps_c }] }),
    lineChart({ title: "Harvest per day, all zones", unit: "kg", xs, xMax: a.days.length, width: 320, height: 150, marker: day, onPick: pick, format: fmt.one, yMin: 0,
      series: [{ name: "harvest", color: "var(--series-1)", values: a.days.map((/** @type {any} */ d) => Object.values(d.zones).reduce((/** @type {number} */ s, /** @type {any} */ z) => s + z.outcome.growth_kg, 0)) }] }));
}

/** @param {any} a @param {number} day */
function dayTable(a, day) {
  const d = a.days[day];
  return h("div", { class: "table-wrap" }, h("table", { class: "data replay-table" },
    h("thead", {},
      h("tr", {}, h("th", { rowspan: "2" }, "Zone"), h("th", { colspan: "3" }, "Observed that morning"), h("th", { colspan: "2", class: "hidden-col" }, "Hidden at the time"),
        h("th", { colspan: "3" }, "Plan applied"), h("th", { colspan: "2" }, "Outcome"), h("th", { colspan: "4", class: "hidden-col" }, "Growth lost to (hidden)")),
      h("tr", {}, ["EC", "Volume L", "Condition"].map((c) => h("th", {}, c)), ["Nutrients g/L", "Salts g/L"].map((c) => h("th", { class: "hidden-col" }, c)),
        ["Irrig. L", "Fert. g", "Flush L"].map((c) => h("th", {}, c)), ["Growth kg", "Transpired L"].map((c) => h("th", {}, c)),
        ["Water", "Nutrients", "Salinity", "Heat"].map((c) => h("th", { class: "hidden-col" }, c)))),
    h("tbody", {}, Object.entries(d.zones).map(([id, /** @type {any} */ z]) => h("tr", {},
      h("td", {}, a.zones[id].name),
      h("td", { class: "num" }, fmt.two(z.morning.ec_ds_m)), h("td", { class: "num" }, fmt.int(z.morning.volume_l)), h("td", { class: "num" }, fmt.two(z.morning.condition)),
      h("td", { class: "num hidden-col" }, fmt.two(z.hidden_morning.nutrient_g_l)), h("td", { class: "num hidden-col" }, fmt.two(z.hidden_morning.salt_g_l)),
      h("td", { class: "num" }, fmt.int(z.plan.irrigation_l)), h("td", { class: "num" }, fmt.int(z.plan.fertilizer_g)), h("td", { class: "num" }, fmt.int(z.plan.flush_l)),
      h("td", { class: "num" }, fmt.one(z.outcome.growth_kg)), h("td", { class: "num" }, fmt.int(z.outcome.transpired_l)),
      h("td", { class: "num hidden-col" }, factor(z.factors.water_factor)), h("td", { class: "num hidden-col" }, factor(z.factors.nutrient_factor)),
      h("td", { class: "num hidden-col" }, factor(z.factors.salinity_factor)), h("td", { class: "num hidden-col" }, factor(z.factors.heat_factor)))))));
}

/** @param {HTMLElement} root @param {string} runId @param {number} startDay */
export async function renderReplay(root, runId, startDay) {
  let report;
  try {
    report = await api.report(runId);
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) { go(`#/run/${runId}`); return; }
    throw err;
  }
  const a = report.analysis;
  const last = a.days.length - 1;
  let day = Number.isInteger(startDay) ? Math.max(0, Math.min(last, startDay)) : 0;

  const draw = () => {
    const d = a.days[day];
    const pick = (/** @type {number} */ x) => { day = Math.max(0, Math.min(last, x)); draw(); };
    const tests = a.tests.filter((/** @type {any} */ t) => t.sampled_day === day);
    const events = a.events.filter((/** @type {any} */ e) => e.day === day + 1);
    const slider = /** @type {HTMLInputElement} */ (h("input", { type: "range", min: "0", max: String(last), step: "1", value: String(day), id: "replay-day",
      oninput: () => pick(Number(slider.value)) }));
    history.replaceState(null, "", `#/run/${runId}/replay/${day}`);
    replace(root, h("div", { class: "stack" },
      h("div", { class: "spread" },
        h("div", {}, h("p", { class: "eyebrow" }, `${report.run.player} · seed ${report.run.seed}`), h("h1", {}, "Replay")),
        h("div", { class: "row" }, h("a", { class: "btn", href: `#/run/${runId}/result` }, "Back to the result"), h("a", { class: "btn primary", href: "#/" }, "New run"))),
      h("p", { class: "analysis-flag" }, "Post-episode analysis. Shaded columns and the nutrient and salt charts show hidden state that was not available during play."),
      h("section", { class: "card pad stack" },
        h("div", { class: "replay-nav" },
          h("button", { type: "button", class: "btn", disabled: day === 0, onclick: () => pick(day - 1) }, "← Previous day"),
          h("div", { class: "replay-day" }, h("label", { for: "replay-day" }, h("b", {}, `Day ${day}`), ` of ${last}`), slider),
          h("button", { type: "button", class: "btn", disabled: day === last, onclick: () => pick(day + 1) }, "Next day →")),
        h("div", { class: "row" },
          badge("plain", `${fmt.temp(d.temp_c)} occurred`),
          badge("plain", `forecast that morning: ${fmt.temp(d.forecast_issued[0])}`),
          d.plan_source === "submitted" ? badge("good", "player's plan") : badge("warn", d.plan_source === "default" ? "default plan (none submitted)" : "default plan, scaled for lack of water"),
          badge("plain", `${fmt.litres(d.fresh_water_used_l)} fresh water used, ${fmt.litres(d.fresh_water_left_l)} left`),
          badge("plain", `day cost ${fmt.eur(Object.values(d.cost).reduce((/** @type {number} */ s, /** @type {any} */ v) => s + v, 0))}`),
          tests.length ? badge("plain", `tests ordered: zone ${tests.map((/** @type {any} */ t) => t.zone_id).join(", ")}`) : null),
        dayTable(a, day),
        events.length ? h("div", {}, h("h3", {}, "Reported the next morning"), h("ul", { class: "events" }, events.map((/** @type {any} */ e) => h("li", {}, h("span", {}, e.text))))) : null),
      h("section", { class: "card pad stack" },
        h("div", { class: "spread" }, h("h2", {}, "The whole season"), h("span", { class: "muted small" }, "click a chart to jump to that day")),
        charts(a, day, pick))));
  };
  draw();
}
