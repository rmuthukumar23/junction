# Cross-reference: what is outdated, and what the deck uses

Checked 15 Nov 2026 against the repo. The deck (`web/src/present/slides.ts`) follows the "Deck uses" column.

| Topic | Conflict | Deck uses |
|---|---|---|
| Model run era | `AGENTS.md` says model runs exist only on earlier rule sets (`runs/archive/`). Outdated: `runs/normal-winter/` holds 17 runs committed 15 Nov (commits d52b8f9, 72f6758) on the current rules; `runs/archive/` holds older ones. | Only the 17 runs of 15 Nov. Archive ignored. `AGENTS.md` still needs updating. |
| Boiler left broken | README says 8 of 17; `runs/ANALYSIS.md` table flags 7. | Not on a slide. If needed: 7. |
| Scenario specifics | Research digest and Part 4 draft talk about lettuce, 2 broccoli + 1 radish compartments, 10-day seed lead time. These belong to `normal-winter` only; lettuce, microgreens, 2- and 3-compartment facilities are all data files. | Architecture: data files, scenario, seed, simulator, one tool. Scenario details stay in the notes of nothing; see Part 3/4 drafts if a judge asks. |
| Digest: lettuce 24-day cycle, Botrytis, 2022 price shock as a scenario | Not modelled in the simulator (no disease counter, no price-shock scenario). Real-world motivation only. | Listed as "not modelled yet". |
| Digest: "no read tools" / tools list | Only `submit_day` exists. | One tool. |
| Unsourced stats | "10x prices", "labour >30%", Blue Radix "100+ sites", "EUR 4/m2", USDA 29%, StoreBench training result | Not used. |
| Chess Elo | README says ~2000 vs ~3600; web sources give ~750-1,800 for LLMs, ~3,650 for Stockfish. | No numbers on the slide. README still has them. |
| Day-only briefing | Recorded: day operator, one call a day. Not recorded: why the night is a morning summary. | Shown, marked "our reasoning" on the slide and in the notes. |
