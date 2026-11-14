// @ts-check
/** Entry point: routing and top-level error handling. Each screen renders itself into <main>. */
import { api, ApiError } from "./api.js";
import { h, replace } from "./dom.js";
import { routeParts } from "./nav.js";
import { renderStart } from "./start.js";
import { renderPlay } from "./play.js";
import { renderEnd } from "./end.js";
import { renderReplay } from "./replay.js";
import { renderRuns } from "./runs.js";

const root = /** @type {HTMLElement} */ (document.getElementById("app"));
/** @type {any} */
let config = null;
let token = 0;

/** @param {string} name */
function setNav(name) {
  document.querySelectorAll("[data-nav]").forEach((a) => {
    if (a.getAttribute("data-nav") === name) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
}

async function route() {
  const mine = ++token;
  const parts = routeParts();
  setNav(parts[0] === "runs" ? "runs" : parts.length === 0 ? "start" : "");
  try {
    if (!config) config = await api.config();
    if (mine !== token) return;
    if (parts[0] === "run" && parts[1]) {
      if (parts[2] === "replay") await renderReplay(root, parts[1], parts[3] === undefined ? 0 : Number(parts[3]));
      else if (parts[2] === "result") await renderEnd(root, parts[1]);
      else await renderPlay(root, parts[1]);
    } else if (parts[0] === "runs") await renderRuns(root);
    else await renderStart(root, config);
  } catch (err) {
    if (mine !== token) return;
    const message = err instanceof ApiError ? err.message : `Something went wrong: ${/** @type {Error} */ (err).message}`;
    replace(root, h("div", { class: "card pad stack", role: "alert" },
      h("h2", {}, "This page could not be shown"),
      h("p", { class: "notice error" }, message),
      h("div", { class: "row" }, h("a", { class: "btn", href: "#/" }, "Start page"), h("a", { class: "btn", href: "#/runs" }, "Past runs"))));
    console.error(err);
  }
  if (mine === token) window.scrollTo(0, 0);
}

window.addEventListener("hashchange", route);
route();
