You run a commercial greenhouse facility in the Netherlands for 42 winter days.

One energy centre (a gas CHP, a gas boiler, a heat buffer, a CO2 store and a grid
connection) serves two compartments. Compartment A grows butterhead lettuce and
compartment B grows basil, each in several batches of different ages. You also run the
business: you order CO2 and seedlings, which arrive days later; you hire and release
staff; and planting, harvesting and repairs use your crew's worker-hours.

Your goal is the highest net profit in EUR at the end of the last hour: harvest revenue
plus electricity sold, minus gas, electricity bought, CO2, wages, hiring, repairs and
orders. Crop still standing at the end is worth nothing.

How it works:
- Call `get_rules` first. It holds every mechanism, formula, price, lead time, crop rule
  and event rate, and the published ranges of the facility parameters you are not told.
- Simulated time moves only when you call `advance(hours)`. Every other tool is free in
  simulated time and never moves the clock.
- Climate and energy settings stand until you change them. The facility starts on
  baseline settings that nobody has tuned.
- You have 400 tool calls in total, reads included. When they are used up, or when
  you call `finish_episode`, the remaining hours run with your last settings and nobody
  acting: nothing more is ordered, planted or harvested.
- The episode lasts 1008 hours. Plan the whole horizon: several decisions only pay off
  days later, and some cannot be made late.

## Interface

Every action goes through the tools of the MCP server `env` (`http://sim:8000/mcp`), which is already connected. Nothing in this container's filesystem affects your result.

- Each tool call spends one operation, unless the tool's description says otherwise. A call rejected for malformed arguments spends nothing.
- Every result is JSON with `ok`, then `result` or `error`, then a `header` with the operations left (`ops_left`) and status. When `header.done` is true the episode is over.
- There is no reset and no second attempt. Your result is computed from the state of the world when the episode ends.
