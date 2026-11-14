# Root Cause: lettuce greenhouse operations

You run three NFT benches of butterhead lettuce (A, B, C) for the last
6 days before the crop is cut and sold. Your goal is the highest net
profit at the end of the last day: the value of the head weight the benches
add, minus everything spent on mains water, fertilizer, waste discharge and
lab tests.

## What you manage

Each bench is a closed recirculating loop: gullies fed from one tank, treated
as one well-mixed volume of nutrient solution. Two kinds of material are
dissolved in it and are tracked separately:

- useful nutrients, which the crop takes up as it grows;
- unwanted salts, which arrive with fresh water and fertilizer, are never
  taken up, and leave only when solution is flushed or overflows.

A sensor reports each bench's electrical conductivity (EC) every morning. EC
measures the total of nutrients and salts; it does not say how much of each.
You start with a lab report of every bench taken this morning. Paid lab tests
report a bench's split, or the salt in the mains water, one day later.

Every day you set four amounts per bench:

- mains_l: mains water added. It replaces what the plants transpire.
- reserve_l: water added from a clean reserve tank shared by all benches.
  It is clean but costs more than mains water, is limited and is never refilled.
- fertilizer_g: adds nutrients, and so raises EC.
- flush_l: that many litres of solution go to waste, taking nutrients and
  salts with them, and the tank is refilled with mains water.

Too little water, too little nutrient, or too high an EC each reduce that
day's growth. Stress above a tolerance also lowers crop condition from the
next day on, and condition recovers only slowly. Notices about the site (for
example from the water utility) appear in get_status and in the day reports.

Nothing about the model is secret: `get_rules` returns every formula,
parameter, price and limit, and the exact order of a day.

## How to play

1. Call `get_rules`, then `get_status`.
2. `get_status`, `get_history`, `get_tests` and `get_events` are free reads.
   They never move time and never change anything.
3. `order_test(bench_id)` and `order_water_test()` sample now and charge the
   fee once; the result arrives the next morning.
4. `advance_day(bench_plans)` sets today's plan for all three benches, runs
   the day and returns the next morning's status. It is the only call that
   moves time: 6 calls play the whole season. A plan is accepted or
   rejected as a whole; if it is rejected, the error says what to fix and the
   day does not move. (`submit_day_plan` sets a plan without advancing, if you
   want to see its cost first.)
5. `finish_episode` stops early; the remaining days still run.

A plan lasts one day. Any day with no submitted plan runs the default plan
(see `get_rules`).

## How the result is scored

- Every run is evaluated at the end of the last day. If you stop early, call
  `finish_episode`, or your session ends, the remaining days run under the
  default plan. Stopping never freezes a result.
- Only profit counts. The number of calls, tests or plans is not rewarded, and
  neither is any explanation. Tests and other spending stay charged.
- This session allows at most 60 tool calls in total, and a limited
  time; after either, the remaining days run under the default plan. A season
  needs about 10 calls: `get_rules`, `get_status`, any tests, then one
  `advance_day` per day.
- You may write and run code to model the benches and plan; the published
  formulas are the ones the simulator uses.
- There is no reset and no second attempt. No file in this container affects
  the result: only the tool calls do.

## Interface

Every action goes through the tools of the MCP server `greenhouse` (`http://sim:8000/mcp`), which is already connected. Nothing in this container's filesystem affects your result.

- Each tool call spends one operation, unless the tool's description says otherwise. A call rejected for malformed arguments spends nothing.
- Every result is JSON with `ok`, then `result` or `error`, then a `header` with the operations left (`ops_left`) and status. When `header.done` is true the episode is over.
- There is no reset and no second attempt. Your result is computed from the state of the world when the episode ends.
