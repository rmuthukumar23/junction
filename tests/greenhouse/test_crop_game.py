"""The real crop models in the game (lucas.md round 2, task 4): in place of FakeCrop,
on the fake facility with Rowan's real business, for 10 days; and fast enough
for a whole episode."""
import json
import time
import unittest

from test_business import CROPS, _Facility, business
from test_crop_growth import ROOT, load

from envkit.rng import Rng
from greenhouse import views
from greenhouse.contracts import ClimateSample, RuleError, StartBatch
from greenhouse.world.crop import model_for, target_climate
from greenhouse.world.modules import Modules
from greenhouse.world.sim import Greenhouse

DAYS = 10
LAMP_HOURS = tuple(range(6, 22))


class _Lit(_Facility):
    """One lettuce and one basil batch a few days from ready, as a handed-over facility would have."""

    def start_batches(self):
        return [StartBatch("A", CROPS[0], 29.0, 500.0), StartBatch("B", CROPS[1], 25.0, 500.0)]


def real_growth():
    return {c: model_for(load(ROOT / "data" / "crops" / f"{c}.toml")) for c in CROPS}


def sim(seed: int = 1, days: int = DAYS) -> Greenhouse:
    rng = Rng(seed)
    modules = Modules(_Lit(rng.stream("facility")), business(seed, horizon_h=days * 24), real_growth(),
                      days * 24, 4)
    return Greenhouse(modules, rng.stream("sim"))


def tend(s: Greenhouse):
    """Heat to the crops' targets with lamps and CO2, and harvest whatever is ready."""
    for c, (day, night) in {"A": (20.0, 16.0), "B": (25.0, 20.0)}.items():
        s.set_climate(c, {"heat_day_c": day, "heat_night_c": night, "co2_ppm": 900.0,
                          "lamp_hours": LAMP_HOURS, "lamp_intensity_pct": 100.0})
    while not s.done:
        s.run_hour()
        for b in s.batch_views():
            if b["status"] == "ready" and not b["harvest_queued"]:
                s.harvest(b["id"])


class InGameTests(unittest.TestCase):
    def test_tended_crops_are_harvested_and_sold(self):
        s = sim()
        tend(s)
        sold = {h["crop_id"]: h for h in s.harvests}
        self.assertEqual(set(sold), set(CROPS), s.harvests)
        for h in s.harvests:
            self.assertTrue(h["sellable"])
            self.assertEqual(h["grade"], "A")
            self.assertGreater(h["eur"], 0)
        self.assertGreater(s.business.totals()["harvest_revenue"], 0)
        basil = next(b for b in s.batches.values() if b.crop_id == CROPS[1])
        self.assertEqual((basil.cuts, basil.status), (1, "growing"))       # basil regrows after a cut

    def test_untended_crops_earn_nothing(self):
        """D5: nobody harvests, so nothing is sold, and the ready batch loses quality."""
        s = sim()
        while not s.done:
            s.run_hour()
        self.assertEqual(s.harvests, [])
        self.assertEqual(s.business.totals()["harvest_revenue"], 0.0)

    def test_planting_uses_the_crop_files_numbers(self):
        s = sim(days=42)
        model = s.growth[CROPS[0]]
        s.business.ops.stock[f"seedlings:{CROPS[0]}"] = 100_000.0
        task = s.plant("A", 100.0)
        self.assertEqual(task.detail["seedlings"], model.seedlings_needed(100.0))
        self.assertAlmostEqual(task.worker_hours, model.labour_hours("plant", 100.0))

    def test_planting_too_late_is_refused(self):
        s = sim()                                   # 10 days, under the crop's min_days_before_end
        s.business.ops.stock[f"seedlings:{CROPS[0]}"] = 100_000.0
        with self.assertRaisesRegex(RuleError, "too late"):
            s.plant("A", 100.0)
        self.assertEqual(s.business.ops.stock[f"seedlings:{CROPS[0]}"], 100_000.0)

    def test_rules_publish_the_crops(self):
        rules = views.rules(sim())
        self.assertEqual(set(rules["crops"]), set(CROPS))
        json.dumps(rules["crops"])

    def test_same_seed_same_game(self):
        def play(seed):
            s = sim(seed)
            tend(s)
            return s.harvests, s.business.totals()
        self.assertEqual(play(2), play(2))


class SpeedTests(unittest.TestCase):
    def test_an_episode_of_crop_steps_is_fast(self):
        """About 1,000 hours x 12 sub-steps x 8 batches, with the two flux calls sim.py makes."""
        models = real_growth()
        batches = [(models[c], models[c].new_batch(f"b{i}", "A", 500.0, 0))
                   for i, c in enumerate(CROPS * 4)]
        dt = 1.0 / 12
        samples = [[ClimateSample(h, dt, s.temp_c, s.rh_pct, s.co2_ppm, s.par_umol_m2_s, s.is_day)
                    for s in [target_climate(models[CROPS[0]].spec, h, dt)]][0] for h in range(1000)]
        start = time.perf_counter()
        for sample in samples:
            for _ in range(12):
                for model, b in batches:
                    model.step(b, sample)
                    model.transpiration_kg_h(b, sample)
                    model.co2_uptake_kg_h(b, sample)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 3.0, f"{elapsed:.2f} s for one episode of crop steps")


if __name__ == "__main__":
    unittest.main()
