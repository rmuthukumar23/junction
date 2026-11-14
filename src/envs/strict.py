"""A minimal strict-contract environment for the backend's own tests.

It exercises three switches a real contract can set and the greenhouse does
not: no built-in tools, exact JSON argument types, and invalid calls charged
against the operation budget. It is a test fixture, not a task.
"""
from __future__ import annotations

from typing import Annotated, Any

from envkit.core import Environment, ToolError, tool


class Counter(Environment):
    builtin_tools = ()
    strict_arguments = True

    def setup(self) -> None:
        self.time = 0
        self.stopped = False

    @tool(cost=0)
    def observe(self) -> dict[str, Any]:
        """The current time. Free; changes nothing."""
        return {"time": self.time}

    @tool()
    def advance(self, to_time: Annotated[int, "Target time, later than now."]) -> dict[str, Any]:
        """Move time forward to `to_time`."""
        if to_time <= self.time:
            raise ToolError("to_time must be later than now")
        self.time = to_time
        return {"time": self.time}

    @tool()
    def finish(self) -> dict[str, Any]:
        """Stop now."""
        self.stopped = True
        return {"time": self.time}

    def on_invalid_call(self, name: str, args: Any) -> bool:
        return True

    def terminated(self) -> str | None:
        return "finish" if self.stopped else None

    def ledger(self) -> dict[str, float | None]:
        return {"progress": min(1.0, self.time / 10.0)}
