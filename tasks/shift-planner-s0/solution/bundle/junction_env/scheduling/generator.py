"""Feasible seeded instances constructed around a discarded witness schedule."""
import random
from .types import EQUIPMENT, Instance, Job


def generate(seed: int, job_count: int = 8) -> Instance:
    return generate_with_witness(seed, job_count)[0]


def generate_with_witness(seed: int, job_count: int = 8) -> tuple[Instance, dict[str, int]]:
    if type(seed) is not int or type(job_count) is not int or job_count not in (8, 10, 12):
        raise ValueError("integer seed and 8, 10, or 12 jobs required")
    rng = random.Random(seed)
    names = [f"J{i + 1:02d}" for i in range(job_count)]
    rng.shuffle(names)
    jobs, starts, ends = [], {}, {}
    for index, name in enumerate(names):
        duration = rng.randint(2, 6)
        technicians = rng.choices([1, 2], weights=[4, 1])[0]
        equipment = rng.choice([*EQUIPMENT, None])
        deps = tuple(sorted(rng.sample(names[:index], k=min(index, rng.choice([0, 1, 1, 2])))))
        start = max((ends[d] for d in deps), default=0)
        while True:
            overlapping = [j for j in jobs if starts[j.id] < start + duration and ends[j.id] > start]
            available = all(
                technicians + sum(j.technicians for j in overlapping
                                  if starts[j.id] <= t < ends[j.id]) <= 2
                for t in range(start, start + duration))
            equipment_free = equipment is None or all(j.equipment != equipment for j in overlapping)
            if available and equipment_free:
                break
            start += 1
        starts[name], ends[name] = start, start + duration
        jobs.append(Job(name, duration, technicians, equipment, deps,
                        ends[name] + rng.randint(0, 3), rng.randint(2, 10)))
    shift_end = max(j.deadline for j in jobs) + 2
    instance = Instance(seed, tuple(sorted(jobs, key=lambda j: j.id)), shift_end)
    return instance, starts
