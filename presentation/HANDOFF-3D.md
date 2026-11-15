# Handoff: rebuilding the pitch deck in the 3D viewer style

Supersedes the old React-deck `HANDOFF.md` for the next step. Branch: `max/deck-3d`, cut from main at `860379b`.

## Where things stand
- The old deck (React, hash routes, pixel art) lives only on branch `max/pixel-site` (commit `1eaba70` and later). It is **not** on main; main has no `web/` app. Do not port its code. Only the research markdown was copied into `presentation/` (staged, not committed).
- The new site is the viewer in `scripts/viz/`: a Python server (`server.py`) serving plain HTML/CSS/JS, three.js vendored in `scripts/viz/vendor/`, no npm, no React. Pages: `index.html` (live viewer, 6 growers side by side), `play.html` and `demo.html` (phone games), `scene.js` (3D greenhouse), `style.css` (dark theme, Pixelify Sans and Silkscreen fonts).
- There is **no presentation page yet**.
- Run it: `uv run python scripts/viz/server.py --port 8765`, then open `http://localhost:8765/index.html`. A server was started in the background in the previous session and may still be running (check the port or kill it). The agent could not render pages (no browser), only confirm HTTP 200.

## What changed on main since the research was written
34 commits, mostly by Emre and Rohan.
- **Renamed to LettuceBench** (was Greenhouse Bench). Title, copy and notes in the research files still say Greenhouse Bench.
- README restructured: "For judges" box, architecture figure (`docs/img/architecture.svg`), "Why it is hard" with the three failure patterns, a failure table linking to specific runs, hour-by-hour variables figure, market-window figure. The chess/Elo section was dropped (matches our earlier decision not to quote Elo).
- 17 model runs committed with Harbor logs, `trajectory.json`, `DAYS.md` (`runs/TRAJECTORIES.md`, `runs/ANALYSIS.md`). README states they are Harbor 0.26 + OpenCode 1.19.5 trials. Re-check the research caveat "official kit not run" against this.
- README says 8 of 17 runs left the boiler broken over a week (resolves the 7-vs-8 conflict in `CROSSREFERENCE.md`).
- New phone game "Beat the AI" (`docs/PHONE_GAME.md`, `bash scripts/phone.sh`): a person plays two mornings of seed 1 and is ranked against the 7 AI runs plus the planner. Candidate demo slide.
- **Not in the repo: the Qwen 3-4B fine-tuning with weights.** No docs, scripts or results found. Ask the owner for numbers or method before filling that slide.

## Decisions from the owner (carry over)
- Slides can be static images; 3D need not be live. PDF export is required.
- Content rules (still valid): short plain titles, no sublines, no source or doc lines on slides, no doubt or caveat lines on slides (caveats go in speaker notes), do not describe what the picture shows, one idea per slide.
- Explain the architecture and environment, not one scenario. Only the 17 model runs of 15 Nov count; ignore `runs/archive/`. No frontier gap is claimed.
- The environment slide needs plain explanations per stage: data files, scenario, seed, simulator (no AI, deterministic), agent (one tool `submit_day`, up to 5 actions a day). Nobody understands "submit_day" unexplained.
- Slide-to-slide pixel-block dissolve was liked in the old deck; use selective reveal steps only where order matters.
- Use the main-branch design language (dark, the viewer's palette), not the old pixel-art cream/green look. `presentation/STYLE.md` Look and Motion sections are for the old deck and must be rewritten; keep its Words rules.

## Proposed structure (about 12 slides)
1. Title: LettuceBench, 3D greenhouse as the image
2. Problem: Dutch glasshouse sector and its energy role (hectares, gas share, CHP only)
3. The job: a grower plans days ahead (energy, crew, orders, repairs); a climate computer drives actuators
4. The gap: long-horizon planning; the three failure patterns
5. The environment: data files, scenario, seed, simulator, one tool (use `docs/img/architecture.svg`)
6. A day: 06:00 `submit_day`, then the night runs with nobody acting
7. Why this design: day-only, one call a day
8. Realism: recorded vs assumed
9. Baselines and results: nobody acts 0.00, stop-early 0.24, planner 0.80, Gemini 0.78, Sonnet 0.70, Haiku 0.62 (seeds 1-3, 15 Nov; verify against `runs/ANALYSIS.md`)
10. What failed, with an example: market-window figure, boiler left broken
11. **Fine-tuning Qwen 3-4B: leave empty**; needs the owner's numbers or method
12. Demo (Beat the AI or replay viewer) and close

Narrative: job, gap, measurable gap, what training does about it. If the Qwen result is good, move it to slide 10 and make it the climax.

## Next steps
1. Commit the copied `presentation/` files on `max/deck-3d`; update them for the LettuceBench rename and the new README facts (compile the research against main; docs-only changes may go on main per the owner's rule, but this branch holds code too).
2. Rewrite `presentation/STYLE.md` for the viewer's design language.
3. Agree slide content with the owner, slide by slide.
4. Build `scripts/viz/present.html`, `present.js`, `present.css` reusing `style.css`, fonts and `scene.js`; serve via the existing server.
5. PDF export: `print.css` with one 16:9 page per slide for browser Print to PDF; WebGL canvases print blank, so use static images (or screenshots) for 3D visuals. Fallback: a headless-browser script that screenshots each slide and merges to PDF (check Chrome or Playwright is installed).
6. Run only quick checks (`bash scripts/quick.sh`); never benchmark scenarios. Update `docs/collaboration/README.md` when build files change.
