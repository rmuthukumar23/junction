// @ts-check
/** The server API. The browser keeps no authoritative state: it shows what the server returns and posts tool calls. */

export class ApiError extends Error {
  /** @param {string} message @param {number} status @param {any} [payload] */
  constructor(message, status, payload) {
    super(message);
    this.status = status;
    this.payload = payload;
  }
}

/**
 * @param {string} path
 * @param {{method?: string, body?: any}} [options]
 * @returns {Promise<any>}
 */
async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      method: options.method || "GET",
      headers: options.body === undefined ? {} : { "Content-Type": "application/json" },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: "no-store",
    });
  } catch (err) {
    throw new ApiError("The server did not respond. Is `python -m rootcause_app` still running?", 0);
  }
  let payload = null;
  try {
    payload = await response.json();
  } catch (err) {
    payload = null;
  }
  if (!response.ok) {
    throw new ApiError((payload && payload.error) || `Request failed (${response.status})`, response.status, payload);
  }
  return payload;
}

export const api = {
  config: () => request("/api/config"),
  runs: () => request("/api/runs"),
  /** @param {number} seed @param {string} player */
  createRun: (seed, player) => request("/api/runs", { method: "POST", body: { seed, player } }),
  /** @param {string} id */
  view: (id) => request(`/api/runs/${id}/view`),
  /** @param {string} id */
  report: (id) => request(`/api/runs/${id}/report`),
  /** @param {string} id @param {number} [day] */
  whatIf: (id, day) => request(`/api/runs/${id}/whatif${day === undefined ? "" : `?day=${day}`}`),
  /**
   * One tool call, exactly as an agent makes it. Returns the engine's envelope {ok, result | error, header}.
   * @param {string} id @param {string} tool @param {any} [args] @param {number} [expectDay]
   */
  call: (id, tool, args, expectDay) =>
    request(`/api/runs/${id}/call`, { method: "POST", body: { tool, args: args || {}, expect_day: expectDay } }),
};
