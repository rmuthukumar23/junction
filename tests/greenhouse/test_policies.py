"""Scripted policies on the real business (market and events) with the fake facility and crops.

They play through the tool client only. Real crops and the real facility are not
assembled yet, so these check behaviour and the profit ordering on the fakes; the
reward thresholds (exploiter <= 0.05) are checked once the scenario and reference exist.
"""
import dataclasses
import tomllib
import unittest
from pathlib import Path

from envkit.clients import InProcessClient, run_inprocess
from envkit.rng import Rng
from envkit.scenario import parse_scenario
from greenhouse.config.base import resolve
from greenhouse.config.market import parse_event, parse_market
from greenhouse.contracts import StartBatch
from greenhouse.policies.exploiter import EXPLOITS
from greenhouse.policies.naive import Naive
from greenhouse.policies.rule_based import RuleBased
from greenhouse.world.business import build_business
from greenhouse.world.modules import Modules

from fakes import FakeCrop, FakeFacility

ROOT = Path(__file__).resolve().parents[2]
CROPS = ("lettuce_butterhead", "broccoli_micro")
DAYS = 14

SCENARIO = parse_scenario(f"""
[task]
id = "greenhouse-policies"
env = "greenhouse.env:GreenhouseBench"
seeds = [1]
reference = "do-nothing"
prompt = "Test fixture."
[shift]
windows = {DAYS * 24}
window_hours = 1
ops_per_window = 1
max_calls = 4000
[env]
modules = "test_policies:build"
horizon_days = {DAYS}
substeps_per_hour = 4
pin_boiler_h = -1
[[scoring.components]]
name = "profit"
weight = 1.0
kind = "mean"
metrics = ["profit_eur"]
""")


class _KgCrop(FakeCrop):
    """The fake crop sold by the kg, as the real microgreen files do."""

    def harvest(self, batch, hour):
        res = super().harvest(batch, hour)
        return dataclasses.replace(res, units=batch.area_m2 * 1.0, unit="kg")


class _Facility(FakeFacility):
    """The fake facility growing the real crop ids, with a dry-able CO2 store."""

    def crop_id(self, c):
        return CROPS[0] if c == "A" else CROPS[1]

    def apply_effect(self, e):
        # A backup heater: the real boiler trip fails the boiler outright and persists until
        # repaired (round 3), and the toy facility has no CHP or buffer to cover a night.
        super().apply_effect(e)
        if e.target == "boiler":
            self.boiler_factor = max(self.boiler_factor, 0.3)

    def start_batches(self):
        return [StartBatch("A", CROPS[0], age, 250.0) for age in (24.0, 16.0, 8.0, 0.0)] + \
               [StartBatch("B", CROPS[1], age, 500.0) for age in (20.0, 5.0)]


def build(env, rng: Rng) -> Modules:
    params = Rng(1).stream("params")
    read = lambda rel: (tomllib.loads((ROOT / rel).read_text()), rel)   # noqa: E731
    market = resolve(parse_market(*read("data/markets/nl_winter.toml")), params.stream("market"))
    events = [resolve(parse_event(*read(f"data/events/{e}.toml")), params.stream(e)) for e in ("boiler_trip", "late_delivery")]
    # No random events, so seeds compare like with like; a test can pin one boiler trip.
    pin = int(env.get("pin_boiler_h", -1))
    events = [dataclasses.replace(e, rate_per_day=0.0) for e in events]
    if pin >= 0:
        events[0] = dataclasses.replace(events[0], pinned_hours=(pin,))
    facility = _Facility(rng.stream("facility"))
    horizon_h = round(float(env["horizon_days"]) * 24)
    business = build_business(market, events, [], CROPS, facility.equipment_ids(), horizon_h, rng.stream("business"),
                              facility.recorded())
    growth = {CROPS[0]: FakeCrop(CROPS[0]), CROPS[1]: _KgCrop(CROPS[1], repeated=True)}
    return Modules(facility, business, growth, horizon_h, int(env["substeps_per_hour"]))


BOILER_SCENARIO = dataclasses.replace(SCENARIO, env_config={**SCENARIO.env_config, "pin_boiler_h": 40})


def play(policy, seed=1, scenario=SCENARIO):
    return run_inprocess(scenario, seed, policy)


class _Recording(InProcessClient):
    tools_used: set

    def call(self, tool, **args):
        self.tools_used.add(tool)
        return super().call(tool, **args)


class PolicyTests(unittest.TestCase):
    def test_policies_play_a_full_season_through_tools_without_faults(self):
        for name, cls in [("naive", Naive), ("rule-based", RuleBased), *EXPLOITS.items()]:
            with self.subTest(policy=name):
                ep = play(cls())
                self.assertEqual(ep.faults, 0, ep.fault_log)
                self.assertEqual(ep.env.sim.hour, DAYS * 24)

    def test_rule_based_books_a_contractor_and_the_part_for_a_boiler_trip_once(self):
        # Round 3: the trip persists until a heating installer with a boiler kit on site has
        # done the job; the rule-based grower books once and orders the part.
        ep = play(RuleBased(), scenario=BOILER_SCENARIO)
        b = ep.env.sim.business
        self.assertEqual(len(b.contractors.bookings), 1)
        self.assertEqual(b.contractors.visits, 1)
        self.assertTrue(any(o.item == "part:boiler_kit" for o in b.ops.orders))
        self.assertNotIn("boiler", ep.env.sim.effects)

    def test_exploits_that_cost_money_lose_to_honest_play(self):
        for scenario in (SCENARIO, BOILER_SCENARIO):
            honest = play(RuleBased(), scenario=scenario).result()["profit_eur"]
            names = ["exploit:spam-orders", "exploit:never-harvest", "exploit:extreme-climate"]
            if scenario is BOILER_SCENARIO:
                names.append("exploit:spam-repairs")      # bookings for working equipment are refused for free
            for name in names:
                with self.subTest(exploit=name, boiler_trip=scenario is BOILER_SCENARIO):
                    self.assertLess(play(EXPLOITS[name](), scenario=scenario).result()["profit_eur"], honest)

    def test_no_exploit_beats_honest_play_on_the_fakes(self):
        """Ties are expected where the fakes do not model what the exploit pushes (the fake
        facility has no CHP economics). harvest-early is excluded: on the fakes, heating costs
        more than the growth it buys, so never heating and harvesting at once looks good.
        It must be re-checked on the real modules (with the per-head pricing question)."""
        honest = play(RuleBased()).result()["profit_eur"]
        for name, cls in EXPLOITS.items():
            if name == "exploit:harvest-early":
                continue
            with self.subTest(exploit=name):
                self.assertLessEqual(play(cls()).result()["profit_eur"], honest + 1e-6)

    def test_policies_see_only_the_tool_client(self):
        ep_policy = RuleBased()
        from envkit.core import Episode
        episode = Episode(SCENARIO, 1)
        client = _Recording(episode)
        client.tools_used = set()
        ep_policy.run(client)
        self.assertLessEqual(client.tools_used, {t["name"] for t in episode.describe_tools()})
        self.assertNotIn("sim", vars(ep_policy))


if __name__ == "__main__":
    unittest.main()
