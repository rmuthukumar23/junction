"""The simulator and the tools under the daily turn (round 3), on fake subsystems (fakes.py)."""
import unittest
from pathlib import Path

from envkit.core import Episode, replay
from envkit.scenario import load_scenario

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "fake-winter.toml"
WARM = {"heat_day_c": 20.0, "heat_night_c": 16.0}
DAY_H = 24


def episode(seed: int = 1) -> Episode:
    return Episode(load_scenario(FIXTURE), seed)


def ok(ep: Episode, tool: str, args=None):
    r = ep.call(tool, args or {})
    assert r["ok"], r
    return r


def ready(ep: Episode, compartment: str | None = None) -> list[str]:
    return [b["id"] for b in ep.env.sim.batch_views() if b["status"] == "ready" and not b["harvest_queued"]
            and (compartment is None or b["compartment"] == compartment)]


def warm(ep: Episode) -> None:
    ok(ep, "set_climate", WARM)
    ok(ep, "set_night_schedule", {"from_hour": 18, "copy_day": True})


def tend(ep: Episode) -> None:
    """One morning: book a repair for a failed boiler, harvest what is ready."""
    if "boiler" in ep.env.sim.effects and "boiler" not in ep.env.sim.business.bookings:
        ok(ep, "book_contractor", {"trade": "heating_installer", "target": "boiler"})
    if ready(ep):
        ok(ep, "harvest", {"batch_ids": ready(ep)})


def play_season(ep: Episode) -> None:
    """Warm both compartments day and night, keep the boiler repaired, harvest whatever
    is ready, end each day."""
    warm(ep)
    while not ep.done:
        tend(ep)
        ep.call("end_shift")


class TurnTests(unittest.TestCase):
    def test_day_1_starts_at_06_after_the_handover_night(self):
        ep = episode()
        self.assertEqual((ep.env.sim.hour, ep.window), (6, 6))
        self.assertEqual(sum(ep.acted), 0)              # the handover night is nobody's turn
        self.assertEqual(len(ep.env.sim.history), 6)

    def test_there_are_no_read_tools_and_the_opening_shows_rules_and_the_briefing(self):
        names = {t["name"] for t in episode().describe_tools()}
        self.assertFalse({n for n in names if n.startswith("get_")})
        self.assertNotIn("advance", names)
        opening = episode().opening
        self.assertEqual(opening["rules"]["turn"]["actions_per_day"], 5)
        self.assertEqual(opening["briefing"]["clock"]["time"], "06:00")
        self.assertIn("status", opening["briefing"])
        self.assertEqual(episode().opening, opening)       # a pure function of the seed

    def test_end_shift_runs_a_whole_day_and_returns_the_next_briefing(self):
        ep = episode()
        r = ok(ep, "end_shift")
        self.assertEqual(ep.env.sim.hour, 6 + DAY_H)
        self.assertEqual(ep.window, ep.env.sim.hour)
        self.assertEqual(r["result"]["briefing"]["clock"]["time"], "06:00")
        self.assertEqual(r["result"]["briefing"]["actions_left_today"], 5)
        self.assertEqual(ep.ops_used, 1)

    def test_the_last_allowed_action_ends_the_day(self):
        ep = episode()
        for i in range(4):
            r = ok(ep, "set_climate", {"heat_day_c": 18.0 + i})
            self.assertEqual(r["result"]["actions_left_today"], 4 - i)
            self.assertEqual(ep.env.sim.hour, 6)
        r = ok(ep, "set_climate", {"heat_day_c": 19.5})
        self.assertIn("day_ended", r["result"])
        self.assertEqual(ep.env.sim.hour, 6 + DAY_H)
        self.assertEqual(r["header"]["actions_left_today"], 5)

    def test_a_refused_action_changes_nothing_and_does_not_count(self):
        ep = episode()
        before = ep.env.sim.climate["A"]
        r = ep.call("set_climate", {"compartments": ["A"], "heat_day_c": 99.0})
        self.assertFalse(r["ok"])
        self.assertIs(ep.env.sim.climate["A"], before)
        self.assertEqual(r["header"]["actions_left_today"], 5)
        self.assertFalse(ep.call("set_climate", {"compartments": ["Z"], "heat_day_c": 10.0})["ok"])
        self.assertFalse(ep.call("set_climate", {"lamp_hours": [25]})["ok"])
        self.assertFalse(ep.call("set_energy", {"priority": {"Z": 2}})["ok"])
        self.assertFalse(ep.call("harvest", {"batch_ids": ["nope"]})["ok"])
        self.assertEqual(ep.env.actions_today, 0)

    def test_lists_are_one_action_and_report_refused_entries(self):
        ep = episode()
        warm(ep)
        while not ready(ep):
            tend(ep)
            if ready(ep):
                break
            ok(ep, "end_shift")
        ids = ready(ep)
        r = ok(ep, "harvest", {"batch_ids": ids + ["nope"]})
        self.assertEqual(set(r["result"]["accepted"]), set(ids))
        self.assertIn("nope", r["result"]["refused"])
        self.assertEqual(r["result"]["actions_left_today"], 4)


class NightTests(unittest.TestCase):
    def test_the_night_schedule_starts_on_the_baseline_and_day_settings_do_not_reach_it(self):
        ep = episode()
        ok(ep, "set_climate", WARM)
        climate, _ = ep.env.sim.settings_at(6 + 14)           # 20:00
        self.assertEqual(climate["A"].heat_night_c, 5.0)        # still the handover schedule
        day, _ = ep.env.sim.settings_at(6 + 4)                  # 10:00
        self.assertEqual(day["A"].heat_day_c, 20.0)

    def test_entries_apply_from_their_hour_until_the_next(self):
        ep = episode()
        ok(ep, "set_night_schedule", {"from_hour": 18, "copy_day": True, "heat_c": 12.0})
        ok(ep, "set_night_schedule", {"from_hour": 2, "heat_c": 9.0, "compartments": ["A"]})
        sim = ep.env.sim
        self.assertEqual(sim.night_entry(23).climate["A"].heat_night_c, 12.0)
        self.assertEqual(sim.night_entry(1).climate["A"].heat_night_c, 12.0)
        self.assertEqual(sim.night_entry(2).climate["A"].heat_night_c, 9.0)
        self.assertEqual(sim.night_entry(5).climate["B"].heat_night_c, 12.0)
        self.assertFalse(ep.call("set_night_schedule", {"from_hour": 18, "remove": True})["ok"])
        self.assertFalse(ep.call("set_night_schedule", {"from_hour": 12, "heat_c": 9.0})["ok"])
        ok(ep, "set_night_schedule", {"from_hour": 2, "remove": True})
        self.assertEqual(sim.night_entry(3).climate["A"].heat_night_c, 12.0)

    def test_the_night_runs_on_the_schedule_and_is_reported_in_the_morning(self):
        ep = episode()
        ok(ep, "set_night_schedule", {"from_hour": 18, "heat_c": 14.0})
        r = ok(ep, "end_shift")
        night = r["result"]["briefing"]["last_night"]
        self.assertEqual(night["night"], {"from_hour": 18, "to_hour": 30})
        applied = [rec.climate["A"]["heat_night_c"] for rec in ep.env.sim.history[18:30]]
        self.assertEqual(set(applied), {14.0})
        self.assertIn("A", night["climate"])

    def test_same_seed_same_night(self):
        a, b = episode(), episode()
        for ep in (a, b):
            ok(ep, "set_climate", WARM)
            ok(ep, "end_shift")
        self.assertEqual(a.env._briefing(), b.env._briefing())


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
        self.assertFalse(ep.call("plant", {"areas_m2": {"A": 5000}})["ok"])  # more than free area
        warm(ep)
        while ep.env.sim.free_area_m2("A") <= 0:
            tend(ep)
            ok(ep, "end_shift")
        free = ep.env.sim.free_area_m2("A")
        ok(ep, "plant", {"areas_m2": {"A": free}})
        self.assertLess(ep.env.sim.business.seedlings["fake_lettuce"], stock)
        self.assertEqual(ep.env.sim.free_area_m2("A"), 0.0)        # the queued planting reserves the area
        while ep.env.sim.hours_left() / 24 >= 3:
            ok(ep, "end_shift")
        r = ep.call("plant", {"areas_m2": {"B": 1}})
        self.assertFalse(r["ok"])
        self.assertIn("too late", r["error"]["message"])

    def test_orders_and_contractors(self):
        ep = episode()
        self.assertFalse(ep.call("place_orders", {"orders": {"co2_kg": 5}})["ok"])
        r = ok(ep, "place_orders", {"orders": {"co2_kg": 500}})
        self.assertEqual(r["result"]["accepted"]["co2_kg"]["arrives_hour"], 6 + 48)
        self.assertFalse(ep.call("book_contractor", {"trade": "heating_installer", "target": "boiler"})["ok"])
        while "boiler" not in ep.env.sim.effects and not ep.done:
            ok(ep, "end_shift")
        ok(ep, "book_contractor", {"trade": "heating_installer", "target": "boiler"})
        self.assertFalse(ep.call("book_contractor", {"trade": "heating_installer", "target": "boiler"})["ok"])
        for _ in range(2):
            ok(ep, "end_shift")
        self.assertNotIn("boiler", ep.env.sim.effects)          # the fake contractor repaired it

    def test_damage_persists_until_repaired(self):
        ep = episode()
        while "boiler" not in ep.env.sim.effects and not ep.done:
            ok(ep, "end_shift")
        for _ in range(3):
            ok(ep, "end_shift")
        self.assertIn("boiler", ep.env.sim.effects)


class EndingTests(unittest.TestCase):
    def test_doing_nothing_runs_every_hour_on_the_baseline_and_loses_money(self):
        ep = episode()
        led = ep.result()
        self.assertEqual(ep.env.sim.hour, 240)
        self.assertTrue(ep.env.sim.unattended)
        self.assertEqual(ep.env.sim.climate["A"].heat_day_c, 5.0)    # the fake facility's baseline
        self.assertLess(led["profit_eur"], 0)
        self.assertEqual(led["harvests"], 0)

    def test_there_is_no_tool_to_stop(self):
        # Quitting is not offered as an action (decided 14 Nov 2026): an agent that stops
        # calling tools has stopped, and the rest runs unattended.
        self.assertNotIn("finish_episode", {t["name"] for t in episode().describe_tools()})

    def test_stopping_keeps_the_day_settings_and_the_night_schedule(self):
        ep = episode()
        ok(ep, "set_climate", WARM)
        ok(ep, "set_night_schedule", {"from_hour": 18, "heat_c": 13.0})
        ep.finalize()
        self.assertTrue(ep.done)
        self.assertEqual(ep.env.sim.hour, 240)
        self.assertEqual(ep.env.sim.climate["A"].heat_day_c, WARM["heat_day_c"])
        self.assertEqual(ep.env.sim.history[-2].climate["A"]["heat_night_c"], 13.0)   # 22:00 on the last day

    def test_stopping_equals_ending_every_day_without_acting(self):
        stopped, idle = episode(), episode()
        for ep in (stopped, idle):
            ok(ep, "set_climate", WARM)
            ok(ep, "end_shift")
        stopped.finalize()
        while not idle.done:
            ok(idle, "end_shift")
        self.assertTrue(stopped.env.sim.unattended and stopped.env.sim.done)
        self.assertEqual(stopped.env.ledger(), idle.env.ledger())

    def test_playing_beats_doing_nothing(self):
        played, idle = episode(), episode()
        play_season(played)
        self.assertGreater(played.result()["profit_eur"], idle.result()["profit_eur"])


class DeterminismTests(unittest.TestCase):
    def test_refused_calls_change_nothing(self):
        a, b = episode(), episode()
        b.call("set_climate", {"heat_day_c": 99.0})
        b.call("harvest", {"batch_ids": ["nope"]})
        play_season(a)
        play_season(b)
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
