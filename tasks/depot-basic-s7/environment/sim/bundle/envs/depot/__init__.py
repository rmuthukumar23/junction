"""Depot: a deliberately small placeholder world.

It exists to exercise every part of the backend (hidden state, an operation
budget, scripted events on all three information channels, a ledger with a
business metric and a service rate, scripted policies of different strength).
Replace it with the real environment; nothing in `envkit` depends on it.
"""
from .world import Depot

__all__ = ["Depot"]
