// @ts-check
/** The end screen: the result, how it was calculated, and the same scenario played by the comparators. */
import { api, ApiError } from "./api.js";
import { h, replace, fmt, badge, actionButton } from "./dom.js";
import { barRows } from "./charts.js";
import { go } from "./nav.js";

/** @param {any} r result ledger @param {any} p prices */
function calculation(r, p) {
  /** @type {[string, string, string][]} */
  const rows = [
    ["Harvest sold", `${fmt.one(r.harvest_kg)} kg × ${fmt.eur(p.price_per_kg)}`, fmt.eur(r.revenue_eur)],
    ["Fresh water", `${fmt.int(r.fresh_water_used_l)} L × ${fmt.eur(p.water_price_per_l)}`, fmt.eur(-r.cost_water_eur)],
    ["Fertilizer", `${fmt.int(r.fertilizer_used_g)} g × ${fmt.eur(p.fertilizer_price_per_g)}`, fmt.eur(-r.cost_fertilizer_eur)],
    ["Discharge to waste", `flushed and overflowed litres × ${fmt.eur(p.discharge_price_per_l)}`, fmt.eur(-r.cost_discharge_eur)],
    ["Lab tests", `${r.tests_ordered} × ${fmt.eur(p.test_price)}`, fmt.eur(-r.cost_tests_eur)],
  ];
  return h("table", { class: "data" },
    h("thead", {}, h("tr", {}, h("th", {}, "Item"), h("th", {}, "Quantity"), h("th", {}, "Amount"))),
    h("tbody", {}, rows.map(([a, b, c]) => h("tr", {}, h("td", {}, a), h("td", { class: "num muted" }, b), h("td", { class: "num" }, c))),
      h("tr", { class: "total" }, h("td", {}, "Net profit"), h("td", {}), h("td", { class: "num" }, fmt.eur(r.profit_eur)))));
}

/** @param {any} report */
function comparison(report) {
  const mine = report.result;
  const runs = report.comparators.runs;
  const rows = [
    { label: `${report.run.player} (this run)`, value: mine.profit_eur, note: `reward ${fmt.reward(mine.reward)}`, emphasis: true, detail: "Your run, recomputed from its action log." },
    ...runs.map((/** @type {any} */ c) => ({ label: c.label, value: c.profit_eur, note: `reward ${fmt.reward(c.reward)}`, detail: c.description })),
  ].sort((a, b) => b.value - a.value);
  const reference = runs.find((/** @type {any} */ c) => c.policy === "reference");
  const gap = mine.profit_eur - reference.profit_eur;
  const llm = report.llm;
  return h("section", { class: "card pad stack" },
    h("div", { class: "spread" }, h("h2", {}, "You vs. the baselines"), h("span", { class: "muted small" }, "net profit, same scenario")),
    barRows(rows, { max: mine.profit_ceiling_eur }),
    h("p", {}, gap >= 0 ? `${fmt.eur0(gap)} ahead of the reference planner.` : `${fmt.eur0(-gap)} behind the reference planner.`,
      h("span", { class: "muted" }, " Every bar is a real run on this same scenario.")),
    h("details", {}, h("summary", {}, "Comparison as a table"),
      h("div", { class: "table-wrap" }, h("table", { class: "data" },
        h("thead", {}, h("tr", {}, ["Player", "Net profit", "Reward", "Harvest kg", "Costs", "Tests", "Days planned"].map((c) => h("th", {}, c)))),
        h("tbody", {},
          h("tr", { class: "selected" }, h("td", {}, `${report.run.player} (this run)`), h("td", { class: "num" }, fmt.eur(mine.profit_eur)), h("td", { class: "num" }, fmt.reward(mine.reward)),
            h("td", { class: "num" }, fmt.one(mine.harvest_kg)), h("td", { class: "num" }, fmt.eur(mine.cost_total_eur)), h("td", { class: "num" }, String(mine.tests_ordered)), h("td", { class: "num" }, String(mine.days_with_a_submitted_plan))),
          runs.map((/** @type {any} */ c) => h("tr", {}, h("td", {}, c.label, h("div", { class: "note" }, c.description)), h("td", { class: "num" }, fmt.eur(c.profit_eur)), h("td", { class: "num" }, fmt.reward(c.reward)),
            h("td", { class: "num" }, fmt.one(c.harvest_kg)), h("td", { class: "num" }, fmt.eur(c.cost_total_eur)), h("td", { class: "num" }, String(c.tests_ordered)), h("td", { class: "num" }, String(c.days_with_a_submitted_plan)))))))),
    h("div", { class: "llm" },
      h("div", { class: "spread" }, h("h3", {}, "AI agent"), llm.status === "recorded" ? badge("good", "recorded runs") : badge("warn", "not run yet")),
      llm.status === "recorded"
        ? h("ul", {}, llm.runs.map((/** @type {any} */ run) => h("li", {}, `${run.model}: ${fmt.eur(run.profit_eur)}, score ${fmt.reward(run.reward)}`)))
        : h("p", { class: "small muted" }, "Needs a model credential: ", h("code", {}, llm.command))));
}

/** @param {any} report */
function zoneTable(report) {
  const a = report.analysis;
  const first = a.days[0].zones;
  return h("section", { class: "card pad stack" },
    h("div", { class: "spread" }, h("h2", {}, "What each zone really was"), h("span", { class: "muted small" }, "hidden during play")),
    h("div", { class: "table-wrap" }, h("table", { class: "data" },
      h("thead", {}, h("tr", {}, ["Zone", "Started as", "EC shown day 0", "Nutrients g/L", "Salts g/L", "Harvest kg", "Final condition"].map((c) => h("th", {}, c)))),
      h("tbody", {}, Object.entries(a.zones).map(([id, /** @type {any} */ z]) => h("tr", {},
        h("td", {}, z.name), h("td", {}, String(z.starting_composition_type).replace("_", ", ")),
        h("td", { class: "num" }, fmt.two(first[id].morning.ec_ds_m)),
        h("td", { class: "num" }, fmt.two(first[id].hidden_morning.nutrient_g_l)),
        h("td", { class: "num" }, fmt.two(first[id].hidden_morning.salt_g_l)),
        h("td", { class: "num" }, fmt.one(z.harvest_kg)), h("td", { class: "num" }, fmt.two(z.final_condition))))))));
}

/** @param {any} w */
function whatIfView(w) {
  if (!w.points.length) return h("p", { class: "muted" }, "No day was played with a decision, so there is nothing to substitute.");
  return h("div", { class: "stack" },
    h("p", { class: "small" }, w.method),
    w.points.map((/** @type {any} */ pt) => h("div", { class: "stack tight" },
      h("h3", {}, `Day ${pt.day}`, h("span", { class: "muted" }, ` (${pt.plan_source === "submitted" ? "your plan" : "default plan"} was applied)`)),
      h("div", { class: "table-wrap" }, h("table", { class: "data" },
        h("thead", {}, h("tr", {}, ["Instead, on that day only", "Final profit", "Change", "Later plans rejected"].map((c) => h("th", {}, c)))),
        h("tbody", {}, pt.alternatives.map((/** @type {any} */ alt) => alt.feasible
          ? h("tr", {}, h("td", {}, alt.alternative), h("td", { class: "num" }, fmt.eur(alt.profit_eur)), h("td", { class: "num" }, fmt.signedEur(alt.delta_eur)), h("td", { class: "num" }, String(alt.later_plans_rejected)))
          : h("tr", {}, h("td", {}, alt.alternative), h("td", { colspan: "3", class: "muted" }, "not feasible at that point, so not evaluated"))))))))
  );
}

/** @param {HTMLElement} root @param {string} runId */
export async function renderEnd(root, runId) {
  let report;
  try {
    report = await api.report(runId);
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) { go(`#/run/${runId}`); return; }
    throw err;
  }
  const r = report.result;
  const view = await api.view(runId);
  const p = view.rules.parameters;
  const whatIf = h("div", {});
  const span = r.profit_ceiling_eur - r.profit_floor_eur;
  replace(root, h("div", { class: "stack" },
    h("div", { class: "spread" },
      h("p", { class: "eyebrow" }, `${report.run.player} · seed ${report.run.seed}`),
      h("div", { class: "row" }, h("a", { class: "btn", href: `#/run/${runId}/replay` }, "Replay day by day"), h("a", { class: "btn primary", href: "#/" }, "New run"))),
    h("section", { class: "card pad verdict" },
      h("div", {}, h("p", { class: "eyebrow" }, "Net profit"), h("p", { class: "hero-figure num" }, fmt.eur0(r.profit_eur)),
        h("p", { class: "muted" }, `${fmt.int(r.harvest_kg)} kg sold for ${fmt.eur0(r.revenue_eur)}, ${fmt.eur0(r.cost_total_eur)} spent`)),
      h("div", {}, h("p", { class: "eyebrow" }, "Score"), h("p", { class: "hero-figure num" }, fmt.reward(r.reward)),
        h("p", { class: "muted" }, "0 = doing nothing · 1 = perfect, unreachable")),
      report.days_played_by_player < r.days_played
        ? h("p", { class: "notice warn" }, `Stopped after ${report.days_played_by_player} day${report.days_played_by_player === 1 ? "" : "s"}; the default plan ran the other ${r.days_played - report.days_played_by_player}.`) : null,
      report.replay.consistent && r.conservation_ok === 1 ? null : h("p", { class: "notice error" }, "This run did not replay cleanly from its action log.")),
    comparison(report),
    zoneTable(report),
    h("details", { class: "card pad" }, h("summary", {}, "How the profit was calculated"),
      h("div", { class: "table-wrap" }, calculation(r, p)),
      h("p", { class: "note" }, `Score = (profit − ${fmt.eur0(r.profit_floor_eur)}) ÷ ${fmt.eur0(span)}. The first number is what the default plan earns here; the range ends at an upper bound no plan reaches. Recomputed from ${report.replay.calls} logged requests.`)),
    h("details", { class: "card pad" }, h("summary", {}, "What-if: would one different day have helped?"),
      h("div", { class: "stack" },
        actionButton("Run the what-if analysis", async () => { replace(whatIf, whatIfView(await api.whatIf(runId))); }, { class: "btn" }), whatIf))));
}
