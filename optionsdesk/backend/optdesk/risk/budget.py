"""
Portfolio-level risk budgeting / concentration control.

:class:`RiskBudget` takes a *desired* lot count from the sizer and trims it so a
new position respects the live book's limits:

  * total capital-at-risk <= ``portfolio_risk_frac`` of equity
  * single position       <= ``max_position_frac``
  * one underlying        <= ``per_ticker_frac``
  * one sector            <= ``per_sector_frac``
  * concurrency           <= ``max_concurrent``

It reads current exposure straight off the open positions (each exposes
``capital_at_risk`` and ``spec.ticker``), so no separate commit/release
bookkeeping is needed — budgeting is a pure function of the current book.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable

from ..contracts import StrategySpec
from .sizing import RiskConfig


@dataclass(slots=True)
class BudgetDecision:
    """Outcome of a sizing/budget evaluation (for transparency / UI)."""
    contracts: int
    unit_risk: float
    position_risk: float
    reason: str
    caps: dict = field(default_factory=dict)


class RiskBudget:
    """Applies concentration + total-risk caps to a desired position size."""

    def __init__(self, cfg: RiskConfig = RiskConfig(),
                 sector_of: Callable[[str], str] | dict[str, str] | None = None):
        self.cfg = cfg
        if isinstance(sector_of, dict):
            self._sector = lambda t: sector_of.get(t.upper(), "UNKNOWN")
        elif callable(sector_of):
            self._sector = sector_of
        else:
            self._sector = lambda t: "UNKNOWN"

    # ------------------------------------------------------------------ #
    def fit(self, spec: StrategySpec, desired: int, unit_risk: float,
            equity: float, open_positions: Iterable, *,
            explain: bool = False):
        """Trim ``desired`` lots to satisfy every cap; return final lots.

        With ``explain=True`` returns a :class:`BudgetDecision` instead of an int.
        """
        c = self.cfg
        positions = list(open_positions)

        if len(positions) >= c.max_concurrent or desired <= 0 or unit_risk <= 0:
            dec = BudgetDecision(0, unit_risk, 0.0,
                                 "concurrency_full" if positions and
                                 len(positions) >= c.max_concurrent else "no_size")
            return dec if explain else 0

        committed = sum(getattr(p, "capital_at_risk", 0.0) for p in positions)
        tk = spec.ticker.upper()
        sec = self._sector(tk)
        ticker_committed = sum(getattr(p, "capital_at_risk", 0.0) for p in positions
                               if p.spec.ticker.upper() == tk)
        sector_committed = sum(getattr(p, "capital_at_risk", 0.0) for p in positions
                               if self._sector(p.spec.ticker.upper()) == sec)

        remaining_portfolio = max(0.0, equity * c.portfolio_risk_frac - committed)
        per_position_cap = equity * c.max_position_frac
        ticker_remaining = max(0.0, equity * c.per_ticker_frac - ticker_committed)
        sector_remaining = max(0.0, equity * c.per_sector_frac - sector_committed)

        allowed_risk = min(remaining_portfolio, per_position_cap,
                           ticker_remaining, sector_remaining)
        max_by_risk = math.floor(allowed_risk / unit_risk)
        final = int(max(0, min(desired, max_by_risk, c.max_contracts)))

        if explain:
            binding = _binding_cap(
                desired, max_by_risk,
                {"portfolio": remaining_portfolio, "position": per_position_cap,
                 "ticker": ticker_remaining, "sector": sector_remaining}, unit_risk)
            return BudgetDecision(
                contracts=final, unit_risk=round(unit_risk, 2),
                position_risk=round(final * unit_risk, 2),
                reason="ok" if final >= desired else f"capped_by_{binding}",
                caps={
                    "remaining_portfolio": round(remaining_portfolio, 2),
                    "per_position_cap": round(per_position_cap, 2),
                    "ticker_remaining": round(ticker_remaining, 2),
                    "sector_remaining": round(sector_remaining, 2),
                    "desired": desired,
                },
            )
        return final


def _binding_cap(desired: int, max_by_risk: int, caps: dict, unit_risk: float) -> str:
    """Identify which cap limited the size (for the explain payload)."""
    if desired <= max_by_risk:
        return "none"
    return min(caps, key=lambda k: caps[k])
