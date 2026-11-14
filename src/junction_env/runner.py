"""Local runner; the external harness is responsible for wall-clock enforcement."""
from copy import deepcopy
from dataclasses import dataclass
import math
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
    score: float | None
    stop_reason: str
    turns: tuple[Turn, ...]
    status: str = "completed"
    error: str | None = None


def run_episode(environment: AgentEnvironment, policy: Policy, *, seed: int,
                max_steps: int) -> EpisodeResult:
    if type(max_steps) is not int or max_steps <= 0:
        raise ValueError("max_steps must be a positive integer")
    turns: list[Turn] = []
    reason, status, error = "step_limit", "interrupted", None
    try:
        observation = deepcopy(environment.reset(seed))
        for _ in range(max_steps):
            before = deepcopy(observation)
            try:
                action = policy(deepcopy(before))
            except Exception as exc:
                reason = "policy_timeout" if isinstance(exc, TimeoutError) else "policy_error"
                error = f"{type(exc).__name__}: {exc}"
                break
            if action is None:
                reason = "policy_stop"
                break
            saved_action = deepcopy(action)
            result = environment.step(deepcopy(saved_action))
            observation = deepcopy(result.observation)
            turns.append(Turn(before, saved_action, deepcopy(observation), result.done))
            if result.done:
                reason, status = "environment_done", "completed"
                break
        interrupt = getattr(environment, "interrupt", None)
        if status == "interrupted" and callable(interrupt):
            interrupt(reason)
        score = environment.score()
        if not isinstance(score, (float, int)) or isinstance(score, bool) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("environment score must be finite and in [0, 1]")
    except Exception as exc:
        return EpisodeResult(seed, None, "infrastructure_error", tuple(turns),
                             "infrastructure_failure", f"{type(exc).__name__}: {exc}")
    return EpisodeResult(seed, float(score), reason, tuple(turns), status, error)
