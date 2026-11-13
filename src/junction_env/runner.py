"""Small deterministic local runner shared by tests and reference policies.

The official AfterQuery/Harbor harness remains the authority for final judging.
This runner never sends the policy anything except agent-visible observations.
"""

from dataclasses import dataclass

from .contracts import AgentEnvironment, JsonObject, Policy


@dataclass(frozen=True)
class Turn:
    observation: JsonObject
    action: JsonObject
    next_observation: JsonObject
    done: bool


@dataclass(frozen=True)
class EpisodeResult:
    seed: int
    score: float
    stop_reason: str
    turns: tuple[Turn, ...]


def run_episode(
    environment: AgentEnvironment,
    policy: Policy,
    *,
    seed: int,
    max_steps: int,
) -> EpisodeResult:
    if max_steps <= 0:
        raise ValueError("max_steps must be positive")
    observation = environment.reset(seed)
    turns: list[Turn] = []
    stop_reason = "step_limit"
    for _ in range(max_steps):
        action = policy(observation)
        if action is None:
            stop_reason = "policy_stop"
            break
        result = environment.step(action)
        turns.append(Turn(observation, action, result.observation, result.done))
        observation = result.observation
        if result.done:
            stop_reason = "environment_done"
            break
    score = environment.score()
    if not 0.0 <= score <= 1.0:
        raise ValueError("environment score must be in [0, 1]")
    return EpisodeResult(seed, score, stop_reason, tuple(turns))
