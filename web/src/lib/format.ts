export const clamp = (v: number, a: number, b: number): number => (v < a ? a : v > b ? b : v);

const isNum = (v: unknown): v is number => typeof v === "number" && !isNaN(v);

/** "EUR 1,234", "-EUR 50", with sign=true "+EUR 50". "-" for missing values. */
export function eur(v: number | null | undefined, sign = false): string {
  if (!isNum(v)) return "-";
  return (v < 0 ? "-" : sign && v > 0 ? "+" : "") + "EUR " + Math.abs(Math.round(v)).toLocaleString("en-US");
}

export function num(v: number | null | undefined, d = 0): string {
  if (!isNum(v)) return "-";
  return Number(v).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
}

/** Hour index -> "D3 06:00" (days from 1). */
export const when = (h: number): string => "D" + (Math.floor(h / 24) + 1) + " " + String(h % 24).padStart(2, "0") + ":00";

export function esc(s: unknown): string {
  return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);
}

/** Index of the first item with .h >= h in an array sorted by h. */
export function lowerBound(arr: ReadonlyArray<{ h: number }>, h: number): number {
  let lo = 0, hi = arr.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (arr[m].h < h) lo = m + 1; else hi = m; }
  return lo;
}

export function hashStr(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}
