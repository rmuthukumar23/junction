"""Scripted policies (spec 9). Every policy plays through the tool client only:
`client.call(tool, **args)` and `client.done`. None imports the simulator.

Owner: Rowan (naive, rule_based, exploiter); the reference is Max + Rowan.
Register them in `GreenhouseBench.policies()` (env.py, Max):

    from .policies.naive import Naive
    from .policies.rule_based import RuleBased
    from .policies.exploiter import EXPLOITS
    return {"naive": Naive, "rule-based": RuleBased, **EXPLOITS}

Numbers in these modules are the policy's own choices (how a scripted grower
behaves), not facts about the world: every world value is read from get_rules,
get_status, get_batches or get_forecast.
"""
