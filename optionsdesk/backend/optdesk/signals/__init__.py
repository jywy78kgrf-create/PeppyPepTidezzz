"""Equity-derived entry signals (trend / realized-vol regime gating)."""
from .equity import SignalGate, build_default_gate, indicator_frame

__all__ = ["SignalGate", "build_default_gate", "indicator_frame"]
