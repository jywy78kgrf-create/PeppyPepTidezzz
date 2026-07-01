"""
Regression tests for the quant core of the options backtester.

Self-contained: builds tiny deterministic synthetic chains/stores in-test (no
dependency on optdesk.data.make_sample or any files on disk).

Covers:
  * Black-Scholes parity / delta bounds / IV round-trip / degenerate edges.
  * Exit direction for credit and debit structures (hand-built chains): a
    credit position must NOT hit its profit target at entry; it triggers when
    the buyback mark rises toward zero, and stops when it falls further.
  * Survivorship: a delisted ticker's position is force-closed at intrinsic
    using the LAST-SEEN underlying (not the stale open-day price),
    reason == "delisted".
  * Accounting identity: starting capital + sum(trade.pnl) == final equity.
  * Strategy builders: POP bounds, payoff-consistent max loss, unquotable
    strikes skipped, deterministic output. Suggester determinism.
  * compute_metrics edge cases (flat curve, sub-day span, drawdown sign).
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from optdesk.backtest.engine import Backtester, compute_metrics
from optdesk.backtest.portfolio import Portfolio
from optdesk.contracts import (
    Action,
    CostModel,
    EquityPoint,
    OptionQuote,
    OptionType,
    Trade,
)
from optdesk.quant.greeks import bs_price, greeks, implied_vol
from optdesk.quant.pricing import CONTRACT_MULTIPLIER, spec_payoff_at_expiry
from optdesk.strategies.library import STRATEGIES
from optdesk.strategies.suggester import StrategySuggester

C, P = OptionType.CALL, OptionType.PUT
R = 0.045


# --------------------------------------------------------------------------- #
# Helpers: synthetic quotes / chains / store
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


def put_chain(tk: str, day: date, u: float, mid90: float, mid80: float):
    """Two-strike put chain (the raw material for a bull put spread)."""
    return [
        q(tk, day, EXP, 90.0, P, mid90, u, -0.30),
        q(tk, day, EXP, 80.0, P, mid80, u, -0.16),
    ]


BASE_PARAMS = {
    "profit_target": 0.50,
    "stop_mult": 1.0,
    "close_dte": 7,
    "signal_cooldown": 100,   # one trade per ticker per run
    "min_dte_to_open": 14,
    "min_open_interest": 1,
}
RISK_1LOT = {"method": "fixed", "fixed_contracts": 1}


def run_engine(store, strategy, tickers, start, end, params=None):
    bt = Backtester(store, CostModel())
    p = dict(BASE_PARAMS)
    p.update(params or {})
    return bt.run(strategy, p, tickers, start, end, capital=100_000.0,
                  risk=dict(RISK_1LOT))


def assert_identity(res, capital=100_000.0, tol=0.02):
    """starting capital + sum(trade pnl) == final equity after liquidation."""
    assert res.equity_curve, "expected a non-empty equity curve"
    final_eq = res.equity_curve[-1].equity
    assert res.equity_curve[-1].open_positions == 0
    total_pnl = sum(t.pnl for t in res.trades)
    assert capital + total_pnl == pytest.approx(final_eq, abs=tol)


# --------------------------------------------------------------------------- #
# 1) Greeks / pricing
# --------------------------------------------------------------------------- #
class TestGreeks:
    def test_put_call_parity(self):
        for S, K, T, sig in [(100, 105, 0.25, 0.3), (50, 40, 1.0, 0.6),
                             (200, 200, 0.05, 0.15)]:
            c = bs_price(S, K, T, R, sig, C)
            p = bs_price(S, K, T, R, sig, P)
            assert c - p == pytest.approx(S - K * math.exp(-R * T), abs=1e-9)

    def test_delta_signs_and_bounds(self):
        for K in (80.0, 100.0, 120.0):
            gc = greeks(100.0, K, 0.25, R, 0.3, C)
            gp = greeks(100.0, K, 0.25, R, 0.3, P)
            assert 0.0 <= gc["delta"] <= 1.0
            assert -1.0 <= gp["delta"] <= 0.0
            # call delta - put delta == 1 (no-dividend BS)
            assert gc["delta"] - gp["delta"] == pytest.approx(1.0, abs=1e-9)
            assert gc["gamma"] >= 0.0 and gp["gamma"] >= 0.0
            assert gc["vega"] >= 0.0 and gp["vega"] >= 0.0

    def test_implied_vol_round_trip(self):
        px = bs_price(100.0, 105.0, 0.25, R, 0.30, C)
        assert implied_vol(px, 100.0, 105.0, 0.25, R, C) == pytest.approx(0.30, abs=1e-4)
        # deep ITM and far OTM round-trips
        for K in (60.0, 150.0):
            px = bs_price(100.0, K, 0.25, R, 0.30, C)
            assert implied_vol(px, 100.0, K, 0.25, R, C) == pytest.approx(0.30, abs=1e-4)

    def test_degenerate_edges_return_intrinsic_no_nan(self):
        assert bs_price(110.0, 100.0, 0.0, R, 0.3, C) == pytest.approx(10.0)
        assert bs_price(90.0, 100.0, 0.25, R, 0.0, P) == pytest.approx(10.0)
        assert bs_price(0.0, 100.0, 0.25, R, 0.3, C) == 0.0
        for g in (greeks(110.0, 100.0, 0.0, R, 0.3, C),
                  greeks(100.0, 100.0, 0.25, R, 0.0, C),
                  greeks(90.0, 100.0, 0.0, R, 0.3, P)):
            for v in g.values():
                assert math.isfinite(v)
        assert greeks(110.0, 100.0, 0.0, R, 0.3, C)["delta"] == 1.0
        assert greeks(90.0, 100.0, 0.0, R, 0.3, P)["delta"] == -1.0
        assert implied_vol(0.0, 100.0, 100.0, 0.25, R, C) == 0.0
        assert implied_vol(5.0, 100.0, 100.0, 0.0, R, C) == 0.0


# --------------------------------------------------------------------------- #
# 2) Exit direction (the credit profit-target bug)
# --------------------------------------------------------------------------- #
class TestExitDirection:
    def test_credit_target_not_triggered_at_entry(self):
        """Marks unchanged on day 1 -> position must stay open; the 50%-decay
        day triggers "target". Pre-fix, `value <= target_value` fired
        immediately (e.g. -120 <= -60) and closed everything in one day."""
        chains = {"CRD": {
            D0: put_chain("CRD", D0, 100.0, 2.00, 0.80),   # entry mark -120
            D1: put_chain("CRD", D1, 100.0, 2.00, 0.80),   # -120: no exit
            D2: put_chain("CRD", D2, 100.0, 0.95, 0.40),   # -55 >= -60: target
            D3: put_chain("CRD", D3, 100.0, 0.95, 0.40),
        }}
        res = run_engine(FakeStore(chains), "bull_put_spread", ["CRD"], D0, D3)
        assert len(res.trades) == 1
        t = res.trades[0]
        assert t.opened == D0
        assert t.closed == D2, "credit target fired before the mark decayed 50%"
        assert t.closed_reason == "target"
        assert t.pnl > 0
        assert_identity(res)

    def test_credit_stop_triggers_on_adverse_move(self):
        """Buyback mark blowing out through entry - 1x capital-at-risk stops."""
        chains = {"CRD": {
            D0: put_chain("CRD", D0, 100.0, 2.00, 0.80),    # stop level -1000
            D1: put_chain("CRD", D1, 88.0, 12.00, 1.00),    # mark -1100 <= -1000
            D2: put_chain("CRD", D2, 88.0, 12.00, 1.00),
        }}
        res = run_engine(FakeStore(chains), "bull_put_spread", ["CRD"], D0, D2)
        assert len(res.trades) == 1
        t = res.trades[0]
        assert t.closed == D1
        assert t.closed_reason == "stop"
        assert t.pnl < 0
        assert_identity(res)

    def test_debit_target_triggers_on_gain_not_at_entry(self):
        """Long call: value must RISE by profit_target x debit before "target"."""
        def call_chain(day, mid):
            return [q("DBT", day, EXP, 100.0, C, mid, 100.0, 0.50)]
        chains = {"DBT": {
            D0: call_chain(D0, 5.00),   # entry mark +500, target ~ +751
            D1: call_chain(D1, 5.00),   # unchanged: no exit
            D2: call_chain(D2, 8.00),   # 800 >= target
            D3: call_chain(D3, 8.00),
        }}
        res = run_engine(FakeStore(chains), "long_call", ["DBT"], D0, D3)
        assert len(res.trades) == 1
        t = res.trades[0]
        assert t.closed == D2
        assert t.closed_reason == "target"
        assert t.pnl > 0
        assert_identity(res)

    def test_debit_stop_unreachable_levels_are_clamped(self):
        """stop_mult > 1 on a debit: the stop level cannot go below zero (a
        debit structure's mark is never negative), so it only fires at total
        loss - and must not fire while value stays positive."""
        def call_chain(day, mid):
            return [q("DBT", day, EXP, 100.0, C, mid, 100.0, 0.50)]
        chains = {"DBT": {
            D0: call_chain(D0, 5.00),
            D1: call_chain(D1, 2.50),   # -50%: neither target nor (clamped) stop
            D2: call_chain(D2, 2.50),
        }}
        res = run_engine(FakeStore(chains), "long_call", ["DBT"], D0, D2,
                         params={"stop_mult": 2.0})
        # position survives to final liquidation ("end"), never "stop"/"target"
        assert len(res.trades) == 1
        assert res.trades[0].closed_reason == "end"
        assert_identity(res)


# --------------------------------------------------------------------------- #
# 3) Survivorship: delist settles at the LAST-SEEN underlying
# --------------------------------------------------------------------------- #
class TestDelistSettlement:
    def _store(self):
        chains = {
            "DEL": {
                D0: put_chain("DEL", D0, 100.0, 2.00, 0.80),
                D1: put_chain("DEL", D1, 80.0, 11.00, 3.00),
                D2: put_chain("DEL", D2, 60.0, 30.20, 20.10),  # last print u=60
                # no chain on D3+
            },
            # survivor keeps the calendar alive past the delist; its quotes are
            # illiquid (OI=0) so no position ever opens on it
            "SRV": {d: [q("SRV", d, EXP, 90.0, P, 1.0, 100.0, -0.3, oi=0)]
                    for d in (D0, D1, D2, D3)},
        }
        return FakeStore(chains, delisted={"DEL": D2})

    def test_force_close_uses_last_seen_underlying(self):
        res = run_engine(self._store(), "bull_put_spread", ["DEL", "SRV"],
                         D0, D3, params={"stop_mult": 10.0})
        assert len(res.trades) == 1
        t = res.trades[0]
        assert t.ticker == "DEL"
        assert t.closed == D3
        assert t.closed_reason == "delisted"
        # settled at intrinsic of the LAST-SEEN u=60: 90P -> 30, 80P -> 20.
        # (The stale open-day u=100 would settle both legs at 0.)
        by_strike = {f.strike: f.price for f in t.close_fills}
        assert by_strike[90.0] == pytest.approx(30.0)
        assert by_strike[80.0] == pytest.approx(20.0)
        # short spread loses ~ width - credit (>= $850 on one lot)
        assert t.pnl < -850.0
        assert_identity(res)
        assert res.metrics.delisted_included == 1

    def test_accounting_identity_multi_ticker_with_delisting(self):
        """Identity over a multi-ticker run including the delisting name."""
        store = self._store()
        # add a second tradeable ticker with several round trips
        crd = {
            D0: put_chain("CRD", D0, 100.0, 2.00, 0.80),
            D1: put_chain("CRD", D1, 100.0, 2.00, 0.80),
            D2: put_chain("CRD", D2, 100.0, 0.90, 0.40),   # target
            D3: put_chain("CRD", D3, 100.0, 2.00, 0.80),   # reopen
        }
        store._chains["CRD"] = crd
        res = run_engine(store, "bull_put_spread", ["CRD", "DEL", "SRV"], D0, D3,
                         params={"stop_mult": 10.0, "signal_cooldown": 1})
        assert len(res.trades) >= 3
        reasons = {t.closed_reason for t in res.trades}
        assert "delisted" in reasons
        assert_identity(res)


# --------------------------------------------------------------------------- #
# 4) Strategy builders + suggester
# --------------------------------------------------------------------------- #
def rich_chain(day: date = D0, u: float = 100.0) -> list[OptionQuote]:
    """Realistic BS-priced chain: 2 expiries x strikes 70..130 x C/P, plus one
    unquotable strike (bid=ask=0) that no builder may select."""
    out: list[OptionQuote] = []
    for dte in (35, 65):
        expiry = day + timedelta(days=dte)
        T = dte / 365.0
        for k in range(70, 131, 5):
            K = float(k)
            for kind in (C, P):
                mid = max(0.02, round(bs_price(u, K, T, R, 0.30, kind), 2))
                delta = greeks(u, K, T, R, 0.30, kind)["delta"]
                out.append(q("SYN", day, expiry, K, kind, mid, u, round(delta, 4)))
        # dead strike: no market at all (bid=ask=last=0)
        out.append(q("SYN", day, expiry, 72.5, P, 0.0, u, -0.05,
                     bid=0.0, ask=0.0, oi=0, volume=0))
    return out


class TestBuilders:
    def test_all_builders_sane(self):
        chain = rich_chain()
        built = 0
        for name, builder in STRATEGIES.items():
            spec = builder(chain, 100.0, {})
            assert spec is not None, f"{name} failed to build on a rich chain"
            built += 1
            assert 0.0 <= spec.pop <= 1.0, f"{name} POP out of [0,1]: {spec.pop}"
            assert spec.max_loss >= 0.0, f"{name} negative max_loss"
            assert spec.max_profit >= 0.0 or spec.max_profit == float("inf")
            for leg in spec.legs:
                assert leg.strike != 72.5, f"{name} picked an unquotable strike"
        assert built == 9

    def test_bull_put_max_loss_matches_payoff_extreme(self):
        chain = rich_chain()
        spec = STRATEGIES["bull_put_spread"](chain, 100.0, {})
        credit = spec.meta["net_premium"]
        assert credit > 0
        strikes = sorted(l.strike for l in spec.legs)
        width = (strikes[1] - strikes[0]) * CONTRACT_MULTIPLIER
        assert spec.max_loss == pytest.approx(width - credit, abs=1e-6)
        # worst payoff at S -> 0 plus the credit equals -max_loss
        worst = spec_payoff_at_expiry(spec, 0.0)
        assert worst + credit == pytest.approx(-spec.max_loss, abs=1e-6)
        assert spec.max_profit == pytest.approx(credit, abs=1e-6)

    def test_iron_condor_max_loss_matches_payoff_extremes(self):
        chain = rich_chain()
        spec = STRATEGIES["iron_condor"](chain, 100.0, {})
        credit = spec.meta["net_premium"]
        assert credit > 0
        worst = min(spec_payoff_at_expiry(spec, 0.0),
                    spec_payoff_at_expiry(spec, 1e6))
        assert worst + credit == pytest.approx(-spec.max_loss, abs=1e-6)
        assert 0.0 <= spec.pop <= 1.0

    def test_short_straddle_pop_is_band_probability(self):
        """POP must equal P(inside the breakeven band), not the 0.5-weighted
        average of the one-sided tails (which overstates it by ~(1-P)/2)."""
        chain = rich_chain()
        spec = STRATEGIES["short_straddle"](chain, 100.0, {})
        from optdesk.strategies.library import _pop_from_d2, effective_iv
        legs = {l.kind: l for l in spec.legs}
        credit = spec.meta["net_premium"] / CONTRACT_MULTIPLIER
        cq = next(x for x in chain if x.kind == C and
                  x.strike == legs[C].strike and x.expiry == legs[C].expiry)
        T = (legs[C].expiry - D0).days / 365.0
        sigma = effective_iv(cq, R)
        expected = max(0.0, _pop_from_d2(100.0, legs[C].strike + credit, T, R, sigma, False)
                       + _pop_from_d2(100.0, legs[P].strike - credit, T, R, sigma, True) - 1.0)
        assert spec.pop == pytest.approx(expected, abs=1e-3)
        assert spec.pop < 0.95  # the old averaged formula gave ~ (1+P)/2

    def test_builders_deterministic(self):
        chain = rich_chain()
        for name, builder in STRATEGIES.items():
            a = builder(chain, 100.0, {})
            b = builder(chain, 100.0, {})
            assert a is not None and b is not None
            assert [(l.action, l.kind, l.strike, l.expiry) for l in a.legs] == \
                   [(l.action, l.kind, l.strike, l.expiry) for l in b.legs]
            assert a.max_loss == b.max_loss and a.pop == b.pop
            assert a.expected_edge == b.expected_edge

    def test_suggester_deterministic_and_bounded(self):
        chain = rich_chain()
        sug = StrategySuggester()
        r1 = sug.suggest(chain, D0, top_k=9)
        r2 = sug.suggest(chain, D0, top_k=9)
        assert [s.name for s in r1] == [s.name for s in r2]
        assert [s.score for s in r1] == [s.score for s in r2]
        assert all(0.0 <= s.pop <= 1.0 for s in r1)
        # sorted by score desc, name asc
        keys = [(-s.score, s.name) for s in r1]
        assert keys == sorted(keys)


# --------------------------------------------------------------------------- #
# 5) compute_metrics
# --------------------------------------------------------------------------- #
class TestMetrics:
    def test_flat_curve_zero_ratios(self):
        curve = [EquityPoint(D0 + timedelta(days=i), 100_000.0, 100_000.0, 0)
                 for i in range(10)]
        m = compute_metrics(curve, [], capital=100_000.0)
        assert m.sharpe == 0.0 and m.sortino == 0.0
        assert m.max_drawdown == 0.0
        assert m.cagr == 0.0 and m.total_return == 0.0
        assert math.isfinite(m.sharpe) and math.isfinite(m.sortino)

    def test_sub_day_span_no_overflow(self):
        one = [EquityPoint(D0, 102_000.0, 102_000.0, 0)]
        m = compute_metrics(one, [], capital=100_000.0)  # pre-fix: OverflowError
        assert m.cagr == pytest.approx(0.02)
        two = [EquityPoint(D0, 100_000.0, 100_000.0, 0),
               EquityPoint(D0, 98_000.0, 98_000.0, 0)]
        m2 = compute_metrics(two, [], capital=100_000.0)
        assert math.isfinite(m2.cagr) and m2.cagr == pytest.approx(-0.02)

    def test_drawdown_nonpositive_and_cagr_uses_capital(self):
        curve = [EquityPoint(D0, 110_000.0, 110_000.0, 0),
                 EquityPoint(D0 + timedelta(days=180), 90_000.0, 90_000.0, 0),
                 EquityPoint(D0 + timedelta(days=365), 105_000.0, 105_000.0, 0)]
        m = compute_metrics(curve, [], capital=100_000.0)
        assert m.max_drawdown <= 0.0
        assert m.max_drawdown == pytest.approx((90_000 - 110_000) / 110_000)
        assert m.total_return == pytest.approx(0.05)   # vs starting CAPITAL
        assert m.cagr == pytest.approx(0.05 * 365.25 / 365, rel=0.05)

    def test_trade_stats_guards(self):
        curve = [EquityPoint(D0, 100_000.0, 100_000.0, 0),
                 EquityPoint(D0 + timedelta(days=30), 101_000.0, 101_000.0, 0)]
        # no trades: win_rate / profit_factor stay 0, no NaN
        m0 = compute_metrics(curve, [], capital=100_000.0)
        assert m0.win_rate == 0.0 and m0.profit_factor == 0.0 and m0.avg_trade == 0.0
        # all-win: profit_factor well-defined (inf allowed, never NaN)
        wins = [Trade("s", "T", D0, D0, [], [], pnl=100.0),
                Trade("s", "T", D0, D0, [], [], pnl=50.0)]
        m1 = compute_metrics(curve, wins, capital=100_000.0)
        assert m1.win_rate == 1.0
        assert m1.profit_factor == float("inf")
        assert not math.isnan(m1.profit_factor)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
