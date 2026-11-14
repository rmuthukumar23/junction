"""The money ledger: categories, signs, pricing helpers and conservation."""
import math
import unittest

from greenhouse.contracts import HarvestResult, LedgerEntry, Metered
from greenhouse.world.ledger import CATEGORIES, EnergyPrices, Grade, Ledger, LedgerError

GRADES = [Grade("A", 0.85, 1.0), Grade("B", 0.60, 0.6), Grade("waste", 0.0, 0.0)]


def harvest(quality=0.9, sellable=True, units=1000.0):
    return HarvestResult("L1", "lettuce_butterhead", units, "head", 220.0, quality, sellable)


class LedgerTests(unittest.TestCase):
    def test_categories_match_the_contract(self):
        self.assertIn("wages", CATEGORIES)
        with self.assertRaises(LedgerError):
            Ledger(0).record(LedgerEntry(0, "bribes", -1.0))     # type: ignore[arg-type]
        with self.assertRaises(LedgerError):
            Ledger(0).record(LedgerEntry(0, "gas", math.nan))

    def test_money_is_conserved_and_profit_is_the_change_in_cash(self):
        book = Ledger(1000.0)
        book.charge(0, "wages", 66.0)
        book.earn(5, "harvest_revenue", 450.0)
        book.charge(5, "co2", 12.5)
        self.assertAlmostEqual(book.cash_eur, 1371.5)
        self.assertAlmostEqual(book.profit_eur, 371.5)
        self.assertEqual(book.conservation_error(), 0.0)
        book.cash_eur += 1.0                                      # money appearing from nowhere is caught
        self.assertGreater(book.conservation_error(), 0.5)

    def test_charges_are_negative_and_zero_records_nothing(self):
        book = Ledger(0.0)
        self.assertIsNone(book.charge(0, "gas", 0.0))
        self.assertEqual(book.charge(0, "gas", 3.0).eur, -3.0)
        with self.assertRaises(LedgerError):
            book.charge(0, "gas", -3.0)

    def test_metered_energy_is_priced_hour_by_hour(self):
        book = Ledger(0.0)
        m = Metered(hour=3, gas_m3=10.0, electricity_import_kwh=100.0, electricity_export_kwh=40.0,
                    external_co2_kg=20.0, co2_from_store_kg=50.0)
        book.price_metered(m, EnergyPrices(0.5, 0.2, 0.1), external_co2_eur_per_kg=0.3)
        t = book.totals()
        self.assertAlmostEqual(t["gas"], -5.0)
        self.assertAlmostEqual(t["electricity_bought"], -20.0)
        self.assertAlmostEqual(t["electricity_sold"], 4.0)
        self.assertAlmostEqual(t["co2"], -6.0)                   # store CO2 was paid on delivery, not here

    def test_negative_prices_are_settled_with_their_sign(self):
        """Recorded day-ahead prices go below zero: exporting then costs money and
        importing pays. It must be booked, not raise (it used to end the episode)."""
        book = Ledger(0.0)
        m = Metered(hour=7, electricity_import_kwh=100.0, electricity_export_kwh=40.0)
        book.price_metered(m, EnergyPrices(0.5, -0.02, -0.05), external_co2_eur_per_kg=0.3)
        t = book.totals()
        self.assertAlmostEqual(t["electricity_bought"], 2.0)     # paid to take power
        self.assertAlmostEqual(t["electricity_sold"], -2.0)      # paid to get rid of it
        self.assertEqual(book.conservation_error(), 0.0)

    def test_buying_at_peaks_shows_as_paying_more_than_the_average_price(self):
        book = Ledger(0.0)
        book.price_metered(Metered(hour=0, electricity_import_kwh=0.0), EnergyPrices(0.5, 0.10, 0.05), 0.3)
        book.price_metered(Metered(hour=1, electricity_import_kwh=100.0), EnergyPrices(0.5, 0.30, 0.05), 0.3)
        self.assertAlmostEqual(book.import_cost_eur / book.import_kwh, 0.30)
        self.assertAlmostEqual(book.sum_import_price / book.hours_priced, 0.20)

    def test_harvests_are_priced_by_grade_and_unsellable_earns_nothing(self):
        book = Ledger(0.0)
        a, grade_a = book.price_harvest(10, harvest(0.9), 0.45, GRADES)
        b, grade_b = book.price_harvest(10, harvest(0.7), 0.45, GRADES)
        w, grade_w = book.price_harvest(10, harvest(0.3), 0.45, GRADES)
        u, grade_u = book.price_harvest(10, harvest(0.95, sellable=False), 0.45, GRADES)
        self.assertEqual((grade_a, grade_b, grade_w, grade_u), ("A", "B", "waste", "unsellable"))
        self.assertAlmostEqual(a.eur, 450.0)
        self.assertAlmostEqual(b.eur, 270.0)
        self.assertIsNone(w)
        self.assertIsNone(u)
        self.assertEqual((book.harvests, book.unsellable_harvests), (4, 1))

    def test_every_entry_carries_hour_category_and_note(self):
        book = Ledger(0.0)
        book.price_harvest(10, harvest(), 0.45, GRADES)
        entry = book.entries[0]
        self.assertEqual((entry.hour, entry.category), (10, "harvest_revenue"))
        self.assertIn("grade A", entry.note)


if __name__ == "__main__":
    unittest.main()
