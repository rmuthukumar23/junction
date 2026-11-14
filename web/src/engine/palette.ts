// The site's one colour set (art/palette.json). Index 0 is transparent; colour i is index i + 1.
import data from "../art/palette.json";

export interface PaletteColor { key: string; name: string; hex: string }

export const COLORS: readonly PaletteColor[] = data.colors.map(([key, name, hex]) => ({ key, name, hex }));

/** Grid character -> palette index (1-based); "." -> 0. */
export const KEY_INDEX: Readonly<Record<string, number>> = Object.fromEntries([[".", 0], ...COLORS.map((c, i) => [c.key, i + 1])]);

/** Palette index -> packed RGBA (little-endian ABGR for a Uint32Array view of ImageData). */
export const RGBA32: Uint32Array = (() => {
  const out = new Uint32Array(COLORS.length + 1);
  COLORS.forEach((c, i) => {
    const r = parseInt(c.hex.slice(1, 3), 16), g = parseInt(c.hex.slice(3, 5), 16), b = parseInt(c.hex.slice(5, 7), 16);
    out[i + 1] = ((255 << 24) | (b << 16) | (g << 8) | r) >>> 0;
  });
  return out;
})();

/** Name -> hex, for fillStyle (e.g. PAL.leafHi). */
export const PAL: Readonly<Record<string, string>> = Object.fromEntries(COLORS.map((c) => [c.name, c.hex]));
/** Key -> hex (e.g. HEX.k). */
export const HEX: Readonly<Record<string, string>> = Object.fromEntries(COLORS.map((c) => [c.key, c.hex]));
