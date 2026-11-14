// Palette-indexed images (no DOM): parse grids, palette swaps, mirror, and RotSprite-style rotation.
// Everything here runs once at load time; drawing uses the baked canvases (bank.ts).
import type { Vec } from "./sheet";

export interface IndexImage {
  w: number;
  h: number;
  /** Palette indices, row-major; 0 = transparent. */
  data: Uint8Array;
  /** Anchor pixel. */
  ax: number;
  ay: number;
  /** Named points, in this image's pixels. */
  pts: Record<string, Vec>;
}

export function parseGrid(rows: readonly string[], keyIndex: Readonly<Record<string, number>>, swap?: Readonly<Record<string, string>>,
  anchor: Vec = [0, 0], pts: Record<string, Vec> = {}): IndexImage {
  const h = rows.length, w = h ? rows[0].length : 0, data = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    let ch = rows[y][x];
    if (swap && swap[ch]) ch = swap[ch];
    const v = keyIndex[ch];
    if (v === undefined) throw new Error(`unknown palette key '${ch}'`);
    data[y * w + x] = v;
  }
  return { w, h, data, ax: anchor[0], ay: anchor[1], pts: { ...pts } };
}

export function flipX(img: IndexImage): IndexImage {
  const { w, h } = img, data = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) data[y * w + x] = img.data[y * w + (w - 1 - x)];
  const pts: Record<string, Vec> = {};
  for (const k in img.pts) pts[k] = [w - 1 - img.pts[k][0], img.pts[k][1]];
  return { w, h, data, ax: w - 1 - img.ax, ay: img.ay, pts };
}

/** Scale2x (EPX): doubles the image, keeping diagonal edges smooth. */
export function scale2x(src: Uint8Array, w: number, h: number): Uint8Array {
  const W = w * 2, out = new Uint8Array(W * h * 2);
  const at = (x: number, y: number) => src[(y < 0 ? 0 : y >= h ? h - 1 : y) * w + (x < 0 ? 0 : x >= w ? w - 1 : x)];
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const P = at(x, y), A = at(x, y - 1), B = at(x + 1, y), C = at(x - 1, y), D = at(x, y + 1);
    const o = y * 2 * W + x * 2;
    out[o] = C === A && C !== D && A !== B ? A : P;
    out[o + 1] = A === B && A !== C && B !== D ? B : P;
    out[o + W] = D === C && D !== B && C !== A ? C : P;
    out[o + W + 1] = B === D && B !== A && D !== C ? D : P;
  }
  return out;
}

/**
 * Rotate by `deg` (clockwise on screen) around the anchor pixel's centre, RotSprite style:
 * upscale 8x with Scale2x, sample the rotated big image at each output pixel's centre, trim.
 * Points rotate with the image. deg = 0 returns a copy.
 */
export function rotate(img: IndexImage, deg: number): IndexImage {
  if (deg === 0) return { ...img, data: img.data.slice(), pts: { ...img.pts } };
  let big = img.data, bw = img.w, bh = img.h;
  for (let i = 0; i < 3; i++) { big = scale2x(big, bw, bh); bw *= 2; bh *= 2; }
  const rad = (deg * Math.PI) / 180, c = Math.cos(rad), s = Math.sin(rad);
  const cx = img.ax + 0.5, cy = img.ay + 0.5;
  // Square canvas big enough for any rotation, anchor pixel at its centre.
  let R = 0;
  for (const [x, y] of [[0, 0], [img.w, 0], [0, img.h], [img.w, img.h]]) R = Math.max(R, Math.hypot(x - cx, y - cy));
  const r = Math.ceil(R) + 1, size = 2 * r + 1, data = new Uint8Array(size * size);
  for (let oy = 0; oy < size; oy++) for (let ox = 0; ox < size; ox++) {
    const dx = ox - r, dy = oy - r; // offset of the output pixel centre from the anchor centre
    const sx = cx + dx * c + dy * s, sy = cy - dx * s + dy * c; // inverse rotation
    if (sx < 0 || sy < 0 || sx >= img.w || sy >= img.h) continue;
    data[oy * size + ox] = big[Math.floor(sy * 8) * bw + Math.floor(sx * 8)];
  }
  const pts: Record<string, Vec> = {};
  for (const k in img.pts) {
    const dx = img.pts[k][0] + 0.5 - cx, dy = img.pts[k][1] + 0.5 - cy;
    pts[k] = [Math.round(r + dx * c - dy * s - 0.0001), Math.round(r + dx * s + dy * c - 0.0001)];
  }
  return trim({ w: size, h: size, data, ax: r, ay: r, pts });
}

/** Crop transparent borders, keeping the anchor and points where they were. */
export function trim(img: IndexImage): IndexImage {
  const { w, h, data } = img;
  let x0 = w, y0 = h, x1 = -1, y1 = -1;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (data[y * w + x]) {
    if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
  }
  if (x1 < 0) return { w: 1, h: 1, data: new Uint8Array(1), ax: 0, ay: 0, pts: { ...img.pts } };
  const nw = x1 - x0 + 1, nh = y1 - y0 + 1, out = new Uint8Array(nw * nh);
  for (let y = 0; y < nh; y++) out.set(data.subarray((y + y0) * w + x0, (y + y0) * w + x0 + nw), y * nw);
  const pts: Record<string, Vec> = {};
  for (const k in img.pts) pts[k] = [img.pts[k][0] - x0, img.pts[k][1] - y0];
  return { w: nw, h: nh, data: out, ax: img.ax - x0, ay: img.ay - y0, pts };
}

/** Angles baked for a rotate spec [from, to, step]. */
export function angleList(spec: readonly [number, number, number]): number[] {
  const out: number[] = [];
  for (let a = spec[0]; a <= spec[1] + 1e-9; a += spec[2]) out.push(Math.round(a * 1000) / 1000);
  return out;
}
