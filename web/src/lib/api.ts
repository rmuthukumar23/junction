import { buildMock, mockList } from "./mock";
import { MOCK } from "./route";

/** GET a JSON endpoint of the Python server; in ?mock=1 mode /api/runs[/id] is answered locally. */
export function fetchJson<T = unknown>(url: string): Promise<T> {
  if (MOCK) {
    if (url.indexOf("/api/runs") === 0) {
      const rest = url.slice(9).replace(/^\//, "");
      return Promise.resolve((rest ? buildMock(decodeURIComponent(rest)) : mockList()) as T);
    }
    return Promise.reject(new Error("mock mode: no backend for " + url));
  }
  return fetch(url).then((r) => {
    if (!r.ok) {
      return r.json().catch(() => ({})).then((j: { error?: string }) => {
        throw new Error(j.error || url + " -> HTTP " + r.status);
      });
    }
    return r.json() as Promise<T>;
  });
}
