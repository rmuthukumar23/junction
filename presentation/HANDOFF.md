# Deck handoff

For the next agent continuing the pitch deck. Read `presentation/STYLE.md` first; it holds the owner's rules.

## What exists
A pitch deck at `#/present/N` on the Pixel site (branch `max/pixel-site`). 11 slides in 5 parts (Problem, Gap, System, Realism, Results).

- `web/src/present/slides.ts`: slide data (id, part, title, visual, steps, notes). Caveats and sources live in `notes` only.
- `web/src/present/visuals.tsx`: one component per slide, registered in `VISUALS`.
- `web/src/present/pixels.tsx`: pixel renderer, 18 8x8 icons, the night greenhouse scene.
- `web/src/present/nlmap.ts`: generated Netherlands map (64x76) from Cartomap/CBS province boundaries (CC BY 4.0). Regenerate, never hand-edit. The scripts that made it (`ras.mjs`, `bake.mjs`) were in a temp scratchpad and are gone; rebuild if you need a new map.
- `web/src/views/Present.tsx`: navigation (arrows, space, click, swipe, digits, F fullscreen, N notes), step state, dissolve.
- `web/src/styles/present.css`: all deck styling.
- `presentation/0*.md`: research drafts. `CROSSREFERENCE.md`: which sources are outdated and what the deck uses.

## Owner decisions so far (do not undo)
- Short plain titles, no sublines, no source or doc lines, no doubt or caveat lines on slides, no text describing what the picture shows.
- Explain the architecture and environment, not one scenario (crops, compartments, lead times are examples of knobs).
- Only the 17 model runs of 15 Nov 2026 count. No frontier gap is claimed; held-out seeds 101-108 not run by models.
- Pixel art first. The pixel-block dissolve plays on every slide change (they like it). Within a slide, reveal steps only where order matters: Netherlands (3 stats), environment (5 stages), a day, benchmark runs.
- Netherlands map: no box or frame, no blue fills, no orange glasshouse patches, no zoom.
- Environment slide: each stage needs a plain explanation (done: five cards with one-line descriptions).

## Not verified
No browser was available, so the deck has never been seen rendered. `npx tsc -b` and vitest pass. First job: open `#/present/1` and check every slide visually (text overflow at 16:9, the map's land/outline colours on the cream background, the five environment cards, the dissolve, phone and print layouts).

## Likely next work
- Visual pass on every slide; the owner found the environment slide barren, so check the others for the same (Scenarios, The juggle, Realism are text-heavy cards; more pixel sprites would help).
- The closing slide ("Thank you" + "Watch a run" link to `#/runs`) should make sense as an ending; the owner flagged this earlier. Re-check.
- Offered but not done: a "Pitch" link in the top bar (`web/src/views/common.tsx` had other people's uncommitted edits); clean URL paths instead of hash routes (needs a server fallback).
- `AGENTS.md` still says model runs exist only on earlier rule sets; that is outdated (see `CROSSREFERENCE.md`). Someone should update it.

## Checks
`cd web && npm run check` (type check + vitest). Quick checks only; do not run benchmark scenarios.
