"""CP-SAT solves ONLY the public instance, then acts through the common API."""
from importlib.metadata import version
from .types import EQUIPMENT, Instance, Schedule


def solve(instance: Instance) -> Schedule:
    from ortools.sat.python import cp_model
    model = cp_model.CpModel()
    starts, ends, intervals = {}, {}, {}
    for job in instance.jobs:
        starts[job.id] = model.new_int_var(0, instance.shift_end, f"start_{job.id}")
        ends[job.id] = model.new_int_var(0, min(job.deadline, instance.shift_end), f"end_{job.id}")
        intervals[job.id] = model.new_interval_var(starts[job.id], job.duration,
                                                  ends[job.id], job.id)
    for job in instance.jobs:
        for parent in job.prerequisites:
            model.add(ends[parent] <= starts[job.id])
    model.add_cumulative(list(intervals.values()), [j.technicians for j in instance.jobs],
                         instance.technician_capacity)
    for equipment in EQUIPMENT:
        model.add_no_overlap([intervals[j.id] for j in instance.jobs if j.equipment == equipment])
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_deterministic_time = 5.0
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"reference could not find an all-on-time schedule: {solver.status_name(status)}")
    return Schedule(tuple(sorted(((j.id, solver.value(starts[j.id])) for j in instance.jobs),
                                 key=lambda pair: (pair[1], pair[0]))),
                    solver.status_name(status), version("ortools"))


class ReferencePolicy:
    def __init__(self):
        self.schedule: Schedule | None = None

    def __call__(self, observation: dict) -> dict:
        instance = Instance.from_public(observation["instance"])
        if self.schedule is None:
            self.schedule = solve(instance)
        remaining = [(key, time) for key, time in self.schedule.starts if key not in observation["starts"]]
        if remaining:
            key, start = remaining[0]
            if start > observation["time"]:
                return {"tool": "advance", "to_time": start}
            return {"tool": "start_job", "job_id": key}
        if observation["running"]:
            return {"tool": "advance", "to_time": max(observation["running"].values())}
        return {"tool": "finish"}


def do_nothing(observation: dict) -> None:
    return None


def stop_early(observation: dict) -> dict:
    if observation["starts"]:
        return {"tool": "finish"}
    job = next(j for j in observation["instance"]["jobs"] if not j["prerequisites"])
    return {"tool": "start_job", "job_id": job["id"]}


def earliest_deadline(observation: dict) -> dict:
    """Simple public-data baseline, not a frontier agent."""
    ready = sorted(observation["instance"]["jobs"], key=lambda j: (j["deadline"], j["id"]))
    for job in ready:
        if job["id"] in observation["starts"] or not set(job["prerequisites"]) <= observation["completed"].keys():
            continue
        if job["technicians"] + observation["occupied_technicians"] > observation["instance"]["technician_capacity"]:
            continue
        if job["equipment"] in observation["occupied_equipment"]:
            continue
        return {"tool": "start_job", "job_id": job["id"]}
    if observation["running"]:
        return {"tool": "advance", "to_time": min(min(observation["running"].values()),
                                                  observation["instance"]["shift_end"])}
    return {"tool": "finish"}
