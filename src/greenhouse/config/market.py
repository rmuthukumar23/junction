"""Schemas for market files (data/markets/*.toml) and event files (data/events/*.toml).

Owner: Rowan. Values live in the data files; this module only reads and checks
them through `Table`, which names the file and key in every error.

A market file holds every price the operation pays or earns that is not energy
(energy prices are data/energy_prices/, owned with the weather code): crop
prices per sale unit, the external CO2 contract, orderable items with lead
times and minimum quantities, staff wages and hiring, start cash and stock.

An event file holds one event type: how often it happens, how long it lasts
(often a hidden per-seed range), what it does, and what a repair costs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import ConfigError, Param, Table

ITEM_CATEGORIES = ("co2", "seedlings", "orders")
EVENT_KINDS = ("equipment", "late_delivery")


# -- market --------------------------------------------------------------------------------

@dataclass(frozen=True)
class CropPrice:
    crop_id: str
    price_eur_per_unit: Param          # per head or per kg, as the crop file's market.unit says


@dataclass(frozen=True)
class ItemSpec:
    """Something that can be ordered. Item ids: "co2_kg", "seedlings:<crop_id>"."""
    id: str
    category: str                      # ledger category charged on delivery
    price_eur_per_unit: Param
    lead_time_h: Param                 # order -> arrival
    min_quantity: float
    dispatch_h: int                    # after this many hours an order can no longer be cancelled
    cancel_fee_eur: float
    warn_below: float                  # stock below this raises a stock_low alarm (0 = never)


@dataclass(frozen=True)
class StaffSpec:
    wage_eur_per_worker_hour: float    # employer cost per paid hour
    shift_start_h: int                 # hour of day the shift starts
    shift_hours: int                   # worker-hours each worker gives per day
    start_crew: int
    max_crew: int
    hiring_fee_eur: float              # per worker, charged when hired
    hire_notice_days: int              # hired workers start after this
    release_notice_days: int           # released workers are paid until this has passed


@dataclass(frozen=True)
class MarketSpec:
    id: str
    source: str
    start_cash_eur: float
    crops: dict[str, CropPrice]
    external_co2_eur_per_kg: Param     # contract supply used by the energy centre, metered hourly
    items: dict[str, ItemSpec]
    staff: StaffSpec
    start_stock: dict[str, float]      # item id -> quantity on hand at hour 0


def parse_market(raw: dict[str, Any], source: str) -> MarketSpec:
    t = Table(raw, source)
    if t.str("schema") != "market/1":
        raise ConfigError(f"{source}: 'schema' must be \"market/1\"")
    crops_raw = t.sub("crops")
    crops = {}
    for crop_id in list(crops_raw.raw):
        c = crops_raw.sub(crop_id)
        crops[crop_id] = CropPrice(crop_id, c.param("price_eur_per_unit", lo=0.0))
        c.done()
    if not crops:
        raise ConfigError(f"{source}: 'crops' must list at least one crop")

    items_raw = t.sub("items")
    items = {}
    for item_id in list(items_raw.raw):
        if item_id != "co2_kg" and not item_id.startswith("seedlings:"):
            raise ConfigError(f"{source}: item '{item_id}' must be \"co2_kg\" or \"seedlings:<crop_id>\"")
        if item_id.startswith("seedlings:") and item_id.partition(":")[2] not in crops:
            raise ConfigError(f"{source}: item '{item_id}' names a crop that has no price in 'crops'")
        i = items_raw.sub(item_id)
        items[item_id] = ItemSpec(
            id=item_id,
            category=i.str("category", choices=ITEM_CATEGORIES),
            price_eur_per_unit=i.param("price_eur_per_unit", lo=0.0),
            lead_time_h=i.param("lead_time_h", lo=1.0),
            min_quantity=i.num("min_quantity", lo=0.0),
            dispatch_h=i.int("dispatch_h", lo=0),
            cancel_fee_eur=i.num("cancel_fee_eur", lo=0.0),
            warn_below=i.num("warn_below", lo=0.0),
        )
        i.done()

    s = t.sub("staff")
    staff = StaffSpec(
        wage_eur_per_worker_hour=s.num("wage_eur_per_worker_hour", lo=0.0),
        shift_start_h=s.int("shift_start_h", lo=0, hi=23),
        shift_hours=s.int("shift_hours", lo=1, hi=24),
        start_crew=s.int("start_crew", lo=0),
        max_crew=s.int("max_crew", lo=0),
        hiring_fee_eur=s.num("hiring_fee_eur", lo=0.0),
        hire_notice_days=s.int("hire_notice_days", lo=0),
        release_notice_days=s.int("release_notice_days", lo=0),
    )
    s.done()
    if staff.start_crew > staff.max_crew:
        raise ConfigError(f"{source}: 'staff.start_crew' must not exceed 'staff.max_crew'")
    if staff.shift_start_h + staff.shift_hours > 24:
        raise ConfigError(f"{source}: the shift must end by midnight (shift_start_h + shift_hours <= 24)")

    stock_raw = t.sub("start_stock")
    start_stock = {}
    for item_id in list(stock_raw.raw):
        if item_id not in items:
            raise ConfigError(f"{source}: 'start_stock.{item_id}' is not an item in 'items'")
        start_stock[item_id] = stock_raw.num(item_id, lo=0.0)
    stock_raw.done()

    spec = MarketSpec(
        id=t.str("id"), source=source,
        start_cash_eur=t.num("start_cash_eur"),
        crops=crops,
        external_co2_eur_per_kg=t.param("co2.external_price_eur_per_kg", lo=0.0),
        items=items, staff=staff, start_stock=start_stock,
    )
    t.done()
    return spec


# -- events --------------------------------------------------------------------------------

@dataclass(frozen=True)
class RepairSpec:
    cost_eur: float
    worker_hours: float
    shortens_to_h: float               # after the repair completes, the outage ends this many hours later


@dataclass(frozen=True)
class EventSpec:
    id: str
    source: str
    kind: str                          # "equipment" | "late_delivery"
    rate_per_day: float                # published
    signal: str                        # what the agent sees; "alarm" in v1
    pinned_hours: tuple[int, ...]      # extra occurrences at fixed hours (demo seeds); usually empty
    # equipment events
    target: str = ""
    capacity_factor: float = 1.0
    leakage_factor: float = 1.0
    duration_h: Param = 0.0            # often a published range: the drawn value is hidden
    repair: RepairSpec | None = None
    # late-delivery events
    delay_h: Param = 0.0
    items: tuple[str, ...] = ()        # item ids it can delay; empty = any item


def parse_event(raw: dict[str, Any], source: str) -> EventSpec:
    t = Table(raw, source)
    if t.str("schema") != "event/1":
        raise ConfigError(f"{source}: 'schema' must be \"event/1\"")
    kind = t.str("kind", choices=EVENT_KINDS)
    common = dict(
        id=t.str("id"), source=source, kind=kind,
        rate_per_day=t.num("rate_per_day", lo=0.0, hi=24.0),
        signal=t.str("signal", choices=("alarm",)),
        pinned_hours=tuple(_hours(t, "pinned_hours")),
    )
    if kind == "equipment":
        spec = EventSpec(
            **common,
            target=t.str("effect.target"),
            capacity_factor=t.num("effect.capacity_factor", default=1.0, lo=0.0, hi=1.0),
            leakage_factor=t.num("effect.leakage_factor", default=1.0, lo=1.0),
            duration_h=t.param("duration_h", lo=1.0),
            repair=RepairSpec(t.num("repair.cost_eur", lo=0.0), t.num("repair.worker_hours", lo=0.0),
                              t.num("repair.shortens_to_h", lo=0.0)),
        )
    else:
        items = t.list("items", default=[])
        if not all(isinstance(i, str) for i in items):
            raise ConfigError(f"{source}: 'items' must be a list of item ids")
        spec = EventSpec(**common, delay_h=t.param("delay_h", lo=1.0), items=tuple(items))
    t.done()
    return spec


def _hours(t: Table, key: str) -> list[int]:
    hours = t.list(key, default=[])
    if not all(isinstance(h, int) and not isinstance(h, bool) and h >= 0 for h in hours):
        raise ConfigError(f"{t.source}: '{key}' must be a list of hours (integers >= 0)")
    return hours
