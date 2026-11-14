"""Deterministic workshop simulation. Only the trusted harness calls reset."""
from copy import deepcopy
from junction_env.contracts import StepResult
from .generator import generate
from .types import EQUIPMENT, Instance


class ShiftPlanner:
    def __init__(self, instance: Instance | None = None, *, job_count: int = 8):
        self._provided = instance
        self.job_count = job_count
        self.reset(instance.seed if instance else 0)

    def reset(self, seed: int) -> dict:
        if self._provided and seed != self._provided.seed:
            raise ValueError("seed must match the supplied instance")
        self.instance = self._provided or generate(seed, self.job_count)
        self.jobs = {j.id: j for j in self.instance.jobs}
        self.time = 0
        self.starts: dict[str, int] = {}
        self.completed: dict[str, int] = {}
        self.actions_used = 0
        self.done = False
        self.termination: str | None = None
        self._history: list[dict] = []
        return self.observe()

    def observe(self) -> dict:
        running = {key: start + self.jobs[key].duration for key, start in self.starts.items()
                   if key not in self.completed}
        return {"instance": self.instance.public(), "instance_hash": self.instance.digest,
                "time": self.time, "starts": dict(self.starts), "completed": dict(self.completed),
                "running": running, "occupied_technicians": sum(self.jobs[k].technicians for k in running),
                "occupied_equipment": sorted({self.jobs[k].equipment for k in running
                                               if self.jobs[k].equipment is not None}),
                "equipment_capacity": {name: 1 for name in EQUIPMENT},
                "actions_used": self.actions_used, "done": self.done, "termination": self.termination}

    def interrupt(self, reason: str = "harness_interruption") -> None:
        if not self.done:
            self.done, self.termination = True, reason

    def step(self, action: dict) -> StepResult:
        snapshot = deepcopy(action)
        if self.done:
            return StepResult({**self.observe(), "error": "episode has terminated"}, True)
        if isinstance(action, dict) and action == {"tool": "observe"}:
            return StepResult(self.observe(), False)
        self.actions_used += 1
        error = self._apply(action)
        if not self.done and self.actions_used >= self.instance.action_limit:
            self.interrupt("action_limit")
        self._history.append({"action": snapshot, "error": error, "time": self.time})
        observation = self.observe()
        if error:
            observation["error"] = error
        return StepResult(observation, self.done)

    def _apply(self, action: dict) -> str | None:
        if not isinstance(action, dict):
            return "action must be an object"
        tool = action.get("tool")
        if not isinstance(tool, str):
            return "tool must be a string"
        if tool == "finish" and set(action) == {"tool"}:
            self.interrupt("finish")
            return None
        if tool == "advance" and set(action) == {"tool", "to_time"}:
            target = action["to_time"]
            if type(target) is not int or not self.time < target <= self.instance.shift_end:
                return "to_time must be an integer later than now and no later than shift_end"
            for key, start in sorted(self.starts.items(), key=lambda item: (item[1] + self.jobs[item[0]].duration, item[0])):
                end = start + self.jobs[key].duration
                if end <= target:
                    self.completed[key] = end
            self.time = target
            if len(self.completed) == len(self.jobs):
                self.interrupt("all_completed")
            elif target == self.instance.shift_end:
                self.interrupt("shift_end")
            return None
        if tool == "start_job" and set(action) == {"tool", "job_id"}:
            return self._start(action["job_id"])
        return "unknown tool or unexpected/missing arguments"

    def _start(self, job_id: object) -> str | None:
        if not isinstance(job_id, str) or job_id not in self.jobs:
            return "unknown job_id"
        if job_id in self.starts:
            return "job already started"
        job = self.jobs[job_id]
        if any(dep not in self.completed for dep in job.prerequisites):
            return "prerequisites must be completed"
        running = [self.jobs[k] for k in self.starts if k not in self.completed]
        if sum(j.technicians for j in running) + job.technicians > self.instance.technician_capacity:
            return "insufficient technicians"
        if job.equipment is not None and any(j.equipment == job.equipment for j in running):
            return "equipment is occupied"
        self.starts[job_id] = self.time
        return None

    def score(self) -> float:
        return sum(self.jobs[k].value for k, end in self.completed.items()
                   if end <= self.jobs[k].deadline) / sum(j.value for j in self.jobs.values())

    def record(self) -> dict:
        return {"schema_version": 1, "instance": self.instance.public(),
                "instance_hash": self.instance.digest, "history": deepcopy(self._history),
                "final": self.observe(), "score": self.score()}
