"""
Realism-semantics tests for the backtest engine (Phase 2, Agent A).

Self-contained (hand-built FakeStore with known dates/quotes — no files, no
sample data). Covers the contract's "New engine semantics":

  * fill_lag DEFAULT 1: a signal on day D fills on the NEXT trading day for
    that ticker at THAT day's quotes; a signal on the last trading day never
    fills; the signal is abandoned when a leg is unquotable at fill time or
    the structure has decayed below min_dte_to_open. fill_lag=0 keeps the old
    same-day behavior.
  * Early assignment: a short ITM leg whose market extrinsic (mid - intrinsic)
    is below assign_extrinsic closes the WHOLE position with reason
    "assigned" (assigned leg at intrinsic, others at market) and charges
    CostModel.assignment_fee per assigned contract.
  * Reg-T-style margin_requirement(): naked shorts get
    premium + max(0.20*U - OTM, 0.10*U calls / 0.10*K puts); defined-risk
    spreads keep width - credit. Used as capital_at_risk for credit structures.
  * BacktestMetrics.closed_reasons histogram: counts sum to n_trades and the
    dict is included in to_summary().
  * Signal-gate hook: lazily imported, ImportError-tolerant, honours
    use_signals, and vetoes signal generation per (ticker, day, strategy).
"""
from __future__ import annotations

import sys
import types
from datetime import date, timedelta

import pytest

from optdesk.backtest.engine import Backtester
from optdesk.backtest.portfolio import Portfolio, margin_requirement
from optdesk.contracts import (
    Action,
    CostModel,
    Fill,
    Leg,
    OptionQuote,
    OptionType,
    StrategySpec,
)

C, P = OptionType.CALL, OptionType.PUT
R = 0.045


# --------------------------------------------------------------------------- #
# Helpers: synthetic quotes / chains / store (mirrors test_quant_backtest.py)
# --------------------------------------------------------------------------- #
def q(ticker: str, asof: date, expiry: date, strike: float, kind: OptionType,
      mid: float, underlying: float, delta: float, *, bid: float | None = None,
      ask: float | None = None, oi: int = 1000, volume: int = 100,
      iv: float = 0.30) -> OptionQuote:
    if bid is None:
        bid = round(max(0.01, mid - 0.05), 4)
    if ask is None:
        ask = round(mid + 0.05, 4)
    return OptionQuote(ticker=ticker, asof=asof, expiry=expiry, strike=strike,
                       kind=kind, bid=bid, ask=ask, last=mid, volume=volume,
                       open_interest=oi, iv=iv, delta=delta, gamma=0.0,
                       theta=0.0, vega=0.0, rho=0.0, underlying=underlying)


class FakeStore:
    """Minimal ChainStore stand-in: {ticker: {date: chain}} plus delist dates."""

    def __init__(self, chains: dict[str, dict[date, list[OptionQuote]]],
                 delisted: dict[str, date] | None = None):
        self._chains = chains
        self._delisted = delisted or {}

    def trading_dates(self, ticker: str):
        if ticker not in self._chains:
            raise FileNotFoundError(ticker)
        return sorted(self._chains[ticker])

    def chain(self, ticker: str, asof: date):
        if ticker not in self._chains:
            raise FileNotFoundError(ticker)
        return self._chains[ticker].get(asof, [])

    def is_active(self, ticker: str, asof: date) -> bool:
        d = self._delisted.get(ticker)
        return d is None or asof <= d

    def delisted_tickers(self):
        return sorted(self._delisted)

    @property
    def universe(self):
        return None


D0 = date(2023, 6, 1)          # Thu
D1 = date(2023, 6, 2)          # Fri
D2 = date(2023, 6, 5)          # Mon
D3 = date(2023, 6, 6)          # Tue
EXP = D0 + timedelta(days=40)  # plenty of DTE so close_dte never interferes

# Per-share slippage on the standard 0.10-wide synthetic market:
# max(min_slippage=0.01, 0.25 * 0.10) = 0.025.
SLIP = 0.025

BASE_PARAMS = {
    "profit_target": 0.50,
    "stop_mult": 1.0,
    "close_dte": 7,
    "signal_cooldown": 100,   # one signal per ticker per run
    "min_dte_to_open": 14,
    "min_open_interest": 1,
    "use_signals": False,     # gate behavior is tested explicitly below
    # NOTE: fill_lag deliberately NOT set — the engine default (1) must apply.
}
RISK_1LOT = {"method": "fixed", "fixed_contracts": 1}


def put_chain(tk: str, day: date, u: float, mid90: float, mid80: float):
    """Two-strike put chain (raw material for a bull put spread)."""
    return [
        q(tk, day, EXP, 90.0, P, mid90, u, -0.30),
        q(tk, day, EXP, 80.0, P, mid80, u, -0.16),
    ]


def run_engine(store, strategy, tickers, start, end, params=None, cost=None):
    # hand-computed price expectations in this file assume the flat model
    bt = Backtester(store, cost or CostModel(dynamic_slippage=False))
    p = dict(BASE_PARAMS)
    p.update(params or {})
    return bt.run(strategy, p, tickers, start, end, capital=100_000.0,
                  risk=dict(RISK_1LOT))


def assert_identity(res, capital=100_000.0, tol=0.02):
    """starting capital + sum(trade pnl) == final equity after liquidation."""
    assert res.equity_curve, "expected a non-empty equity curve"
    assert res.equity_curve[-1].open_positions == 0
    total_pnl = sum(t.pnl for t in res.trades)
    assert capital + total_pnl == pytest.approx(res.equity_curve[-1].equity, abs=tol)


# --------------------------------------------------------------------------- #
# 1) T+1 fills (fill_lag default 1)
# --------------------------------------------------------------------------- #
class TestFillLag:
    def test_signal_fills_next_trading_day_at_that_days_quotes(self):
        """Signal on D0 -> fill on D1, priced from D1's (different) quotes."""
        chains = {"CRD": {
            D0: put_chain("CRD", D0, 100.0, 2.00, 0.80),   # signal day quotes
            D1: put_chain("CRD", D1, 100.0, 3.00, 1.00),   # fill day quotes
            D2: put_chain("CRD", D2, 100.0, 3.00, 1.00),
            D3: put_chain("CRD", D3, 100.0, 3.00, 1.00),
        }}
        res = run_engine(FakeStore(chains), "bull_put_spread", ["CRD"], D0, D3)
        assert len(res.trades) == 1
        t = res.trades[0]
        assert t.opened == D1, "T+1 fill must land on the next trading day"
        # Legs re-located by strike/expiry and priced from D1's market:
        # sell 90P at 3.00 mid - slip, buy 80P at 1.00 mid + slip.
        px = {f.strike: f.price for f in t.open_fills}
        assert px[90.0] == pytest.approx(3.00 - SLIP)
        assert px[80.0] == pytest.approx(1.00 + SLIP)
        assert_identity(res)

    def test_fill_waits_for_the_tickers_next_trading_day(self):
        """CRD prints no chain on D1 (calendar kept alive by another ticker):
        the D0 signal fills on CRD's next trading day, D2."""
        chains = {
            "CRD": {
                D0: put_chain("CRD", D0, 100.0, 2.00, 0.80),
                # no chain on D1
                D2: put_chain("CRD", D2, 100.0, 2.00, 0.80),
                D3: put_chain("CRD", D3, 100.0, 2.00, 0.80),
            },
            # illiquid survivor keeps D1 in the union calendar, never trades
            "OTH": {d: [q("OTH", d, EXP, 90.0, P, 1.0, 100.0, -0.3, oi=0)]
                    for d in (D0, D1, D2, D3)},
        }
        res = run_engine(FakeStore(chains), "bull_put_spread", ["CRD", "OTH"],
                         D0, D3)
        assert len(res.trades) == 1
        assert res.trades[0].opened == D2

    def test_signal_on_last_trading_day_never_fills(self):
        """The chain only supports a build on the final day: with T+1 fills the
        signal queues and is dropped; with fill_lag=0 it would have traded."""
        chains = {"CRD": {
            # illiquid (OI=0) on D0 -> no spec builds
            D0: [q("CRD", D0, EXP, 90.0, P, 2.0, 100.0, -0.3, oi=0),
                 q("CRD", D0, EXP, 80.0, P, 0.8, 100.0, -0.16, oi=0)],
            D1: put_chain("CRD", D1, 100.0, 2.00, 0.80),   # last day: liquid
        }}
        res = run_engine(FakeStore(chains), "bull_put_spread", ["CRD"], D0, D1)
        assert res.metrics.n_trades == 0
        assert res.trades == []
        # contrast: same store with same-day fills DOES trade on the last day
        res0 = run_engine(FakeStore(chains), "bull_put_spread", ["CRD"], D0, D1,
                          params={"fill_lag": 0})
        assert res0.metrics.n_trades == 1

    def test_fill_lag_zero_preserves_same_day_fill(self):
        chains = {"CRD": {
            D0: put_chain("CRD", D0, 100.0, 2.00, 0.80),
            D1: put_chain("CRD", D1, 100.0, 2.00, 0.80),
        }}
        res = run_engine(FakeStore(chains), "bull_put_spread", ["CRD"], D0, D1,
                         params={"fill_lag": 0})
        assert len(res.trades) == 1
        assert res.trades[0].opened == D0

    def test_abandoned_when_leg_unquotable_on_fill_day(self):
        """The 80P leg disappears overnight -> the queued signal is abandoned
        (not filled one-legged, not retried under cooldown)."""
        chains = {"CRD": {
            D0: put_chain("CRD", D0, 100.0, 2.00, 0.80),
            D1: [q("CRD", D1, EXP, 90.0, P, 2.00, 100.0, -0.30)],  # 80P gone
            D2: put_chain("CRD", D2, 100.0, 2.00, 0.80),
            D3: put_chain("CRD", D3, 100.0, 2.00, 0.80),
        }}
        res = run_engine(FakeStore(chains), "bull_put_spread", ["CRD"], D0, D3)
        assert res.metrics.n_trades == 0

    def test_abandoned_when_below_min_dte_at_fill(self):
        """DTE is exactly the minimum on signal day and one short on fill day."""
        dte0 = (EXP - D0).days
        chains = {"CRD": {
            D0: put_chain("CRD", D0, 100.0, 2.00, 0.80),
            D1: put_chain("CRD", D1, 100.0, 2.00, 0.80),
            D2: put_chain("CRD", D2, 100.0, 2.00, 0.80),
        }}
        res = run_engine(FakeStore(chains), "bull_put_spread", ["CRD"], D0, D2,
                         params={"min_dte_to_open": dte0, "close_dte": 0})
        assert res.metrics.n_trades == 0

    def test_default_fill_lag_is_one(self):
        from optdesk.backtest.engine import _RUN_DEFAULTS
        assert _RUN_DEFAULTS["fill_lag"] == 1
        assert _RUN_DEFAULTS["assign_extrinsic"] == 0.03


# --------------------------------------------------------------------------- #
# 2) Early assignment
# --------------------------------------------------------------------------- #
class TestAssignment:
    def _chains(self, mid90_d1: float, u_d1: float):
        return {"CRD": {
            D0: put_chain("CRD", D0, 100.0, 2.00, 0.80),
            D1: put_chain("CRD", D1, u_d1, mid90_d1, 10.50),
            D2: put_chain("CRD", D2, u_d1, mid90_d1, 10.50),
        }}

    def test_deep_itm_short_with_near_zero_extrinsic_is_assigned(self):
        """u=70: short 90P intrinsic 20, mid 20.01 -> extrinsic 0.01 < 0.03.
        The WHOLE position closes with reason "assigned": the assigned leg at
        intrinsic, the long 80P at market. The position is gone that day."""
        res = run_engine(FakeStore(self._chains(20.01, 70.0)),
                         "bull_put_spread", ["CRD"], D0, D2,
                         params={"fill_lag": 0, "stop_mult": 50.0})
        assert len(res.trades) == 1
        t = res.trades[0]
        assert t.closed_reason == "assigned"
        assert t.closed == D1
        # assigned short leg settles at intrinsic exactly (no spread crossing)
        px = {f.strike: f.price for f in t.close_fills}
        assert px[90.0] == pytest.approx(20.0)
        # remaining long leg is liquidated at market (mid 10.50 - slip)
        assert px[80.0] == pytest.approx(10.50 - SLIP)
        # position is GONE the day it is assigned
        day1_point = next(p for p in res.equity_curve if p.asof == D1)
        assert day1_point.open_positions == 0
        assert res.metrics.closed_reasons == {"assigned": 1}
        assert_identity(res)

    def test_assignment_fee_charged_per_contract(self):
        """Identical runs with fee 0 vs 5 differ in trade costs by exactly 5."""
        kw = dict(params={"fill_lag": 0, "stop_mult": 50.0})
        base = run_engine(FakeStore(self._chains(20.01, 70.0)),
                          "bull_put_spread", ["CRD"], D0, D2, **kw)
        feed = run_engine(FakeStore(self._chains(20.01, 70.0)),
                          "bull_put_spread", ["CRD"], D0, D2,
                          cost=CostModel(assignment_fee=5.0, dynamic_slippage=False), **kw)
        assert base.trades[0].closed_reason == "assigned"
        assert feed.trades[0].closed_reason == "assigned"
        assert feed.trades[0].costs - base.trades[0].costs == pytest.approx(5.0)
        assert base.trades[0].pnl - feed.trades[0].pnl == pytest.approx(5.0)
        assert_identity(feed)

    def test_itm_short_with_real_extrinsic_not_assigned(self):
        """u=88: short 90P intrinsic 2, mid 12 -> extrinsic 10 >> 0.03."""
        res = run_engine(FakeStore(self._chains(12.00, 88.0)),
                         "bull_put_spread", ["CRD"], D0, D2,
                         params={"fill_lag": 0, "stop_mult": 50.0})
        assert "assigned" not in res.metrics.closed_reasons

    def test_otm_short_never_assigned_even_at_zero_extrinsic(self):
        """u=100: the 90P is OTM; a collapsing mid must not trigger assignment
        (it triggers the profit target instead)."""
        chains = {"CRD": {
            D0: put_chain("CRD", D0, 100.0, 2.00, 0.80),
            D1: put_chain("CRD", D1, 100.0, 0.05, 0.02),
            D2: put_chain("CRD", D2, 100.0, 0.05, 0.02),
        }}
        res = run_engine(FakeStore(chains), "bull_put_spread", ["CRD"], D0, D2,
                         params={"fill_lag": 0})
        assert len(res.trades) == 1
        assert res.trades[0].closed_reason == "target"
        assert "assigned" not in res.metrics.closed_reasons

    def test_assignment_works_with_t1_fills_too(self):
        """End-to-end with the DEFAULT fill_lag: signal D0, fill D1, assign D2."""
        chains = {"CRD": {
            D0: put_chain("CRD", D0, 100.0, 2.00, 0.80),
            D1: put_chain("CRD", D1, 100.0, 2.00, 0.80),
            D2: put_chain("CRD", D2, 70.0, 20.005, 10.50),
            D3: put_chain("CRD", D3, 70.0, 20.005, 10.50),
        }}
        res = run_engine(FakeStore(chains), "bull_put_spread", ["CRD"], D0, D3,
                         params={"stop_mult": 50.0})
        assert len(res.trades) == 1
        t = res.trades[0]
        assert t.opened == D1
        assert t.closed == D2
        assert t.closed_reason == "assigned"
        assert_identity(res)


# --------------------------------------------------------------------------- #
# 3) Reg-T-style margin
# --------------------------------------------------------------------------- #
def _fill(action: Action, kind: OptionType, strike: float, price: float,
          qty: int = 1) -> Fill:
    return Fill(D0, action, kind, strike, EXP, qty, price, 0.7, SLIP)


class TestRegTMargin:
    def test_naked_short_put_exceeds_defined_risk_spread(self):
        """Naked 90P: (2.00 + max(0.20*100 - 10, 0.10*90)) * 100 = 1200.
        Equivalent 90/80 credit spread keeps width - credit = 880."""
        naked_legs = [Leg(Action.SELL, P, 90.0, EXP)]
        naked_fills = [_fill(Action.SELL, P, 90.0, 2.00)]
        spread_legs = [Leg(Action.SELL, P, 90.0, EXP),
                       Leg(Action.BUY, P, 80.0, EXP)]
        spread_fills = naked_fills + [_fill(Action.BUY, P, 80.0, 0.80)]
        m_naked = margin_requirement(naked_legs, 100.0, naked_fills)
        m_spread = margin_requirement(spread_legs, 100.0, spread_fills)
        assert m_naked == pytest.approx(1200.0)
        assert m_spread == pytest.approx((90 - 80) * 100 - (2.00 - 0.80) * 100)
        assert m_naked > m_spread

    def test_naked_call_uses_ten_pct_underlying_floor(self):
        # ATM-ish: 20% of U dominates -> (2 + max(20-5, 10)) * 100 = 1700
        legs = [Leg(Action.SELL, C, 105.0, EXP)]
        m = margin_requirement(legs, 100.0, [_fill(Action.SELL, C, 105.0, 2.00)])
        assert m == pytest.approx((2.00 + 15.0) * 100)
        # deep OTM: the 10%-of-underlying floor binds -> (0.1 + 10) * 100
        legs = [Leg(Action.SELL, C, 130.0, EXP)]
        m = margin_requirement(legs, 100.0, [_fill(Action.SELL, C, 130.0, 0.10)])
        assert m == pytest.approx((0.10 + 10.0) * 100)

    def test_fully_covered_short_requires_nothing(self):
        """Short 90P offset by a long 95P (higher strike) has no downside."""
        legs = [Leg(Action.SELL, P, 90.0, EXP), Leg(Action.BUY, P, 95.0, EXP)]
        fills = [_fill(Action.SELL, P, 90.0, 2.00),
                 _fill(Action.BUY, P, 95.0, 4.00)]
        assert margin_requirement(legs, 100.0, fills) == 0.0

    def test_quantity_scaling_and_partial_offsets(self):
        """2 short puts vs 1 long put: one lot is defined-risk, one is naked."""
        legs = [Leg(Action.SELL, P, 90.0, EXP, quantity=2),
                Leg(Action.BUY, P, 80.0, EXP, quantity=1)]
        fills = [_fill(Action.SELL, P, 90.0, 2.00, qty=2),
                 _fill(Action.BUY, P, 80.0, 0.80, qty=1)]
        m = margin_requirement(legs, 100.0, fills)
        assert m == pytest.approx(880.0 + 1200.0)

    def test_engine_capital_at_risk_uses_regt_for_naked_credit(self):
        """A naked short put's capital_at_risk = max(modelled max_loss, Reg-T)
        — here the Reg-T requirement dominates a small modelled max_loss."""
        chain = [q("NKD", D0, EXP, 90.0, P, 2.00, 100.0, -0.30)]
        spec = StrategySpec(name="naked_put", ticker="NKD", asof=D0,
                            legs=[Leg(Action.SELL, P, 90.0, EXP)])
        spec.max_loss = 50.0  # deliberately understated model risk
        spec.meta["underlying"] = 100.0
        pf = Portfolio(100_000.0, CostModel(), R)
        pos = pf.open(spec, chain, D0, 0.5, 1.0)
        assert pos is not None
        expected = margin_requirement(spec.legs, 100.0, pos.open_fills)
        # fill premium = 2.00 - slip -> (1.975 + 10) * 100
        assert expected == pytest.approx((2.00 - SLIP + 10.0) * 100)
        assert pos.capital_at_risk == pytest.approx(expected)
        assert pos.capital_at_risk > spec.max_loss

    def test_defined_risk_spread_capital_at_risk_stays_width_minus_credit(self):
        """Engine-level: the bull put spread's CAR is width - credit (fills)."""
        chains = {"CRD": {D0: put_chain("CRD", D0, 100.0, 2.00, 0.80),
                          D1: put_chain("CRD", D1, 100.0, 2.00, 0.80)}}
        bt = Backtester(FakeStore(chains), CostModel())
        p = dict(BASE_PARAMS)
        p["fill_lag"] = 0
        res = bt.run("bull_put_spread", p, ["CRD"], D0, D1, capital=100_000.0,
                     risk=dict(RISK_1LOT))
        t = res.trades[0]
        fill_credit = sum((1 if f.action == Action.SELL else -1) * f.price * 100
                          for f in t.open_fills)
        m = margin_requirement([Leg(f.action, f.kind, f.strike, f.expiry,
                                    f.quantity) for f in t.open_fills],
                               100.0, t.open_fills)
        assert m == pytest.approx((90 - 80) * 100 - fill_credit)


# --------------------------------------------------------------------------- #
# 4) closed_reasons histogram
# --------------------------------------------------------------------------- #
class TestClosedReasons:
    def test_counts_sum_to_n_trades_across_mixed_reasons(self):
        chains = {
            # TGT: decays to the profit target on D2
            "TGT": {
                D0: put_chain("TGT", D0, 100.0, 2.00, 0.80),
                D1: put_chain("TGT", D1, 100.0, 2.00, 0.80),
                D2: put_chain("TGT", D2, 100.0, 0.90, 0.40),
                D3: put_chain("TGT", D3, 100.0, 0.90, 0.40),
            },
            # ASG: collapses deep ITM with no extrinsic on D2
            "ASG": {
                D0: put_chain("ASG", D0, 100.0, 2.00, 0.80),
                D1: put_chain("ASG", D1, 100.0, 2.00, 0.80),
                D2: put_chain("ASG", D2, 70.0, 20.01, 10.50),
                D3: put_chain("ASG", D3, 70.0, 20.01, 10.50),
            },
            # END: nothing ever happens; liquidated at the end of the run
            "END": {d: put_chain("END", d, 100.0, 2.00, 0.80)
                    for d in (D0, D1, D2, D3)},
        }
        res = run_engine(FakeStore(chains), "bull_put_spread",
                         ["TGT", "ASG", "END"], D0, D3,
                         params={"fill_lag": 0, "stop_mult": 50.0})
        assert res.metrics.n_trades == 3
        assert sum(res.metrics.closed_reasons.values()) == res.metrics.n_trades
        assert res.metrics.closed_reasons == {"target": 1, "assigned": 1,
                                              "end": 1}
        # every count agrees with the trade list itself
        for reason, n in res.metrics.closed_reasons.items():
            assert sum(1 for t in res.trades if t.closed_reason == reason) == n

    def test_included_in_to_summary_and_empty_dict_when_no_trades(self):
        chains = {"CRD": {D0: put_chain("CRD", D0, 100.0, 2.00, 0.80),
                          D1: put_chain("CRD", D1, 100.0, 2.00, 0.80)}}
        res = run_engine(FakeStore(chains), "bull_put_spread", ["CRD"], D0, D1)
        summary = res.to_summary()
        assert "closed_reasons" in summary
        assert summary["closed_reasons"] == res.metrics.closed_reasons
        # T+1 over a 2-day run: signal D0 fills D1, force-closed at end
        assert summary["closed_reasons"] == {"end": 1}
        # a run with no trades reports an empty histogram, not a missing key
        res0 = run_engine(FakeStore(chains), "bull_put_spread", ["CRD"], D0, D0)
        assert res0.metrics.n_trades == 0
        assert res0.to_summary()["closed_reasons"] == {}


# --------------------------------------------------------------------------- #
# 5) Signal-gate hook (lazy import, ImportError-tolerant)
# --------------------------------------------------------------------------- #
def _install_gate(monkeypatch, allow_fn):
    """Inject a stub optdesk.signals.equity with build_default_gate."""
    pkg = types.ModuleType("optdesk.signals")
    pkg.__path__ = []  # mark as package
    mod = types.ModuleType("optdesk.signals.equity")

    calls: list[tuple] = []

    class _Gate:
        def allow(self, ticker, day, strategy):
            calls.append((ticker, day, strategy))
            return allow_fn(ticker, day, strategy)

    mod.build_default_gate = lambda tickers, params: _Gate()
    pkg.equity = mod
    monkeypatch.setitem(sys.modules, "optdesk.signals", pkg)
    monkeypatch.setitem(sys.modules, "optdesk.signals.equity", mod)
    return calls


def _two_day_store():
    return FakeStore({"CRD": {D0: put_chain("CRD", D0, 100.0, 2.00, 0.80),
                              D1: put_chain("CRD", D1, 100.0, 2.00, 0.80)}})


class TestSignalGate:
    def test_gate_veto_blocks_all_signals(self, monkeypatch):
        calls = _install_gate(monkeypatch, lambda tk, d, s: False)
        res = run_engine(_two_day_store(), "bull_put_spread", ["CRD"], D0, D1,
                         params={"fill_lag": 0, "use_signals": True})
        assert res.metrics.n_trades == 0
        # consulted pre-build with the STRATEGY NAME string
        assert calls and calls[0] == ("CRD", D0, "bull_put_spread")

    def test_gate_allow_passes_signals_through(self, monkeypatch):
        _install_gate(monkeypatch, lambda tk, d, s: True)
        res = run_engine(_two_day_store(), "bull_put_spread", ["CRD"], D0, D1,
                         params={"fill_lag": 0, "use_signals": True})
        assert res.metrics.n_trades == 1

    def test_missing_signals_module_is_not_an_error(self, monkeypatch):
        """ImportError (module absent / blocked) -> gate None -> normal run."""
        monkeypatch.setitem(sys.modules, "optdesk.signals", None)
        monkeypatch.setitem(sys.modules, "optdesk.signals.equity", None)
        res = run_engine(_two_day_store(), "bull_put_spread", ["CRD"], D0, D1,
                         params={"fill_lag": 0, "use_signals": True})
        assert res.metrics.n_trades == 1

    def test_use_signals_false_never_touches_the_module(self, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("gate must not be built when use_signals=False")

        pkg = types.ModuleType("optdesk.signals")
        pkg.__path__ = []
        mod = types.ModuleType("optdesk.signals.equity")
        mod.build_default_gate = _boom
        pkg.equity = mod
        monkeypatch.setitem(sys.modules, "optdesk.signals", pkg)
        monkeypatch.setitem(sys.modules, "optdesk.signals.equity", mod)
        res = run_engine(_two_day_store(), "bull_put_spread", ["CRD"], D0, D1,
                         params={"fill_lag": 0, "use_signals": False})
        assert res.metrics.n_trades == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
