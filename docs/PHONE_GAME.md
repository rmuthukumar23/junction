# Two days vs the AIs (phone game)

A person plays the first two mornings of a seed on a phone and is ranked against every recorded AI
run on that seed and the reference planner, on the same checks.

    bash scripts/phone.sh        # starts the server and prints the link to open on the phone

`scripts/phone.sh` runs `scripts/viz/server.py --host 0.0.0.0` and prints `http://<laptop-ip>:8765/play.html`
for phones on the same Wi-Fi. If `cloudflared` is installed (`brew install cloudflared`) it also prints a public
`https://….trycloudflare.com/play.html` link that works on any network and enables the camera background on
iPhone; with `qrencode` installed it prints QR codes. Everything the page needs is served by the laptop
(three.js r128 is vendored in `scripts/viz/vendor/`), so it works without other internet access.

1. **Pick a seed** (1, 2 or 3). Every recorded model run on that seed (`runs/normal-winter/`: 5 to 7 runs by
   Gemini 4 Hydrogen, Claude Sonnet 5.5 and Claude Haiku 5.5) started from this same morning.
2. **Play two mornings:** the same briefing, the same `submit_day` tool and the same limit of 5 actions the
   models had. The phone shows the briefing in plain words (what is ready and worth how much, what each crop's
   buyers still want this week, seed in stock and on the way, cold houses, damage, news) and offers the actions
   as cards: sell, sow, order seed, climate, repairs, crew. A 💡 hint names the most urgent thing.
3. **Watch each day** play out from 06:00 to 18:00 on the viewer's 3D site (cuts and sales pop up over the
   houses); the night runs fast; morning 2 shows what changed overnight.
4. **Ranking:** you, every model run and the reference planner, by checks passed (`scripts/viz/failures.py`),
   then by the profit of the two days. Each model run also shows its real 42-day benchmark score for scale. ▶
   replays any model's two days on the same site. The model side depends only on the seed: it is computed once
   per seed, in a thread, while the person plays.

   | Pattern | Check |
   |---|---|
   | Missing interacting constraints | houses heated for the crop; sold within the week's demand |
   | Not revising after new information | cut ready crops while buyers wanted them; no morning sat out with work waiting |
   | Losing track of unfinished work | seed ordered for benches freeing up within the 10-day lead time; no empty bench without seed coming; only sowed with seed in stock |
   | Action mechanics | every action accepted |

Limits: two days are a small slice of a 42-day season, so the checks measure the kind of mistake, not the
season's outcome. A season score for the player was tried (the reference planner finishing the game after day
2) and dropped: the planner cannot fairly pick up a game it did not start. Repairs are not checked: on these
seeds they barely pay.
