// @ts-check
/** The start screen: the one idea, shown, and a button. */
import { api } from "./api.js";
import { h, replace, actionButton } from "./dom.js";
import { go } from "./nav.js";

/** @param {string} label @param {number} nutrient @param {number} salt @param {string} verdict */
function ecRow(label, nutrient, salt, verdict) {
  const ec = (1.5 * (nutrient + salt)).toFixed(1);
  return h("div", { class: "ec-row" }, h("b", {}, label),
    h("div", { class: "ec-bar", role: "img", "aria-label": `${label}: EC ${ec}. Nutrients ${nutrient}, salts ${salt} grams per litre. ${verdict}` },
      h("span", { class: "nut", style: `flex:${nutrient}` }, "nutrients"), h("span", { class: "salt", style: `flex:${salt}` }, "salts")),
    h("span", { class: "ec-says" }, h("b", { class: "num" }, `EC ${ec}`), h("span", { class: "muted" }, verdict)));
}

/** @param {HTMLElement} root @param {any} config */
export async function renderStart(root, config) {
  const seeds = config.seeds;
  const select = /** @type {HTMLSelectElement} */ (h("select", { id: "seed", "aria-label": "Scenario" },
    h("option", { value: String(seeds.demo) }, `Demo scenario`),
    [...seeds.development, ...seeds.evaluation].map((/** @type {number} */ v) => h("option", { value: String(v) }, `Seed ${v}`))));
  const name = /** @type {HTMLInputElement} */ (h("input", { id: "player", type: "text", maxlength: "40", placeholder: "Your name", autocomplete: "off", "aria-label": "Your name" }));
  const error = h("p", { class: "notice error", hidden: true, role: "alert" });
  const start = actionButton("Start →", async () => {
    error.hidden = true;
    try {
      go(`#/run/${(await api.createRun(Number(select.value), name.value)).run.run_id}`);
    } catch (err) {
      error.textContent = /** @type {Error} */ (err).message;
      error.hidden = false;
    }
  }, { class: "btn primary big" });

  replace(root, h("section", { class: "card intro" },
    h("h1", {}, "Same sensor reading. Opposite problem."),
    h("div", { class: "ec-demo" },
      ecRow("Zone X", 2.0, 0.4, "overfed"),
      ecRow("Zone Y", 0.5, 1.9, "starving in salt")),
    h("p", { class: "lede" }, `Run four tomato zones for ${config.days} days. Each day: water, feed or flush each zone, then advance. End with the most profit.`),
    h("div", { class: "trio" },
      h("div", {}, h("b", {}, "Feed"), h("span", {}, "fixes hunger, raises EC")),
      h("div", {}, h("b", {}, "Flush"), h("span", {}, "removes salt, costs scarce water")),
      h("div", {}, h("b", {}, "Test · €25"), h("span", {}, "shows the split, tomorrow"))),
    h("div", { class: "start-row" }, name, select, start),
    error,
    h("p", { class: "note" }, "A benchmark: an AI agent plays this same game through tools and is scored on the same profit. At the end you see your result beside a do-nothing baseline, a rule-based policy and a reference planner.")));
  name.focus();
}
