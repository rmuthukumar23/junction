// Palette, bitmap font, mascots and crop sprites for the Greenhouse Bench pixel site.
// Everything is procedural: no images, no fonts. All draw calls are allocation free.
(function () {
  "use strict";

  const P = {
    ink: "#0b1018", plate: "#10151f", plateEdge: "#2c3a52", white: "#f2f6fb", snow: "#e6eef7",
    brick: "#4b505f", brick2: "#3f4452", brickHi: "#5a6073", roof: "#2b2f3a", roofHi: "#3c4252",
    chimney: "#6a4a3a", chimneyHi: "#85604c", grass: "#3f7f2c", grass2: "#58a23a", soil: "#5a3b25", soil2: "#4a2f1d", soil3: "#6d4a2e",
    road: "#2b303a", road2: "#3a404c", paint: "#aeb6c4",
    wood: "#8a5a32", woodHi: "#a9743f", woodDk: "#5e3c20",
    glass: "#cfeaff", glassDim: "#8fb9d8", frame: "#dce9f5",
    heat: "#ff6a4d", heatDim: "#6b2a24", co2: "#5ff2d8", co2Dim: "#1d5a55", gas: "#e8b830",
    good: "#6fe36f", bad: "#ff4d57", warn: "#ffc247", info: "#74c0ff", grid: "#ffd84a", export: "#6fe36f",
    steel: "#8d98ab", steelDk: "#566074", steelHi: "#c3ccda",
    skin: "#f0c090", cloth: "#2d6cd6", clothDk: "#1f4aa0", hat: "#e0b040",
  };

  // ---------------------------------------------------------------- 3x5 bitmap font
  // Each glyph is five digits, one per row; each digit is three bits (4 = left pixel, 1 = right pixel).
  const FONT_SRC = {
    A: "25755", B: "65656", C: "34443", D: "65556", E: "74647", F: "74644", G: "34553", H: "55755", I: "72227",
    J: "11152", K: "55655", L: "44447", M: "77555", N: "65555", O: "25552", P: "65644", Q: "25573", R: "65655",
    S: "34216", T: "72222", U: "55557", V: "55552", W: "55577", X: "55255", Y: "55222", Z: "71247",
    0: "75557", 1: "26227", 2: "71747", 3: "71717", 4: "55711", 5: "74717", 6: "74757", 7: "71122", 8: "75757", 9: "75717",
    ".": "00002", ":": "02020", "-": "00700", "+": "02720", "%": "51245", "/": "11244", ",": "00024", "'": "22000",
    "!": "22202", "?": "61202", "(": "24442", ")": "21112", "°": "25200", "€": "34643", "·": "00200", ">": "42124",
    "<": "12421", "_": "00007", "=": "07070", "#": "57575", "^": "25000", " ": "00000", "*": "52725", "x": "05250",
  };
  const FONT = {};
  for (const k in FONT_SRC) { const s = FONT_SRC[k], rows = []; for (let i = 0; i < 5; i++) rows.push(+s[i]); FONT[k] = rows; }
  const UNKNOWN = FONT["?"];

  function textWidth(s, sc) { return (s.length * 4 - 1) * (sc || 1); }
  function text(ctx, s, x, y, col, sc) {
    sc = sc || 1; ctx.fillStyle = col; x = Math.round(x); y = Math.round(y);
    for (let i = 0; i < s.length; i++) {
      let ch = s[i]; const g = FONT[ch] || FONT[ch.toUpperCase()] || UNKNOWN, ox = x + i * 4 * sc;
      for (let r = 0; r < 5; r++) {
        const bits = g[r]; if (!bits) continue;
        if (bits & 4) ctx.fillRect(ox, y + r * sc, sc, sc);
        if (bits & 2) ctx.fillRect(ox + sc, y + r * sc, sc, sc);
        if (bits & 1) ctx.fillRect(ox + 2 * sc, y + r * sc, sc, sc);
      }
    }
  }
  // Dark label plate with text; (x, y) is the top-left corner. Returns plate width.
  function plate(ctx, s, x, y, col, bg) {
    const w = textWidth(s) + 5;
    ctx.fillStyle = P.plateEdge; ctx.fillRect(x, y, w, 9);
    ctx.fillStyle = bg || P.plate; ctx.fillRect(x + 1, y + 1, w - 2, 7);
    text(ctx, s, x + 3, y + 2, col || P.white);
    return w;
  }

  function rect(ctx, col, x, y, w, h) { ctx.fillStyle = col; ctx.fillRect(x, y, w, h); }
  // Pixel line (Bresenham), no allocation.
  function line(ctx, x0, y0, x1, y1, col) {
    x0 = Math.round(x0); y0 = Math.round(y0); x1 = Math.round(x1); y1 = Math.round(y1);
    const dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    let err = dx + dy; ctx.fillStyle = col;
    for (let n = 0; n < 600; n++) {
      ctx.fillRect(x0, y0, 1, 1); if (x0 === x1 && y0 === y1) break;
      const e2 = 2 * err; if (e2 >= dy) { err += dy; x0 += sx; } if (e2 <= dx) { err += dx; y0 += sy; }
    }
  }
  function hash(n) { n = (n ^ 61) ^ (n >>> 16); n = (n + (n << 3)) | 0; n ^= n >>> 4; n = Math.imul(n, 0x27d4eb2d); n ^= n >>> 15; return (n >>> 0) / 4294967296; }
  function hashStr(s) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }

  // ---------------------------------------------------------------- mascots (icon heads)
  // Generic glyphs only (no brand logos). Each is a 5x5 bitmap.
  const GLYPHS = {
    term: ["#....", ".#...", "..#..", ".#...", "#.###"],
    star: ["#.#.#", ".###.", "#####", ".###.", "#.#.#"],
    ring: [".###.", "#...#", "#...#", "#...#", ".###."],
    diamond: ["..#..", ".###.", "#####", ".###.", "..#.."],
    bolt: ["...##", "..##.", ".###.", "..##.", "##..."],
    leaf: ["..###", ".####", "####.", "###..", "#...."],
    cross: ["..#..", "..#..", "#####", "..#..", "..#.."],
    x: ["#...#", ".#.#.", "..#..", ".#.#.", "#...#"],
    tri: ["..#..", ".###.", ".###.", "#####", "....."],
    dots: ["#.#.#", ".....", "#.#.#", ".....", "#.#.#"],
    wave: [".....", "#.#..", ".#.#.", "..#.#", "....."],
    gear: [".#.#.", "#####", ".#.#.", "#####", ".#.#."],
    zzz: ["###..", "..#..", ".#.##", "#..#.", "..###"],
  };
  const GLYPH_NAMES = Object.keys(GLYPHS);
  const HEAD_COLORS = ["#d8572a", "#2f6fd8", "#2f9e5c", "#8a4fd0", "#d8a21d", "#c7377a", "#1fa3a8", "#6a7388"];
  const GLYPH_BITS = {};
  for (const n of GLYPH_NAMES) { const b = []; for (let y = 0; y < 5; y++) for (let x = 0; x < 5; x++) b.push(GLYPHS[n][y][x] === "#" ? 1 : 0); GLYPH_BITS[n] = b; }

  // Stable mascot description for a run (or any string id).
  function mascotFor(meta) {
    const key = String((meta && (meta.model || meta.policy || meta.label || meta.id)) || "agent");
    const kind = meta && meta.kind;
    const h = hashStr(key.toLowerCase());
    let glyph = GLYPH_NAMES[h % (GLYPH_NAMES.length - 1)];
    if (kind === "policy" && /nothing|idle|noop/i.test(key)) glyph = "zzz";
    else if (kind === "policy") glyph = ["gear", "dots", "tri", "cross"][h % 4];
    if (/terminal|opencode|bash/i.test(key)) glyph = "term";
    return { glyph, color: HEAD_COLORS[(h >>> 8) % HEAD_COLORS.length], skin: (h >>> 4) % 3, h };
  }

  // Draw a mascot. (x, y) is the top-left of the 7-wide head; s is the integer pixel scale.
  // pose: 0 stand, 1/2 walking frames, 3 arm up (swing), 4 bend. face: 1 right, -1 left (head glyph is not mirrored).
  function mascot(ctx, m, x, y, s, pose, face) {
    s = s || 1; pose = pose || 0; face = face || 1;
    const bend = pose === 4 ? 1 : 0, hx = x, hy = y + bend * s;
    // head: 7x7 square, 1px border, glyph in the 5x5 interior
    ctx.fillStyle = P.ink; ctx.fillRect(hx * 1, hy, 7 * s, 7 * s);
    ctx.fillStyle = m.color; ctx.fillRect(hx + s, hy + s, 5 * s, 5 * s);
    const bits = GLYPH_BITS[m.glyph] || GLYPH_BITS.term; ctx.fillStyle = "#fff6e8";
    for (let i = 0; i < 25; i++) if (bits[i]) ctx.fillRect(hx + s + (i % 5) * s, hy + s + ((i / 5) | 0) * s, s, s);
    // body
    const by = y + (7 + bend) * s, bx = x + s;
    ctx.fillStyle = P.cloth; ctx.fillRect(bx, by, 5 * s, 4 * s);
    ctx.fillStyle = P.clothDk; ctx.fillRect(bx, by + 3 * s, 5 * s, s);
    ctx.fillStyle = P.hat; ctx.fillRect(bx + 2 * s, by, s, 2 * s);   // strap
    // arms
    ctx.fillStyle = P.skin;
    if (pose === 3) { ctx.fillRect(face > 0 ? bx + 5 * s : bx - s, by - 3 * s, s, 4 * s); ctx.fillRect(face > 0 ? bx - s : bx + 5 * s, by + s, s, 3 * s); }
    else { ctx.fillRect(bx - s, by + s, s, 3 * s); ctx.fillRect(bx + 5 * s, by + s, s, 3 * s); }
    // legs
    const ly = by + 4 * s; ctx.fillStyle = "#2b2f44";
    if (pose === 1) { ctx.fillRect(bx, ly, 2 * s, 2 * s); ctx.fillRect(bx + 3 * s, ly, 2 * s, s); }
    else if (pose === 2) { ctx.fillRect(bx, ly, 2 * s, s); ctx.fillRect(bx + 3 * s, ly, 2 * s, 2 * s); }
    else { ctx.fillRect(bx, ly, 2 * s, 2 * s); ctx.fillRect(bx + 3 * s, ly, 2 * s, 2 * s); }
    ctx.fillStyle = P.ink; ctx.fillRect(bx, ly + (pose === 1 ? 2 : pose === 2 ? 1 : 2) * s - 0, 0, 0);
  }
  // Big hero-style mascot for cards: draws onto its own small canvas at integer scale.
  function mascotCanvas(m, scale) {
    const c = document.createElement("canvas"); c.width = 9 * scale; c.height = 13 * scale;
    const x = c.getContext("2d"); x.imageSmoothingEnabled = false; mascot(x, m, scale, 0, scale, 0, 1); return c;
  }

  // ---------------------------------------------------------------- crops
  // Quality tiers: 0 healthy, 1 pale, 2 wilted.
  const LEAF = [["#2f8f3a", "#4fbf4a", "#8fe060"], ["#6d9a2c", "#9ab536", "#c4d054"], ["#5e4d24", "#7d6128", "#9a7c36"]];
  const BASIL = [["#238a3c", "#34b24d", "#77de6c"], ["#6d9a2c", "#9ab536", "#c4d054"], ["#5e4d24", "#7d6128", "#9a7c36"]];
  const BROC = [["#1c6e34", "#2a9448", "#5ec46a"], ["#5b8a2c", "#85ab36", "#b0c850"], ["#4f4220", "#6c5724", "#8c7030"]];
  const STEM = ["#6fc05a", "#a9b85a", "#8a6b2f"];
  const PINK = ["#e04a6c", "#d08a60", "#8a6b2f"];
  const FAM = { lettuce: 0, basil: 1, broccoli: 2, radish: 3 };
  const famCache = {};
  function family(id) {
    let f = famCache[id]; if (f !== undefined) return f;
    const s = String(id || "").toLowerCase(); f = 4;
    for (const k in FAM) if (s.indexOf(k) >= 0) { f = FAM[k]; break; }
    famCache[id] = f; return f;
  }
  const SPACING = [11, 7, 5, 4, 7];

  // Draw one plant standing on baseline by at column x. g: growth 0..1, tier: quality tier, sw: -1..1 sway.
  function plant(ctx, fam, x, by, g, tier, sw) {
    const t = tier | 0, dx = sw > 0.5 ? 1 : sw < -0.5 ? -1 : 0;
    if (g < 0.04) g = 0.04;
    if (fam === 0) { // lettuce rosette
      const w = 3 + Math.round(g * 8), hgt = Math.max(1, Math.round((1 + g * 5) * (t === 2 ? 0.6 : 1))), c = LEAF[t], x0 = x - (w >> 1);
      ctx.fillStyle = c[0]; ctx.fillRect(x0, by - hgt, w, hgt);
      if (hgt > 2) { ctx.fillRect(x0 - 1, by - 2, w + 2, 2); }
      ctx.fillStyle = c[1]; ctx.fillRect(x0 + 1, by - hgt, Math.max(1, w - 2), Math.max(1, hgt - 1));
      ctx.fillStyle = c[2]; ctx.fillRect(x0 + 1 + dx, by - hgt, Math.max(1, (w >> 1) - 1), 1);
      if (g > 0.6 && t < 2) ctx.fillRect(x + 1, by - hgt + 1, 1, 1);
    } else if (fam === 1 || fam === 4) { // herb / generic: stem with leaf pairs
      const hgt = Math.max(2, Math.round((2 + g * 22) * (t === 2 ? 0.7 : 1))), c = BASIL[t];
      ctx.fillStyle = STEM[t]; ctx.fillRect(x, by - hgt, 1, hgt);
      for (let y = by - 3; y > by - hgt; y -= 4) {
        const lw = 1 + Math.min(2, Math.round(g * 2.6)); ctx.fillStyle = c[1];
        ctx.fillRect(x - lw, y, lw, 1); ctx.fillRect(x + 1, y - 1, lw, 1);
        ctx.fillStyle = c[2]; ctx.fillRect(x - lw, y - 1, 1, 1);
      }
      ctx.fillStyle = c[2]; ctx.fillRect(x - 1 + dx, by - hgt - 1, 3, 2);
      if (t === 2) { ctx.fillStyle = c[0]; ctx.fillRect(x + 1, by - hgt, 2, 1); }
    } else if (fam === 2) { // broccoli (also micro): stem + dark floret
      const hgt = Math.max(2, Math.round((2 + g * 8) * (t === 2 ? 0.7 : 1))), fw = 2 + Math.round(g * 5), fh = 2 + Math.round(g * 3), c = BROC[t];
      ctx.fillStyle = STEM[t]; ctx.fillRect(x, by - hgt, 1, hgt);
      const x0 = x - (fw >> 1) + dx, y0 = by - hgt - fh + 1;
      ctx.fillStyle = c[0]; ctx.fillRect(x0, y0, fw, fh); ctx.fillStyle = c[1]; ctx.fillRect(x0 + 1, y0, Math.max(1, fw - 2), Math.max(1, fh - 1));
      ctx.fillStyle = c[2]; ctx.fillRect(x0 + 1, y0, 1, 1); if (fw > 5) ctx.fillRect(x0 + fw - 2, y0 + 1, 1, 1);
    } else { // radish micro: pink stem + two cotyledons
      const hgt = Math.max(2, Math.round((2 + g * 9) * (t === 2 ? 0.7 : 1))), c = LEAF[t];
      ctx.fillStyle = PINK[t]; ctx.fillRect(x, by - hgt, 1, hgt);
      ctx.fillStyle = c[1]; ctx.fillRect(x - 2 + dx, by - hgt - 1, 2, 2); ctx.fillRect(x + 1 + dx, by - hgt - 1, 2, 2);
      ctx.fillStyle = c[2]; ctx.fillRect(x - 2 + dx, by - hgt - 1, 1, 1);
    }
  }

  // Cloud sprites drawn once onto small canvases.
  function cloudSprite(variant, base, shade) {
    const dims = [[44, 14], [64, 18], [30, 10]][variant], c = document.createElement("canvas"); c.width = dims[0]; c.height = dims[1];
    const x = c.getContext("2d"), w = dims[0], h = dims[1];
    x.fillStyle = base;
    const lumps = variant === 0 ? [[4, 7, 36, 6], [10, 4, 22, 4], [18, 1, 12, 4]] : variant === 1 ? [[4, 11, 56, 6], [10, 7, 40, 5], [18, 3, 18, 5], [38, 4, 14, 4]] : [[2, 5, 26, 4], [7, 2, 14, 3]];
    for (const l of lumps) x.fillRect(l[0], l[1], l[2], l[3]);
    x.fillStyle = shade; x.fillRect(lumps[0][0], lumps[0][1] + lumps[0][3] - 1, lumps[0][2], 1);
    return c;
  }

  window.Sprites = { P, text, textWidth, plate, rect, line, hash, hashStr, mascotFor, mascot, mascotCanvas, plant, family, SPACING, GLYPH_NAMES, cloudSprite };
})();
