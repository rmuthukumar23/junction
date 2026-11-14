"""Immutable public scheduling contract; no solver or cloud dependencies."""
from dataclasses import asdict, dataclass
import hashlib
import json

GENERATOR_VERSION = "shift-v1"
EQUIPMENT = ("lathe", "bench")


@dataclass(frozen=True)
class Job:
    id: str
    duration: int
    technicians: int
    equipment: str | None
    prerequisites: tuple[str, ...]
    deadline: int
    value: int


@dataclass(frozen=True)
class Instance:
    seed: int
    jobs: tuple[Job, ...]
    shift_end: int
    technician_capacity: int = 2
    action_limit: int = 64
    generator_version: str = GENERATOR_VERSION

    def __post_init__(self):
        if type(self.seed) is not int:
            raise ValueError("seed must be an integer")
        for value in (self.shift_end, self.technician_capacity, self.action_limit):
            if type(value) is not int or value <= 0:
                raise ValueError("limits must be positive integers")
        ids = {j.id for j in self.jobs}
        if not self.jobs or len(ids) != len(self.jobs):
            raise ValueError("jobs must be nonempty with unique IDs")
        for j in self.jobs:
            if not isinstance(j.id, str) or not j.id:
                raise ValueError("job ID must be a nonempty string")
            if any(type(v) is not int or v <= 0 for v in
                   (j.duration, j.technicians, j.deadline, j.value)):
                raise ValueError("job numeric fields must be positive integers")
            if j.technicians > self.technician_capacity or j.equipment not in (*EQUIPMENT, None):
                raise ValueError("invalid resource requirement")
            if len(set(j.prerequisites)) != len(j.prerequisites) or not set(j.prerequisites) <= ids:
                raise ValueError("invalid prerequisites")
        remaining = {j.id: set(j.prerequisites) for j in self.jobs}
        while remaining:
            ready = {key for key, deps in remaining.items() if not deps}
            if not ready:
                raise ValueError("cyclic prerequisites")
            remaining = {k: v - ready for k, v in remaining.items() if k not in ready}

    def public(self) -> dict:
        # JSON roundtrip gives callers detached lists rather than internal tuples.
        return json.loads(json.dumps(asdict(self)))

    @property
    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.public(), sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()

    @classmethod
    def from_public(cls, data: dict) -> "Instance":
        values = dict(data)
        values["jobs"] = tuple(Job(**{**j, "prerequisites": tuple(j["prerequisites"])})
                               for j in values["jobs"])
        return cls(**values)


@dataclass(frozen=True)
class Schedule:
    starts: tuple[tuple[str, int], ...]
    status: str
    solver_version: str
