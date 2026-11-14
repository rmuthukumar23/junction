// Fixed-size particle pool in typed arrays: no allocation after construction.
// Colours are palette hex strings chosen per particle by index into `colors`.

export const Kind = { Dot: 0, Streak: 1, Chunk: 2 } as const;
export type Kind = (typeof Kind)[keyof typeof Kind];

export class Particles {
  readonly n: number;
  x: Float32Array; y: Float32Array; vx: Float32Array; vy: Float32Array;
  life: Float32Array; max: Float32Array; grav: Float32Array;
  kind: Uint8Array; col: Uint8Array; size: Uint8Array; bounce: Uint8Array;
  private cursor = 0;

  constructor(n: number, readonly colors: readonly string[]) {
    this.n = n;
    this.x = new Float32Array(n); this.y = new Float32Array(n); this.vx = new Float32Array(n); this.vy = new Float32Array(n);
    this.life = new Float32Array(n); this.max = new Float32Array(n); this.grav = new Float32Array(n);
    this.kind = new Uint8Array(n); this.col = new Uint8Array(n); this.size = new Uint8Array(n); this.bounce = new Uint8Array(n);
  }

  /** Add one particle (reuses the oldest slot when full). Velocities in px/s, gravity in px/s², life in s. */
  spawn(x: number, y: number, vx: number, vy: number, life: number, col: number, kind: Kind = Kind.Dot, size = 1, grav = 0, bounce = false): void {
    let i = this.cursor;
    for (let k = 0; k < this.n; k++) { const j = (this.cursor + k) % this.n; if (this.life[j] <= 0) { i = j; break; } }
    this.cursor = (i + 1) % this.n;
    this.x[i] = x; this.y[i] = y; this.vx[i] = vx; this.vy[i] = vy; this.life[i] = life; this.max[i] = life;
    this.col[i] = col; this.kind[i] = kind; this.size[i] = size; this.grav[i] = grav; this.bounce[i] = bounce ? 1 : 0;
  }

  /** Step all live particles by dt seconds. Particles with `bounce` land on floorY and skid to rest. */
  update(dt: number, floorY: number): void {
    for (let i = 0; i < this.n; i++) {
      if (this.life[i] <= 0) continue;
      this.life[i] -= dt;
      this.vy[i] += this.grav[i] * dt;
      this.x[i] += this.vx[i] * dt; this.y[i] += this.vy[i] * dt;
      if (this.bounce[i] && this.y[i] >= floorY) {
        this.y[i] = floorY;
        this.vy[i] = this.vy[i] > 30 ? -this.vy[i] * 0.3 : 0;
        this.vx[i] *= 0.6;
      }
    }
  }

  alive(): number { let c = 0; for (let i = 0; i < this.n; i++) if (this.life[i] > 0) c++; return c; }

  /** Draw at integer pixels, offset by (ox, oy). Streaks draw a short line back along their velocity. */
  draw(ctx: CanvasRenderingContext2D, ox = 0, oy = 0): void {
    for (let i = 0; i < this.n; i++) {
      if (this.life[i] <= 0) continue;
      ctx.fillStyle = this.colors[this.col[i]];
      const x = Math.round(this.x[i] + ox), y = Math.round(this.y[i] + oy), s = this.size[i];
      if (this.kind[i] === Kind.Streak) {
        const sp = Math.hypot(this.vx[i], this.vy[i]) || 1, len = Math.min(5, 1 + sp * 0.02 * (this.life[i] / this.max[i]));
        const dx = -this.vx[i] / sp, dy = -this.vy[i] / sp;
        for (let k = 0; k < len; k++) ctx.fillRect(Math.round(x + dx * k), Math.round(y + dy * k), 1, 1);
      } else {
        ctx.fillRect(x, y, s, s);
      }
    }
  }
}

/** Screen shake: call kick(amplitude, seconds); read offset each frame. Deterministic, no allocation. */
export class Shake {
  amp = 0; t = 0; dur = 0; ox = 0; oy = 0; private seed = 7;
  kick(amp: number, dur: number): void { this.amp = Math.max(this.amp * (1 - this.t / (this.dur || 1)), amp); this.dur = dur; this.t = 0; }
  update(dt: number): void {
    if (this.t >= this.dur) { this.ox = this.oy = 0; return; }
    this.t += dt;
    const a = this.amp * Math.max(0, 1 - this.t / this.dur);
    this.seed = (this.seed * 1103515245 + 12345) & 0x7fffffff; this.ox = Math.round(((this.seed % 1000) / 500 - 1) * a);
    this.seed = (this.seed * 1103515245 + 12345) & 0x7fffffff; this.oy = Math.round(((this.seed % 1000) / 500 - 1) * a);
  }
}
