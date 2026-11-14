import { describe, expect, it } from "vitest";
import { COLORS, KEY_INDEX } from "./palette";
import { angleList, flipX, parseGrid, rotate, trim } from "./pixels";
import { Player, animKeys, ease } from "./player";
import { Particles, Shake } from "./particles";
import { validateSheet, type SheetFile } from "./sheet";
import { AnimSprite } from "./anim";
import { SpriteView } from "./bank";

const KEYS = new Set(COLORS.map((c) => c.key));
const rows = (img: { w: number; h: number; data: Uint8Array }) => {
  const inv = Object.fromEntries(Object.entries(KEY_INDEX).map(([k, v]) => [v, k]));
  const out: string[] = [];
  for (let y = 0; y < img.h; y++) { let r = ""; for (let x = 0; x < img.w; x++) r += inv[img.data[y * img.w + x]]; out.push(r); }
  return out;
};

describe("palette", () => {
  it("has 24-32 unique one-character keys and valid hex colours", () => {
    expect(COLORS.length).toBeGreaterThanOrEqual(24);
    expect(COLORS.length).toBeLessThanOrEqual(32);
    expect(KEYS.size).toBe(COLORS.length);
    expect(new Set(COLORS.map((c) => c.hex)).size).toBe(COLORS.length);
    for (const c of COLORS) { expect(c.key).toHaveLength(1); expect(c.key).not.toBe("."); expect(c.hex).toMatch(/^#[0-9a-f]{6}$/); }
  });
});

describe("pixels", () => {
  const L = ["k..", "k..", "kkk"];
  it("parses grids with palette swaps", () => {
    const img = parseGrid(["kg."], KEY_INDEX, { g: "o" });
    expect(rows(img)).toEqual(["ko."]);
    expect(() => parseGrid(["#"], KEY_INDEX)).toThrow();
  });
  it("mirrors pixels, anchor and points", () => {
    const img = flipX(parseGrid(L, KEY_INDEX, undefined, [0, 2], { tip: [2, 2] }));
    expect(rows(img)).toEqual(["..k", "..k", "kkk"]);
    expect([img.ax, img.ay]).toEqual([2, 2]);
    expect(img.pts.tip).toEqual([0, 2]);
  });
  it("rotates 90 degrees clockwise about the anchor, moving points with it", () => {
    const img = parseGrid(L, KEY_INDEX, undefined, [0, 2], { tip: [2, 2] });
    const r = rotate(img, 90);
    expect(rows(r)).toEqual(["kkk", "k..", "k.."]);
    expect(r.pts.tip).toEqual([r.ax, r.ay + 2]); // the tip, right of the corner, is now below it
    expect(rotate(img, 0).data).toEqual(img.data);
  });
  it("keeps a sprite's pixel count roughly constant under rotation", () => {
    const bar = parseGrid(["kkkkkkkkkkkk", "kkkkkkkkkkkk"], KEY_INDEX, undefined, [0, 0]);
    for (const a of [15, 30, 45, -60]) {
      const n = rotate(bar, a).data.reduce((s, v) => s + (v ? 1 : 0), 0);
      expect(n).toBeGreaterThan(24 * 0.7); expect(n).toBeLessThan(24 * 1.5);
    }
  });
  it("trims transparent borders", () => {
    const t = trim(parseGrid(["....", ".k..", "...."], KEY_INDEX, undefined, [1, 1]));
    expect([t.w, t.h, t.ax, t.ay]).toEqual([1, 1, 0, 0]);
  });
  it("lists rotation angles", () => { expect(angleList([-10, 10, 5])).toEqual([-10, -5, 0, 5, 10]); });
});

describe("player", () => {
  const keys = [{ ms: 100, event: "a" }, { ms: 50, event: "b" }, { ms: 100 }];
  it("fires the first key's event on the first update, then each key entered", () => {
    const seen: string[] = [], p = new Player(keys, true, (n) => seen.push(n));
    p.update(0); expect(seen).toEqual(["a"]);
    p.update(120); expect(p.index).toBe(1); expect(seen).toEqual(["a", "b"]);
    p.update(40); expect(p.index).toBe(2);
    p.update(100); expect(p.index).toBe(0); expect(seen).toEqual(["a", "b", "a"]);
  });
  it("stops on the last key of a one-shot", () => {
    const p = new Player(keys, false);
    p.update(1000);
    expect(p.done).toBe(true); expect(p.index).toBe(2); expect(p.e).toBe(1);
    p.update(100); expect(p.index).toBe(2);
  });
  it("survives a huge dt without looping forever", () => {
    const p = new Player(keys, true);
    p.update(1e9);
    expect(p.index).toBeGreaterThanOrEqual(0); expect(p.time).toBeLessThan(100);
  });
  it("honours speed and easing", () => {
    const p = new Player([{ ms: 100, ease: "inout" as const }, { ms: 100 }], true);
    p.speed = 2; p.update(25);
    expect(p.t).toBeCloseTo(0.5); expect(p.e).toBeCloseTo(0.5);
    expect(ease("hold", 0.7)).toBe(0); expect(ease("in", 0.5)).toBe(0.25);
  });
  it("rejects empty or zero-length keys", () => {
    expect(() => new Player([])).toThrow();
    expect(() => new Player([{ ms: 0 }])).toThrow();
  });
  it("builds keys from sheet animations", () => {
    expect(animKeys([[0, 100], [1, 60, "blink"]])).toEqual([{ frame: 0, ms: 100, ease: "hold" }, { frame: 1, ms: 60, ease: "hold", event: "blink" }]);
  });
});

describe("particles", () => {
  it("never exceeds the pool and dies out", () => {
    const p = new Particles(8, ["#fff"]);
    for (let i = 0; i < 20; i++) p.spawn(0, 0, 10, -50, 0.5, 0, 0, 1, 200, true);
    expect(p.alive()).toBe(8);
    for (let i = 0; i < 60; i++) p.update(1 / 60, 10);
    expect(p.alive()).toBe(0);
  });
  it("lands bouncing particles on the floor", () => {
    const p = new Particles(1, ["#fff"]);
    p.spawn(0, 0, 0, 0, 5, 0, 0, 1, 400, true);
    for (let i = 0; i < 120; i++) p.update(1 / 60, 20);
    expect(p.y[0]).toBe(20);
  });
  it("shakes and settles", () => {
    const s = new Shake(); s.kick(3, 0.2);
    let moved = false;
    for (let i = 0; i < 30; i++) { s.update(1 / 60); if (s.ox || s.oy) moved = true; expect(Math.abs(s.ox)).toBeLessThanOrEqual(3); }
    expect(moved).toBe(true); expect([s.ox, s.oy]).toEqual([0, 0]);
  });
});

describe("sheet validation", () => {
  const good: SheetFile = { format: "pixel-sprites/1", sprites: { a: { frames: [["k.", ".k"]], anchor: [1, 1], points: { p: [0, 0] } } }, anims: { a1: { sprite: "a", frames: [[0, 100]] } } };
  it("accepts a valid sheet", () => { expect(validateSheet(good, KEYS)).toEqual([]); });
  it("reports ragged rows, unknown keys, bad anchors and bad anims", () => {
    const bad: SheetFile = { format: "pixel-sprites/1", sprites: { a: { frames: [["k.", "#"]], anchor: [5, 0], variants: { v: { k: "?" } } } }, anims: { x: { sprite: "a", frames: [[3, 0]] }, y: { sprite: "nope", frames: [[0, 1]] } } };
    const errs = validateSheet(bad, KEYS).join("\n");
    for (const s of ["width 1", "'#'", "anchor", "variant v", "frame 3", "duration", "unknown sprite"]) expect(errs).toContain(s);
  });
});

describe("AnimSprite", () => {
  const frames = [0, 1, 2].map((i) => ({ img: null as unknown as HTMLCanvasElement, w: 1, h: 1, ax: 0, ay: 0, pts: {}, i }));
  const view = new SpriteView("t", frames, [], [], null);
  it("walks the animation's frames and fires events", () => {
    const seen: string[] = [];
    const a = new AnimSprite(view, { sprite: "t", loop: true, frames: [[0, 100], [2, 100, "tick"]] }, 0, (n) => seen.push(n));
    expect((a.frame() as unknown as { i: number }).i).toBe(0);
    a.update(0); a.update(150);
    expect((a.frame() as unknown as { i: number }).i).toBe(2); expect(seen).toEqual(["tick"]);
    a.update(100); expect((a.frame() as unknown as { i: number }).i).toBe(0);
  });
  it("offsets the phase and finishes one-shots", () => {
    const a = new AnimSprite(view, { sprite: "t", loop: false, frames: [[0, 100], [1, 100]] }, 120);
    expect((a.frame() as unknown as { i: number }).i).toBe(1);
    a.update(500); expect(a.done).toBe(true);
  });
});
