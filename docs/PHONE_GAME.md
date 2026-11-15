# One day vs the AI (phone game)

A person plays one real morning from a recorded model run on a phone, and then sees which
failure patterns they hit, next to the model's on the same morning.

    uv run python scripts/viz/server.py --host 0.0.0.0      # then open http://<laptop-ip>:8765/play.html
    cloudflared tunnel --url http://localhost:8765            # optional: an https link (camera background, tilt)

1. **Pick a morning:** opening day (vs Gemini 4 Hydrogen's best run), radish week (vs Claude Haiku 5.5) or
   broccoli rush (vs Claude Haiku 5.5). The server replays the model's recorded calls up to that morning.
2. **Play it:** the same briefing, the same `submit_day` tool and the same limit of 5 actions the model had.
   The phone shows the briefing in plain words (what is ready and worth how much, how much each crop's
   buyers still want this week, seed in stock and on the way, damage, news) and offers the actions as
   cards: sell, sow, order seed, climate, repairs, crew. Sell cards say whether a cut still fits this
   week's demand; a 💡 hint button points at the most urgent thing.
3. **Watch the day:** it plays out from 06:00 to 18:00 on the viewer's 3D site (cuts and sales pop up
   over the houses), then the night runs fast. Meanwhile the server replays the model's morning and
   finishes both seasons (`/api/challenge/report` is polled; the comparison is ready when the day ends).
4. **Failure report** (`scripts/viz/failures.py`): the same checks run on your morning and on the model's
   recorded morning from the same state, grouped by the README's patterns, next to the good calls each
   made (cut a ready crop at full price, ordered seed ahead, brought the houses up to temperature, every
   action accepted). "Watch the AI's day" replays the model's day on the same site.

   | Pattern | Check |
   |---|---|
   | Missing interacting constraints | sold above the rolling week's demand; houses left far below the crop's climate |
   | Not revising after new information | a ready crop left standing while the week had room at full price; a morning sat out with work waiting |
   | Losing track of unfinished work | benches freeing up within the 10-day seed lead time with no seed coming; empty benches with no seed; planting with no seed |
   | Action mechanics | any refused action (unknown argument, invalid item) |

5. **Season score:** after each morning the reference planner finishes the season on that copy, so both
   mornings are judged by the same hands, with the official score. For scale the page also shows the
   model's whole real run (replayed from its recorded calls; it reproduces the recorded profit exactly) and
   the planner's own season (0.80).

Limits: one morning moves a season by a few percent at most, and the planner's mid-season takeover is
weaker than its own full run, so read the season numbers as a comparison between the two mornings, not
as a benchmark result. Storm-glass and boiler repairs are not flagged: on these seeds they barely pay.
