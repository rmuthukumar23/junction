// An animated sprite: a baked SpriteView driven by a sheet animation ([frame, ms, event?] keys).
import type { Frame, SpriteBank, SpriteView, ViewOptions } from "./bank";
import { Player, animKeys, type Key } from "./player";
import type { AnimDef } from "./sheet";

type AnimKey = Key & { frame: number };

export class AnimSprite {
  readonly player: Player<AnimKey>;

  /** `phaseMs` starts the animation part-way in, so repeated sprites (lamps, vines) do not move in lockstep. */
  constructor(readonly view: SpriteView, def: AnimDef, phaseMs = 0, onEvent: ((name: string) => void) | null = null) {
    this.player = new Player(animKeys(def.frames), def.loop !== false, onEvent ? (n) => onEvent(n) : null);
    if (phaseMs > 0) this.player.update(phaseMs);
  }

  update(dtMs: number): void { this.player.update(dtMs); }
  get done(): boolean { return this.player.done; }
  restart(): void { this.player.reset(); }
  /** Current frame, at the baked angle nearest `deg`. */
  frame(deg = 0): Frame { return this.view.frame(this.player.key.frame, deg); }
}

/** Build an AnimSprite from a named animation of the bank. Call at setup time. */
export function makeAnim(bank: SpriteBank, name: string, opt: ViewOptions = {}, phaseMs = 0, onEvent: ((name: string) => void) | null = null): AnimSprite {
  const def = bank.anims[name];
  if (!def) throw new Error(`unknown animation ${name}`);
  return new AnimSprite(bank.view(def.sprite, opt), def, phaseMs, onEvent);
}
