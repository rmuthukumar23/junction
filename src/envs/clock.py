"""A fixture for multi-window advances and bundled data files.

One window is one hour. `advance(hours)` runs up to `hours` hours itself and
stops early at the end of an hour in which an alarm fires (every `alarm_every`
hours), then asks the engine to close as many windows as it ran. Hours nobody
ran (after a stop) are run by `on_window_end`, in "unattended" mode. It is a
test fixture, not a task.
"""
from __future__ import annotations

import tomllib
from typing import Annotated, Any

from envkit.bundle import ROOT
from envkit.core import Environment, ToolError, tool


class Clock(Environment):
    builtin_tools = ()

    def setup(self) -> None:
        data = tomllib.loads((ROOT / self.config["data"]).read_text())
        self.alarm_every = int(data["alarm_every"])
        self.hour = 0
        self.log: list[tuple[int, str]] = []
        self.stopped = False

    @classmethod
    def data_files(cls, config: dict[str, Any]) -> list[str]:
        return [config["data"]]

    def _run_hour(self, mode: str) -> bool:
        self.log.append((self.hour, mode))
        self.hour += 1
        return self.hour % self.alarm_every == 0

    @tool(cost=0)
    def observe(self) -> dict[str, Any]:
        """The current hour. Free."""
        return {"hour": self.hour}

    @tool(cost=1)
    def advance(self, hours: Annotated[int, "1 to 24"]) -> dict[str, Any]:
        """Run up to `hours` hours; stops early after an alarm."""
        if not 1 <= hours <= 24:
            raise ToolError("hours must be 1 to 24", spend=False)
        left = self.shift.windows - self.hour
        ran, alarm = 0, False
        while ran < min(hours, left) and not alarm:
            alarm = self._run_hour("played")
            ran += 1
        self.close_windows(ran)
        return {"ran": ran, "alarm": alarm, "hour": self.hour}

    @tool(cost=0)
    def finish(self) -> dict[str, Any]:
        """Stop."""
        self.stopped = True
        return {}

    def on_window_end(self, window: int) -> None:
        if self.hour <= window:
            self._run_hour("unattended")

    def terminated(self) -> str | None:
        return "finish" if self.stopped else None

    def on_finish(self) -> None:
        while self.hour < self.shift.windows:
            self._run_hour("unattended")

    def ledger(self) -> dict[str, float | None]:
        return {"played": sum(m == "played" for _, m in self.log) / self.shift.windows}
