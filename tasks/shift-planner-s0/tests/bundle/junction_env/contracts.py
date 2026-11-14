"""Stable local contract. Adapt this to AfterQuery's official harness at the edge.

Observations and actions must be JSON-serializable. Do not expose hidden state
or scoring internals through an observation. `score()` is called after a run,
including early stops and timeouts; incomplete work must receive little credit.
"""

from dataclasses import dataclass
from typing import Protocol, TypeAlias

JsonObject: TypeAlias = dict[str, object]


@dataclass(frozen=True)
class StepResult:
    observation: JsonObject
    done: bool


class AgentEnvironment(Protocol):
    def reset(self, seed: int) -> JsonObject:
        """Start a deterministic episode and return the agent-visible observation."""

    def step(self, action: JsonObject) -> StepResult:
        """Apply one action. Invalid-action behavior belongs in scenario rules."""

    def score(self) -> float:
        """Return objective task performance in [0, 1], even if stopped early."""


class Policy(Protocol):
    def __call__(self, observation: JsonObject) -> JsonObject | None:
        """Choose an action, or return None to stop early."""
