// @ts-check
/** Hash routes: #/ start, #/runs, #/run/<id> play, #/run/<id>/result, #/run/<id>/replay[/<day>]. */

/** @param {string} hash */
export function go(hash) {
  if (location.hash === hash) window.dispatchEvent(new HashChangeEvent("hashchange"));
  else location.hash = hash;
}

/** @returns {string[]} */
export function routeParts() {
  return (location.hash.replace(/^#/, "") || "/").split("/").filter(Boolean);
}
