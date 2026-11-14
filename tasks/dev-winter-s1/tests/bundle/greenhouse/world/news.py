"""The news feed (spec 14.3). Owner: Rowan.

Headlines are drawn once, when the episode is built, from named streams `news/<id>/...`.
The feed is a pure function of the seed, the news files and the recorded series
(weather, gas prices) and of the storm hours, so every agent on a seed reads the same
feed and nothing it does can change it.

For each news file (`relates_to`):
  * `storm`: a real event is a storm of the storm event file (the first hour of a windy
    spell on the recorded wind);
  * `frost`: the first recorded hour below `frost_below_c`, at most one per `window_h`;
  * `gas_price`: an hour whose recorded gas price is at least `rise_fraction` above the
    price `window_h` earlier, at most one per `window_h`.
A real event gets a signal with probability `hit_rate`, published `lead_h` hours ahead
(drawn per signal, clamped to hour 0). False alarms are drawn per hour with probability
`false_alarms_per_day / 24`. A headline is picked from the file's list and names no
equipment, compartment or hour. `Feed.since(hour, days)` never returns a later headline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from envkit.rng import Rng

from ..config.market import NewsSpec
from ..contracts import Recorded


@dataclass(frozen=True)
class Headline:
    hour: int
    text: str
    news_id: str
    real: bool               # whether a real event follows; never shown to the agent


def real_events(spec: NewsSpec, storm_starts: Sequence[int], recorded: Recorded, horizon_h: int) -> list[int]:
    """Hours of the real events a news file warns about, on the recorded series."""
    if spec.relates_to == "storm":
        return [h for h in storm_starts if h < horizon_h]
    hours: list[int] = []
    last: int | None = None
    if spec.relates_to == "frost":
        for h, w in enumerate(recorded.weather[:horizon_h]):
            if w.temp_c < spec.frost_below_c and (last is None or h - last >= spec.window_h):
                hours.append(h)
                last = h
    else:
        price = recorded.gas_eur_per_m3[:horizon_h]
        for h in range(spec.window_h, len(price)):
            before = price[h - spec.window_h]
            if before > 0 and price[h] >= before * (1.0 + spec.rise_fraction) and (last is None or h - last >= spec.window_h):
                hours.append(h)
                last = h
    return hours


def build_feed(specs: Sequence[NewsSpec], storm_starts: Sequence[int], recorded: Recorded,
               horizon_h: int, rng: Rng) -> list[Headline]:
    feed: list[Headline] = []
    for spec in sorted(specs, key=lambda s: s.id):
        base = rng.stream(f"news/{spec.id}")
        for k, event_hour in enumerate(real_events(spec, storm_starts, recorded, horizon_h)):
            if not base.stream(f"hit/{k}").bernoulli(spec.hit_rate):
                continue
            lead = base.stream(f"lead/{k}").uniform(spec.lead_min_h, spec.lead_max_h)
            feed.append(Headline(max(0, event_hour - round(lead)),
                                 base.stream(f"headline/{k}").choice(spec.headlines), spec.id, True))
        false = base.stream("false_alarm")
        p = spec.false_alarms_per_day / 24.0
        for h in range(horizon_h):
            if false.bernoulli(p):
                feed.append(Headline(h, base.stream(f"false_headline/{h}").choice(spec.headlines), spec.id, False))
    feed.sort(key=lambda x: (x.hour, x.news_id, x.text))
    return feed


class Feed:
    def __init__(self, specs: Sequence[NewsSpec], storm_starts: Sequence[int], recorded: Recorded,
                 horizon_h: int, rng: Rng):
        self.specs = {s.id: s for s in specs}
        self.items = build_feed(specs, storm_starts, recorded, horizon_h, rng)

    def since(self, hour: int, days: float) -> list[dict[str, Any]]:
        """Headlines published in the last `days` days up to `hour` (oldest first), never later ones."""
        return [{"hour": x.hour, "day": x.hour // 24, "headline": x.text}
                for x in self.items if hour - 24 * days < x.hour <= hour]

    def rules(self) -> list[dict[str, Any]]:
        """Published signal types: how early, how reliable, how often wrong. Never the feed."""
        out = []
        for s in self.specs.values():
            row: dict[str, Any] = {"id": s.id, "relates_to": s.relates_to, "lead_h": [s.lead_min_h, s.lead_max_h],
                                   "hit_rate": s.hit_rate, "false_alarms_per_day": s.false_alarms_per_day}
            if s.relates_to == "frost":
                row["frost_below_c"] = s.frost_below_c
            elif s.relates_to == "gas_price":
                row.update(rise_fraction=s.rise_fraction, window_h=s.window_h)
            out.append(row)
        return out
