# Deck style guide

Read this before editing `web/src/present/` (slides, visuals, `present.css`). It records the direction the deck owner set on 15 Nov 2026.

## Words
- **Titles are short and plain**: "The gap", "A day", "Benchmark runs". No sentences, no clever phrasing.
- **No sublines** under titles, and **no source or doc references** on slides. Sources live in `presentation/0*.md` and in the speaker notes.
- **No doubt lines on slides.** Do not write "few runs per cell", "no frontier gap claimed", "not run on held-out seeds", "official kit unverified", "our reasoning", "built / config" labels. The slide shows the result; caveats go in the speaker notes (`notes`), where the speaker can say them if asked.
- **Do not describe what the picture already shows.** If a label can be read off the visual, delete it.
- A slide has one idea: a title, one visual, at most a few words per element.
- Explain the architecture and the environment, not one scenario. Scenario specifics (which crops, how many compartments, the lead times) are examples of knobs, not the story.
- Use only the 17 model runs of 15 Nov 2026 (`runs/normal-winter/`). Ignore `runs/archive/`.

## Look
- Pixel art first. Visuals are drawn on a pixel grid (`present/pixels.tsx`): the Netherlands map, the greenhouse scene, 8x8 icons. Prefer a new sprite or icon over a text box.
- Same palette as the site (`--px-*` tokens in `site.css`); title and closing slides are dark (`#17281d`) with the lit greenhouse scene.
- No rounded corners, no blur, stepped shadows, `steps()` easing for every animation so motion looks like frames.
- Bars are made of blocks, not smooth fills.

## Motion
- **Within a slide, the default is no animation.** Do not add reveals to a slide unless order explains something.
- **Steps** (`steps: n`) only where order is the point: the Netherlands (stat by stat), the environment pipeline (stage by stage), a day (day, night, loop), benchmark runs (baselines, models, planner). Each tap reveals the next step; Back reverses. Do not put steps on every slide.
- **Dissolve**: the pixel-block dissolve plays on every slide change. It is the deck's signature; keep it.
- Every animation uses `steps()` easing so it reads as frames. Print/PDF shows every step.

## Maps and generated art
- The Netherlands (`present/nlmap.ts`) is rasterised from real province boundaries (Cartomap/CBS, CC BY 4.0), not hand-drawn; no glasshouse patches, no frame or box around it. Regenerate rather than editing the rows by hand. No blue sea or lake fills: water is simply the panel background.

## Adding or changing a slide
1. Add the object in `slides.ts` (`id`, `part`, `title`, `visual`, `steps`, `notes`).
2. Add the visual in `visuals.tsx` (receives `step`; hide with `r(step, k)`); register it in `VISUALS` and in `VisualId`.
3. Put sprites in `pixels.tsx` (ASCII rows plus a palette).
4. Put anything cautious or sourced into `notes`.
5. `cd web && npm run check`.
