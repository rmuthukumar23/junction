# Pixel site backend

A separate site (port 8800) that replays recorded Greenhouse Bench runs as a pixel-art greenhouse. This page covers the backend in `scripts/pixel/` (`server.py`, `runs.py`, `replay.py`); the page and analytics are other files.

Run: `python scripts/pixel/server.py [--port 8800] [--artifacts <dir>] [--policy-scenario normal-winter]`, then open http://127.0.0.1:8800. Needs the repo venv with `PYTHONPATH=src`. Stdlib only. `--selftest` replays `scenarios/smoke.toml` and prints sizes. It calls no model and runs no benchmark: recorded traces are replayed through the simulator, and scripted policies play through the same tools.

## API

- `GET /` serves `scripts/pixel/index.html` (a placeholder if missing); other files under `scripts/pixel/` (and `assets/`) by name. `.py` files and traversal are refused. All responses are `no-store`.
- `GET /api/runs` gives `{"runs": [RunMeta]}`, agent runs newest first, then the scripted policies. RunMeta: `id, label, kind ("agent"|"policy"), model, policy, scenario, seed, score, profit_eur, baseline_profit_eur (do-nothing profit, the score's zero), days, status ("complete"|"partial"|"failed"), failure, started, source`.
  - Agent runs are Harbor trials found under the artifacts dir (default: `artifacts/` of the main checkout) as `**/artifacts/var/lib/envkit/trace.jsonl`, with `result.json`, `config.json`, `exception.txt` and `verifier/` beside them. Id `agent:<hash>`.
  - Policies `reference`, `rule-based`, `naive`, `do-nothing` for seeds 1-3 have id `policy:<name>:s<seed>`; they are played on demand (the first fetch of a 42-day one takes about 7 s). Listed scores come from `calibration.json` and are replaced by the recomputed score when the run is fetched.
  - `failed`: no tool call recorded, scenario not in this checkout, or the run died before scoring. `failure` holds the text. `partial`: graded but the agent crashed, or a legacy trace recorded before the daily turn (tools like `advance`); a legacy replay shows the unattended world, not the agent's play.
- `GET /api/runs/<id>` gives the replay: `meta` (RunMeta plus `shift, max_calls, compartments, crops, objective, hours, replay_verified, mismatches, end_reason, calls_used, ledger_score`), `frames`, `actions`, `events`, `alarms`, `daily`. Cached under `artifacts/pixel-cache/`, keyed by id and trace mtime.
  - `frames`: hour 0 and one per simulated hour after it (`hours + 1`), each as in `scripts/viz/server.py` plus `day` (hour // 24, from 0), `hod`, `damage` (`{compartment: 0..1}`, broken panes over the storm's maximum), `panes` (`{compartment: n}`), and `orders[].placed`.
  - `actions`: `{h, day, tool, args, ok, err, resp_summary}`, one per action inside a `submit_day` (at hour 6 of the day), plus rows for any other tool called.
  - `events` (`{h, day, kind, target, text, severity}`), all from the simulation: `storm`, `window_break` / `window_repaired` (per compartment, from the glass outages), `equipment` (non-glass effects appearing or clearing), `plant`, `harvest`, `order_placed`, `order_arrived`, `late_delivery`, `hire`, `release`, `contractor_booked`, `crew_started`, `contractor`, `batch_ready`, `batch_lost`, `stock_low`, `frost_risk`, `price`, `bankruptcy`.
  - `alarms`: the simulation's alarm log. `daily`: `{day, cash, profit, revenue, costs, harvested_kg, alarms (count)}` at the end of each day.
  - `replay_verified` is true when every recorded response digest reproduced, false if any did not, null if no calls.
- `GET /api/stats` runs `compute_stats(runs, load_replay)` from `scripts/pixel/analytics.py`; it returns `{"error": "analytics not built yet"}` while that file is missing.

Errors are `{"error": ...}`: 404 unknown run or endpoint, 422 scenario not in this checkout, 500 replay failure.
