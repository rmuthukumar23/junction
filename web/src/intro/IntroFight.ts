// The intro: two fighters with icon heads clash a shovel and a pitchfork in a glass greenhouse.
// 320x180 internal canvas; every sprite comes from web/src/art/*.json through the SpriteBank.
import { AnimSprite, makeAnim } from "../engine/anim";
import { drawFrame, type Frame, type SpriteBank, type SpriteView } from "../engine/bank";
import { PAL } from "../engine/palette";
import { Kind, Particles, Shake } from "../engine/particles";
import { Player, type Key } from "../engine/player";

export const W = 320, H = 180, GROUND = 164, FLOOR_Y = 136, FAR_H = 112;

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
const X_OFF = [0, 0, -8, 11, 11, -4];       // body shift toward the other fighter, px
const PROP_A = [-35, -35, -80, -12, -12, 25]; // weapon angle, degrees clockwise (before mirroring)
const HEAD_A = [0, 0, -4, 8, 8, -8];          // head tilt
const POSE = ["idle", "windup", "windup", "strike", "recoil", "idle"] as const;
const HITSTOP_MS = 110;

const LEFT_X = 94, RIGHT_X = 226;

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

interface Fighter {
  side: 1 | -1;
  x0: number;
  idle: AnimSprite;
  poses: Record<"windup" | "strike" | "recoil", SpriteView>;
  head: SpriteView;
  glyph: SpriteView;
  prop: SpriteView;
  /** Last drawn weapon tip, scene pixels (for the clash point). */
  tipX: number;
  tipY: number;
}

function rng(seed: number): () => number {
  let s = seed >>> 0;
  return () => { s = (s + 0x6d2b79f5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

export class IntroFight {
  private t = 0;
  private stop = 0;
  private flash = 0;
  private readonly cycle: Player<Key & { name: string }>;
  private readonly far: Frame; private readonly glass: Frame; private readonly floor: Frame; private readonly wall: Frame;
  private readonly bedFrame: Frame; private readonly pipeV: Frame; private readonly pipe: Frame;
  private readonly tomatoes: AnimSprite; private readonly leafy: AnimSprite;
  private readonly lamps: { a: AnimSprite; x: number; y: number }[];
  private readonly vines: { a: AnimSprite; x: number; y: number }[];
  private readonly spray: AnimSprite; private readonly alert: AnimSprite; private readonly stats: AnimSprite;
  private readonly fighters: Fighter[];
  private readonly sparkView: SpriteView;
  private spark: AnimSprite | null = null;
  private sparkX = 0; private sparkY = 0;
  private readonly dust = new Particles(160, [PAL.wood, PAL.woodDk, PAL.woodHi, PAL.sandDk, PAL.glow, PAL.lamp, PAL.gold, PAL.orangeHi]);
  private readonly shake = new Shake();
  private readonly rand = rng(2026);
  /** Fast-forward the scene by ms (used for ?at= screenshots). */
  seek(ms: number): void { for (let i = 0; i < ms / 16; i++) this.update(0.016); }
  /** Count of completed clashes (tests and the page can read it). */
  clashes = 0;

  constructor(private readonly bank: SpriteBank) {
    const f = (name: string) => bank.view(name).frame(0);
    this.far = f("far"); this.glass = f("glass"); this.floor = f("floor"); this.wall = f("wall");
    this.bedFrame = f("lettuce_bed"); this.pipeV = f("pipe_v"); this.pipe = f("pipe");
    this.tomatoes = makeAnim(bank, "tomato_sway"); this.leafy = makeAnim(bank, "leafy_sway", {}, 300);
    this.lamps = [{ a: makeAnim(bank, "lamp_flicker"), x: 84, y: 14 }, { a: makeAnim(bank, "lamp_flicker", {}, 1700), x: 236, y: 14 }];
    this.vines = [
      { a: makeAnim(bank, "vine_a_sway"), x: 40, y: 0 }, { a: makeAnim(bank, "vine_b_sway", {}, 400), x: 122, y: 0 }, { a: makeAnim(bank, "vine_c_sway", {}, 700), x: 188, y: 0 },
      { a: makeAnim(bank, "vine_a_sway", {}, 200), x: 286, y: 0 }, { a: makeAnim(bank, "vine_c_sway", {}, 900), x: 12, y: 0 },
    ];
    this.spray = makeAnim(bank, "spray_fall"); this.alert = makeAnim(bank, "alert_blink"); this.stats = makeAnim(bank, "stats_anim");
    this.sparkView = bank.view("spark");
    const mk = (side: 1 | -1, x0: number, variant: "green" | "orange", head: "dark" | "orange", glyph: string, prop: string): Fighter => {
      const flip = side === -1;
      return {
        side, x0, tipX: x0, tipY: 100,
        idle: makeAnim(bank, "fighter_idle", { variant, flip }, side === 1 ? 0 : 380),
        poses: { windup: bank.view("fighter_windup", { variant, flip }), strike: bank.view("fighter_strike", { variant, flip }), recoil: bank.view("fighter_recoil", { variant, flip }) },
        head: bank.view("head", { variant: head }), glyph: bank.view(glyph), prop: bank.view(prop, { flip }),
      };
    };
    this.fighters = [mk(1, LEFT_X, "green", "dark", "glyph_term", "shovel"), mk(-1, RIGHT_X, "orange", "orange", "glyph_star", "pitchfork")];
    this.cycle = new Player(KEYS, true, (ev) => { if (ev === "impact") this.impact(); });
  }

  /** Reset to the start of the cycle. */
  restart(): void { this.cycle.reset(); this.spark = null; this.t = 0; }

  private impact(): void {
    this.clashes++;
    const a = this.fighters[0], b = this.fighters[1];
    this.sparkX = Math.round((a.tipX + b.tipX) / 2); this.sparkY = Math.round((a.tipY + b.tipY) / 2);
    this.spark = new AnimSprite(this.sparkView, this.bank.anims.spark_burst);
    this.stop = HITSTOP_MS; this.flash = 90;
    this.shake.kick(3, 0.28);
    const R = this.rand;
    for (let i = 0; i < 26; i++) { // flying dirt
      const ang = -Math.PI * (0.15 + 0.7 * R()), sp = 50 + 110 * R();
      this.dust.spawn(this.sparkX, this.sparkY, Math.cos(ang) * sp * (R() < 0.5 ? -1 : 1), Math.sin(ang) * sp, 1.3 + R() * 0.6, (R() * 4) | 0, Kind.Dot, R() < 0.35 ? 2 : 1, 420, true);
    }
    for (let i = 0; i < 16; i++) { // spark streaks
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
    for (const a of [this.tomatoes, this.leafy, this.spray, this.alert, this.stats, ...this.lamps.map((l) => l.a), ...this.vines.map((v) => v.a)]) a.update(dt);
    for (const fgt of this.fighters) fgt.idle.update(dt);
    if (this.spark) { this.spark.update(real); if (this.spark.done) this.spark = null; }
    this.dust.update(dtSec, GROUND + 1);
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
    // slow camera drift gives the parallax: far moves most, glass half, set pieces not at all
    const drift = Math.sin(this.t / 2600) * 3;
    ctx.fillStyle = PAL.ink; ctx.fillRect(0, 0, W, H);
    drawFrame(ctx, this.far, Math.round(drift * 1.0) + sx, sy);
    drawFrame(ctx, this.glass, Math.round(drift * 0.5) + sx, sy);
    drawFrame(ctx, this.wall, sx, FAR_H + sy);
    for (const v of this.vines) drawFrame(ctx, v.a.frame(), v.x + sx, v.y + sy);
    // wall panels and the spray rig (set pieces)
    drawFrame(ctx, this.alert.frame(), 6 + sx, 38 + sy);
    drawFrame(ctx, this.stats.frame(), 268 + sx, 62 + sy);
    drawFrame(ctx, this.pipe, 236 + sx, 4 + sy);
    const noz = this.pipe.pts.nozzle;
    if (noz) drawFrame(ctx, this.spray.frame(), 236 + noz[0] + sx, 4 + noz[1] + sy);
    for (const l of this.lamps) {
      drawFrame(ctx, l.a.frame(), l.x + sx, l.y + sy);
      ctx.globalAlpha = 0.09; ctx.fillStyle = PAL.lamp; // soft warm cone under the lamp
      ctx.beginPath(); ctx.moveTo(l.x - 5 + sx, l.y + 24 + sy); ctx.lineTo(l.x + 5 + sx, l.y + 24 + sy); ctx.lineTo(l.x + 38 + sx, FLOOR_Y + sy); ctx.lineTo(l.x - 38 + sx, FLOOR_Y + sy); ctx.fill();
      ctx.globalAlpha = 1;
    }
    drawFrame(ctx, this.tomatoes.frame(), 22 + sx, FLOOR_Y + 13 + sy);
    drawFrame(ctx, this.leafy.frame(), 288 + sx, FLOOR_Y + 13 + sy);
    drawFrame(ctx, this.bedFrame, 160 + sx, FLOOR_Y + 13 + sy);
    drawFrame(ctx, this.pipeV, 232 + sx, FLOOR_Y + 13 + sy);
    drawFrame(ctx, this.floor, sx, FLOOR_Y + sy);
    for (const fg of this.fighters) this.drawFighter(ctx, fg, sx, sy);
    if (this.spark) drawFrame(ctx, this.spark.frame(), this.sparkX + sx, this.sparkY + sy);
    this.dust.draw(ctx, sx, sy);
    if (this.flash > 0) { ctx.globalAlpha = 0.28; ctx.fillStyle = PAL.glow; ctx.fillRect(0, 0, W, H); ctx.globalAlpha = 1; }
  }

  private drawFighter(ctx: CanvasRenderingContext2D, fg: Fighter, sx: number, sy: number): void {
    const x = Math.round(fg.x0 + fg.side * this.at(X_OFF)) + sx, y = GROUND + sy;
    const pose = POSE[this.cycle.index];
    const body = pose === "idle" ? fg.idle.frame() : fg.poses[pose].frame(0);
    // soft shadow: a short dithered strip on the floor
    ctx.fillStyle = PAL.dark;
    for (let r = 0; r < 3; r++) for (let c = -26 + r * 2; c < 26 - r * 2; c += 2) ctx.fillRect(x + c + ((r + 1) & 1), y - 1 + r, 1, 1);
    drawFrame(ctx, body, x, y);
    const neck = body.pts.neck, hand = body.pts.hand;
    const bob = pose === "idle" && fg.idle.player.key.frame === 1 ? -1 : 0;
    if (neck) {
      const hx = x + neck[0], hy = y + neck[1] + bob, tilt = this.at(HEAD_A) * fg.side;
      const hf = fg.head.frame(0, tilt);
      drawFrame(ctx, hf, hx, hy);
      const g = hf.pts.glyph;
      if (g) drawFrame(ctx, fg.glyph.frame(0), hx + g[0], hy + g[1]);
    }
    if (hand) {
      const px = x + hand[0], py = y + hand[1], pf = fg.prop.frame(0, this.at(PROP_A));
      drawFrame(ctx, pf, px, py);
      const tip = pf.pts.tip;
      if (tip) { fg.tipX = px + tip[0]; fg.tipY = py + tip[1]; }
    }
  }
}
