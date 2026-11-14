"""The money ledger. Owner: Rowan.

Every money movement in the episode is one `LedgerEntry` recorded here, so
every euro in the final profit can be traced to an hour, a category and a
note. Income is positive, cost negative. Cash is start cash plus the sum of
entries, which `conservation_error` checks.

Pricing helpers turn physical flows into entries:
  * `price_metered` prices one hour of `Metered` energy and CO2 flows;
  * `price_harvest` prices a `HarvestResult` by the crop's grades.
No price lives in this module: callers pass the prices from the data files.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import get_args

from ..contracts import HarvestResult, LedgerCategory, LedgerEntry, Metered

CATEGORIES: tuple[str, ...] = get_args(LedgerCategory)


class LedgerError(ValueError):
    """An entry the ledger refuses: unknown category or non-finite amount."""


@dataclass(frozen=True)
class EnergyPrices:
    """Prices for one hour, from the energy price series (owned with the weather code)."""
    gas_eur_per_m3: float
    import_eur_per_kwh: float
    export_eur_per_kwh: float
    peak: bool = False            # this hour counts as a price peak (for failure-mode evidence)


@dataclass(frozen=True)
class Grade:
    """One sale grade from a crop file: the best grade whose min_quality is met applies."""
    name: str
    min_quality: float
    price_factor: float


class Ledger:
    def __init__(self, start_cash_eur: float):
        if not math.isfinite(start_cash_eur):
            raise LedgerError("start cash must be finite")
        self.start_cash_eur = float(start_cash_eur)
        self.cash_eur = float(start_cash_eur)
        self.entries: list[LedgerEntry] = []
        # Evidence for failure modes (outcome.py), not money.
        self.peak_import_kwh = 0.0
        self.import_kwh = 0.0
        self.harvests = 0
        self.unsellable_harvests = 0
        self.harvest_units = 0.0

    # -- recording ---------------------------------------------------------------------

    def record(self, entry: LedgerEntry) -> LedgerEntry:
        if entry.category not in CATEGORIES:
            raise LedgerError(f"unknown ledger category {entry.category!r}; categories are {list(CATEGORIES)}")
        if not math.isfinite(entry.eur):
            raise LedgerError(f"ledger amount must be finite, got {entry.eur!r}")
        self.entries.append(entry)
        self.cash_eur += entry.eur
        return entry

    def charge(self, hour: int, category: LedgerCategory, cost_eur: float, note: str = "") -> LedgerEntry | None:
        """Record a cost (a positive number becomes a negative entry). Zero records nothing."""
        if cost_eur < 0:
            raise LedgerError(f"a charge must be >= 0, got {cost_eur}")
        if cost_eur == 0:
            return None
        return self.record(LedgerEntry(hour, category, -float(cost_eur), note))

    def earn(self, hour: int, category: LedgerCategory, income_eur: float, note: str = "") -> LedgerEntry | None:
        if income_eur < 0:
            raise LedgerError(f"income must be >= 0, got {income_eur}")
        if income_eur == 0:
            return None
        return self.record(LedgerEntry(hour, category, float(income_eur), note))

    # -- pricing -----------------------------------------------------------------------

    def price_metered(self, m: Metered, prices: EnergyPrices, external_co2_eur_per_kg: float) -> list[LedgerEntry]:
        """One hour of metered energy and CO2. CO2 from the on-site store was paid on
        delivery, so only external contract CO2 is charged here."""
        out = [
            self.charge(m.hour, "gas", m.gas_m3 * prices.gas_eur_per_m3, f"{m.gas_m3:.2f} m3 gas"),
            self.charge(m.hour, "electricity_bought", m.electricity_import_kwh * prices.import_eur_per_kwh,
                        f"{m.electricity_import_kwh:.1f} kWh imported"),
            self.earn(m.hour, "electricity_sold", m.electricity_export_kwh * prices.export_eur_per_kwh,
                      f"{m.electricity_export_kwh:.1f} kWh exported"),
            self.charge(m.hour, "co2", m.external_co2_kg * external_co2_eur_per_kg,
                        f"{m.external_co2_kg:.1f} kg external CO2"),
        ]
        self.import_kwh += m.electricity_import_kwh
        if prices.peak:
            self.peak_import_kwh += m.electricity_import_kwh
        return [e for e in out if e is not None]

    def price_harvest(self, hour: int, result: HarvestResult, unit_price_eur: float,
                      grades: list[Grade]) -> tuple[LedgerEntry | None, str]:
        """Revenue for one harvest. Unsellable produce (below the crop's minimum weight)
        earns 0. Returns the entry (None for 0) and the grade name."""
        self.harvests += 1
        if not result.sellable:
            self.unsellable_harvests += 1
            return None, "unsellable"
        grade = next((g for g in sorted(grades, key=lambda g: -g.min_quality) if result.quality >= g.min_quality), None)
        if grade is None or grade.price_factor <= 0:
            return None, grade.name if grade else "ungraded"
        self.harvest_units += result.units
        eur = result.units * unit_price_eur * grade.price_factor
        entry = self.earn(hour, "harvest_revenue", eur,
                          f"{result.units:.1f} {result.unit} of {result.crop_id}, grade {grade.name}")
        return entry, grade.name

    # -- reading -----------------------------------------------------------------------

    @property
    def profit_eur(self) -> float:
        return self.cash_eur - self.start_cash_eur

    def totals(self) -> dict[str, float]:
        """Sum per category, every category present (0 if unused)."""
        out = {c: 0.0 for c in CATEGORIES}
        for e in self.entries:
            out[e.category] += e.eur
        return out

    def conservation_error(self) -> float:
        """|start + sum(entries) - cash|: 0 unless money appeared or vanished."""
        return abs(self.start_cash_eur + math.fsum(e.eur for e in self.entries) - self.cash_eur)

    def view(self) -> dict[str, float]:
        """What the agent may see: cash, profit so far and totals by category."""
        return {"cash_eur": round(self.cash_eur, 2), "profit_so_far_eur": round(self.profit_eur, 2),
                **{f"{k}_eur": round(v, 2) for k, v in self.totals().items()}}
