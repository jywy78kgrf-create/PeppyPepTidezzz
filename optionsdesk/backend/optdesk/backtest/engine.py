"""
Event-driven options backtester.

Walks every trading date in the store, opens one position per strategy signal,
manages each to a profit-target / stop-loss / close-DTE / expiry exit, marks
equity daily, and applies a realistic cost model (spread crossing, per-leg/side
commissions + exchange fees, and daily cost-of-carry on capital held).

Survivorship is handled explicitly: delisted tickers are *included*, and when
``store.is_active`` flips False a position is force-closed at intrinsic value
with reason ``"delisted"``. The resulting :class:`BacktestMetrics` records the
universe size, how many delisted names were traded, and a survivorship note.
"""
from __future__ import annotations

import math
from dataclasses import replace
from datetime import date

from ..config import SETTINGS
from ..contracts import (
    BacktestMetrics,
    BacktestResult,
    CostModel,
    EquityPoint,
    OptionQuote,
    StrategySpec,
    Trade,
)
from ..data.loader import ChainStore
from ..risk import PositionSizer, RiskBudget, RiskConfig, unit_risk_for
from ..strategies.library import STRATEGIES
from .portfolio import OpenPosition, Portfolio

TRADING_DAYS_PER_YEAR = 252

# Default management knobs (override via params).
_RUN_DEFAULTS: dict = {
    "profit_target": 0.50,    # capture 50% of credit / 50% gain on debit
    "stop_mult": 1.0,         # stop at 1x capital-at-risk adverse
    "close_dte": 7,           # roll/close when the near leg is <= this DTE
    "max_concurrent": 5,      # cap open positions across the whole book
    "signal_cooldown": 5,     # min trading days between new signals per ticker
    "min_dte_to_open": 14,    # don't open a structure with too little time
}


class Backtester:
    """Run a single strategy across a universe over a date range."""

    def __init__(self, store: ChainStore, cost_model: CostModel = CostModel(),
                 settings=SETTINGS):
        """Bind the data store, cost model, and settings (risk-free rate, capital)."""
        self.store = store
        self.cost = cost_model
        self.settings = settings
        self.r = settings.risk_free_apr

    # ------------------------------------------------------------------ #
    def run(self, strategy_name: str, params: dict, tickers: list[str],
            start: date, end: date, capital: float | None = None,
            risk: RiskConfig | dict | None = None) -> BacktestResult:
        """Backtest ``strategy_name`` over ``tickers`` within ``[start, end]``.

        ``risk`` selects the position-sizing rule and portfolio risk budget
        (see :class:`optdesk.risk.RiskConfig`); positions are sized to that
        budget instead of a flat 1 lot. Returns a :class:`BacktestResult` with a
        daily equity curve, round-trip trades, and survivorship-aware metrics.
        """
        if strategy_name not in STRATEGIES:
            raise KeyError(f"Unknown strategy '{strategy_name}'. "
                           f"Known: {sorted(STRATEGIES)}")
        builder = STRATEGIES[strategy_name]
        cfg = dict(_RUN_DEFAULTS)
        cfg.update(params or {})

        # Position sizing + portfolio risk budget.
        rc = risk if isinstance(risk, RiskConfig) else RiskConfig.from_dict(risk)
        rc.max_concurrent = cfg["max_concurrent"]
        sizer = PositionSizer(rc)
        budget = RiskBudget(rc, self._sector_map())
        cfg["risk"] = rc.to_dict()

        start, end = _as_date(start), _as_date(end)
        capital = float(capital if capital is not None else self.settings.starting_capital)
        pf = Portfolio(capital, self.cost, self.r, max_concurrent=cfg["max_concurrent"])

        # Union of trading dates across the (survivorship-complete) universe.
        all_dates = self._calendar(tickers, start, end)
        delisted_set = {t.upper() for t in self.store.delisted_tickers()}
        delisted_traded: set[str] = set()
        last_signal: dict[str, date] = {}

        equity_curve: list[EquityPoint] = []

        for day in all_dates:
            chains = self._chains_on(tickers, day)

            # 1) Force-close anything whose ticker just went inactive (delist).
            for pos in list(pf.open_positions):
                tk = pos.spec.ticker
                if not self.store.is_active(tk, day):
                    chain = chains.get(tk, [])
                    pf.accrue_carry(pos, day)
                    pf.close(pos, chain, day, reason="delisted", at_intrinsic=True,
                             underlying=pos.spec.meta.get("underlying"))

            # 2) Accrue carry and evaluate managed exits on survivors.
            for pos in list(pf.open_positions):
                chain = chains.get(pos.spec.ticker, [])
                pf.accrue_carry(pos, day)
                reason = self._exit_reason(pos, chain, day, cfg)
                if reason is not None:
                    at_intrinsic = reason == "expiry"
                    pf.close(pos, chain, day, reason=reason, at_intrinsic=at_intrinsic)

            # 3) Generate new signals (one per ticker per cooldown window).
            cur_equity = pf.equity(chains, day)  # sizing basis for today
            for tk in tickers:
                if not pf.can_open():
                    break
                if not self.store.is_active(tk, day):
                    continue
                chain = chains.get(tk)
                if not chain:
                    continue
                last = last_signal.get(tk)
                if last is not None and (day - last).days < cfg["signal_cooldown"]:
                    continue
                if any(p.spec.ticker == tk for p in pf.open_positions):
                    continue
                spec = self._build(builder, chain, params or {}, cfg)
                if spec is None:
                    continue
                # Size the position to the risk budget, then scale the legs.
                unit_risk = unit_risk_for(spec, cur_equity, rc)
                desired = sizer.desired_contracts(spec, cur_equity, unit_risk)
                qty = budget.fit(spec, desired, unit_risk, cur_equity, pf.open_positions)
                if qty < 1:
                    continue
                spec = _scale_spec(spec, qty, unit_risk)
                opened = pf.open(spec, chain, day, cfg["profit_target"], cfg["stop_mult"])
                if opened is not None:
                    last_signal[tk] = day
                    if tk.upper() in delisted_set:
                        delisted_traded.add(tk.upper())

            # 4) Mark equity for the day.
            eq = pf.equity(chains, day)
            equity_curve.append(EquityPoint(asof=day, equity=round(eq, 2),
                                            cash=round(pf.cash, 2),
                                            open_positions=len(pf.open_positions)))

        # 5) Final liquidation at the last date's intrinsic for anything still open.
        if all_dates:
            last_day = all_dates[-1]
            chains = self._chains_on(tickers, last_day)
            for pos in list(pf.open_positions):
                chain = chains.get(pos.spec.ticker, [])
                pf.accrue_carry(pos, last_day)
                pf.close(pos, chain, last_day, reason="end", at_intrinsic=True)
            if equity_curve:
                equity_curve[-1] = EquityPoint(
                    asof=last_day, equity=round(pf.cash, 2), cash=round(pf.cash, 2),
                    open_positions=0)

        metrics = compute_metrics(
            equity_curve, pf.trades, capital=capital,
            universe_size=len(tickers),
            delisted_included=len(delisted_traded),
            tickers=tickers, store=self.store,
        )
        return BacktestResult(
            config_name=strategy_name, metrics=metrics,
            equity_curve=equity_curve, trades=pf.trades, params=cfg,
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _sector_map(self) -> dict[str, str]:
        """ticker -> sector from the universe (for concentration limits)."""
        u = self.store.universe
        if u is None or u.empty or "sector" not in u or "ticker" not in u:
            return {}
        out: dict[str, str] = {}
        for _, row in u.iterrows():
            tk = row.get("ticker")
            if isinstance(tk, str):
                out[tk.upper()] = str(row.get("sector") or "UNKNOWN")
        return out

    def _calendar(self, tickers: list[str], start: date, end: date) -> list[date]:
        """Sorted union of in-range trading dates across all tickers."""
        days: set[date] = set()
        for tk in tickers:
            try:
                for d in self.store.trading_dates(tk):
                    if start <= d <= end:
                        days.add(d)
            except FileNotFoundError:
                continue
        return sorted(days)

    def _chains_on(self, tickers: list[str], day: date) -> dict[str, list[OptionQuote]]:
        """Map ticker -> chain snapshot on ``day`` (empty if none)."""
        out: dict[str, list[OptionQuote]] = {}
        for tk in tickers:
            try:
                out[tk] = self.store.chain(tk, day)
            except FileNotFoundError:
                out[tk] = []
        return out

    def _build(self, builder, chain: list[OptionQuote], params: dict,
               cfg: dict) -> StrategySpec | None:
        """Build a spec, rejecting structures with too little time to expiry."""
        spec = builder(chain, _underlying(chain), params)
        if spec is None:
            return None
        min_dte = min((l.expiry - spec.asof).days for l in spec.legs)
        if min_dte < cfg["min_dte_to_open"]:
            return None
        return spec

    def _exit_reason(self, pos: OpenPosition, chain: list[OptionQuote], day: date,
                     cfg: dict) -> str | None:
        """Decide whether/why to close a position today.

        Order of precedence: expiry -> close-DTE -> profit target -> stop.
        """
        near_dte = min((l.expiry - day).days for l in pos.spec.legs)
        if near_dte <= 0:
            return "expiry"
        mark = pos.spec  # alias for readability below
        value = _position_mark(pos, chain, day, self.r)
        entry_credit = sum(_signed_open(pos))
        if near_dte <= cfg["close_dte"]:
            return "close_dte"
        if entry_credit > 0:  # credit structure: profit as buyback value shrinks
            if value <= pos.target_value:
                return "target"
            if value <= pos.stop_value:
                return "stop"
        else:  # debit structure: profit as asset value rises
            if value >= pos.target_value:
                return "target"
            if value <= pos.stop_value:
                return "stop"
        return None


# --------------------------------------------------------------------------- #
# Module-level helpers
# --------------------------------------------------------------------------- #
def _underlying(chain: list[OptionQuote]) -> float:
    """Underlying price from a chain snapshot."""
    return next((q.underlying for q in chain if q.underlying > 0), 0.0)


def _scale_spec(spec: StrategySpec, qty: int, unit_risk: float) -> StrategySpec:
    """Scale a 1-lot spec to ``qty`` contracts (legs + max P&L), recording size.

    Multiplies every leg's quantity and the per-lot max_loss/max_profit so the
    portfolio's capital-at-risk, carry, and exit thresholds all scale coherently.
    """
    spec.legs = [replace(leg, quantity=leg.quantity * qty) for leg in spec.legs]
    if math.isfinite(spec.max_loss):
        spec.max_loss *= qty
    if math.isfinite(spec.max_profit):
        spec.max_profit *= qty
    spec.meta = {**spec.meta, "contracts": qty, "unit_risk": round(unit_risk, 2),
                 "position_risk": round(qty * unit_risk, 2)}
    return spec


def _signed_open(pos: OpenPosition) -> list[float]:
    """Per-leg signed open premium (SELL +, BUY -), x100."""
    from .portfolio import _premium_signed
    return [_premium_signed(f) for f in pos.open_fills]


def _position_mark(pos: OpenPosition, chain: list[OptionQuote], day: date,
                   r: float) -> float:
    """Signed liquidation mark (x100) of a position's legs today."""
    from ..quant.pricing import mark_leg, CONTRACT_MULTIPLIER
    u = _underlying(chain) or pos.spec.meta.get("underlying", 0.0)
    return sum(mark_leg(l, chain, day, u, r) * CONTRACT_MULTIPLIER for l in pos.spec.legs)


def _as_date(d: date | str) -> date:
    """Coerce ISO strings to ``date``."""
    if isinstance(d, str):
        from datetime import datetime
        return datetime.strptime(d, "%Y-%m-%d").date()
    return d


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def compute_metrics(equity_curve: list[EquityPoint], trades: list[Trade], *,
                    capital: float, universe_size: int = 0,
                    delisted_included: int = 0, tickers: list[str] | None = None,
                    store: ChainStore | None = None) -> BacktestMetrics:
    """Summarise an equity curve and trade list into :class:`BacktestMetrics`.

    Sharpe/Sortino are annualised from daily equity returns. All ratios guard
    against divide-by-zero. Survivorship transparency fields are populated from
    the universe/delisted inputs.
    """
    m = BacktestMetrics()
    if not equity_curve:
        m.survivorship_note = _survivorship_note(delisted_included, universe_size, store)
        m.universe_size = universe_size
        m.delisted_included = delisted_included
        return m

    m.start = equity_curve[0].asof
    m.end = equity_curve[-1].asof
    m.n_trades = len(trades)
    m.universe_size = universe_size
    m.delisted_included = delisted_included

    equities = [p.equity for p in equity_curve]
    start_eq = capital if capital > 0 else (equities[0] or 1.0)
    end_eq = equities[-1]
    m.total_return = (end_eq / start_eq) - 1.0 if start_eq else 0.0

    # Daily simple returns.
    rets: list[float] = []
    for i in range(1, len(equities)):
        prev = equities[i - 1]
        rets.append((equities[i] - prev) / prev if prev else 0.0)

    n_days = len(equity_curve)
    years = max((m.end - m.start).days / 365.25, 1e-9)
    if start_eq > 0 and end_eq > 0:
        m.cagr = (end_eq / start_eq) ** (1.0 / years) - 1.0
    else:
        m.cagr = 0.0

    if rets:
        mean = sum(rets) / len(rets)
        var = sum((x - mean) ** 2 for x in rets) / len(rets)
        std = math.sqrt(var)
        downside = [x for x in rets if x < 0.0]
        d_var = sum(x * x for x in downside) / len(rets) if downside else 0.0
        d_std = math.sqrt(d_var)
        ann = math.sqrt(TRADING_DAYS_PER_YEAR)
        m.sharpe = (mean / std) * ann if std > 1e-12 else 0.0
        m.sortino = (mean / d_std) * ann if d_std > 1e-12 else 0.0

    # Max drawdown on the equity curve.
    peak = equities[0]
    max_dd = 0.0
    for e in equities:
        peak = max(peak, e)
        if peak > 0:
            dd = (e - peak) / peak
            max_dd = min(max_dd, dd)
    m.max_drawdown = max_dd

    # Trade stats.
    if trades:
        wins = [t for t in trades if t.pnl > 0]
        gross_win = sum(t.pnl for t in wins)
        gross_loss = -sum(t.pnl for t in trades if t.pnl < 0)
        m.win_rate = len(wins) / len(trades)
        m.profit_factor = (gross_win / gross_loss) if gross_loss > 1e-12 else (
            float("inf") if gross_win > 0 else 0.0)
        m.avg_trade = sum(t.pnl for t in trades) / len(trades)
        m.total_costs = sum(t.costs for t in trades)
        m.total_holding_cost = sum(t.holding_cost for t in trades)

    # Exposure: fraction of days with at least one open position.
    exposed = sum(1 for p in equity_curve if p.open_positions > 0)
    m.exposure = exposed / n_days if n_days else 0.0

    m.survivorship_note = _survivorship_note(delisted_included, universe_size, store)
    return m


def _survivorship_note(delisted_included: int, universe_size: int,
                       store: ChainStore | None) -> str:
    """Human-readable survivorship statement for the metrics block."""
    total_delisted = len(store.delisted_tickers()) if store is not None else delisted_included
    return (f"Survivorship-bias-free: {universe_size} tickers backtested including "
            f"{delisted_included} delisted name(s) traded ({total_delisted} delisted in "
            f"universe). Delisted positions force-closed at intrinsic on the delist date.")
