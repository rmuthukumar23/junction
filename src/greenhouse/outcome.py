"""The final outcome: the ledger dict the scorer reads, and failure modes. Owner: Rowan.

`ledger(sim)` is what `env.py` (Max) returns from `Environment.ledger()`. It
reads three objects the simulator holds: `sim.ledger` (world/ledger.Ledger),
`sim.ops` (world/operations.Operations) and `sim.events` (world/events.Events).
Crop and energy modules can add their own evidence through
`sim.failure_evidence()` if the simulator provides it (a dict of name -> number).

Scored metric: `profit_eur` (change in cash over the episode). Standing crop is
worth nothing, so only sold harvests count. Everything else is evidence:
  * `money_<category>_eur`: money by ledger category (income positive, cost negative);
  * `fm_*`: failure-mode signals read after the run. They never enter the reward.
A run whose money does not balance is refused (`MoneyError`), so the verifier
reports an infrastructure failure rather than a score.
"""
from __future__ import annotations

from typing import Any

TOLERANCE_EUR = 1e-6    # numerical tolerance of the money balance, not a game value


class MoneyError(RuntimeError):
    """The ledger does not balance: never score such a run."""


def profit_eur(sim: Any) -> float:
    return sim.ledger.profit_eur


def failure_modes(sim: Any) -> dict[str, float | None]:
    ledger, ops, events = sim.ledger, sim.ops, sim.events
    outages = events.outages
    responded = [o.repair_requested_hour - o.start_hour for o in outages if o.repair_requested_hour is not None]
    out: dict[str, float | None] = {
        "fm_co2_store_empty_days": ops.co2_short_hours / 24.0,
        "fm_co2_short_kg": ops.co2_short_kg,
        "fm_late_deliveries": float(ops.late_deliveries),
        "fm_harvest_wait_h": ops.task_wait_h["harvest"],
        "fm_plant_wait_h": ops.task_wait_h["plant"],
        "fm_tasks_never_done": float(len(ops.waiting())),
        "fm_unsellable_harvests": float(ledger.unsellable_harvests),
        "fm_harvests": float(ledger.harvests),
        "fm_peak_import_kwh": ledger.peak_import_kwh,
        "fm_import_kwh": ledger.import_kwh,
        "fm_outages": float(len(outages)),
        "fm_outages_never_repaired": float(sum(1 for o in outages if o.repair_requested_hour is None)),
        "fm_mean_repair_response_h": (sum(responded) / len(responded)) if responded else None,
        "fm_repairs_wasted": float(events.repairs_wasted),
        "fm_orders_placed": float(len(ops.orders)),
        "fm_orders_cancelled": float(sum(1 for o in ops.orders if o.status == "cancelled")),
    }
    extra = getattr(sim, "failure_evidence", None)
    if callable(extra):
        for key, value in extra().items():
            out[key if key.startswith("fm_") else f"fm_{key}"] = None if value is None else float(value)
    return out


def ledger(sim: Any) -> dict[str, float | None]:
    """Terminal metrics. Call once the last hour has been played."""
    book = sim.ledger
    error = book.conservation_error()
    if error > TOLERANCE_EUR:
        raise MoneyError(f"money does not balance: start + entries differs from cash by {error:.9f} EUR")
    totals = book.totals()
    out: dict[str, float | None] = {
        "profit_eur": round(book.profit_eur, 6),
        "cash_eur": round(book.cash_eur, 6),
        "revenue_eur": round(totals["harvest_revenue"] + totals["electricity_sold"], 6),
    }
    for category, eur in totals.items():      # income positive, cost negative; every category present
        out[f"money_{category}_eur"] = round(eur, 6)
    out["money_conservation_error_eur"] = error
    out.update(failure_modes(sim))
    return out
