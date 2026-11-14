// Sprite sheet file format ("pixel-sprites/1"), as stored in web/src/art/*.json.
//
// {
//   "format": "pixel-sprites/1",
//   "sprites": {
//     "<name>": {
//       "frames": [["..kk..", ".kGGk.", ...], ...],   // palette-key grids, "." transparent; all frames one size
//       "anchor": [x, y],                              // pivot pixel: drawing at (X, Y) puts this pixel there (default 0,0)
//       "points": {"tip": [x, y]},                     // named attachment points, in frame pixels
//       "hitbox": [x, y, w, h],                        // optional, in frame pixels
//       "variants": {"rust": {"g": "o", "G": "O"}},     // palette swaps: key -> key
//       "rotate": [from, to, step]                     // optional: bake rotations (degrees) at load
//     }
//   },
//   "anims": {
//     "<name>": {"sprite": "<name>", "loop": true, "frames": [[frame, ms], [frame, ms, "event"]]}
//   }
// }

export type Vec = [number, number];

export interface SpriteDef {
  frames: string[][];
  anchor?: Vec;
  points?: Record<string, Vec>;
  hitbox?: [number, number, number, number];
  variants?: Record<string, Record<string, string>>;
  rotate?: [number, number, number];
  note?: string;
}

export type AnimFrame = [frame: number, ms: number, event?: string];

export interface AnimDef {
  sprite: string;
  loop?: boolean;
  frames: AnimFrame[];
}

export interface SheetFile {
  format: "pixel-sprites/1";
  about?: string;
  sprites: Record<string, SpriteDef>;
  anims?: Record<string, AnimDef>;
}

/** Problems with a sheet ([] when valid). `keys`: the palette keys allowed in grids besides ".". */
export function validateSheet(sheet: SheetFile, keys: ReadonlySet<string>, file = "sheet"): string[] {
  const err: string[] = [];
  if (sheet.format !== "pixel-sprites/1") err.push(`${file}: format must be "pixel-sprites/1"`);
  for (const [name, s] of Object.entries(sheet.sprites || {})) {
    const at = `${file}:${name}`;
    if (!Array.isArray(s.frames) || !s.frames.length) { err.push(`${at}: no frames`); continue; }
    const h = s.frames[0].length, w = h ? s.frames[0][0].length : 0;
    if (!w || !h) err.push(`${at}: empty frame`);
    s.frames.forEach((rows, fi) => {
      if (rows.length !== h) err.push(`${at}[${fi}]: ${rows.length} rows, expected ${h}`);
      rows.forEach((row, y) => {
        if (row.length !== w) err.push(`${at}[${fi}] row ${y}: width ${row.length}, expected ${w}`);
        for (const ch of row) if (ch !== "." && !keys.has(ch)) { err.push(`${at}[${fi}] row ${y}: '${ch}' is not a palette key`); break; }
      });
    });
    const inside = (p: Vec | undefined) => !p || (p[0] >= 0 && p[1] >= 0 && p[0] < w && p[1] < h);
    if (!inside(s.anchor)) err.push(`${at}: anchor outside the frame`);
    for (const [pn, p] of Object.entries(s.points || {})) if (!inside(p)) err.push(`${at}: point ${pn} outside the frame`);
    if (s.hitbox) { const [x, y, bw, bh] = s.hitbox; if (x < 0 || y < 0 || bw <= 0 || bh <= 0 || x + bw > w || y + bh > h) err.push(`${at}: hitbox outside the frame`); }
    for (const [vn, map] of Object.entries(s.variants || {}))
      for (const [a, b] of Object.entries(map)) if (!keys.has(a) || !keys.has(b)) err.push(`${at}: variant ${vn} maps ${a}->${b}, not palette keys`);
    if (s.rotate) { const [a, b, st] = s.rotate; if (!(st > 0) || b < a) err.push(`${at}: rotate needs from <= to and step > 0`); }
  }
  for (const [name, a] of Object.entries(sheet.anims || {})) {
    const at = `${file}:anim ${name}`, s = sheet.sprites?.[a.sprite];
    if (!s) { err.push(`${at}: unknown sprite ${a.sprite}`); continue; }
    if (!a.frames?.length) err.push(`${at}: no frames`);
    for (const [f, ms] of a.frames || []) {
      if (!(f >= 0 && f < s.frames.length)) err.push(`${at}: frame ${f} out of range`);
      if (!(ms > 0)) err.push(`${at}: duration must be > 0`);
    }
  }
  return err;
}
