"""Schemas for market files (data/markets/*.toml), event files (data/events/*.toml) and
news files (data/news/*.toml).

Owner: Rowan. Values live in the data files; this module only reads and checks
them through `Table`, which names the file and key in every error.

A market file holds every price the operation pays or earns that is not energy
(energy prices are data/energy_prices/, owned with the weather code): crop
prices per sale unit, the external CO2 contract, orderable items (CO2, seedlings
and spare parts) with lead times and minimum quantities, contractors, staff wages
and hiring, start cash and stock.

An event file holds one event type: how often it happens, how long it lasts
(often a hidden per-seed range) or that it persists until a contractor repairs it,
and what it does. A storm event follows the recorded wind. A news file holds one
kind of headline signal (spec 14.3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import ConfigError, Param, Table

ITEM_CATEGORIES = ("co2", "seedlings", "orders", "parts")
EVENT_KINDS = ("equipment", "late_delivery", "storm")
NEWS_TYPES = ("storm", "frost", "gas_price")


# -- market --------------------------------------------------------------------------------

@dataclass(frozen=True)
class CropPrice:
    crop_id: str
    price_eur_per_unit: Param          # per head or per kg, as the crop file's market.unit says
    demand_per_week: Param | None = None   # what the buyers take at full price in any 7 days (market units)
    demand_week_factors: tuple[float, ...] = ()   # demand in episode week w = demand_per_week x factors[w]
    glut_at: float = 2.0                # the price reaches 0 at this multiple of the week's demand


@dataclass(frozen=True)
class ItemSpec:
    """Something that can be ordered. Item ids: "co2_kg", "seedlings:<crop_id>", "part:<part_id>"."""
    id: str
    category: str                      # ledger category charged on delivery
    price_eur_per_unit: Param
    lead_time_h: Param                 # order -> arrival
    min_quantity: float
    dispatch_h: int                    # after this many hours an order can no longer be cancelled
    cancel_fee_eur: float
    warn_below: float = 0.0            # stock below this raises a stock_low alarm (0 = never)
    surge_lead_time_h: Param = 0.0     # lead time while a regional storm surge lasts; defaults to lead_time_h
    express_price_eur_per_unit: Param | None = None   # express option: dearer, shorter lead time
    express_lead_fraction: float | None = None        # express lead time = this x the lead time that applies


@dataclass(frozen=True)
class ContractorSpec:
    """A trade (spec 14.2). An equipment id is fixed by the trade when it equals a `fixes`
    kind or ends with ".<kind>" ("glass" matches "A.glass")."""
    id: str
    fixes: tuple[str, ...]
    part: str                          # item id of the part each job needs
    callout_eur: Param
    rate_eur_per_h: Param
    job_hours_base: float
    job_hours_per_part: float
    response_h: Param                  # booking -> earliest visit
    surge_response_h: Param            # the same while a regional storm surge lasts

    def fixes_target(self, target: str) -> bool:
        return any(target == k or target.endswith("." + k) for k in self.fixes)


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
    contractors: dict[str, ContractorSpec] = field(default_factory=dict)
    site_start_h: int = 6              # contractors work on site in clock hours [site_start_h, site_end_h)
    site_end_h: int = 18


def parse_market(raw: dict[str, Any], source: str) -> MarketSpec:
    t = Table(raw, source)
    if t.str("schema") != "market/1":
        raise ConfigError(f"{source}: 'schema' must be \"market/1\"")
    crops_raw = t.sub("crops")
    crops = {}
    for crop_id in list(crops_raw.raw):
        c = crops_raw.sub(crop_id)
        factors = tuple(float(x) for x in c.raw.get("demand_week_factors", ())) if c.has("demand_week_factors") else ()
        if c.has("demand_week_factors"):
            c.raw.pop("demand_week_factors")
        glut = float(c.raw.pop("glut_at", 2.0))
        if glut <= 1.0:
            raise ConfigError(f"{source}: crops.{crop_id}.glut_at must be above 1")
        crops[crop_id] = CropPrice(crop_id, c.param("price_eur_per_unit", lo=0.0),
                                   c.param("demand_per_week", lo=0.0) if c.has("demand_per_week") else None, factors, glut)
        c.done()
    if not crops:
        raise ConfigError(f"{source}: 'crops' must list at least one crop")

    items_raw = t.sub("items")
    items = {}
    for item_id in list(items_raw.raw):
        if item_id != "co2_kg" and not item_id.startswith(("seedlings:", "part:")):
            raise ConfigError(f"{source}: item '{item_id}' must be \"co2_kg\", \"seedlings:<crop_id>\" "
                              "or \"part:<part_id>\"")
        if item_id.startswith("seedlings:") and item_id.partition(":")[2] not in crops:
            raise ConfigError(f"{source}: item '{item_id}' names a crop that has no price in 'crops'")
        i = items_raw.sub(item_id)
        category = i.str("category", choices=ITEM_CATEGORIES)
        if item_id.startswith("part:") != (category == "parts"):
            raise ConfigError(f"{source}: item '{item_id}': only \"part:<part_id>\" items have category \"parts\"")
        lead = i.param("lead_time_h", lo=1.0)
        surge = i.param("surge_lead_time_h", lo=1.0) if i.has("surge_lead_time_h") else lead
        has_price, has_fraction = i.has("express_price_eur_per_unit"), i.has("express_lead_fraction")
        if has_price != has_fraction:
            raise ConfigError(f"{source}: item '{item_id}' needs both 'express_price_eur_per_unit' and "
                              "'express_lead_fraction', or neither")
        items[item_id] = ItemSpec(
            id=item_id,
            category=category,
            price_eur_per_unit=i.param("price_eur_per_unit", lo=0.0),
            lead_time_h=lead,
            min_quantity=i.num("min_quantity", lo=0.0),
            dispatch_h=i.int("dispatch_h", lo=0),
            cancel_fee_eur=i.num("cancel_fee_eur", lo=0.0),
            warn_below=i.num("warn_below", default=0.0, lo=0.0),
            surge_lead_time_h=surge,
            express_price_eur_per_unit=i.param("express_price_eur_per_unit", lo=0.0) if has_price else None,
            express_lead_fraction=i.num("express_lead_fraction", lo=0.01, hi=1.0) if has_fraction else None,
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
    if staff.shift_start_h < 6 or staff.shift_start_h + staff.shift_hours > 18:
        raise ConfigError(f"{source}: the staff shift must lie inside the 06:00-18:00 duty window "
                          "(shift_start_h >= 6 and shift_start_h + shift_hours <= 18)")

    contractors: dict[str, ContractorSpec] = {}
    if t.has("contractors"):
        cs = t.sub("contractors")
        for trade in list(cs.raw):
            c = cs.sub(trade)
            fixes = c.list("fixes")
            if not fixes or not all(isinstance(k, str) and k for k in fixes):
                raise ConfigError(f"{source}: 'contractors.{trade}.fixes' must be a non-empty list of equipment kinds")
            part = c.str("part")
            if part not in items or items[part].category != "parts":
                raise ConfigError(f"{source}: 'contractors.{trade}.part' {part!r} is not a part item in 'items'")
            contractors[trade] = ContractorSpec(
                id=trade, fixes=tuple(fixes), part=part,
                callout_eur=c.param("callout_eur", lo=0.0),
                rate_eur_per_h=c.param("rate_eur_per_h", lo=0.0),
                job_hours_base=c.num("job_hours_base", lo=0.0),
                job_hours_per_part=c.num("job_hours_per_part", lo=0.0),
                response_h=c.param("response_h", lo=0.0),
                surge_response_h=c.param("surge_response_h", lo=0.0),
            )
            c.done()
    site_start, site_end = 6, 18
    if contractors:
        site = t.sub("site_hours")
        site_start, site_end = site.int("start_h", lo=0, hi=23), site.int("end_h", lo=1, hi=24)
        site.done()
        if site_end <= site_start:
            raise ConfigError(f"{source}: 'site_hours.end_h' must be after 'site_hours.start_h'")

    stock_raw = t.sub("start_stock")
    start_stock = {}
    for item_id in list(stock_raw.raw):
        if item_id not in items:
            raise ConfigError(f"{source}: 'start_stock.{item_id}' is not an item in 'items'")
        if items[item_id].category == "co2":
            raise ConfigError(f"{source}: 'start_stock.{item_id}': the CO2 store belongs to the facility; "
                              "set its start level in the facility file")
        start_stock[item_id] = stock_raw.num(item_id, lo=0.0)
    stock_raw.done()

    spec = MarketSpec(
        id=t.str("id"), source=source,
        start_cash_eur=t.num("start_cash_eur"),
        crops=crops,
        external_co2_eur_per_kg=t.param("co2.external_price_eur_per_kg", lo=0.0),
        items=items, staff=staff, start_stock=start_stock,
        contractors=contractors, site_start_h=site_start, site_end_h=site_end,
    )
    t.done()
    return spec


# -- events --------------------------------------------------------------------------------

@dataclass(frozen=True)
class RepairSpec:
    """What fixes a persistent fault: a trade and the parts its visit uses. For a storm the
    parts are per broken pane."""
    trade: str
    parts: dict[str, float]            # item id -> quantity


@dataclass(frozen=True)
class EventSpec:
    id: str
    source: str
    kind: str                          # "equipment" | "late_delivery" | "storm"
    rate_per_day: float                # published; 0 for a storm (it follows the recorded wind)
    signal: str                        # what the agent sees; "alarm" in v1
    pinned_hours: tuple[int, ...]      # extra occurrences at fixed hours (demo seeds); usually empty
    # equipment events
    target: str = ""
    capacity_factor: float = 1.0
    leakage_factor: float = 1.0
    persistent: bool = False           # lasts until a contractor repairs it (no duration_h)
    duration_h: Param = 0.0            # often a published range: the drawn value is hidden
    repair: RepairSpec | None = None   # persistent equipment events and storms
    # late-delivery events
    delay_h: Param = 0.0
    items: tuple[str, ...] = ()        # item ids it can delay; empty = any item
    # storms
    wind_threshold_m_s: float = 0.0    # fires when the recorded hourly wind reaches this
    min_gap_h: int = 0                 # at least this long after the previous storm
    panes_min: float = 0.0             # panes broken per compartment, drawn per storm in [min, max]
    panes_max: float = 0.0
    leakage_per_pane: float = 0.0      # leakage_factor = 1 + panes x this
    surge_days: float = 0.0            # regional surge after a storm: parts and contractors are slow


def parse_event(raw: dict[str, Any], source: str) -> EventSpec:
    t = Table(raw, source)
    if t.str("schema") != "event/1":
        raise ConfigError(f"{source}: 'schema' must be \"event/1\"")
    kind = t.str("kind", choices=EVENT_KINDS)
    common = dict(
        id=t.str("id"), source=source, kind=kind,
        rate_per_day=t.num("rate_per_day", default=0.0, lo=0.0, hi=24.0) if kind == "storm"
        else t.num("rate_per_day", lo=0.0, hi=24.0),
        signal=t.str("signal", choices=("alarm",)),
        pinned_hours=tuple(_hours(t, "pinned_hours")),
    )
    if kind == "equipment":
        persistent = t.bool("persistent", default=False)
        spec = EventSpec(
            **common,
            target=t.str("effect.target"),
            capacity_factor=t.num("effect.capacity_factor", default=1.0, lo=0.0, hi=1.0),
            leakage_factor=t.num("effect.leakage_factor", default=1.0, lo=1.0),
            persistent=persistent,
            duration_h=0.0 if persistent else t.param("duration_h", lo=1.0),
            repair=_repair(t) if persistent else None,
        )
    elif kind == "storm":
        spec = EventSpec(
            **common, persistent=True,
            wind_threshold_m_s=t.num("wind_threshold_m_s", lo=0.0),
            min_gap_h=t.int("min_gap_h", lo=0),
            panes_min=t.num("panes.min", lo=0.0), panes_max=t.num("panes.max", lo=0.0),
            leakage_per_pane=t.num("leakage_per_pane", lo=0.0),
            surge_days=t.num("surge_days", lo=0.0),
            repair=_repair(t),
        )
        if spec.panes_min > spec.panes_max:
            raise ConfigError(f"{source}: 'panes' needs min <= max")
    else:
        items = t.list("items", default=[])
        if not all(isinstance(i, str) for i in items):
            raise ConfigError(f"{source}: 'items' must be a list of item ids")
        spec = EventSpec(**common, delay_h=t.param("delay_h", lo=1.0), items=tuple(items))
    t.done()
    return spec


def _repair(t: Table) -> RepairSpec:
    parts_t = t.sub("repair.parts")
    parts = {item: parts_t.num(item, lo=0.0) for item in list(parts_t.raw)}
    parts_t.done()
    if not parts or not all(p.startswith("part:") for p in parts):
        raise ConfigError(f"{t.source}: 'repair.parts' must list \"part:<part_id>\" items")
    return RepairSpec(t.str("repair.trade"), parts)


def _hours(t: Table, key: str) -> list[int]:
    hours = t.list(key, default=[])
    if not all(isinstance(h, int) and not isinstance(h, bool) and h >= 0 for h in hours):
        raise ConfigError(f"{t.source}: '{key}' must be a list of hours (integers >= 0)")
    return hours


# -- news ----------------------------------------------------------------------------------

@dataclass(frozen=True)
class NewsSpec:
    """One kind of headline signal (spec 14.3). The feed is drawn once at the start."""
    id: str
    source: str
    relates_to: str                    # "storm" | "frost" | "gas_price"
    lead_min_h: float                  # a signal appears this long before the real event (drawn per signal)
    lead_max_h: float
    hit_rate: float                    # chance a real event gets a signal
    false_alarms_per_day: float        # signals with no event behind them
    headlines: tuple[str, ...]
    frost_below_c: float = 0.0         # frost: a real event is the first hour below this
    rise_fraction: float = 0.0         # gas_price: the price is this fraction above its level window_h earlier
    window_h: int = 0                  # frost and gas_price: at most one real event per window


def parse_news(raw: dict[str, Any], source: str) -> NewsSpec:
    t = Table(raw, source)
    if t.str("schema") != "news/1":
        raise ConfigError(f"{source}: 'schema' must be \"news/1\"")
    relates = t.str("relates_to", choices=NEWS_TYPES)
    headlines = t.list("headlines")
    if not headlines or not all(isinstance(h, str) and h.strip() for h in headlines):
        raise ConfigError(f"{source}: 'headlines' must be a non-empty list of strings")
    extra: dict[str, Any] = {}
    if relates == "frost":
        extra = dict(frost_below_c=t.num("frost_below_c"), window_h=t.int("window_h", lo=1))
    elif relates == "gas_price":
        extra = dict(rise_fraction=t.num("rise_fraction", lo=0.0), window_h=t.int("window_h", lo=1))
    spec = NewsSpec(
        id=t.str("id"), source=source, relates_to=relates,
        lead_min_h=t.num("lead_h.min", lo=0.0), lead_max_h=t.num("lead_h.max", lo=0.0),
        hit_rate=t.num("hit_rate", lo=0.0, hi=1.0),
        false_alarms_per_day=t.num("false_alarms_per_day", lo=0.0, hi=24.0),
        headlines=tuple(headlines), **extra,
    )
    if spec.lead_min_h > spec.lead_max_h:
        raise ConfigError(f"{source}: 'lead_h' needs min <= max")
    t.done()
    return spec
