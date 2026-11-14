"""Root Cause: a greenhouse operations simulator.

Four tomato zones, fourteen days, limited fresh water. Each zone is a closed
recirculating loop in which useful nutrients and unwanted salts are separate
masses. Electrical conductivity (EC) measures their sum, so EC alone does not
say whether a zone needs fertilizer, fresh water, or nothing.

This is a transparent, simplified research simulator. It is not a validated
agronomic model and makes no prediction about a real farm. Every rule and
parameter is public to the player; see docs/GREENHOUSE.md.

  model       the public physics: parameters, response curves, one zone-day
  generator   seeded instances: zones, weather, forecasts, sensor noise
  sim         the simulator: plans, tests, daily update, accounting, report
  env         the envkit binding: the tools an agent or the browser calls
  policies    observation-only comparators: rule-based, stop-early
  planner     the reference: a receding-horizon planner over candidate plans
"""
from .model import Params
from .sim import Greenhouse, RuleError

__all__ = ["Greenhouse", "Params", "RuleError"]
