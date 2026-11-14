"""The simulator and the one tool, submit_day, under the daily turn (round 3), on fake
subsystems (fakes.py)."""
import unittest
from pathlib import Path

from envkit.core import Episode, replay
from envkit.scenario import load_scenario

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "fake-winter.toml"
WARM = {"heat_day_c": 20.0, "heat_night_c": 16.0}
COPY_NIGHT = {"tool": "set_night_schedule", "from_hour": 18, "copy_day": True}
DAY_H = 24


def episode(seed: int = 1) -> Episode:
    return Episode(load_scenario(FIXTURE), seed)


def day(ep: Episode, *actions: dict) -> dict:
    """Submit one day; the call must be accepted. Returns its result."""
    r = ep.call("submit_day", {"actions": list(actions)})
    assert r["ok"], r
    return r["result"]


def ready(ep: Episode, compartment: str | None = None) -> list[str]:
    return [b["id"] for b in ep.env.sim.batch_views() if b["status"] == "ready" and not b["harvest_queued"]
            and (compartment is None or b["compartment"] == compartment)]


def morning(ep: Episode) -> list[dict]:
    """A careful morning: book a repair for a failed boiler, harvest what is ready."""
    out = []
    if "boiler" in ep.env.sim.effects and "boiler" not in ep.env.sim.business.bookings:
        out.append({"tool": "book_contractor", "trade": "heating_installer", "target": "boiler"})
    if ready(ep):
        out.append({"tool": "harvest", "batch_ids": ready(ep)})
    return out


def play_season(ep: Episode) -> None:
    """Warm both compartments day and night, keep the boiler repaired, harvest whatever is ready."""
    day(ep, {"tool": "set_climate", **WARM}, COPY_NIGHT)
    while not ep.done:
        day(ep, *morning(ep))


class TurnTests(unittest.TestCase):
    def test_day_1_starts_at_06_after_the_handover_night(self):
        ep = episode()
        self.assertEqual((ep.env.sim.hour, ep.window), (6, 6))
        self.assertEqual(sum(ep.acted), 0)              # the handover night is nobody's turn
        self.assertEqual(len(ep.env.sim.history), 6)

    def test_submit_day_is_the_only_tool_and_the_opening_shows_rules_and_the_briefing(self):
        self.assertEqual([t["name"] for t in episode().describe_tools()], ["submit_day"])
        opening = episode().opening
        self.assertEqual(opening["rules"]["turn"]["actions_per_day"], 5)
        self.assertIn("harvest", opening["rules"]["turn"]["actions"])
        self.assertEqual(opening["briefing"]["clock"]["time"], "06:00")
        self.assertIn("status", opening["briefing"])
        self.assertEqual(episode().opening, opening)       # a pure function of the seed

    def test_one_call_is_one_day_and_returns_the_next_briefing(self):
        ep = episode()
        out = day(ep)
        self.assertEqual(ep.env.sim.hour, 6 + DAY_H)
        self.assertEqual(ep.window, ep.env.sim.hour)
        self.assertEqual(out["briefing"]["clock"]["time"], "06:00")
        self.assertEqual(ep.ops_used, 1)
        out = day(ep, {"tool": "set_climate", **WARM})
        self.assertEqual(ep.env.sim.hour, 6 + 2 * DAY_H)
        self.assertTrue(out["results"][0]["ok"])

    def test_more_than_the_daily_limit_is_refused_whole(self):
        ep = episode()
        r = ep.call("submit_day", {"actions": [{"tool": "set_climate", "heat_day_c": 18.0}] * 6})
        self.assertFalse(r["ok"])
        self.assertEqual((ep.env.sim.hour, ep.env.sim.climate["A"].heat_day_c), (6, 5.0))

    def test_a_refused_action_changes_nothing_and_the_others_still_apply(self):
        ep = episode()
        out = day(ep, {"tool": "set_climate", "compartments": ["A"], "heat_day_c": 99.0},
                  {"tool": "set_climate", "compartments": ["Z"], "heat_day_c": 10.0},
                  {"tool": "set_energy", "priority": {"Z": 2}},
                  {"tool": "harvest", "batch_ids": ["nope"]},
                  {"tool": "set_climate", "compartments": ["B"], "heat_day_c": 12.0})
        self.assertEqual([r["ok"] for r in out["results"]], [False, False, False, False, True])
        self.assertEqual(ep.env.sim.climate["A"].heat_day_c, 5.0)
        self.assertEqual(ep.env.sim.climate["B"].heat_day_c, 12.0)

class NightTests(unittest.TestCase):
    def test_the_night_schedule_starts_on_the_baseline_and_day_settings_do_not_reach_it(self):
        ep = episode()
        day(ep, {"tool": "set_climate", **WARM})
        night = [rec.climate["A"]["heat_night_c"] for rec in ep.env.sim.history[18:30]]
        self.assertEqual(set(night), {5.0})                      # still the handover schedule
        self.assertEqual(ep.env.sim.history[10].climate["A"]["heat_day_c"], 20.0)

    def test_the_night_is_reported_in_the_morning(self):
        ep = episode()
        out = day(ep, {"tool": "set_night_schedule", "from_hour": 18, "heat_c": 14.0})
        night = out["briefing"]["last_night"]
        self.assertEqual(night["night"], {"from_hour": 18, "to_hour": 30})
        self.assertEqual({rec.climate["A"]["heat_night_c"] for rec in ep.env.sim.history[18:30]}, {14.0})
        self.assertIn("A", night["climate"])

class OperationTests(unittest.TestCase):
    def test_harvest_sells_and_needs_worker_hours(self):
        ep = episode()
        play_season(ep)
        led = ep.result()
        self.assertGreater(led["eur_harvest_revenue"], 0)
        self.assertGreater(led["harvests"], 0)

    def test_orders_and_contractors(self):
        ep = episode()
        out = day(ep, {"tool": "place_orders", "orders": {"co2_kg": 5}},
                  {"tool": "place_orders", "orders": {"co2_kg": 500}},
                  {"tool": "book_contractor", "trade": "heating_installer", "target": "boiler"})
        self.assertEqual([r["ok"] for r in out["results"]], [False, True, False])   # nothing broken yet
        self.assertEqual(out["results"][1]["result"]["accepted"]["co2_kg"]["arrives_hour"], 6 + 48)
        while "boiler" not in ep.env.sim.effects and not ep.done:
            day(ep)
        booking = {"tool": "book_contractor", "trade": "heating_installer", "target": "boiler"}
        out = day(ep, booking, booking)
        self.assertEqual([r["ok"] for r in out["results"]], [True, False])           # already booked
        day(ep)
        self.assertNotIn("boiler", ep.env.sim.effects)          # the fake contractor repaired it

    def test_damage_persists_until_repaired(self):
        ep = episode()
        while "boiler" not in ep.env.sim.effects and not ep.done:
            day(ep)
        for _ in range(3):
            day(ep)
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
        day(ep, {"tool": "set_climate", **WARM}, {"tool": "set_night_schedule", "from_hour": 18, "heat_c": 13.0})
        ep.finalize()
        self.assertTrue(ep.done)
        self.assertEqual(ep.env.sim.hour, 240)
        self.assertEqual(ep.env.sim.climate["A"].heat_day_c, WARM["heat_day_c"])
        self.assertEqual(ep.env.sim.history[-2].climate["A"]["heat_night_c"], 13.0)   # 22:00 on the last day

    def test_stopping_equals_submitting_empty_days(self):
        stopped, idle = episode(), episode()
        for ep in (stopped, idle):
            day(ep, {"tool": "set_climate", **WARM})
        stopped.finalize()
        while not idle.done:
            day(idle)
        self.assertTrue(stopped.env.sim.unattended and stopped.env.sim.done)
        self.assertEqual(stopped.env.ledger(), idle.env.ledger())

    def test_playing_beats_doing_nothing(self):
        played, idle = episode(), episode()
        play_season(played)
        self.assertGreater(played.result()["profit_eur"], idle.result()["profit_eur"])


class DeterminismTests(unittest.TestCase):
    def test_refused_submissions_change_nothing(self):
        a, b = episode(), episode()
        b.call("submit_day", {"actions": [{"tool": "hire", "workers": 1}] * 9})
        b.call("submit_day", {"actions": "not a list"})
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

if __name__ == "__main__":
    unittest.main()
