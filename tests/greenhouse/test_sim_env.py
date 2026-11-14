"""The simulator and the tools, on fake subsystems (fakes.py)."""
import unittest
from pathlib import Path

from envkit.core import Episode, replay
from envkit.scenario import load_scenario

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "fake-winter.toml"
WARM = {"heat_day_c": 20.0, "heat_night_c": 16.0}


def episode(seed: int = 1) -> Episode:
    return Episode(load_scenario(FIXTURE), seed)


def ok(ep: Episode, tool: str, args=None):
    r = ep.call(tool, args or {})
    assert r["ok"], r
    return r


def play_season(ep: Episode, extra_reads: bool = False) -> None:
    """Warm both compartments, harvest whatever is ready, advance to the end."""
    for c in ("A", "B"):
        ok(ep, "set_climate", {"compartment": c, **WARM})
    while not ep.done:
        if extra_reads:
            ep.call("get_status")
            ep.call("get_forecast", {"hours": 24})
        for b in ep.env.sim.batch_views():
            if b["status"] == "ready" and not b["harvest_queued"]:
                ok(ep, "harvest", {"batch_id": b["id"]})
        ep.call("advance", {"hours": 24})


class ClockTests(unittest.TestCase):
    def test_reads_are_free_and_move_nothing(self):
        ep = episode()
        for tool in ("get_rules", "get_status", "get_batches", "get_forecast"):
            r = ok(ep, tool)
            self.assertEqual(r["header"]["hour"], 0)
        self.assertEqual(ep.ops_used, 0)
        self.assertEqual(ep.call("get_status")["result"], ep.call("get_status")["result"])

    def test_advance_runs_hours_and_closes_as_many_windows(self):
        ep = episode()
        r = ok(ep, "advance", {"hours": 5})
        self.assertEqual(r["result"]["hours_run"], 5)
        self.assertEqual(r["header"]["hour"], 5)
        self.assertEqual(ep.window, 5)
        self.assertEqual(ep.ops_used, 1)

    def test_advance_stops_after_an_alarm(self):
        ep = episode()
        ok(ep, "set_climate", {"compartment": "A", **WARM})
        r = ok(ep, "advance", {"hours": 24})
        while not r["result"]["stopped_early"] and not ep.done:
            r = ok(ep, "advance", {"hours": 24})
        self.assertTrue(r["result"]["stopped_early"])
        self.assertLess(r["result"]["hours_run"], 24)
        self.assertEqual(r["result"]["stop_reason"], "alarm")
        self.assertTrue(r["result"]["alarms"])
        self.assertEqual(ep.window, ep.env.sim.hour)

    def test_a_rejected_advance_moves_nothing(self):
        ep = episode()
        r = ep.call("advance", {"hours": 25})
        self.assertFalse(r["ok"])
        self.assertEqual((ep.window, ep.env.sim.hour, ep.ops_used), (0, 0, 0))


class SettingTests(unittest.TestCase):
    def test_settings_stand_until_changed(self):
        ep = episode()
        ok(ep, "set_climate", {"compartment": "A", "heat_day_c": 21.0})
        ok(ep, "advance", {"hours": 1})
        climate = ok(ep, "get_status")["result"]["settings"]["climate"]["A"]
        self.assertEqual(climate["heat_day_c"], 21.0)
        self.assertEqual(climate["heat_night_c"], 5.0)

    def test_a_rejected_setting_changes_nothing(self):
        ep = episode()
        before = ep.env.sim.climate["A"]
        r = ep.call("set_climate", {"compartment": "A", "heat_day_c": 99.0})
        self.assertFalse(r["ok"])
        self.assertIs(ep.env.sim.climate["A"], before)
        self.assertFalse(ep.call("set_climate", {"compartment": "Z", "heat_day_c": 10.0})["ok"])
        self.assertFalse(ep.call("set_climate", {"compartment": "A", "lamp_hours": [25]})["ok"])
        self.assertFalse(ep.call("set_energy", {"priority": {"Z": 2}})["ok"])

    def test_energy_maps_merge(self):
        ep = episode()
        ok(ep, "set_energy", {"priority": {"A": 2}})
        r = ok(ep, "set_energy", {"priority": {"B": 1}})
        self.assertEqual(r["result"]["energy"]["priority"], {"A": 2, "B": 1})


class OperationTests(unittest.TestCase):
    def test_harvest_sells_and_needs_worker_hours(self):
        ep = episode()
        play_season(ep)
        led = ep.result()
        self.assertGreater(led["eur_harvest_revenue"], 0)
        self.assertGreater(led["harvests"], 0)

    def test_planting_uses_seedlings_and_is_refused_late(self):
        ep = episode()
        stock = ep.env.sim.business.seedlings["fake_lettuce"]
        self.assertFalse(ep.call("plant", {"compartment": "A", "area_m2": 5000})["ok"])  # more than free area
        ok(ep, "set_climate", {"compartment": "A", **WARM})
        while ep.env.sim.free_area_m2("A") <= 0:
            for b in ep.env.sim.batch_views():
                if b["compartment"] == "A" and b["status"] == "ready" and not b["harvest_queued"]:
                    ok(ep, "harvest", {"batch_id": b["id"]})
            ok(ep, "advance", {"hours": 6})
        free = ep.env.sim.free_area_m2("A")
        ok(ep, "plant", {"compartment": "A", "area_m2": free})
        self.assertLess(ep.env.sim.business.seedlings["fake_lettuce"], stock)
        self.assertEqual(ep.env.sim.free_area_m2("A"), 0.0)        # the queued planting reserves the area
        while ep.env.sim.hours_left() / 24 >= 3:
            ep.call("advance", {"hours": 24})
        r = ep.call("plant", {"compartment": "B", "area_m2": 1})
        self.assertFalse(r["ok"])
        self.assertIn("too late", r["error"]["message"])

    def test_orders_and_repairs(self):
        ep = episode()
        self.assertFalse(ep.call("place_order", {"item": "co2_kg", "quantity": 5})["ok"])
        r = ok(ep, "place_order", {"item": "co2_kg", "quantity": 500})
        self.assertEqual(r["result"]["arrives_hour"], 48)
        self.assertFalse(ep.call("repair", {"equipment_id": "boiler"})["ok"])   # nothing broken yet
        while "boiler" not in ep.env.sim.effects and not ep.done:
            ok(ep, "advance", {"hours": 24})
        ok(ep, "repair", {"equipment_id": "boiler"})
        self.assertFalse(ep.call("repair", {"equipment_id": "boiler"})["ok"])   # already queued


class EndingTests(unittest.TestCase):
    def test_doing_nothing_runs_every_hour_on_the_baseline_and_loses_money(self):
        ep = episode()
        led = ep.result()
        self.assertEqual(ep.env.sim.hour, 240)
        self.assertTrue(ep.env.sim.unattended)
        self.assertEqual(ep.env.sim.climate["A"].heat_day_c, 5.0)    # the fake facility's baseline
        self.assertLess(led["profit_eur"], 0)
        self.assertEqual(led["harvests"], 0)

    def test_finish_keeps_the_standing_settings(self):
        ep = episode()
        ok(ep, "set_climate", {"compartment": "A", **WARM})
        ok(ep, "advance", {"hours": 3})
        ok(ep, "finish_episode")
        self.assertTrue(ep.done)
        self.assertEqual(ep.env.sim.hour, 240)
        self.assertEqual(ep.env.sim.climate["A"].heat_day_c, WARM["heat_day_c"])

    def test_stopping_equals_advancing_without_acting(self):
        stopped, idle = episode(), episode()
        for ep in (stopped, idle):
            ok(ep, "set_climate", {"compartment": "A", **WARM})
            ok(ep, "advance", {"hours": 2})
        stopped.finalize()
        while not idle.done:
            ok(idle, "advance", {"hours": 24})
        self.assertTrue(stopped.env.sim.unattended and stopped.env.sim.done)
        self.assertEqual(stopped.env.ledger(), idle.env.ledger())

    def test_playing_beats_doing_nothing(self):
        played, idle = episode(), episode()
        play_season(played)
        self.assertGreater(played.result()["profit_eur"], idle.result()["profit_eur"])


class DeterminismTests(unittest.TestCase):
    def test_extra_reads_change_nothing(self):
        a, b = episode(), episode()
        play_season(a)
        play_season(b, extra_reads=True)
        self.assertEqual(a.result()["profit_eur"], b.result()["profit_eur"])
        self.assertEqual(a.env.sim.history[-1], b.env.sim.history[-1])

    def test_replay_reproduces_every_response(self):
        ep = episode()
        play_season(ep)
        again, mismatches = replay(load_scenario(FIXTURE), 1, ep.trace.records)
        self.assertEqual(mismatches, [])
        self.assertEqual(again.result()["profit_eur"], ep.result()["profit_eur"])

    def test_seeds_differ(self):
        a, b = episode(1), episode(2)
        play_season(a)
        play_season(b)
        self.assertNotEqual(a.result()["profit_eur"], b.result()["profit_eur"])


if __name__ == "__main__":
    unittest.main()
