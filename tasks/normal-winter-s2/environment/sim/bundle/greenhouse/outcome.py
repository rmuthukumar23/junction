"""The final outcome: the ledger dict the scorer reads, and failure modes. Owner: Rowan.

`ledger(sim)` is what `env.py` (Max) adds to `Environment.ledger()`. It reads the
business (`sim.business`, world/business.Business), which holds `ledger`
(world/ledger.Ledger), `ops` (world/operations.Operations) and `events`
(world/events.Events); the contractors are `business.contractors`. It also accepts
an object holding those directly.
Crop and energy modules add their own evidence through `sim.failure_evidence()`
if the simulator provides it (a dict of name -> number), e.g. the facility's
hours with an empty CO2 store (the store is the facility's, not the business's).

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


def _business(sim: Any) -> Any:
    return getattr(sim, "business", sim)


def profit_eur(sim: Any) -> float:
    return _business(sim).ledger.profit_eur


def failure_modes(sim: Any) -> dict[str, float | None]:
    b = _business(sim)
    ledger, ops, events = b.ledger, b.ops, b.events
    contractors = getattr(b, "contractors", None)
    outages = events.outages
    end = events.horizon_h
    responded = [o.booked_hour - o.start_hour for o in outages if o.booked_hour is not None]
    # Hours each persistent outage was in force: from its start to its repair, or to the end of the run.
    last_hour = getattr(sim, "hour", None)
    damage_h = 0.0
    for o in outages:
        if o.persistent:
            stop = o.repaired_hour + 1 if o.repaired_hour is not None else (end if last_hour is None else last_hour)
            damage_h += max(0.0, stop - o.start_hour)
    out: dict[str, float | None] = {
        "fm_late_deliveries": float(ops.late_deliveries),
        "fm_harvest_wait_h": ops.task_wait_h["harvest"],
        "fm_plant_wait_h": ops.task_wait_h["plant"],
        "fm_tasks_never_done": float(len(ops.waiting())),
        "fm_unsellable_harvests": float(ledger.unsellable_harvests),
        "fm_harvests": float(ledger.harvests),
        "fm_import_kwh": ledger.import_kwh,
        # Paid per kWh imported vs the average hourly price: above average = bought at peaks.
        "fm_import_price_paid_eur_per_kwh": (ledger.import_cost_eur / ledger.import_kwh) if ledger.import_kwh else None,
        "fm_import_price_mean_eur_per_kwh": (ledger.sum_import_price / ledger.hours_priced) if ledger.hours_priced else None,
        "fm_outages": float(len(outages)),
        # A persistent outage nobody ever booked a contractor for.
        "fm_outages_never_repaired": float(sum(1 for o in outages if o.persistent and o.booked_hour is None)),
        "fm_mean_booking_response_h": (sum(responded) / len(responded)) if responded else None,
        "fm_damage_hours": damage_h,
        # Spare parts left in stock at the end are worth nothing.
        "fm_parts_unused": float(sum(q for i, q in ops.stock.items() if ops.items[i].category == "parts")),
        "fm_express_orders": float(sum(1 for o in ops.orders if o.express)),
        "fm_storms": float(len(events.storm_starts())),
        "fm_contractor_visits": float(contractors.visits if contractors is not None else 0),
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
    book = _business(sim).ledger
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
