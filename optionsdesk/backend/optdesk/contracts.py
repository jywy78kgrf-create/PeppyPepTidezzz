"""
Shared domain contracts for the ATLAS options desk.

Everything that crosses a subsystem boundary (data -> strategy -> backtest ->
learn -> paper -> api) is defined here so each subsystem can be built and
tested independently against a stable interface. No subsystem should invent
its own version of these types.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional


# --------------------------------------------------------------------------- #
# Instruments
# --------------------------------------------------------------------------- #
class OptionType(str, Enum):
    CALL = "C"
    PUT = "P"


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True, slots=True)
class OptionQuote:
    """A single option contract observed on a single date (full greeks)."""
    ticker: str
    asof: date
    expiry: date
    strike: float
    kind: OptionType
    bid: float
    ask: float
    last: float
    volume: int
    open_interest: int
    iv: float
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
    underlying: float  # underlying close on `asof`

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return 0.5 * (self.bid + self.ask)
        return self.last

    @property
    def spread(self) -> float:
        return max(0.0, self.ask - self.bid)

    @property
    def dte(self) -> int:
        return (self.expiry - self.asof).days


# --------------------------------------------------------------------------- #
# Strategies (a strategy = a named set of legs at construction time)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Leg:
    action: Action
    kind: OptionType
    strike: float
    expiry: date
    quantity: int = 1  # number of contracts (100 multiplier applied in engine)


@dataclass(slots=True)
class StrategySpec:
    """A concrete, tradeable proposal for one underlying on one date."""
    name: str            # e.g. "bull_put_spread"
    ticker: str
    asof: date
    legs: list[Leg]
    rationale: str = ""
    tags: list[str] = field(default_factory=list)
    # filled by the suggester / scorer
    score: float = 0.0
    expected_edge: float = 0.0
    max_loss: float = 0.0
    max_profit: float = 0.0
    pop: float = 0.0     # probability of profit (model estimate)
    meta: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Execution & accounting
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class Fill:
    asof: date
    action: Action
    kind: OptionType
    strike: float
    expiry: date
    quantity: int
    price: float          # per-share option price actually paid/received
    commission: float
    slippage: float       # modelled adverse fill vs mid, per share


@dataclass(slots=True)
class Trade:
    """A round-trip position from open to close (or expiry)."""
    spec_name: str
    ticker: str
    opened: date
    closed: Optional[date]
    open_fills: list[Fill]
    close_fills: list[Fill] = field(default_factory=list)
    pnl: float = 0.0              # net of all costs
    holding_cost: float = 0.0     # cost of carry on margin/debit
    gross_pnl: float = 0.0
    costs: float = 0.0            # commissions + slippage + holding
    closed_reason: str = ""       # "expiry" | "target" | "stop" | "delisted"


# --------------------------------------------------------------------------- #
# Cost model — the difference between a toy and a real backtest
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class CostModel:
    commission_per_contract: float = 0.65     # IBKR-ish
    exchange_fee_per_contract: float = 0.05
    slippage_frac_of_spread: float = 0.25     # fraction of bid/ask spread paid
    min_slippage: float = 0.01                # per share floor
    financing_apr: float = 0.065              # cost of carry on debit/margin
    borrow_apr: float = 0.0                   # short-stock borrow (assignment)
    assignment_fee: float = 0.0


# --------------------------------------------------------------------------- #
# Backtest results
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class EquityPoint:
    asof: date
    equity: float
    cash: float
    open_positions: int


@dataclass(slots=True)
class BacktestMetrics:
    start: Optional[date] = None
    end: Optional[date] = None
    n_trades: int = 0
    cagr: float = 0.0
    total_return: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_trade: float = 0.0
    total_costs: float = 0.0
    total_holding_cost: float = 0.0
    exposure: float = 0.0
    # survivorship transparency
    universe_size: int = 0
    delisted_included: int = 0
    survivorship_note: str = ""


@dataclass(slots=True)
class BacktestResult:
    config_name: str
    metrics: BacktestMetrics
    equity_curve: list[EquityPoint] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    params: dict = field(default_factory=dict)

    def to_summary(self) -> dict:
        m = self.metrics
        return {
            "config": self.config_name,
            "params": self.params,
            "start": m.start.isoformat() if m.start else None,
            "end": m.end.isoformat() if m.end else None,
            "n_trades": m.n_trades,
            "cagr": round(m.cagr, 4),
            "total_return": round(m.total_return, 4),
            "sharpe": round(m.sharpe, 3),
            "sortino": round(m.sortino, 3),
            "max_drawdown": round(m.max_drawdown, 4),
            "win_rate": round(m.win_rate, 4),
            "profit_factor": round(m.profit_factor, 3),
            "avg_trade": round(m.avg_trade, 2),
            "total_costs": round(m.total_costs, 2),
            "total_holding_cost": round(m.total_holding_cost, 2),
            "universe_size": m.universe_size,
            "delisted_included": m.delisted_included,
            "survivorship_note": m.survivorship_note,
        }


# --------------------------------------------------------------------------- #
# Learning loop
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class LearnIteration:
    iteration: int
    strategy: str
    params: dict
    oos_score: float           # out-of-sample objective (e.g. risk-adj return)
    is_score: float            # in-sample
    metrics: dict
    accepted: bool
    note: str = ""


@dataclass(slots=True)
class PaperPosition:
    ticker: str
    spec_name: str
    opened: datetime
    legs: list[dict]
    cost_basis: float
    current_value: float
    upnl: float
    status: str = "OPEN"
