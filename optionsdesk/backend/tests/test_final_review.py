"""Final-review upgrades: width-aware slippage, daily margin re-mark,
earnings gate, kill-switch responsiveness, trials transparency."""
from __future__ import annotations

import threading
from datetime import date, datetime, timedelta

from optdesk.contracts import (
    Action, CostModel, Leg, OptionQuote, OptionType, StrategySpec,
)
from optdesk.quant.pricing import slippage_fraction

from tests.test_autopilot import FakeBroker, FakeStore, good_learn, make_pilot


# --------------------------------------------------------------------------- #
# Width-aware slippage
# --------------------------------------------------------------------------- #
def test_slippage_flat_when_dynamic_off():
    cost = CostModel(dynamic_slippage=False)
    assert slippage_fraction(1.0, 0.5, cost) == cost.slippage_frac_of_spread


def test_slippage_wide_pays_more_than_tight():
    cost = CostModel()
    tight = slippage_fraction(5.00, 0.05, cost)   # 1% wide
    typical = slippage_fraction(2.00, 0.20, cost)  # 10% wide
    wide = slippage_fraction(1.00, 0.40, cost)     # 40% wide
    assert tight < typical < wide
    assert wide == cost.slippage_frac_max            # capped
    assert tight >= 0.5 * cost.slippage_frac_of_spread  # floored


def test_slippage_flows_into_fill_price():
    from optdesk.backtest.portfolio import Portfolio
    q_tight = OptionQuote("T", date(2026, 6, 1), date(2026, 7, 17), 100.0,
                          OptionType.PUT, 4.98, 5.02, 5.0, 100, 1000,
                          0.3, -0.5, 0.02, -0.03, 0.1, 0.01, 100.0)
    q_wide = OptionQuote("T", date(2026, 6, 1), date(2026, 7, 17), 100.0,
                         OptionType.PUT, 4.00, 6.00, 5.0, 100, 1000,
                         0.3, -0.5, 0.02, -0.03, 0.1, 0.01, 100.0)
    pf = Portfolio(100_000, CostModel(), 0.045)
    p_tight, slip_tight = pf._fill_price(q_tight, Action.BUY)
    p_wide, slip_wide = pf._fill_price(q_wide, Action.BUY)
    # same mid, but the wide market costs far more to cross
    assert abs(q_tight.mid - q_wide.mid) < 1e-9
    assert slip_wide > 10 * slip_tight
    assert p_wide > p_tight


# --------------------------------------------------------------------------- #
# Daily margin re-mark
# --------------------------------------------------------------------------- #
def _naked_put_position(u0: float = 100.0):
    from optdesk.backtest.portfolio import Portfolio
    asof = date(2026, 6, 1)
    expiry = date(2026, 7, 17)
    q = OptionQuote("T", asof, expiry, 95.0, OptionType.PUT, 2.0, 2.2, 2.1,
                    100, 1000, 0.3, -0.3, 0.02, -0.03, 0.1, 0.01, u0)
    spec = StrategySpec(
        name="naked_put", ticker="T", asof=asof,
        legs=[Leg(Action.SELL, OptionType.PUT, 95.0, expiry)],
        max_loss=float("inf"), max_profit=210.0, pop=0.7,
    )
    pf = Portfolio(100_000, CostModel(), 0.045)
    pos = pf.open(spec, [q], asof, profit_target=0.5, stop_mult=1.0)
    assert pos is not None
    return pf, pos


def test_margin_remark_rises_when_underlying_falls():
    pf, pos = _naked_put_position(u0=100.0)
    car_open = pos.capital_at_risk
    car_down = pf.remark_margin(pos, 80.0)   # short put deep ITM -> more margin
    assert car_down > car_open
    pf.remark_margin(pos, 120.0)             # far OTM -> less margin than open
    assert pos.capital_at_risk < car_open


def test_margin_remark_carry_uses_live_requirement():
    pf, pos = _naked_put_position()
    d1 = pos.opened + timedelta(days=1)
    pf.remark_margin(pos, 80.0)
    charge_stressed = pf.accrue_carry(pos, d1)
    pf2, pos2 = _naked_put_position()
    charge_flat = pf2.accrue_carry(pos2, d1)
    assert charge_stressed > charge_flat > 0


def test_margin_remark_ignores_debit_structures():
    from optdesk.backtest.portfolio import Portfolio
    asof, expiry = date(2026, 6, 1), date(2026, 7, 17)
    q = OptionQuote("T", asof, expiry, 105.0, OptionType.CALL, 2.0, 2.2, 2.1,
                    100, 1000, 0.3, 0.4, 0.02, -0.03, 0.1, 0.01, 100.0)
    spec = StrategySpec(name="long_call", ticker="T", asof=asof,
                        legs=[Leg(Action.BUY, OptionType.CALL, 105.0, expiry)],
                        max_loss=220.0, max_profit=float("inf"), pop=0.4)
    pf = Portfolio(100_000, CostModel(), 0.045)
    pos = pf.open(spec, [q], asof, profit_target=0.5, stop_mult=1.0)
    car = pos.capital_at_risk
    pf.remark_margin(pos, 50.0)
    assert pos.capital_at_risk == car  # debit paid never changes


# --------------------------------------------------------------------------- #
# Earnings gate (fail-open, short-premium only)
# --------------------------------------------------------------------------- #
def _pilot_with_earnings(tmp_path, calendar):
    import optdesk.live.alpha_vantage as av_mod
    pilot = make_pilot(tmp_path, FakeBroker())
    orig = av_mod.fetch_earnings_calendar
    av_mod.fetch_earnings_calendar = lambda av, horizon="3month": calendar
    return pilot, av_mod, orig


def test_earnings_gate_blocks_short_premium_through_report(tmp_path):
    cal = {"earnings": {"AAA": ["2026-07-10"]}}
    pilot, av_mod, orig = _pilot_with_earnings(tmp_path, cal)
    try:
        now = datetime(2026, 7, 1, 14, 0, 0)
        expiry = date(2026, 7, 17)  # report 07-10 inside [today, expiry]
        assert pilot._earnings_ok("AAA", expiry, "bull_put_spread", now) is False
        assert pilot._earnings_ok("AAA", expiry, "long_call", now) is True
        # report after expiry+buffer -> fine
        assert pilot._earnings_ok("AAA", date(2026, 7, 8), "bull_put_spread",
                                  now) is True
        # other ticker unaffected
        assert pilot._earnings_ok("BBB", expiry, "iron_condor", now) is True
    finally:
        av_mod.fetch_earnings_calendar = orig


def test_earnings_gate_fails_open_on_error(tmp_path):
    pilot, av_mod, orig = _pilot_with_earnings(
        tmp_path, {"error": "rate limited"})
    try:
        now = datetime(2026, 7, 1, 14, 0, 0)
        assert pilot._earnings_ok("AAA", date(2026, 7, 17),
                                  "short_straddle", now) is True
    finally:
        av_mod.fetch_earnings_calendar = orig


# --------------------------------------------------------------------------- #
# Kill-switch responsiveness
# --------------------------------------------------------------------------- #
def test_tick_is_non_reentrant(tmp_path):
    broker = FakeBroker()
    pilot = make_pilot(tmp_path, broker)
    pilot.enable()
    pilot._tick_gate.acquire()  # simulate a tick already in flight
    try:
        pilot.tick()            # must return immediately, doing nothing
    finally:
        pilot._tick_gate.release()
    assert broker.opened_specs == []


def test_kill_during_research_blocks_trade_phase(tmp_path):
    """disable() mid-research must not deadlock, and the trade phase after
    research must be skipped — the kill switch wins."""
    broker = FakeBroker()
    events = []

    def slow_learn(strategy, tickers, start, end):
        events.append("learn_started")
        # kill switch pulled from another thread while research is running
        t = threading.Thread(target=lambda: pilot.disable("mid-research kill"))
        t.start()
        t.join(timeout=5)
        assert not t.is_alive(), "disable() blocked during research"
        return good_learn(strategy, tickers, start, end)

    pilot = make_pilot(tmp_path, broker, learn=slow_learn)
    pilot.enable()
    pilot.research_tick()              # research runs on its own heartbeat now
    assert events == ["learn_started"]
    assert pilot.status()["enabled"] is False
    pilot.tick()                       # a trade tick after the kill does nothing
    assert broker.opened_specs == []


# --------------------------------------------------------------------------- #
# Trials transparency
# --------------------------------------------------------------------------- #
def test_learn_result_reports_trials():
    from optdesk.data.loader import ChainStore
    from optdesk.learn.loop import LearningLoop
    loop = LearningLoop(ChainStore())
    out = loop.run("bull_put_spread", ["AAPL"], date(2023, 1, 2),
                   date(2023, 12, 27), n_iter=2)
    assert out["trials"] == len(out["history"]) > 0
