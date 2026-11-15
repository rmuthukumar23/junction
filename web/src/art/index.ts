// All sprite sheets, baked lazily into one bank (needs the DOM, so create it on first use).
import { SpriteBank } from "../engine/bank";
import type { SheetFile } from "../engine/sheet";
import fighters from "./fighters.json";
import scene from "./scene.json";

let bank: SpriteBank | null = null;

export function getBank(): SpriteBank {
  if (!bank) bank = new SpriteBank([fighters, scene] as unknown as SheetFile[]);
  return bank;
}
