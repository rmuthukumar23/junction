// @ts-check
/** The game screen: the greenhouse, three sliders per bay, one button. Everything else is in Details. */
import { api, ApiError } from "./api.js";
import { h, replace, fmt, actionButton } from "./dom.js";
import { meter } from "./charts.js";
import { go } from "./nav.js";
import { PLAN_FIELDS, historyPanel } from "./zonecard.js";
import { planTotals } from "./summary.js";
import { testsPanel, rulesPanel, timeline } from "./panels.js";
import { greenhouseScene } from "./scene.js";
import { bay } from "./bay.js";

/** @typedef {{runId: string, root: HTMLElement, view: any, plan: Record<string, Record<string, number>>, error: string, report: any, bar: HTMLElement | null}} Ctx */

/** Today's starting plan: yesterday's water and feed (so only changes need touching), no flush. @param {any} view */
function startingPlan(view) {
  const st = view.status, today = st.plan_for_today, y = st.yesterday_plan;
  /** @type {Record<string, Record<string, number>>} */
  const out = {};
  for (const z of st.zones) {
    const base = today.source === "submitted" || !y ? today.zones[z.zone_id] : { ...y.zones[z.zone_id], flush_l: 0 };
    out[z.zone_id] = {};
    for (const f of PLAN_FIELDS) out[z.zone_id][f.key] = Math.round(Number(base[f.key]));
  }
  return out;
}

/** @param {HTMLElement} root @param {string} runId */
export async function renderPlay(root, runId) {
  const view = await api.view(runId);
  if (view.run.done) { go(`#/run/${runId}/result`); return; }
  draw({ runId, root, view, plan: startingPlan(view), error: "", report: null, bar: null });
}

/** @param {Ctx} ctx */
function hud(ctx) {
  const st = ctx.view.status, p = ctx.view.rules.parameters, w = st.fresh_water;
  const net = st.harvest_value_so_far_eur - st.costs_so_far.total_eur;
  return h("section", { class: "hud card" },
    h("div", { class: "hud-cell" }, h("span", { class: "label" }, "Day"), h("b", { class: "big num" }, `${st.day + 1}`, h("span", { class: "of" }, ` / ${st.days_total}`)),
      h("div", { class: "pips", "aria-hidden": "true" }, Array.from({ length: st.days_total }, (_, i) => h("i", { class: i < st.day ? "done" : i === st.day ? "now" : "" })))),
    h("div", { class: "hud-cell" }, h("span", { class: "label" }, "Fresh water left"), h("b", { class: "big num" }, fmt.litres(w.left_l)),
      meter({ value: w.left_l, max: w.allocation_l, label: "Fresh water left for the season" })),
    h("div", { class: "hud-cell" }, h("span", { class: "label" }, "Profit so far"), h("b", { class: "big num" }, fmt.eur0(net)),
      h("span", { class: "note" }, `${fmt.int(st.harvest_so_far_kg)} kg sold − ${fmt.eur0(st.costs_so_far.total_eur)} spent`)),
    h("div", { class: "hud-cell wide" }, h("span", { class: "label" }, "Forecast"),
      h("div", { class: "forecast", role: "list" }, ctx.view.forecast.days.map((/** @type {any} */ d) => {
        const hot = d.temp_c >= p.growth_heat_onset_c;
        return h("div", { class: `fc${hot ? " hot" : ""}${d.lead_days === 0 ? " today" : ""}`, role: "listitem", title: hot ? "Hot: plants drink more and grow less" : null },
          h("span", { class: "fc-day" }, d.lead_days === 0 ? "today" : `+${d.lead_days}`), h("b", { class: "num" }, `${Math.round(d.temp_c)}°`));
      }))));
}

/** @param {Ctx} ctx */
function draw(ctx) {
  const st = ctx.view.status;
  const on = {
    onPlan: (/** @type {string} */ zone, /** @type {string} */ key, /** @type {number} */ value) => { ctx.plan[zone][key] = value; ctx.error = ""; refreshBar(ctx); },
    onTest: async (/** @type {string} */ zone) => {
      await guarded(ctx, async () => {
        const reply = await api.call(ctx.runId, "order_test", { zone_id: zone, test_type: "composition" });
        ctx.error = reply.ok ? "" : reply.error.message;
        ctx.view = await api.view(ctx.runId);
      });
      draw(ctx);
    },
  };
  ctx.bar = h("div", { class: "actionbar card" });
  const grown = ctx.report ? ctx.report.zones.reduce((/** @type {number} */ a, /** @type {any} */ z) => a + z.growth_kg, 0) : 0;
  /** @type {HTMLElement} */
  const lazy = h("div", { class: "stack" });
  replace(ctx.root,
    hud(ctx),
    ctx.report ? h("p", { class: "flash", role: "status" }, `Yesterday: ${fmt.temp(ctx.report.temp_c)}, +${fmt.int(grown)} kg, cost ${fmt.eur0(ctx.report.day_cost_eur)}` +
      (ctx.report.tests_delivered.length ? ` · ${ctx.report.tests_delivered.length} test result${ctx.report.tests_delivered.length > 1 ? "s" : ""} in` : "")) : null,
    h("section", { class: "card house" },
      greenhouseScene(ctx.view),
      h("div", { class: "bays" }, st.zones.map((/** @type {any} */ z) => bay(ctx.view, z, ctx.plan[z.zone_id], on)))),
    ctx.bar,
    h("details", { class: "card pad drawer", ontoggle: (/** @type {Event} */ ev) => {
      if (/** @type {HTMLDetailsElement} */ (ev.currentTarget).open && !lazy.childElementCount) {
        replace(lazy, st.zones.map((/** @type {any} */ z) => h("div", { class: "stack" }, h("h3", {}, z.name), historyPanel(ctx.view, z.zone_id))),
          testsPanel(ctx.view), rulesPanel(ctx.view), timeline(ctx.view.events.events));
      }
    } }, h("summary", {}, "Details: charts, lab results, rules, log"), lazy));
  refreshBar(ctx);
}

/** @param {Ctx} ctx */
function refreshBar(ctx) {
  if (!ctx.bar) return;
  const st = ctx.view.status, w = st.fresh_water, t = planTotals(ctx.view, ctx.plan);
  const problem = t.problems[0] || ctx.error;
  const last = st.days_left === 1;
  replace(ctx.bar,
    h("div", { class: "ab-water" }, h("span", { class: "label" }, "Water today"),
      meter({ value: t.water, max: Math.max(w.available_today_l, 1), state: t.water > w.available_today_l ? "bad" : "ok", label: "Fresh water this plan uses today" }),
      h("span", { class: "num" }, `${fmt.int(t.water)} / ${fmt.int(w.available_today_l)} L`)),
    h("div", { class: "ab-cost" }, h("span", { class: "label" }, "Cost today"), h("b", { class: "num" }, fmt.eur0(t.total))),
    problem ? h("p", { class: "ab-error", role: "alert" }, problem) : h("span", { class: "ab-spacer" }),
    h("button", { type: "button", class: "btn quiet small", title: "Today runs these settings; every remaining day runs the default plan.",
      onclick: () => { if (window.confirm(`Stop here? The remaining ${st.days_left - 1} days run on the default plan and the result is final.`)) advance(ctx, true); } }, "Stop here"),
    actionButton(last ? "Finish season →" : "Next day →", () => advance(ctx, false), { class: "btn primary big go", disabled: t.problems.length > 0 }));
}

/** @param {Ctx} ctx @param {() => Promise<void>} action */
async function guarded(ctx, action) {
  try {
    await action();
  } catch (err) {
    ctx.error = err instanceof ApiError ? err.message : `Something went wrong: ${/** @type {Error} */ (err).message}`;
    try { ctx.view = await api.view(ctx.runId); } catch (ignored) { /* keep the last view */ }
  }
}

/**
 * Submit the plan, then advance one day (or stop for good). Each request names its day, so a
 * repeated click or a stale tab cannot play a day twice.
 * @param {Ctx} ctx @param {boolean} stop
 */
async function advance(ctx, stop) {
  const day = ctx.view.status.day;
  let moved = false;
  await guarded(ctx, async () => {
    const submitted = await api.call(ctx.runId, "submit_day_plan", { zone_plans: ctx.plan }, day);
    if (!submitted.ok) { ctx.error = submitted.error.message; return; }
    const reply = await api.call(ctx.runId, stop ? "finish_episode" : "advance_day", {}, day);
    if (!reply.ok) { ctx.error = reply.error.message; return; }
    ctx.error = "";
    ctx.report = stop ? null : reply.result;
    ctx.view = await api.view(ctx.runId);
    moved = true;
  });
  if (ctx.view.run.done) { go(`#/run/${ctx.runId}/result`); return; }
  if (moved) ctx.plan = startingPlan(ctx.view);
  draw(ctx);
  if (moved) window.scrollTo(0, 0);
}
