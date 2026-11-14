// Bakes sprite frames into 1x canvases once, then draws them with integer positions only.
// Views are created at setup time; the per-frame path (SpriteView.frame / drawFrame) allocates nothing.
import { KEY_INDEX, RGBA32 } from "./palette";
import { angleList, flipX, parseGrid, rotate, type IndexImage } from "./pixels";
import type { AnimDef, SheetFile, SpriteDef, Vec } from "./sheet";

export interface Frame {
  img: HTMLCanvasElement;
  w: number;
  h: number;
  /** Anchor pixel: drawFrame(ctx, f, X, Y) puts it at (X, Y). */
  ax: number;
  ay: number;
  /** Named points relative to the anchor (add to the draw position). */
  pts: Record<string, Vec>;
}

export interface ViewOptions { variant?: string; flip?: boolean }

export class SpriteView {
  /** frames[i] is frame i unrotated; byAngle[a][i] is frame i at angles[a]. */
  constructor(
    readonly name: string,
    readonly frames: Frame[],
    readonly angles: number[],
    readonly byAngle: Frame[][],
    readonly hitbox: [number, number, number, number] | null,
  ) {}

  /** Frame `i` at the baked angle nearest to `deg` (unrotated if the sprite has no rotations). */
  frame(i: number, deg = 0): Frame {
    const n = this.frames.length, fi = ((i % n) + n) % n;
    if (!this.angles.length) return this.frames[fi];
    const a = this.angles, step = a.length > 1 ? a[1] - a[0] : 1;
    let k = Math.round((deg - a[0]) / step);
    k = k < 0 ? 0 : k >= a.length ? a.length - 1 : k;
    return this.byAngle[k][fi];
  }
}

function toCanvas(img: IndexImage): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = img.w; c.height = img.h;
  const ctx = c.getContext("2d") as CanvasRenderingContext2D, id = ctx.createImageData(img.w, img.h);
  const px = new Uint32Array(id.data.buffer);
  for (let i = 0; i < img.data.length; i++) px[i] = RGBA32[img.data[i]];
  ctx.putImageData(id, 0, 0);
  return c;
}

function toFrame(img: IndexImage): Frame {
  const pts: Record<string, Vec> = {};
  for (const k in img.pts) pts[k] = [img.pts[k][0] - img.ax, img.pts[k][1] - img.ay];
  return { img: toCanvas(img), w: img.w, h: img.h, ax: img.ax, ay: img.ay, pts };
}

export class SpriteBank {
  readonly sprites: Record<string, SpriteDef> = {};
  readonly anims: Record<string, AnimDef> = {};
  private views = new Map<string, SpriteView>();

  constructor(sheets: SheetFile[]) {
    for (const sh of sheets) {
      for (const [k, v] of Object.entries(sh.sprites)) { if (this.sprites[k]) throw new Error(`duplicate sprite ${k}`); this.sprites[k] = v; }
      for (const [k, v] of Object.entries(sh.anims || {})) { if (this.anims[k]) throw new Error(`duplicate anim ${k}`); this.anims[k] = v; }
    }
  }

  /** A baked view of a sprite (cached). Call at setup time, not per frame. */
  view(name: string, opt: ViewOptions = {}): SpriteView {
    const key = `${name}|${opt.variant || ""}|${opt.flip ? 1 : 0}`;
    const hit = this.views.get(key);
    if (hit) return hit;
    const def = this.sprites[name];
    if (!def) throw new Error(`unknown sprite ${name}`);
    const swap = opt.variant ? def.variants?.[opt.variant] : undefined;
    if (opt.variant && !swap) throw new Error(`sprite ${name} has no variant ${opt.variant}`);
    const base = def.frames.map((rows) => parseGrid(rows, KEY_INDEX, swap, def.anchor, def.points));
    const fin = (im: IndexImage) => toFrame(opt.flip ? flipX(im) : im);
    const angles = def.rotate ? angleList(def.rotate) : [];
    const byAngle = angles.map((a) => base.map((im) => fin(rotate(im, a))));
    let hb = def.hitbox || null;
    if (hb && opt.flip) hb = [base[0].w - hb[0] - hb[2], hb[1], hb[2], hb[3]];
    const v = new SpriteView(name, base.map(fin), angles, byAngle, hb);
    this.views.set(key, v);
    return v;
  }
}

/** Draw a frame with its anchor at (x, y), rounded to whole pixels. */
export function drawFrame(ctx: CanvasRenderingContext2D, f: Frame, x: number, y: number): void {
  ctx.drawImage(f.img, Math.round(x) - f.ax, Math.round(y) - f.ay);
}
