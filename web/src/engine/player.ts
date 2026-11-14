// A tiny keyframe player. Frame animations ([frame, ms, event?]) and choreography timelines both run on it.
// No allocation in update(): events go to a callback set once.

export type Ease = "linear" | "in" | "out" | "inout" | "hold";

export interface Key {
  /** How long this key lasts, in ms (> 0). */
  ms: number;
  /** Fired when the player enters this key. */
  event?: string;
  /** How to move from this key to the next one (default linear). "hold" stays on this key. */
  ease?: Ease;
}

export function ease(kind: Ease | undefined, t: number): number {
  switch (kind) {
    case "hold": return 0;
    case "in": return t * t;
    case "out": return 1 - (1 - t) * (1 - t);
    case "inout": return t < 0.5 ? 2 * t * t : 1 - 2 * (1 - t) * (1 - t);
    default: return t;
  }
}

export class Player<K extends Key = Key> {
  index = 0;
  /** ms spent in the current key. */
  time = 0;
  done = false;
  speed = 1;
  private entered = false;

  constructor(
    readonly keys: readonly K[],
    readonly loop = true,
    public onEvent: ((name: string, key: K, player: Player<K>) => void) | null = null,
  ) {
    if (!keys.length) throw new Error("player needs at least one key");
    for (const k of keys) if (!(k.ms > 0)) throw new Error("key durations must be > 0");
  }

  reset(): void { this.index = 0; this.time = 0; this.done = false; this.entered = false; }

  /** Advance by dtMs (scaled by speed). Fires events of every key entered, in order. */
  update(dtMs: number): void {
    if (!this.entered) { this.entered = true; this.fire(); }
    if (this.done) return;
    this.time += dtMs * this.speed;
    // Bounded: a long dt (tab switch) skips at most one full pass of keys.
    for (let guard = this.keys.length + 1; guard > 0 && this.time >= this.keys[this.index].ms; guard--) {
      this.time -= this.keys[this.index].ms;
      if (this.index + 1 < this.keys.length) this.index++;
      else if (this.loop) this.index = 0;
      else { this.time = this.keys[this.index].ms; this.done = true; return; }
      this.fire();
    }
    if (this.time >= this.keys[this.index].ms) this.time = 0;
  }

  get key(): K { return this.keys[this.index]; }
  /** The key after the current one (the first again when looping; the last for a finished one-shot). */
  get next(): K { const i = this.index + 1; return this.keys[i < this.keys.length ? i : this.loop ? 0 : this.index]; }
  /** Raw progress 0..1 through the current key. */
  get t(): number { return Math.min(1, this.time / this.key.ms); }
  /** Eased progress, using the current key's ease. */
  get e(): number { return this.done ? 1 : ease(this.key.ease, this.t); }

  private fire(): void { const k = this.key; if (k.event && this.onEvent) this.onEvent(k.event, k, this); }
}

/** Keys from a sheet animation's [frame, ms, event?] list. */
export function animKeys(frames: readonly (readonly [number, number, string?])[]): (Key & { frame: number })[] {
  return frames.map(([frame, ms, event]) => ({ frame, ms, ease: "hold" as const, ...(event ? { event } : {}) }));
}
