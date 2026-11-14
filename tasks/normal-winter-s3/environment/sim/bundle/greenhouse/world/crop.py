"""Crop growth models, chosen by `growth_model` in a crop data file.

    model = model_for(spec)            # one instance per crop spec
    batch = model.new_batch("A-1", "A", 400.0, planted_hour=0)
    model.step(batch, climate_sample)  # every sub-step

`leafy_vanhenten` is the one-state lettuce model of Van Henten (1994), as
tabulated in van Straten et al. (2010, ch. 6): canopy dry weight X (kg m-2)
grows by canopy photosynthesis minus maintenance respiration,

    dX/dt = c_ab * P - c_resp,d * X * q10_r ** ((T - T_r) / 10)
    P     = (1 - exp(-c_pl,d X)) * eps I * g (C - Gamma) / (eps I + g (C - Gamma))
    g     = 1 / (1/g_bnd + 1/g_stm + 1/g_car(T)),   Gamma = c_Gamma * q10_G ** ((T - T_G) / 10)

with light (I), CO2 (C, capped at the crop's saturation level) and temperature
(T) from the ClimateSample. Fresh
weight is dry weight over the crop's dry-matter fraction. Every coefficient
comes from the crop file; this module holds the mechanism only.

Units crossing to other modules: `transpiration_kg_h` is kg of water vapour per
hour for the whole batch; `co2_uptake_kg_h` is kg of CO2 per hour for the whole
batch, net of respiration, so it is negative at night (the batch releases CO2).
"""
from __future__ import annotations

import bisect
import dataclasses
import math
from typing import Any, Literal

from envkit.rng import Rng

from ..config import curves
from ..config.crop import CropSpec
from ..contracts import BatchEstimate, BatchState, ClimateSample, GrowthModel, HarvestResult

# Unit definitions, not crop values.
_S_PER_H = 3600.0
_H_PER_DAY = 24
_G_PER_KG = 1000.0
_UMOL_PER_MOL = 1e6
_PCT = 100.0
_Q10_STEP_C = 10.0          # a Q10 is, by definition, the factor per 10 C
_PER_1000 = 1000.0          # labour is given per 1000 plants in the crop file
_COUNT_DIGITS = 6           # area x density is rounded here before ceil, so 12.5 m2 x 20 is 250, not 251

# Keys of BatchState.model_state for this model.
DRY = "dry_weight_kg_m2"    # canopy dry weight per m2 of batch area
DAY = "day"                 # day index (hour // 24) the accumulators below belong to
DAY_H = "day_elapsed_h"
DAY_LIGHT = "day_light_mol_m2"
DAY_TEMP_SUM = "day_temp_sum_c_h"   # sum of T * dt during the photoperiod
DAY_LIT_H = "day_photoperiod_h"
DAY_TEMP_MIN = "day_temp_min_c"
RGR_START_DRY = "rgr_start_dry_kg_m2"  # dry weight at the start of the growth-rate window
RGR_H = "rgr_window_h"      # hours in the window: the day so far, or since the last cut
RGR = "rgr_per_day"         # relative growth rate over the last closed window (0 until one closes)
READY_LOSS = "ready_loss"   # quality lost while waiting ready


def target_climate(spec: CropSpec, hour: int, dt_h: float) -> ClimateSample:
    """The midpoints of the crop's published climate targets, with the target
    DLI spread evenly over the photoperiod at the start of each day. It is the
    climate `nominal_days` refers to and the one batches older than the episode
    grew under."""
    t = spec.climate_targets

    def mid(pair: tuple[float, float]) -> float:
        return (pair[0] + pair[1]) / 2

    is_day = hour % _H_PER_DAY < t.photoperiod_h
    par = mid(t.dli_mol_m2_d) * _UMOL_PER_MOL / (t.photoperiod_h * _S_PER_H) if is_day else 0.0
    return ClimateSample(hour=hour, dt_h=dt_h, temp_c=mid(t.day_temp_c if is_day else t.night_temp_c),
                         rh_pct=mid(t.rh_pct), co2_ppm=mid(t.co2_ppm), par_umol_m2_s=par, is_day=is_day)


class LeafyVanHenten:
    """The `leafy_vanhenten` growth model for one crop spec."""

    def __init__(self, spec: CropSpec):
        self.spec = spec
        p = spec.growth
        self._p = p
        self._density = spec.planting.density_per_m2
        # fresh g per plant = X * _fresh_g_per_dry_kg_m2
        self._fresh_g_per_dry_kg_m2 = _G_PER_KG / (self._density * p.dry_matter_fraction)
        self._ready_dry = spec.cycle.ready_fresh_weight_g / self._fresh_g_per_dry_kg_m2
        self._transplant_dry = spec.planting.transplant_dry_weight_g * self._density / _G_PER_KG
        self._fixed_resistance = 1 / p.boundary_conductance_m_s + 1 / p.stomatal_conductance_m_s
        self._counters = tuple((c.name, c.signal, c.curve) for c in spec.stress.counters)
        self._frost_kill_c = spec.stress.frost_kill_c
        self._ready_loss_per_h = spec.stress.ready_loss_per_day / _H_PER_DAY
        self._target_path = self._grow_path_at_targets()

    # -- GrowthModel ------------------------------------------------------------------

    def new_batch(self, batch_id: str, compartment_id: str, area_m2: float,
                  planted_hour: int, age_days: float = 0.0) -> BatchState:
        """A batch planted at `planted_hour`. With `age_days`, it has already grown
        that long under `target_climate`, hour by hour from `planted_hour`."""
        batch = BatchState(id=batch_id, crop_id=self.spec.id, compartment_id=compartment_id,
                           area_m2=area_m2, planted_hour=planted_hour,
                           stress={c.name: 0.0 for c in self.spec.stress.counters},
                           model_state={DRY: self._transplant_dry, RGR: 0.0, READY_LOSS: 0.0})
        self._open_day(batch.model_state, planted_hour // _H_PER_DAY)
        for h in range(planted_hour, planted_hour + round(age_days * _H_PER_DAY)):
            self.step(batch, target_climate(self.spec, h, 1.0))
        return batch

    def step(self, batch: BatchState, climate: ClimateSample) -> None:
        if batch.status in ("harvested", "lost"):
            return
        ms = batch.model_state
        temp = climate.temp_c
        if temp < self._frost_kill_c:
            batch.status = "lost"
            return
        day = climate.hour // _H_PER_DAY
        if day != ms[DAY]:
            self._close_day(batch)
            self._open_day(ms, day)
        if ms[DAY_H] == 0 or temp < ms[DAY_TEMP_MIN]:
            ms[DAY_TEMP_MIN] = temp
        dt_h = climate.dt_h
        ms[DAY_H] += dt_h
        ms[RGR_H] += dt_h
        ms[DAY_LIGHT] += climate.par_umol_m2_s * dt_h * _S_PER_H / _UMOL_PER_MOL
        if climate.is_day:
            ms[DAY_TEMP_SUM] += temp * dt_h
            ms[DAY_LIT_H] += dt_h

        # Midpoint (RK2) step, so 12 sub-steps of 5 minutes and one hour agree closely.
        p = self._p
        x = ms[DRY]
        dt_s = dt_h * _S_PER_H
        respiration = p.respiration_dry_per_s * p.respiration_q10 ** ((temp - p.respiration_ref_c) / _Q10_STEP_C)
        k1 = p.yield_factor * self._photosynthesis(x, climate) - respiration * x
        xm = max(0.0, x + k1 * dt_s / 2)
        k2 = p.yield_factor * self._photosynthesis(xm, climate) - respiration * xm
        ms[DRY] = max(0.0, x + k2 * dt_s)

        if batch.status == "ready":
            ms[READY_LOSS] += self._ready_loss_per_h * dt_h
        elif ms[DRY] >= self._ready_dry:
            batch.status = "ready"
            batch.ready_hour = climate.hour

    def estimate(self, batch: BatchState, hour: int, rng: Rng) -> BatchEstimate:
        """Weight with multiplicative noise and quality with additive noise, sigmas from
        the crop file, each from its own sub-stream of `rng` (so the same stream gives the
        same answer however often it is read). `days_to_ready` is how long the estimated
        weight takes to reach the ready weight if the published target climate is held.
        For kg-sold crops, `units` is the kg a cut would yield now."""
        noise = self.spec.estimate
        weight_g = max(0.0, self.fresh_weight_g(batch) * (1 + rng.stream("weight").normal(0.0, noise.weight_rel_sigma)))
        quality = min(1.0, max(0.0, self.quality(batch) + rng.stream("quality").normal(0.0, noise.quality_sigma)))
        days = self._days_to_ready(weight_g / self._fresh_g_per_dry_kg_m2) if batch.status == "growing" else None
        plants = self._density * batch.area_m2
        if self.spec.market.unit == "kg":
            cut_g = weight_g * (1 - (self.spec.cycle.regrow_fraction or 0.0))
            units, per_unit = cut_g * plants / _G_PER_KG, _G_PER_KG
        else:
            units, per_unit = plants, weight_g
        return BatchEstimate(fresh_weight_g_per_unit=per_unit, units=units, days_to_ready=days, quality=quality)

    def harvest(self, batch: BatchState, hour: int) -> HarvestResult:
        """Cut a growing or ready batch. Produce below the crop's minimum sellable
        weight per plant is returned with sellable=False (it sells for nothing).
        Single crops become 'harvested'. Repeated crops keep `regrow_fraction` of
        their weight and grow on as new leaves (stress and waiting loss reset) until
        `max_cuts`. `units` is heads, or kg for kg-sold crops, where
        `fresh_weight_g_per_unit` is then the grams in a kg."""
        if batch.status not in ("growing", "ready"):
            raise ValueError(f"batch {batch.id} is {batch.status} and cannot be harvested")
        cycle, ms = self.spec.cycle, batch.model_state
        quality = self.quality(batch)
        weight_g = self.fresh_weight_g(batch)
        plants = self._density * batch.area_m2
        if cycle.harvest_mode == "single":
            cut_g = weight_g
            batch.status = "harvested"
        else:
            cut_g = weight_g * (1 - cycle.regrow_fraction)
            ms[DRY] *= cycle.regrow_fraction
            batch.cuts += 1
            batch.status = "harvested" if batch.cuts >= cycle.max_cuts else "growing"
            batch.ready_hour = None
            ms[READY_LOSS] = 0.0
            for name in batch.stress:
                batch.stress[name] = 0.0
            ms[RGR_START_DRY] = ms[DRY]     # the growth-rate window restarts from the cut
            ms[RGR_H] = 0.0
        if self.spec.market.unit == "kg":
            units, per_unit = cut_g * plants / _G_PER_KG, _G_PER_KG
        else:
            units, per_unit = plants, cut_g
        market = self.spec.market
        sellable = cut_g >= market.min_sellable_fresh_weight_g
        # Unsellable produce is labelled with the lowest grade and priced at 0, whatever
        # that grade's factor (the schema does not force the lowest factor to 0).
        grade = market.grade(quality) if sellable else market.grades[-1]
        return HarvestResult(batch_id=batch.id, crop_id=batch.crop_id, units=units, unit=market.unit,
                             fresh_weight_g_per_unit=per_unit, quality=quality, sellable=sellable,
                             grade=grade.name, price_factor=grade.price_factor if sellable else 0.0)

    def transpiration_kg_h(self, batch: BatchState, climate: ClimateSample) -> float:
        if batch.status in ("harvested", "lost"):
            return 0.0
        tr = self._p.transpiration
        t = climate.temp_c
        saturation_kg_m3 = tr.vapour_c1_j_m3 / (tr.gas_constant_j_kmol_k * (t + tr.celsius_to_kelvin)) * \
            math.exp(tr.vapour_c2 * t / (t + tr.vapour_c3_c))
        deficit = saturation_kg_m3 * max(0.0, 1 - climate.rh_pct / _PCT)
        return self._cover(batch.model_state[DRY]) * tr.canopy_conductance_m_s * deficit * \
            batch.area_m2 * _S_PER_H

    def co2_uptake_kg_h(self, batch: BatchState, climate: ClimateSample) -> float:
        if batch.status in ("harvested", "lost"):
            return 0.0
        p = self._p
        x = batch.model_state[DRY]
        respiration = p.respiration_co2_per_s * x * \
            p.respiration_q10 ** ((climate.temp_c - p.respiration_ref_c) / _Q10_STEP_C)
        return (self._photosynthesis(x, climate) - respiration) * batch.area_m2 * _S_PER_H

    def labour_hours(self, action: Literal["plant", "harvest"], area_m2: float) -> float:
        """Worker-hours to plant or harvest `area_m2`, from the crop file's rate per 1000 plants."""
        planting = self.spec.planting
        if action == "plant":
            per_1000 = planting.plant_worker_hours_per_1000
        elif action == "harvest":
            per_1000 = planting.harvest_worker_hours_per_1000
        else:
            raise ValueError(f"labour_hours: action must be 'plant' or 'harvest', got {action!r}")
        return self._density * area_m2 / _PER_1000 * per_1000

    def seedlings_needed(self, area_m2: float) -> int:
        """Plants needed to fill `area_m2` at the crop file's density, rounded up."""
        return math.ceil(round(self._density * area_m2, _COUNT_DIGITS))

    def min_days_before_end(self) -> float:
        return float(self.spec.cycle.min_days_before_end)

    def describe(self) -> dict[str, Any]:
        """The crop file as published rules (spec 5, get_rules), plus the model's
        equations in words. Crop files hold no hidden parameters, so everything in
        the spec is public. Curves carry their kind name, as in the file."""
        out = _jsonable(dataclasses.asdict(self.spec))
        out["growth"]["temperature"] = _curve_json(self._p.temperature)
        out["stress"]["counters"] = [{"name": c.name, "signal": c.signal, **_curve_json(c.curve)}
                                     for c in self.spec.stress.counters]
        out["mechanics"] = _MECHANICS[self.spec.growth_model]
        return out

    # -- helpers for the simulator and views ---------------------------------------------

    def fresh_weight_g(self, batch: BatchState) -> float:
        """True fresh weight per plant, g."""
        return batch.model_state[DRY] * self._fresh_g_per_dry_kg_m2

    def quality(self, batch: BatchState) -> float:
        """True quality: 1 minus the stress counters and the waiting loss, clipped to 0..1."""
        return min(1.0, max(0.0, 1 - sum(batch.stress.values()) - batch.model_state[READY_LOSS]))

    # -- internals --------------------------------------------------------------------

    def _cover(self, x: float) -> float:
        return 1 - math.exp(-self._p.canopy_closure_m2_kg * x)

    def _photosynthesis(self, x: float, climate: ClimateSample) -> float:
        """Gross canopy CO2 assimilation, kg CO2 m-2 s-1."""
        p = self._p
        light = p.light_use_efficiency_kg_j * climate.par_umol_m2_s * p.radiation_j_per_umol
        if light <= 0:
            return 0.0
        t = climate.temp_c
        g_car = p.carboxylation_conductance_max_m_s * p.temperature(t)
        if g_car <= 0:
            return 0.0
        gamma = p.co2_compensation_kg_m3 * p.co2_compensation_q10 ** ((t - p.co2_compensation_ref_c) / _Q10_STEP_C)
        co2 = (min(climate.co2_ppm, p.co2_saturation_ppm) * p.co2_kg_m3_per_ppm - gamma) / (self._fixed_resistance + 1 / g_car)
        if co2 <= 0:
            return 0.0
        return self._cover(x) * light * co2 / (light + co2)

    def _grow_path_at_targets(self) -> list[float]:
        """Dry weight hour by hour from transplant to ready under `target_climate`, for
        `days_to_ready`. Kept as a running maximum (night respiration dips), so it is
        sorted and entry i is the most the crop has weighed by hour i. Growth depends only
        on the weight and the climate, so the same path serves regrowth after a cut.
        Stops early if a whole day adds nothing."""
        path = [self._transplant_dry]
        batch = BatchState(id="", crop_id=self.spec.id, compartment_id="", area_m2=1.0, planted_hour=0,
                           model_state={DRY: self._transplant_dry, RGR: 0.0, READY_LOSS: 0.0})
        self._open_day(batch.model_state, 0)
        hour, day_start = 0, self._transplant_dry
        while path[-1] < self._ready_dry:
            self.step(batch, target_climate(self.spec, hour, 1.0))
            if batch.status == "lost":
                break
            path.append(max(path[-1], batch.model_state[DRY]))
            hour += 1
            if hour % _H_PER_DAY == 0:
                if path[-1] <= day_start:
                    break
                day_start = path[-1]
        return path

    def _days_to_ready(self, dry: float) -> float | None:
        if dry >= self._ready_dry:
            return 0.0
        path = self._target_path
        if path[-1] < self._ready_dry:
            return None                  # the targets never make this crop ready
        return (len(path) - 1 - bisect.bisect_left(path, dry)) / _H_PER_DAY

    def _open_day(self, ms: dict[str, float], day: int) -> None:
        """Reset the day's accumulators; the day's first sample sets its minimum."""
        ms[DAY] = day
        ms[DAY_H] = ms[DAY_LIGHT] = ms[DAY_TEMP_SUM] = ms[DAY_LIT_H] = ms[DAY_TEMP_MIN] = ms[RGR_H] = 0.0
        ms[RGR_START_DRY] = ms[DRY]

    def _close_day(self, batch: BatchState) -> None:
        """Add each stress counter's curve of the finished day's signal, and record
        the day's relative growth rate. A partial day (the planting day) counts too."""
        ms = batch.model_state
        if ms[DAY_H] <= 0:
            return
        signals = {
            "dli_excess": ms[DAY_LIGHT],
            "temp_day_mean": ms[DAY_TEMP_SUM] / ms[DAY_LIT_H] if ms[DAY_LIT_H] > 0 else None,
            "temp_min": ms[DAY_TEMP_MIN],
        }
        stress = batch.stress
        for name, signal, curve in self._counters:
            value = signals[signal]
            if value is not None:
                stress[name] = stress.get(name, 0.0) + curve(value)
        if ms[RGR_H] > 0 and ms[RGR_START_DRY] > 0 and ms[DRY] > 0:
            ms[RGR] = math.log(ms[DRY] / ms[RGR_START_DRY]) * _H_PER_DAY / ms[RGR_H]


_CURVE_KINDS = {curves.Cardinal: "cardinal", curves.Saturating: "saturating", curves.LinearAbove: "linear_above",
                curves.LinearBelow: "linear_below", curves.Piecewise: "piecewise"}


def _curve_json(c: curves.Curve) -> dict[str, Any]:
    return {"curve": _CURVE_KINDS[type(c)], **_jsonable(dataclasses.asdict(c))}


def _jsonable(v: Any) -> Any:
    """Tuples become lists, so the result compares equal after a JSON round trip."""
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


# What each model does, for get_rules. Words only: every number is in the crop file.
_MECHANICS: dict[str, dict[str, str]] = {
    "leafy_vanhenten": {
        "growth": ("Van Henten (1994) one-state model. Canopy dry weight X (kg m-2) changes by "
                   "yield_factor * P - respiration_dry_per_s * X * respiration_q10^((T - respiration_ref_c)/10). "
                   "P = (1 - exp(-canopy_closure_m2_kg X)) * eps*I * g*(C - Gamma) / (eps*I + g*(C - Gamma)), "
                   "eps*I = light_use_efficiency_kg_j * PAR * radiation_j_per_umol, "
                   "g = 1/(1/boundary + 1/stomatal + 1/(carboxylation_max * temperature(T))), "
                   "C = min(CO2 ppm, co2_saturation_ppm) * co2_kg_m3_per_ppm, "
                   "Gamma = co2_compensation_kg_m3 * co2_compensation_q10^((T - co2_compensation_ref_c)/10). "
                   "Fresh weight per plant = X / dry_matter_fraction / density_per_m2."),
        "ready": "A batch is ready when fresh weight per plant reaches cycle.ready_fresh_weight_g.",
        "stress": ("At the end of each day every stress counter adds curve(signal of that day). Signals: "
                   "dli_excess = the day's light integral (mol m-2), temp_day_mean = mean temperature in "
                   "the photoperiod, temp_min = the day's lowest temperature. "
                   "Quality = 1 - sum of counters - ready_loss_per_day * days waiting ready, clipped to 0..1. "
                   "Below frost_kill_c the batch is lost at once."),
        "harvest": ("Below market.min_sellable.fresh_weight_g per plant (per cut for repeated crops) the "
                    "produce sells for nothing. Otherwise the grade is the first in market.grades whose "
                    "min_quality the quality reaches; revenue = units * market price * price_factor. "
                    "Single crops are then gone; repeated crops keep regrow_fraction of their weight, "
                    "reset stress and grow on, up to max_cuts."),
        "estimates": ("get_batches shows fresh weight with relative noise estimate.weight_rel_sigma and "
                      "quality with absolute noise estimate.quality_sigma; days_to_ready assumes the "
                      "midpoints of climate_targets."),
    },
}

MODELS: dict[str, type] = {"leafy_vanhenten": LeafyVanHenten}


def model_for(spec: CropSpec) -> GrowthModel:
    return MODELS[spec.growth_model](spec)
