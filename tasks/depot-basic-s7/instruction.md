You are taking over a small distribution depot for the next 15 days.

Customers place orders around the clock. You ship them from stock and restock
from a supplier. Each item has its own selling price, supplier cost and
supplier lead time. An order that is not shipped by its deadline is cancelled
and you pay a penalty. Stock sitting on the shelf costs money every window,
and every purchase order carries a fixed fee.

You are judged on the depot's net assets at the end of your term, on the share
of ordered units you shipped, and on showing up: after the last window any
stock you still hold is sold off at a fraction of what it cost, so stock you
cannot sell in time is money lost. How fast each item sells is not given to
you; your own sales history shows it. Conditions change during the term. Some
changes are announced in alerts, some reach you only as rumors, and some you
will see only in your own numbers.

Time is windowed. There are 30 windows of 12 hours, and
each window has a budget of 12 tool operations. Every tool
result ends with a header showing the window, the operations left, your cash
and the units customers are waiting for. Spending the last operation, or
calling end_window, advances the clock. If you stop before the last window,
the remaining windows still happen with nobody at the desk.

## Interface

Every action goes through the tools of the MCP server `depot` (`http://sim:8000/mcp`), which is already connected. Nothing in this container's filesystem affects your result.

- Each tool call spends one operation, unless the tool's description says otherwise. A call rejected for malformed arguments spends nothing.
- `end_window` closes the current window.
- `read_alerts` returns announcements and rumors that have arrived.
- Every result is JSON with `ok`, then `result` or `error`, then a `header` with the operations left (`ops_left`) and status. When `header.done` is true the episode is over.
- There is no reset and no second attempt. Your result is computed from the state of the world when the episode ends.
