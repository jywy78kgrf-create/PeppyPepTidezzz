"""
Position sizing.

A :class:`PositionSizer` turns a strategy proposal + account equity into a
*desired* contract count, using one of several money-management rules. The
portfolio-level caps (concentration, total risk budget) are applied separately
by :class:`optdesk.risk.budget.RiskBudget`, so sizing and budgeting compose:

    desired = sizer.desired_contracts(spec, equity, unit_risk)
    final   = budget.fit(spec, desired, unit_risk, equity, open_positions, sector_of)

`unit_risk` is the dollar risk of a **single** 1-lot of the structure (i.e.
``spec.max_loss``), with a sane fallback for undefined-risk structures.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Literal

from ..contracts import StrategySpec

SizingMethod = Literal["fixed", "fixed_fraction", "kelly", "risk_parity"]


@dataclass(slots=True)
class RiskConfig:
    """Money-management + risk-budgeting parameters.

    Sizing rules (``method``):
      * ``fixed``           — always ``fixed_contracts`` lots.
      * ``fixed_fraction``  — risk ``risk_per_trade`` of equity per position.
      * ``kelly``           — fractional Kelly from the trade's POP and reward:risk.
      * ``risk_parity``     — split the total risk budget evenly across slots.

    Portfolio caps (applied by RiskBudget) are fractions of current equity.
    """
    method: SizingMethod = "fixed_fraction"

    # per-trade sizing
    risk_per_trade: float = 0.02          # 2% of equity at risk per position
    kelly_fraction: float = 0.40          # fraction of full Kelly (safety)
    fixed_contracts: int = 1
    max_contracts: int = 100
    kelly_b_cap: float = 4.0              # cap reward:risk for undefined-profit trades

    # portfolio risk budget / concentration (fractions of equity)
    max_concurrent: int = 5
    portfolio_risk_frac: float = 0.30     # total capital-at-risk ceiling
    max_position_frac: float = 0.08       # single position ceiling
    per_ticker_frac: float = 0.12         # all positions in one underlying
    per_sector_frac: float = 0.40         # all positions in one sector

    # fallback when a structure's max_loss is non-positive / unbounded
    default_unit_risk_frac: float = 0.05  # treat as 5% of equity per lot

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "RiskConfig":
        if not d:
            return cls()
        fields = {f for f in cls.__slots__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in fields})


def unit_risk_for(spec: StrategySpec, equity: float, cfg: RiskConfig) -> float:
    """Dollar risk of a single 1-lot of ``spec`` (basis for sizing).

    Uses ``spec.max_loss`` when it is finite and positive; otherwise falls back
    to ``default_unit_risk_frac`` of equity so undefined-risk structures (e.g.
    naked short premium, covered calls marked stock-to-zero) still size sanely.
    """
    ml = spec.max_loss
    if ml is not None and math.isfinite(ml) and ml > 0:
        # guard pathological huge max_loss (stock-to-zero) against starving size
        cap = max(cfg.default_unit_risk_frac * equity, 1.0)
        return min(ml, max(cap, ml if ml < 5 * cap else cap))
    return max(cfg.default_unit_risk_frac * equity, 1.0)


class PositionSizer:
    """Computes a desired contract count from a sizing rule."""

    def __init__(self, cfg: RiskConfig = RiskConfig()):
        self.cfg = cfg

    def desired_contracts(self, spec: StrategySpec, equity: float,
                          unit_risk: float) -> int:
        """Desired lots for ``spec`` given ``equity`` and per-lot ``unit_risk``.

        Always clamped to ``[0, max_contracts]``. Returns 0 only when even a
        single lot would exceed the per-trade risk allowance under ``fixed``-free
        rules — the caller then skips the trade.
        """
        c = self.cfg
        if equity <= 0 or unit_risk <= 0:
            return 0

        if c.method == "fixed":
            n = c.fixed_contracts
        elif c.method == "risk_parity":
            slot_risk = equity * c.portfolio_risk_frac / max(1, c.max_concurrent)
            n = math.floor(slot_risk / unit_risk)
        elif c.method == "kelly":
            n = self._kelly(spec, equity, unit_risk)
        else:  # fixed_fraction (default)
            n = math.floor(equity * c.risk_per_trade / unit_risk)

        return int(max(0, min(n, c.max_contracts)))

    # ------------------------------------------------------------------ #
    def _kelly(self, spec: StrategySpec, equity: float, unit_risk: float) -> int:
        """Fractional-Kelly lots from POP and reward:risk.

        f* = (b·p − q) / b, with b = reward:risk, p = POP, q = 1−p. Negative
        edge -> 0. Scaled by ``kelly_fraction`` and converted to lots via the
        risk allowance ``f*·equity``.
        """
        c = self.cfg
        p = min(max(spec.pop, 0.0), 1.0)
        if p <= 0.0:
            # fall back to fixed-fraction when POP is unknown
            return math.floor(equity * c.risk_per_trade / unit_risk)
        q = 1.0 - p
        mp = spec.max_profit
        if mp is None or not math.isfinite(mp) or mp <= 0:
            b = c.kelly_b_cap
        else:
            b = min(c.kelly_b_cap, max(1e-6, mp / unit_risk))
        f_star = (b * p - q) / b
        f = max(0.0, f_star) * c.kelly_fraction
        if f <= 0.0:
            return 0
        return math.floor((f * equity) / unit_risk)
