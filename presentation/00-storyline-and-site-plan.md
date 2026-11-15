# Presentation: storyline and site-integration plan

Scout output. Numbers below come from README.md (17 model runs, seeds 1-3, scores 0 = nobody acts, 0.8 = planner) and the research digest; re-check each against the README before it goes on a slide. Dutch stats need a fresh web check (digest rule).

## A. Storyline

Target: 16 main slides (about 20-25 s each, 6 min) plus 5 appendix slides. One idea per slide, one number or one picture per slide.

Arc: **the world runs on planning -> models are weak at planning (chess analogy) -> we built a greenhouse that measures it -> it is realistic, so the result matters -> here is what we found.**

### Part 1: Intro and problem (slides 1-4)
1. **Title.** "Greenhouse Bench: can an AI agent run a winter greenhouse for 42 days?" Intro canvas art as backdrop.
2. **The stakes (Dutch stats).** About 10,000 ha of glasshouse, about 9% of Dutch natural gas, 1,000+ CHP units. A grower makes hundreds of linked decisions a day.
3. **Real money, thin margins.** 2022 energy crisis: prices about 10x, firms without CHP went bankrupt. A good plan is the margin between profit and bankruptcy.
4. **The gap.** AI is entering these sites (Blue Radix at 100+ sites, Autonomous Greenhouse Challenge). Open question: does it plan, not only react?
- Transition 1->2: "Why a greenhouse?" Transition 4->5: "To see if models can plan, look at the cleanest case we know: chess."

### Part 2: The planning gap (slides 5-8)
5. **Chess.** Models about 2000 Elo, Stockfish about 3600; a 1600 gap means expected score 0.0001. Show the formula as a pixel bar chart.
6. **They know the rules, they lose the plan.** Three failure patterns as three pixel icons: missing interacting constraints, not revising after news, losing track of unfinished work.
7. **Why existing benchmarks miss it.** Short horizon, no lead times, no state that persists (StoreBench: 26% of runs underbought; Vending-Bench derails on delivery schedules).
8. **So we need a long-horizon, fully observable, scored-in-euros test.** Nothing hidden: planner and agent read the same briefing.
- Transition 8->9: "Here is that test."

### Part 3: System and baseline results (slides 9-13)
9. **Greenhouse Bench in one picture.** 3 compartments + energy centre, 42 days, one tool `submit_day`, score = net profit vs doing nothing.
10. **The daily turn.** Morning briefing -> one `submit_day` with actions -> simulator runs 24 h -> next morning. Replay is hour-by-hour and verified.
11. **Baseline ladder.** nobody 0 / harvest-early 0.10 / stop-early 0.24 / planner 0.80. Shows the score is not exploitable.
12. **How we made the planner honest.** First version too forgiving (models tied it at 0.79 vs 0.80); oversupply made costly; planner rebuilt with a dynamic programme (+14% on held-out seeds).
13. **17 model runs.** Gemini 0.781, Sonnet 0.695 (0.781 without the day-9 stop), Haiku 0.622, planner 0.800. Frontier is just under; the CIs are wide (state this).
- Transition 13->14: "Why do the models lose these points? Because the greenhouse is a real planning problem."

### Part 4: Realism and what the agent juggles (slides 14-16)
14. **What the agent juggles.** Climate, heat, CO2, power price, lamps, labour, orders, seed lead time (10 days), weekly demand, storms. Everything interacts.
15. **Realism and design choices.** CHP + boiler + buffer + grid is the Dutch standard; CHP makes heat, power and CO2 together (the core trade-off); why we show only the day, not the night (the night is the same state, the decisions happen in the morning briefing; showing it adds noise, not information).
16. **Takeaway and call to action.** Three failure patterns in real runs; a benchmark where every euro of gap is a decision; "watch a run" link to `#/runs`.

### Appendix (A1-A5, reachable by `#/present/a1`... or numbers 17-21)
- A1 Seed lead-time timeline (order -> arrive -> plant -> harvest).
- A2 Rolling demand window and the price curve (zero at 1.25x demand).
- A3 Per-seed score matrix (reuse `docs/img/matrix.svg` as reference, redraw in pixels).
- A4 Known limits (few runs per cell, storm glass never repaired, reference beatable).
- A5 Reproduction: Harbor task, commands, code SHA, "no official frontier gap is claimed" (AGENTS.md rule: do not claim compatibility or a gap).

Guard rails for wording: say "stalls", not "freezes" (do-nothing); do not quote the unverified StoreBench training result; do not claim official event-kit compatibility.

## B. Site integration

### Route
`web/src/lib/route.ts`:
- Add `| { view: "present"; slide: number }` to `Route`. Slide is 1-based; a missing or bad number gives 1; appendix uses numbers after the main deck (17-21), so no letters in the parser.
- In `parseHash` add `if (parts[0] === "present") return { view: "present", slide: Math.max(1, parseInt(parts[1] ?? "1", 10) || 1) };`.
- Caveat: `useHashRoute` calls `window.scrollTo(0, 0)` on every hashchange; harmless for a fixed full-viewport deck.
- Slide changes must use `history.replaceState` or `location.hash`. Use `location.hash = "#/present/N"` (creates history, browser back works); `App` must NOT remount per slide (see below), else animations restart.

`web/src/App.tsx`: add `case "present": return <Present slide={route.slide} />;` and import. Do not key the component on slide.

### Files
- `web/src/views/Present.tsx` - the viewer (keyboard, progress, rendering of a slide).
- `web/src/present/slides.ts` - the typed slide data (single source for the content).
- `web/src/present/visuals.tsx` - pixel visual components referenced by slides (greenhouse, energy flow, ladder, timeline).
- `web/src/styles/present.css` - imported from `Present.tsx` (`import "../styles/present.css"`); check how `site.css`/`stats.css` are imported in `main.tsx` and follow the same way.
- Optional `web/src/present/slides.test.ts` (vitest, node env): every slide id unique, hash round-trip, slide count matches.

### Navigation entry
- `common.tsx`: extend `type Nav = "runs" | "stats" | "how" | "present" | ""` and add `link("present", "Pitch")` in the nav. NOTE: `common.tsx` has uncommitted changes by someone else; make a minimal one-line-pair edit and re-read the file first.
- Intro corner HUD (`Intro.tsx`, also modified in the working tree): add `<a className="hud-link" href="#/present">Pitch</a>` only after the owner of those edits has committed, or skip it; the Topbar entry and the direct URL are enough.
- The Present view itself should not show the Topbar in presentation mode (full viewport); show a small "exit" link to `#/`.

### Slides as data (`slides.ts`)
```ts
export type Visual = "title" | "greenhouse" | "energy" | "ladder" | "timeline" | "chess" | "juggle" | "runs-bars" | "matrix" | "none";
export interface Slide {
  id: string;            // stable key, e.g. "chess-gap"
  part: 1 | 2 | 3 | 4 | "appendix";
  title: string;         // the one-line message
  bullets?: string[];    // max 3, short
  stat?: { value: string; label: string };  // one big number
  visual?: Visual;       // component in visuals.tsx
  data?: Record<string, number | string>;   // numbers for the visual (typed per visual later)
  source?: string;       // small footer citation
  notes?: string;        // speaker notes, shown with key N
}
export const SLIDES: Slide[] = [ /* 16 + 5 */ ];
```
Other agents paste markdown content as one object per slide; no JSX in the data. Visuals are looked up in a `Record<Visual, React.FC<{ slide: Slide }>>`.

### Viewer behaviour
- Keys: Right/PageDown/Space = next, Left/PageUp/Backspace = previous, Home/End, digits 1-9 jump (two-digit: buffer digits for 600 ms), F = fullscreen (`document.documentElement.requestFullscreen()`, feature-check), N = toggle notes, G = grid overview, Esc exits fullscreen/overview. Ignore keys when a modifier is held.
- Click: right 2/3 of the stage = next, left 1/3 = previous; swipe on touch (pointer events, 50 px threshold).
- Progress: pixel segmented bar at the bottom, one cell per slide, part colours (green, info blue, terracotta, teal), current cell highlighted with `--px-accent`; cells are `<a href="#/present/N">`. Counter "07 / 21".
- URL: `#/present/N` is the source of truth; `Present` takes `slide` prop and clamps to `[1, SLIDES.length]`; navigation sets `location.hash`.
- Print: `@media print` in `present.css`, render every slide stacked, `page-break-after: always`, 16:9 `@page` size, hide the progress bar. Simplest is to render all slides in DOM and hide non-current with CSS class; print CSS shows them all. This also gives an easy PDF export fallback (browser print).
- Stage: fixed 16:9 box scaled to fit (`min(100vw, 100vh*16/9)`), base design width 1280 with a CSS variable `--u` for scaling, so text never reflows during the talk.
- Preload: render visuals on first show only; stop canvas rAF loops when the slide is not current (`rafLoop` in `lib/loop.ts`).

### Reuse
- Styles: `.px-panel`, `.px-title`, `.px-btn`, `.px-tag` (with `.good .bad .warn .info`), the `--px-*` tokens (light theme), the `.intro` dark tokens (`--i-ink/cream/orange/ember/glass`) for the title and closing slides, `.bar` for simple bars, `.hud .cell` for stat tiles, `.intro .strip` for the "42 days / 1 tool / net profit" strip. Stepped shadows, no blur, no rounded corners (global `* { border-radius:0 }`).
- Fonts: monospace stack `--px-font`, weight 700; `BigText` (canvas pixel font from `legacy/sprites`) for titles at integer scales.
- `Mascot` (icon heads) for model names in the results slides (`S.mascotFor(run)` expects a run-like object with a model; pass `{ model: "gemini..." }` style stubs, check `mascotFor` in `legacy/sprites.ts`).
- Sprites: `getBank()` gives `fighters.json` (fighters, heads, `glyph_*` icons: term, star, ring, diamond, bolt, leaf, cross, x, tri, dots, wave, gear, zzz, spark, shovel, pitchfork) and `scene.json` (`bg`, `lamp_glow`, `alert_icons`, `stats_chart`, `spray`, `sway_lettuce/tomato/leafy`). `makeAnim(bank, "sway_lettuce")` for plant animation; `drawFrame` to blit. The `glyph_*` set is good for the three failure-pattern icons (diamond = constraints, bolt = new info, zzz = lost work, to be chosen).
- API/data: slides need no backend. Hardcode figures in `slides.ts` (they are published results). Optional later: `fetchJson("/api/runs")` for live bars, but the deck must work offline and on a static host, so do not depend on it.

### Visuals worth building (feasibility vs existing code)
| Part | Visual | Build | Feasibility |
|---|---|---|---|
| 1 | Title backdrop | Reuse `IntroFight` canvas as in `Intro.tsx` | Easy, same code; extract only if Intro is not being edited (it is modified now): copy the 15-line canvas setup instead |
| 1 | Stat tiles (ha, % gas, CHP units) | `.hud .cell` HTML, big pixel numbers via `BigText` | Easy |
| 2 | Chess Elo bar (2000 vs 3600) | Two `.bar` elements, or a canvas of pixel blocks | Easy |
| 2 | Three failure patterns | Three `.px-panel` with `glyph_*` sprites | Easy |
| 3 | Greenhouse + energy centre | Canvas, small pixel scene: 3 glass houses, CHP/boiler/buffer/CO2 tank/grid | Medium. `legacy/scene.ts` (the real 360x270 farm world) is untyped and being edited; do NOT import it. A pixel replica from `public/hero.png` crop (an `<img>` with `image-rendering: pixelated`) is the zero-risk option; a cropped screenshot of a real replay (`#/run/policy:reference:s1`) is the honest one |
| 3 | Energy flow diagram: gas -> CHP -> {heat -> buffer -> houses, power -> grid, CO2 -> tank -> houses}; boiler -> buffer | Inline SVG with `shape-rendering="crispEdges"`, stepped lines, tokens `--px-heat` (red), `--px-co2` (teal), `--px-info` for power, animated dashes with `steps()` | Medium, self-contained |
| 3 | Daily-turn loop | Four `.px-panel` boxes with arrows | Easy |
| 3 | Baseline ladder bars | Horizontal pixel bars 0 / 0.10 / 0.24 / 0.80 | Easy; draw as divs with `.bar` style |
| 3 | Model results: per-seed dots + mean bars with 95% CI | SVG or divs; Mascot heads at the left | Medium; data from README table |
| 4 | Seed lead-time timeline (day 0 order, day 10 arrive, ~24 d to harvest, 2 d top-grade window) | SVG axis with `.scrub`-like ticks | Easy |
| 4 | "Everything interacts" web (nodes: price, CHP, CO2, labour, orders, demand, storm) | Static SVG graph | Easy |
| 4 | Day-only note | A day/night strip with only the morning decision point highlighted | Easy |
| any | Day-by-day profit curve from a real run | `GET /api/runs/<id>` `daily` | Needs backend; skip or precompute 2 curves into `slides.ts` |

All charts: build as small components taking `slide.data`, with the colours from `--px-*` tokens so they follow the palette and keep 4.5:1 text contrast.

## C. Risks
- **Uncommitted changes by others:** `web/src/legacy/scene.ts` (must not be touched or imported), `web/src/views/Intro.tsx`, `web/src/views/common.tsx`, `web/src/styles/site.css`, `web/src/views/replayController.ts`, `web/src/art/fighters.json`, `docs/features/pixel-site.md`. Prefer new files; edit only `route.ts`, `App.tsx` and (carefully, minimally) `common.tsx`. Keep new CSS in `present.css`, not `site.css`.
- **Collaboration board:** AGENTS.md says to read `docs/collaboration/README.md` and stay in owned files; a new view must be recorded there and in `docs/features/pixel-site.md` (Markdown only: commit to main per the user's rule, but code goes on branch `max/pixel-site`).
- **Build config:** strict TS with `noUnusedLocals/Parameters`; `tsc -b` runs in `npm run build`, so unused slide fields or imports fail the build. `vite.config.ts` has `base: "./"`, so asset URLs are relative: reference images through `import` or `public/` with relative paths; hash routing means refresh on `#/present/5` works with the Python static server and any static host. Do not run the build in the scouting step (instruction); the implementer runs `npm run check`.
- **Tests:** vitest env is `node` (no DOM), so test only pure data/hash logic.
- **Mobile width:** `.replay` collapses at 980 px; the deck needs its own rule: below 760 px drop to a vertical scroll layout (slides stacked, no scaling stage), progress bar becomes a thin top strip, swipe still works. The 16:9 stage would make text unreadably small on a phone. Judges may view on a laptop in a browser, so desktop is the priority.
- **Fullscreen/projector:** font 13px base is too small; slide text must be at least 28 px at 1280 design width, and test at 1024x768 (4:3 projector) via letterboxing.
- **Canvas cost:** several rAF loops on hidden slides waste CPU; mount visuals only for the current slide (and next, for preloading).
- **Honesty:** do not claim a frontier gap or official event-kit compatibility (AGENTS.md; README "Known limits"). Put the "few runs per cell" note on the results slide.
- **Stats freshness:** Dutch figures come from a secondary digest; verify before they go on slides, and put the source in `slide.source`.
- **Keyboard conflicts:** the replay page uses Space/arrows; the deck binds its own listener only while mounted and removes it on unmount.
