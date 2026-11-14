# Root Cause: greenhouse operations

You run a greenhouse with four tomato zones (A, B, C, D) for the last 14
days before the crop is cleared. Your goal is the highest net profit at the end
of the last day: harvest sales minus everything spent on fresh water,
fertilizer, waste discharge and lab tests.

## What you manage

Each zone is a closed recirculating loop holding one well-mixed volume of
solution. Two kinds of material are dissolved in it and are tracked separately:

- useful nutrients, which the crop takes up as it grows;
- unwanted salts, which arrive with every litre of fresh water and with
  fertilizer, are never taken up, and leave only when solution is flushed or
  overflows.

A sensor reports each zone's electrical conductivity (EC) every morning. EC
measures the total of nutrients and salts. It does not say how much of each,
so two zones with the same EC can need opposite treatment. A paid lab test
reports the two separately, for the moment the sample was taken, and arrives
one day after you order it.

Every day you set three amounts per zone:

- irrigation_l: fresh water added. It replaces what the plants transpire and
  dilutes the solution. Hot days raise water demand.
- fertilizer_g: adds nutrients, and so raises EC.
- flush_l: that many litres of solution go to waste, taking nutrients and
  salts with them in proportion, and are replaced by fresh water.

Too little water, too little nutrient, or too high an EC each reduce that
day's growth. Stress above a tolerance also lowers crop condition from the
next day on, and condition recovers only slowly. Fresh water is shared by all
zones and is limited twice: a season allocation and a daily delivery cap.

Nothing about the model is secret. `get_rules` returns every formula,
parameter, price, limit and capacity, the exact order of a day, and each zone's
growth potential and water demand. What you are not told is each zone's
current split between nutrients and salts, and the weather that will actually
occur: you get a forecast.

## How to play

1. Call `get_rules` first.
2. `get_status`, `get_forecast`, `get_history`, `get_pending_tests` and
   `get_events` are free reads. They never move time and never change anything.
3. `order_test(zone_id)` takes a sample now and charges the fee once. The
   result is delivered the next morning.
4. `submit_day_plan(zone_plans)` sets today's plan for all four zones at once.
   It is accepted or rejected as a whole; a rejected plan changes nothing and
   the error says what to fix. You can resubmit before advancing.
5. `advance_day` applies the plan in effect, runs the day and moves to the next
   morning. It is the only call that moves time: 14 calls play the
   whole season.
6. `finish_episode` stops early; see below.

A plan lasts one day. Any day with no submitted plan runs the default plan
(the same fixed amounts for every zone; see `get_rules`).

## How the result is scored

- Every run is evaluated at the same moment, the end of the last day. If you
  stop early, call `finish_episode`, or your session ends, the remaining days
  still run under the default plan. Stopping never freezes a result.
- Raw result: profit in EUR. Reward: clamp((profit - floor) / (ceiling - floor), 0, 1),
  where floor is the profit the default plan alone earns on this same
  scenario and ceiling is an upper bound on profit for it. Doing nothing
  therefore scores 0. Both bounds are fixed by the scenario.
- Only profit counts. The number of calls, tests or plans is not rewarded, and
  neither is any explanation. Tests and other spending stay charged. Unused
  water and fertilizer are worth nothing.
- You may write and run code to model the greenhouse and plan; the published
  formulas are the ones the simulator uses.
- There is no reset and no second attempt. No file in this container affects
  the result: only the tool calls do.

## Interface

Every action goes through the tools of the MCP server `greenhouse` (`http://sim:8000/mcp`), which is already connected. Nothing in this container's filesystem affects your result.

- Each tool call spends one operation, unless the tool's description says otherwise. A call rejected for malformed arguments spends nothing.
- Every result is JSON with `ok`, then `result` or `error`, then a `header` with the operations left (`ops_left`) and status. When `header.done` is true the episode is over.
- There is no reset and no second attempt. Your result is computed from the state of the world when the episode ends.
