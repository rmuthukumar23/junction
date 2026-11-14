"""Shift Planner served by the envkit backend.

The scheduling core stays the single authority on rules. Every request, valid
or not, is passed to `ShiftPlanner.step`, so action accounting, errors and
termination are exactly those of docs/SCENARIO.md. envkit supplies what
surrounds the core: the MCP tool surface, the action trace, replay-based
verification and the Harbor task.

The whole episode is one envkit window whose operation budget is the
instance's action limit.
"""
from typing import Annotated, Any

from envkit.core import Environment, ToolError, tool
from envkit.policies import Client, Policy

from .environment import ShiftPlanner
from .generator import generate
from .types import Instance
from .verifier import VerificationError, check_intervals


class ShiftPlannerEnv(Environment):
    builtin_tools = ()          # the contract has exactly four tools
    strict_arguments = True     # 2.0 and "2" are not integers

    def setup(self) -> None:
        public = self.config.get("instance")
        instance = (Instance.from_public(public) if public
                    else generate(self.rng.seed, int(self.config.get("jobs", 8))))
        if self.shift.windows != 1 or self.shift.ops_per_window != instance.action_limit:
            raise ValueError(f"[shift] must be windows = 1, ops_per_window = {instance.action_limit}")
        self.core = ShiftPlanner(instance)

    # -- the four contract tools -------------------------------------------------

    @tool(cost=0)
    def observe(self) -> dict[str, Any]:
        """Inspect all jobs, resources and current state. Does not consume an action."""
        return self.core.observe()

    @tool
    def start_job(self, job_id: Annotated[str, "ID of a pending job, as listed by observe."]) -> dict[str, Any]:
        """Start a pending job at current virtual time; no time passes. Cannot cancel it."""
        return self._step({"tool": "start_job", "job_id": job_id})

    @tool
    def advance(self, to_time: Annotated[int, "Target virtual time: later than now, at most shift_end."]) -> dict[str, Any]:
        """Advance strictly forward, at most to shift_end; process every intervening completion."""
        return self._step({"tool": "advance", "to_time": to_time})

    @tool
    def finish(self) -> dict[str, Any]:
        """End now. Only already completed, on-time jobs receive credit."""
        return self._step({"tool": "finish"})

    def _step(self, action: dict[str, Any]) -> dict[str, Any]:
        observation = self.core.step(action).observation
        if "error" in observation:
            raise ToolError(observation["error"])
        return observation

    # -- engine hooks --------------------------------------------------------------

    def on_invalid_call(self, name: str, args: Any) -> bool:
        # Invalid requests consume one action. Hand the request to the core so
        # its own counter and action-limit termination stay authoritative.
        action = {**args, "tool": name} if isinstance(args, dict) else {"tool": name, "arguments": args}
        if isinstance(args, dict) and "tool" in args:
            action["unexpected_tool_argument"] = args["tool"]
        if action == {"tool": "observe"}:
            return False
        self.core.step(action)
        return True

    def terminated(self) -> str | None:
        return self.core.termination if self.core.done else None

    def on_finish(self) -> None:
        self.core.interrupt("harness_interruption")  # no effect if already terminated

    def header(self) -> dict[str, Any]:
        return {"time": self.core.time, "shift_end": self.core.instance.shift_end,
                "actions_used": self.core.actions_used}

    def snapshot(self) -> dict[str, Any]:
        rows = []
        for job in self.core.instance.jobs:
            end = self.core.completed.get(job.id)
            rows.append({"job": job.id, "start": self.core.starts.get(job.id), "completion": end,
                         "deadline": job.deadline, "value": job.value,
                         "outcome": "unfinished" if end is None else "on time" if end <= job.deadline else "late"})
        return {"termination": self.core.termination, "time": self.core.time,
                "instance_hash": self.core.instance.digest, "table": rows}

    def ledger(self) -> dict[str, float | None]:
        core, instance = self.core, self.core.instance
        score = core.score()
        # Second, independent accounting from start times alone (no replay).
        if check_intervals(instance, core.starts, core.time) != score:
            raise VerificationError("interval accounting differs from the simulated score")
        on_time = sum(1 for key, end in core.completed.items() if end <= core.jobs[key].deadline)
        return {"score": score, "jobs_total": len(core.jobs), "jobs_on_time": on_time,
                "jobs_late": len(core.completed) - on_time, "jobs_unfinished": len(core.jobs) - len(core.completed),
                "actions_used": core.actions_used, "final_time": core.time}

    # -- scripted policies ---------------------------------------------------------

    @classmethod
    def policies(cls) -> dict[str, Any]:
        from .reference import ReferencePolicy, earliest_deadline, stop_early
        return {
            "reference": lambda: ContractPolicy(ReferencePolicy()),
            "earliest-deadline": lambda: ContractPolicy(earliest_deadline),
            "stop-early": lambda: ContractPolicy(stop_early),
            "absentee": lambda: ContractPolicy(lambda observation: {"tool": "finish"}),
        }

    @classmethod
    def fuzz_args(cls, tool_name: str, rng) -> dict[str, Any] | None:
        if tool_name == "start_job":
            return {"job_id": rng.choice([f"J{i:02d}" for i in range(1, 13)] + ["?"])}
        if tool_name == "advance":
            return {"to_time": rng.randint(0, 45)}
        return None


class ContractPolicy(Policy):
    """Runs an observation -> action policy (junction_env.contracts.Policy)
    through tool calls, so it plays over MCP exactly as it does in-process."""

    def __init__(self, decide):
        self.decide = decide

    def run(self, client: Client) -> None:
        observation = client.call("observe")["result"]
        for _ in range(observation["instance"]["action_limit"]):
            action = self.decide(observation)
            if action is None:
                return
            response = client.call(action["tool"], **{k: v for k, v in action.items() if k != "tool"})
            if client.done:
                return
            observation = response["result"] if response["ok"] else client.call("observe")["result"]
