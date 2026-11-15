// The intro: two fighters with icon heads clash a shovel and a pitchfork in a glass greenhouse.
// 320x180 internal canvas. The art is cut from web/public/hero.png (palette-quantised) and lives in
// web/src/art/{fighters,scene}.json; every sprite comes from there through the SpriteBank.
import { AnimSprite, makeAnim } from "../engine/anim";
import { drawFrame, type Frame, type SpriteBank, type SpriteView } from "../engine/bank";
import { PAL } from "../engine/palette";
import { Kind, Particles, Shake } from "../engine/particles";
import { Player, type Key } from "../engine/player";

export const W = 320, H = 180, GROUND = 168;

// ---- choreography: one clash cycle ------------------------------------------------------------
// Values are those at the START of each key; each key interpolates to the next key's value.
const KEYS: (Key & { name: string })[] = [
  { name: "idle", ms: 900, ease: "linear" },
  { name: "windup", ms: 380, ease: "inout" },
  { name: "strike", ms: 110, ease: "in", event: "strike" },
  { name: "impact", ms: 160, ease: "hold", event: "impact" },
  { name: "recoil", ms: 450, ease: "out" },
  { name: "reset", ms: 500, ease: "inout" },
];
const X_OFF = [-3, -3, -9, 0, 0, -6];   // body shift toward the other fighter, px (0 = the reference pose)
const PROP_A = [16, 16, 48, 0, 0, 30];  // weapon pulled back by this many degrees (strike pose = 0)
const HEAD_A = [0, 0, -4, 6, 6, -6];    // head tilt
const POSE = ["idle", "windup", "windup", "strike", "recoil", "idle"] as const;
const HITSTOP_MS = 110;

const LEFT_X = 80, RIGHT_X = 250;
/** Where the weapons meet at the impact pose (the centre of the spark in the reference). */
const SPARK_X = 160, SPARK_Y = 70;

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

type Pose = "windup" | "strike" | "recoil";
interface Fighter {
  side: 1 | -1;
  x0: number;
  idle: AnimSprite;
  poses: Record<Pose, SpriteView>;
  head: SpriteView;
  glyph: SpriteView;
  prop: SpriteView;
  hand: SpriteView;
  /** Last drawn weapon tip, scene pixels (for the clash point). */
  tipX: number;
  tipY: number;
}

interface Placed { a: AnimSprite; x: number; y: number }

function rng(seed: number): () => number {
  let s = seed >>> 0;
  return () => { s = (s + 0x6d2b79f5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

export class IntroFight {
  private t = 0;
  private stop = 0;
  private flash = 0;
  private readonly cycle: Player<Key & { name: string }>;
  private readonly plate: Frame;
  private readonly sway: Placed[];
  private readonly lamps: Placed[];
  private readonly alert: Placed; private readonly stats: Placed; private readonly spray: Placed;
  private readonly fighters: Fighter[];
  private readonly sparkView: SpriteView;
  private spark: AnimSprite | null = null;
  private sparkX = 0; private sparkY = 0;
  private readonly dust = new Particles(160, [PAL.woodDk, PAL.rust, PAL.clay, PAL.brick, PAL.white, PAL.skinHi, PAL.orangeHi, PAL.skin]);
  private readonly shake = new Shake();
  private readonly rand = rng(2026);
  /** Fast-forward the scene by ms (used for ?introAt= screenshots). */
  seek(ms: number): void { for (let i = 0; i < ms / 16; i++) this.update(0.016); }
  /** Count of completed clashes (tests and the page can read it). */
  clashes = 0;

  constructor(private readonly bank: SpriteBank) {
    this.plate = bank.view("bg").frame(0);
    const at = (anim: string, x: number, y: number, phase = 0): Placed => ({ a: makeAnim(bank, anim, {}, phase), x, y });
    this.sway = [
      at("sway_tl", 0, 0), at("sway_tomato", 0, 56, 150), at("sway_top", 96, 0, 300),
      at("sway_tr", 236, 0, 90), at("sway_leafy", 272, 78, 220), at("sway_lettuce", 45, 100, 60),
    ];
    this.lamps = [at("lamp_glow_l", 74, 29), at("lamp_glow_r", 247, 29, 500)];
    this.alert = at("alert_icons", 19, 36);
    this.stats = at("stats_anim", 282, 63);
    this.spray = at("spray_fall", 305, 23);
    this.sparkView = bank.view("spark");
    const mk = (side: 1 | -1, x0: number, k: "l" | "r", glyph: string, prop: string): Fighter => ({
      side, x0, tipX: x0, tipY: 100,
      idle: makeAnim(bank, `fighter_${k}_idle`, {}, side === 1 ? 0 : 380),
      poses: { windup: bank.view(`fighter_${k}_windup`), strike: bank.view(`fighter_${k}_strike`), recoil: bank.view(`fighter_${k}_recoil`) },
      head: bank.view(`head_${k}`), glyph: bank.view(glyph), prop: bank.view(prop), hand: bank.view(`glove_${k}`),
    });
    this.fighters = [mk(1, LEFT_X, "l", "glyph_term", "shovel"), mk(-1, RIGHT_X, "r", "glyph_star", "pitchfork")];
    this.cycle = new Player(KEYS, true, (ev) => { if (ev === "impact") this.impact(); });
  }

  /** Reset to the start of the cycle. */
  restart(): void { this.cycle.reset(); this.spark = null; this.t = 0; }

  private impact(): void {
    this.clashes++;
    this.sparkX = SPARK_X; this.sparkY = SPARK_Y;
    this.spark = new AnimSprite(this.sparkView, this.bank.anims.spark_burst);
    this.stop = HITSTOP_MS; this.flash = 90;
    this.shake.kick(3, 0.28);
    const R = this.rand;
    for (let i = 0; i < 28; i++) { // flying dirt
      const ang = -Math.PI * (0.1 + 0.8 * R()), sp = 50 + 120 * R();
      this.dust.spawn(this.sparkX, this.sparkY, Math.cos(ang) * sp * (R() < 0.5 ? -1 : 1), Math.sin(ang) * sp, 1.3 + R() * 0.6, (R() * 4) | 0, Kind.Dot, R() < 0.35 ? 2 : 1, 420, true);
    }
    for (let i = 0; i < 18; i++) { // spark streaks
      const ang = R() * Math.PI * 2, sp = 90 + 130 * R();
      this.dust.spawn(this.sparkX, this.sparkY, Math.cos(ang) * sp, Math.sin(ang) * sp, 0.18 + R() * 0.16, 4 + ((R() * 4) | 0), Kind.Streak, 1, 80, false);
    }
  }

  update(dtSec: number): void {
    const real = dtSec * 1000;
    let dt = real;
    if (this.stop > 0) { this.stop -= real; dt = 0; }
    this.t += dt;
    this.cycle.update(dt);
    for (const p of [...this.sway, ...this.lamps, this.alert, this.stats, this.spray]) p.a.update(real);
    for (const fgt of this.fighters) fgt.idle.update(dt);
    if (this.spark) { this.spark.update(real); if (this.spark.done) this.spark = null; }
    this.dust.update(dtSec, GROUND - 2);
    this.shake.update(dtSec);
    if (this.flash > 0) this.flash -= real;
  }

  /** Value of a per-key table at the cycle's current moment. */
  private at(table: readonly number[]): number {
    const i = this.cycle.index;
    return lerp(table[i], table[(i + 1) % table.length], this.cycle.e);
  }

  draw(ctx: CanvasRenderingContext2D): void {
    ctx.imageSmoothingEnabled = false;
    const sx = this.shake.ox, sy = this.shake.oy;
    ctx.fillStyle = PAL.ink; ctx.fillRect(0, 0, W, H);
    drawFrame(ctx, this.plate, sx, sy);
    for (const p of this.sway) drawFrame(ctx, p.a.frame(), p.x + sx, p.y + sy);
    for (const p of [this.alert, this.stats, ...this.lamps]) drawFrame(ctx, p.a.frame(), p.x + sx, p.y + sy);
    for (const l of this.lamps) { // soft warm cone under each lamp, stepped so it stays pixel-clean
      ctx.fillStyle = PAL.skinHi;
      for (let k = 0; k < 3; k++) {
        ctx.globalAlpha = 0.045;
        const top = l.y + 8, hgt = 70 - k * 14, spread = 8 + 14 * (k + 1);
        ctx.beginPath(); ctx.moveTo(l.x + 3 + sx, top + sy); ctx.lineTo(l.x + 18 + sx, top + sy); ctx.lineTo(l.x + 10 + spread + sx, top + hgt + sy); ctx.lineTo(l.x + 11 - spread + sx, top + hgt + sy); ctx.fill();
      }
      ctx.globalAlpha = 1;
    }
    drawFrame(ctx, this.spray.a.frame(), this.spray.x + sx, this.spray.y + sy);
    for (const fg of this.fighters) this.drawFighter(ctx, fg, sx, sy);
    if (this.spark) drawFrame(ctx, this.spark.frame(), this.sparkX + sx, this.sparkY + sy);
    this.dust.draw(ctx, sx, sy);
    if (this.flash > 0) { ctx.globalAlpha = 0.24; ctx.fillStyle = PAL.white; ctx.fillRect(0, 0, W, H); ctx.globalAlpha = 1; }
  }

  private drawFighter(ctx: CanvasRenderingContext2D, fg: Fighter, sx: number, sy: number): void {
    const x = Math.round(fg.x0 + fg.side * this.at(X_OFF)) + sx, y = GROUND + sy;
    const pose = POSE[this.cycle.index];
    const body = pose === "idle" ? fg.idle.frame() : fg.poses[pose].frame(0);
    // soft shadow: short dark strips on the floor
    ctx.fillStyle = PAL.woodDk; ctx.globalAlpha = 0.45;
    ctx.fillRect(x - 34, y - 3, 68, 1); ctx.fillRect(x - 28, y - 2, 56, 1); ctx.fillRect(x - 20, y - 1, 40, 1);
    ctx.globalAlpha = 1;
    drawFrame(ctx, body, x, y);
    const neck = body.pts.neck, hand = body.pts.hand;
    const bob = pose === "idle" && fg.idle.player.key.frame === 1 ? 1 : 0;
    if (hand) {
      const px = x + hand[0], py = y + hand[1] + bob, pf = fg.prop.frame(0, -fg.side * this.at(PROP_A));
      drawFrame(ctx, pf, px, py);
      drawFrame(ctx, fg.hand.frame(0), px, py);
      const tip = pf.pts.tip;
      if (tip) { fg.tipX = px + tip[0]; fg.tipY = py + tip[1]; }
    }
    if (neck) {
      const hx = x + neck[0], hy = y + neck[1] + bob, tilt = this.at(HEAD_A) * fg.side;
      const hf = fg.head.frame(0, tilt);
      drawFrame(ctx, hf, hx, hy);
      const g = hf.pts.glyph;
      if (g) drawFrame(ctx, fg.glyph.frame(0), hx + g[0], hy + g[1]);
    }
  }
}
