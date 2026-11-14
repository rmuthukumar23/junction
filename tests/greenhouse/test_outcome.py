"""The outcome dict: profit, money by category, failure modes, and refusal of unbalanced runs.

These use a minimal stand-in for world/sim.py holding the three objects outcome.py reads.
"""
import json
import tomllib
import unittest
from dataclasses import replace
from pathlib import Path

from envkit.rng import Rng
from greenhouse import outcome
from greenhouse.config.market import parse_event, parse_market
from greenhouse.contracts import HarvestResult
from greenhouse.world.events import DeliveryDelay, Events
from greenhouse.world.ledger import Grade, Ledger
from greenhouse.world.operations import Operations

ROOT = Path(__file__).resolve().parents[2]
MARKET = parse_market(tomllib.loads((ROOT / "data/markets/nl_winter.toml").read_text()), "nl_winter")
EVENTS = [parse_event(tomllib.loads(p.read_text()), p.name) for p in sorted((ROOT / "data/events").glob("*.toml"))]
HORIZON = 42 * 24


class StandIn:
    """Only what outcome.py reads: ledger, ops, events. Plays the hours like sim.py will."""

    def __init__(self, seed=1):
        rng = Rng(seed)
        self.ledger = Ledger(MARKET.start_cash_eur)
        self.ops = Operations(MARKET, self.ledger, rng)
        self.events = Events(EVENTS, HORIZON, rng)

    def play(self, last_hour=HORIZON - 1, first_hour=0):
        for h in range(first_hour, last_hour + 1):
            for x in self.events.due(h):
                if isinstance(x, DeliveryDelay):
                    self.ops.delay(h, x.delay_h, x.items)
            for task in self.ops.end_hour(h).completed:
                if task.kind == "repair":
                    self.events.complete_repair(h, task.target)
        return self


class OutcomeTests(unittest.TestCase):
    def test_the_outcome_reads_the_business_inside_a_simulator(self):
        class Sim:
            business = StandIn().play(30)
        self.assertEqual(outcome.ledger(Sim())["profit_eur"], outcome.ledger(Sim.business)["profit_eur"])

    def test_doing_nothing_loses_exactly_the_fixed_wages(self):
        sim = StandIn().play()
        result = outcome.ledger(sim)
        s = MARKET.staff
        wages = s.start_crew * s.wage_eur_per_worker_hour * s.shift_hours * 42
        self.assertAlmostEqual(result["profit_eur"], -wages, places=6)
        self.assertAlmostEqual(result["money_wages_eur"], -wages, places=6)
        self.assertEqual(result["money_harvest_revenue_eur"], 0.0)
        self.assertLess(result["profit_eur"], 0)

    def test_profit_is_reproducible_bit_for_bit(self):
        def once():
            sim = StandIn(seed=5)
            sim.ops.place_order(10, "co2_kg", 2000)
            sim.play()
            return json.dumps(outcome.ledger(sim), sort_keys=True)
        self.assertEqual(once(), once())

    def test_every_money_key_is_present_whatever_happened(self):
        keys = set(outcome.ledger(StandIn().play(10)))
        busy = StandIn()
        busy.ledger.price_harvest(0, HarvestResult("b", "lettuce_butterhead", 10, "head", 200, 0.9, True), 0.45,
                                  [Grade("A", 0.0, 1.0)])
        self.assertEqual(keys, set(outcome.ledger(busy.play(10))))

    def test_failure_modes_record_what_went_wrong(self):
        sim = StandIn()
        sim.ops.queue(0, "harvest", "L1", 10_000.0)               # more work than the crew can ever do
        sim.ledger.price_harvest(0, HarvestResult("b", "lettuce_butterhead", 10, "head", 90, 0.9, False), 0.45, [])
        sim.events = Events([replace(e, rate_per_day=0.0, pinned_hours=(30,)) if e.kind == "equipment" else
                             replace(e, rate_per_day=0.0) for e in EVENTS], HORIZON, Rng(1))
        sim.play(100)
        fm = outcome.failure_modes(sim)
        self.assertEqual(fm["fm_tasks_never_done"], 1.0)
        self.assertEqual(fm["fm_unsellable_harvests"], 1.0)
        self.assertEqual((fm["fm_outages"], fm["fm_outages_never_repaired"]), (1.0, 1.0))
        self.assertIsNone(fm["fm_mean_repair_response_h"])

    def test_an_unbalanced_ledger_is_never_scored(self):
        sim = StandIn().play(10)
        sim.ledger.cash_eur += 100.0
        with self.assertRaises(outcome.MoneyError):
            outcome.ledger(sim)

    def test_extra_evidence_from_other_modules_is_merged(self):
        sim = StandIn().play(5)
        sim.failure_evidence = lambda: {"batches_frozen": 2, "fm_kwh_lamps": 10.0}
        fm = outcome.failure_modes(sim)
        self.assertEqual((fm["fm_batches_frozen"], fm["fm_kwh_lamps"]), (2.0, 10.0))


if __name__ == "__main__":
    unittest.main()
