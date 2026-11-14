// @ts-check
/** Small DOM helpers. Text always goes in as text nodes, never as HTML. */

const SVG_NS = "http://www.w3.org/2000/svg";

/**
 * @param {Element} node
 * @param {Record<string, any>} attrs
 * @param {any[]} children
 */
function fill(node, attrs, children) {
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.setAttribute("class", String(value));
    else if (key === "dataset") Object.assign(/** @type {HTMLElement} */ (node).dataset, value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (key === "value" || key === "checked" || key === "disabled" || key === "selected") {
      /** @type {any} */ (node)[key] = value;
    } else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/**
 * Create an HTML element.
 * @param {string} tag
 * @param {Record<string, any>} [attrs]
 * @param {...any} children
 * @returns {HTMLElement}
 */
export function h(tag, attrs, ...children) {
  return /** @type {HTMLElement} */ (fill(document.createElement(tag), attrs || {}, children));
}

/**
 * Create an SVG element.
 * @param {string} tag
 * @param {Record<string, any>} [attrs]
 * @param {...any} children
 * @returns {SVGElement}
 */
export function s(tag, attrs, ...children) {
  return /** @type {SVGElement} */ (fill(document.createElementNS(SVG_NS, tag), attrs || {}, children));
}

/** @param {Element} node @param {...any} children */
export function replace(node, ...children) {
  node.replaceChildren(...children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false)
    .map((c) => (c instanceof Node ? c : document.createTextNode(String(c)))));
  return node;
}

const nf0 = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("en-GB", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const fmt = {
  /** @param {number} v */ int: (v) => nf0.format(v),
  /** @param {number} v */ one: (v) => nf1.format(v),
  /** @param {number} v */ two: (v) => nf2.format(v),
  /** @param {number} v */ eur: (v) => (v < 0 ? "−€" : "€") + nf2.format(Math.abs(v)),
  /** @param {number} v */ eur0: (v) => (v < 0 ? "−€" : "€") + nf0.format(Math.abs(v)),
  /** @param {number} v */ signedEur: (v) => (v < 0 ? "−€" : "+€") + nf0.format(Math.abs(v)),
  /** @param {number} v */ litres: (v) => nf0.format(v) + " L",
  /** @param {number} v */ kg: (v) => nf1.format(v) + " kg",
  /** @param {number} v */ grams: (v) => nf0.format(v) + " g",
  /** @param {number} v */ temp: (v) => nf1.format(v) + " °C",
  /** @param {number} v */ pct: (v) => nf0.format(v * 100) + "%",
  /** @param {number} v */ reward: (v) => v.toFixed(3),
  /** @param {string} iso */
  date: (iso) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
  },
};

/**
 * A status label that never relies on color alone: a shape, then words.
 * @param {"good"|"warn"|"bad"|"plain"} kind
 * @param {string} label
 */
export function badge(kind, label) {
  const icon = { good: "●", warn: "▲", bad: "■", plain: "" }[kind];
  return h("span", { class: `badge ${kind === "plain" ? "" : kind}` }, icon && h("span", { "aria-hidden": "true" }, icon), label);
}

/**
 * A button that shows progress and cannot be pressed twice while its action runs.
 * @param {string} label
 * @param {() => Promise<any>} action
 * @param {Record<string, any>} [attrs]
 */
export function actionButton(label, action, attrs) {
  const text = h("span", {}, label);
  const button = /** @type {HTMLButtonElement} */ (h("button", { type: "button", ...(attrs || {}) }, text));
  button.classList.add("btn");
  let busy = false;
  button.addEventListener("click", async () => {
    if (busy || button.disabled) return;
    busy = true;
    button.disabled = true;
    const spinner = h("span", { class: "spinner", "aria-hidden": "true" });
    button.prepend(spinner);
    try {
      await action();
    } finally {
      spinner.remove();
      busy = false;
      if (button.isConnected) button.disabled = false;
    }
  });
  return button;
}
