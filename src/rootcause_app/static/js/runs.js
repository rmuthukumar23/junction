// @ts-check
/** Every run that has been played on this server. Starting a new run never removes one. */
import { api } from "./api.js";
import { h, replace, fmt, badge } from "./dom.js";

/** @param {HTMLElement} root */
export async function renderRuns(root) {
  const { runs } = await api.runs();
  replace(root, h("div", { class: "stack" },
    h("div", { class: "spread" }, h("h1", {}, "Past runs"), h("a", { class: "btn primary", href: "#/" }, "New run")),
    runs.length === 0
      ? h("p", { class: "card pad muted" }, "No runs yet.")
      : h("section", { class: "card pad" }, h("div", { class: "table-wrap" }, h("table", { class: "data" },
        h("thead", {}, h("tr", {}, ["Player", "Seed", "Started", "Status", "Net profit", "Reward", ""].map((c) => h("th", {}, c)))),
        h("tbody", {}, runs.map((/** @type {any} */ r) => {
          const res = r.result;
          return h("tr", {},
            h("td", {}, r.player), h("td", { class: "num" }, String(r.seed)), h("td", {}, fmt.date(r.created_at)),
            h("td", {}, r.done ? badge("good", "finished") : badge("warn", `in progress, day ${r.day} of ${r.days_total}`)),
            h("td", { class: "num" }, r.done ? fmt.eur(res.profit_eur) : h("span", { class: "muted" }, "no result yet")),
            h("td", { class: "num" }, r.done ? fmt.reward(res.reward) : h("span", { class: "muted" }, "–")),
            h("td", {}, h("a", { class: "btn small", href: r.done ? `#/run/${r.run_id}/result` : `#/run/${r.run_id}` }, r.done ? "Result" : "Continue")));
        }))))),
    h("p", { class: "note" }, "Results are recomputed from each run's action log every time this page loads. An unfinished run has no result, and none is estimated: closing the browser does not freeze a position. Whenever it is ended, the default plan runs every day that was not played.")));
}
