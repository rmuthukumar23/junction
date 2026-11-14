// @ts-check
/**
 * The plan summary: what today's plan draws and costs, before it is committed.
 * Everything here is arithmetic on values the player can already see (the plan, this
 * morning's volumes, published prices and limits). It predicts no growth and no stress.
 */
import { h, fmt, actionButton } from "./dom.js";
import { meter } from "./charts.js";
import { PLAN_FIELDS } from "./zonecard.js";

/** @param {any} view @param {Record<string, Record<string, number>>} plan */
export function planTotals(view, plan) {
  const p = view.rules.parameters, st = view.status;
  let irrigation = 0, flush = 0, fertilizer = 0, overflow = 0;
  /** @type {string[]} */
  const problems = [];
  /** @type {string[]} */
  const notes = [];
  for (const z of st.zones) {
    const zp = plan[z.zone_id];
    for (const f of PLAN_FIELDS) {
      const v = zp[f.key];
      if (!Number.isFinite(v) || v < 0) problems.push(`${z.name}: ${f.label.toLowerCase()} must be a number, 0 or more.`);
    }
    const irr = Math.max(0, zp.irrigation_l || 0), fl = Math.max(0, zp.flush_l || 0), fe = Math.max(0, zp.fertilizer_g || 0);
    if (irr > p.irrigation_max_l) problems.push(`${z.name}: irrigation is limited to ${fmt.int(p.irrigation_max_l)} L per day.`);
    if (fe > p.fertilizer_max_g) problems.push(`${z.name}: fertilizer is limited to ${fmt.int(p.fertilizer_max_g)} g per day.`);
    if (fl > z.pumpable_l) problems.push(`${z.name}: at most ${fmt.int(z.pumpable_l)} L can be flushed (the volume above ${fmt.int(p.dead_volume_l)} L).`);
    const over = Math.max(0, z.volume_l + irr - p.capacity_l);
    if (over > 0.05) notes.push(`${z.name} would overflow about ${fmt.int(over)} L to waste: it holds ${fmt.int(z.volume_l)} L and capacity is ${fmt.int(p.capacity_l)} L.`);
    irrigation += irr; flush += fl; fertilizer += fe; overflow += over;
  }
  const water = irrigation + flush;
  if (water > st.fresh_water.available_today_l + 1e-6) {
    problems.push(`The plan draws ${fmt.int(water)} L of fresh water but only ${fmt.int(st.fresh_water.available_today_l)} L can be delivered today. Reduce irrigation or flushing by ${fmt.int(water - st.fresh_water.available_today_l)} L.`);
  }
  const cost = { water: water * p.water_price_per_l, fertilizer: fertilizer * p.fertilizer_price_per_g, discharge: (flush + overflow) * p.discharge_price_per_l };
  return { irrigation, flush, fertilizer, water, overflow, cost, total: cost.water + cost.fertilizer + cost.discharge, problems, notes };
}

/**
 * @param {any} view @param {Record<string, Record<string, number>>} plan
 * @param {{error: string, confirmStop: boolean, useDefault: () => void, reuseYesterday: (() => void) | null,
 *   advanceLabel: string, advance: () => Promise<void>, askStop: () => void, stop: () => Promise<void>}} o
 */
export function planSummary(view, plan, o) {
  const st = view.status, w = st.fresh_water;
  const t = planTotals(view, plan);
  const blocked = t.problems.length > 0;
  const after = w.left_l - t.water;
  const perDay = st.days_left > 1 ? after / (st.days_left - 1) : 0;
  return h("section", { class: "card pad stack summary", "aria-label": "Plan summary" },
    h("div", { class: "spread" }, h("h2", {}, `Today's plan`), h("span", { class: "muted small" }, `day ${st.day}`)),
    h("div", { class: "row" },
      h("button", { type: "button", class: "btn small", onclick: o.useDefault, title: "The default operating plan: the same amounts for every zone." }, "Default plan"),
      h("button", { type: "button", class: "btn small", onclick: o.reuseYesterday || undefined, disabled: !o.reuseYesterday,
        title: o.reuseYesterday ? "Copy the plan that was applied yesterday." : "No day has been played yet." }, "Reuse yesterday's plan")),
    h("div", { class: "table-wrap" }, h("table", { class: "data compact" },
      h("thead", {}, h("tr", {}, h("th", {}, "Zone"), PLAN_FIELDS.map((f) => h("th", {}, `${f.label} ${f.unit}`)))),
      h("tbody", {}, st.zones.map((/** @type {any} */ z) => h("tr", {}, h("td", {}, z.zone_id),
        PLAN_FIELDS.map((f) => h("td", { class: "num" }, fmt.int(plan[z.zone_id][f.key] || 0))))),
        h("tr", { class: "total" }, h("td", {}, "Total"), h("td", { class: "num" }, fmt.int(t.irrigation)), h("td", { class: "num" }, fmt.int(t.fertilizer)), h("td", { class: "num" }, fmt.int(t.flush)))))),
    h("div", { class: "stack tight" },
      h("div", { class: "spread" }, h("span", {}, "Fresh water today"), h("b", { class: "num" }, `${fmt.int(t.water)} of ${fmt.int(w.available_today_l)} L`)),
      meter({ value: t.water, max: Math.max(w.available_today_l, 1), label: "Fresh water this plan draws, against what can be delivered today",
        state: t.water > w.available_today_l ? "bad" : "ok" }),
      h("p", { class: "note" }, after >= 0
        ? `Leaves ${fmt.litres(after)} in the allocation${st.days_left > 1 ? `, about ${fmt.int(perDay)} L a day for the ${st.days_left - 1} day${st.days_left - 1 === 1 ? "" : "s"} after today` : ""}.`
        : "More than the allocation holds.")),
    h("table", { class: "data compact costs" },
      h("tbody", {},
        h("tr", {}, h("td", {}, "Water"), h("td", { class: "num" }, fmt.eur(t.cost.water))),
        h("tr", {}, h("td", {}, "Fertilizer"), h("td", { class: "num" }, fmt.eur(t.cost.fertilizer))),
        h("tr", {}, h("td", {}, "Discharge (flush and overflow)"), h("td", { class: "num" }, fmt.eur(t.cost.discharge))),
        h("tr", { class: "total" }, h("td", {}, "Cost today"), h("td", { class: "num" }, fmt.eur(t.total))))),
    t.notes.map((n) => h("p", { class: "notice warn" }, n)),
    t.problems.length ? h("div", { class: "notice error", role: "alert" }, h("strong", {}, "This plan cannot be applied. "), h("ul", {}, t.problems.map((m) => h("li", {}, m)))) : null,
    o.error ? h("p", { class: "notice error", role: "alert" }, h("strong", {}, "Not applied. "), o.error) : null,
    h("p", { class: "note" }, "Costs are what this plan itself spends today. Growth is not predicted here."),
    actionButton(o.advanceLabel, o.advance, { class: "btn primary big", disabled: blocked }),
    h("button", { type: "button", class: "btn quiet small", onclick: o.askStop, "aria-expanded": String(o.confirmStop) }, o.confirmStop ? "Keep playing" : "Stop deciding…"),
    o.confirmStop ? h("div", { class: "notice warn stack tight" },
      h("p", {}, `Stopping does not end the season. Today runs the plan above, and the remaining ${Math.max(0, st.days_left - 1)} day${st.days_left - 1 === 1 ? "" : "s"} run the default plan. The result is taken at the end of the last day and cannot be changed afterwards.`),
      actionButton("Stop and let the default plan finish", o.stop, { class: "btn small", disabled: blocked })) : null);
}
