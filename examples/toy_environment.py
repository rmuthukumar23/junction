"""Contract smoke test only. This is NOT the AfterQuery submission scenario.

The toy task verifies deterministic reset, multi-step interaction, a solvable
reference, and zero reward for doing nothing or stopping after inspection.
"""

from junction_env.contracts import JsonObject, StepResult
from junction_env.runner import run_episode


class ToyEnvironment:
    def __init__(self) -> None:
        self.target = 0
        self.turn = 0
        self.inspected = False
        self.correct = False
        self.done = False

    def reset(self, seed: int) -> JsonObject:
        self.target = seed % 2
        self.turn = 0
        self.inspected = False
        self.correct = False
        self.done = False
        return self._observation()

    def _observation(self, error: str | None = None) -> JsonObject:
        observation: JsonObject = {
            "goal": "Inspect the target, then commit its value within two turns.",
            "turns_left": 2 - self.turn,
            "actions": ["inspect", "commit"],
        }
        if self.inspected:
            observation["target"] = self.target
        if error:
            observation["error"] = error
        return observation

    def step(self, action: JsonObject) -> StepResult:
        if self.done:
            raise RuntimeError("episode is already over")
        self.turn += 1
        name = action.get("name")
        error = None
        if name == "inspect":
            self.inspected = True
        elif name == "commit":
            value = action.get("value")
            self.correct = self.inspected and type(value) is int and value == self.target
            self.done = True
        else:
            error = "invalid action; turn consumed"
        if self.turn >= 2:
            self.done = True
        return StepResult(self._observation(error), self.done)

    def score(self) -> float:
        return 1.0 if self.correct else 0.0


def reference(observation: JsonObject) -> JsonObject:
    if "target" not in observation:
        return {"name": "inspect"}
    return {"name": "commit", "value": observation["target"]}


def do_nothing(_observation: JsonObject) -> None:
    return None


def stop_early(observation: JsonObject) -> JsonObject | None:
    return {"name": "inspect"} if "target" not in observation else None


if __name__ == "__main__":
    scores = {
        "reference": run_episode(ToyEnvironment(), reference, seed=7, max_steps=2).score,
        "do_nothing": run_episode(ToyEnvironment(), do_nothing, seed=7, max_steps=2).score,
        "stop_early": run_episode(ToyEnvironment(), stop_early, seed=7, max_steps=2).score,
    }
    print(scores)
    assert scores == {"reference": 1.0, "do_nothing": 0.0, "stop_early": 0.0}
