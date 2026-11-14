"""Deterministic random streams.

Two rules make an environment reproducible:

1. Every random draw comes from an `Rng`, never from `random`, `time`, `os`
   or hash ordering.
2. Independent processes use independent named streams. Draw customer demand
   from `rng.stream("demand")` and supplier noise from `rng.stream("supply")`,
   so that an agent's extra tool call cannot shift the demand it will face.

Only `random.Random.random()` is used underneath. It is the one method whose
output Python guarantees to be stable across versions, so a trace recorded on
one interpreter replays identically on another.
"""
from __future__ import annotations

import hashlib
import math
import random
from typing import Sequence, TypeVar

T = TypeVar("T")


class Rng:
    def __init__(self, seed: int, name: str = "root"):
        self.seed = int(seed)
        self.name = name
        digest = hashlib.sha256(f"{self.seed}/{name}".encode()).digest()
        self._r = random.Random(int.from_bytes(digest[:8], "big"))

    def stream(self, name: str) -> "Rng":
        """An independent stream, a pure function of (seed, path of names)."""
        return Rng(self.seed, f"{self.name}/{name}")

    # -- draws ---------------------------------------------------------------

    def random(self) -> float:
        """Uniform in [0, 1)."""
        return self._r.random()

    def uniform(self, a: float, b: float) -> float:
        return a + (b - a) * self.random()

    def randint(self, a: int, b: int) -> int:
        """Uniform integer in [a, b], both ends included."""
        if b < a:
            raise ValueError("randint: b < a")
        return a + min(b - a, int(self.random() * (b - a + 1)))

    def bernoulli(self, p: float) -> bool:
        return self.random() < p

    def choice(self, items: Sequence[T]) -> T:
        if not items:
            raise ValueError("choice from an empty sequence")
        return items[self.randint(0, len(items) - 1)]

    def weighted_choice(self, items: Sequence[T], weights: Sequence[float]) -> T:
        total = float(sum(weights))
        if total <= 0:
            raise ValueError("weights must sum to a positive number")
        x = self.random() * total
        acc = 0.0
        for item, w in zip(items, weights):
            acc += w
            if x < acc:
                return item
        return items[-1]

    def shuffled(self, items: Sequence[T]) -> list[T]:
        out = list(items)
        for i in range(len(out) - 1, 0, -1):
            j = self.randint(0, i)
            out[i], out[j] = out[j], out[i]
        return out

    def normal(self, mu: float = 0.0, sigma: float = 1.0) -> float:
        u1 = 1.0 - self.random()  # (0, 1], so log is finite
        u2 = self.random()
        return mu + sigma * math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)

    def poisson(self, lam: float) -> int:
        if lam <= 0:
            return 0
        if lam > 30:
            return max(0, int(round(self.normal(lam, math.sqrt(lam)))))
        limit, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= self.random()
            if p <= limit:
                return k
            k += 1
