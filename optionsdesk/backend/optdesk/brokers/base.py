"""Abstract broker interface — the seam between the desk and any live venue."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..contracts import StrategySpec


class BrokerBase(ABC):
    """Minimal lifecycle every live/paper broker adapter must implement."""

    @abstractmethod
    def connect(self) -> bool:
        """Establish a session; return True on success."""

    @abstractmethod
    def is_connected(self) -> bool:
        """True if a live session is currently usable."""

    @abstractmethod
    def place(self, spec: StrategySpec, qty: int = 1) -> dict:
        """Submit an order for ``spec``; return a broker order/ack descriptor."""

    @abstractmethod
    def positions(self) -> list[dict]:
        """Return currently held positions as plain dicts."""

    @abstractmethod
    def account(self) -> dict:
        """Return an account summary (cash, net liq, buying power, ...)."""
