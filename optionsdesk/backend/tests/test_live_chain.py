"""
The live-chain fix: the autopilot must OPEN positions from the same live
Alpha Vantage chain it later MARKS against — never from a stale historical
chain. Opening stale + marking live manufactured a huge phantom P&L the
instant a position opened (the ~10-day vintage gap). These tests pin the fix:

  * `live_chain` builds real OptionQuotes (with greeks) from the AV format.
  * A position opened from a live chain and immediately marked from the SAME
    source shows only entry slippage — NOT a phantom jump. (The regression.)
  * The autopilot opens from the injected live chain, and opens NOTHING when
    no live chain is available (never falls back to stale data).
  * Account reset clears the book but keeps promoted strategies.

Run from optionsdesk/backend:  python -m pytest tests/test_live_chain.py -q
All AV traffic is mocked by monkeypatching httpx — NO network.
"""
from __future__ import annotations

from datetime import date, datetime

import httpx
import pytest

from optdesk.live.alpha_vantage import AlphaVantage, live_chain
from optdesk.paper.broker import PaperBroker

_ASOF = date(2026, 7, 6)
_OPEN_TS = datetime(2026, 7, 6, 15, 0)  # 11:00 ET Monday — market open
_UNDERLYING = 500.0
_EXPIRIES = ["2026-08-21", "2026-09-18"]


def _bs_ish(strike: float, kind: str, dte: int) -> dict:
    """A crude-but-consistent option row: intrinsic + time value, delta that
    slides monotonically across strikes so delta-based builders can select."""
    t = dte / 365.0
    intrinsic = max(0.0, (_UNDERLYING - strike) if kind == "call" else (strike - _UNDERLYING))
    tv = 6.0 * (t ** 0.5) * pow(2.71828, -((strike - _UNDERLYING) / 60.0) ** 2)
    mid = round(intrinsic + tv + 0.05, 2)
    moneyness = (_UNDERLYING - strike) / _UNDERLYING
    delta = 0.5 + 4.0 * moneyness
    delta = max(0.02, min(0.98, delta))
    if kind == "put":
        delta = -(1.0 - delta)
    return {
        "symbol": "SPY",
        "expiration": _EXPIRIES[0] if dte < 60 else _EXPIRIES[1],
        "strike": f"{strike:.2f}",
        "type": kind,
        "last": f"{mid:.2f}",
        "mark": f"{mid:.2f}",
        "bid": f"{max(0.01, mid - 0.10):.2f}",
        "ask": f"{mid + 0.10:.2f}",
        "volume": "1200",
        "open_interest": "5000",
        "implied_volatility": "0.20",
        "delta": f"{delta:.5f}",
        "gamma": "0.010",
        "theta": "-0.050",
        "vega": "0.120",
        "rho": "0.030",
    }


def _raw_options_payload() -> dict:
    rows = []
    for dte in (46, 74):
        for strike in (460, 470, 480, 490, 500, 510, 520, 530, 540):
            rows.append(_bs_ish(float(strike), "call", dte))
            rows.append(_bs_ish(float(strike), "put", dte))
    return {"endpoint": "Realtime Options", "message": "success", "data": rows}


def _quote_payload() -> dict:
    return {"Global Quote": {"01. symbol": "SPY", "05. price": f"{_UNDERLYING:.2f}",
                             "08. previous close": "498.00"}}


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._p


def _router():
    """httpx.get replacement routing by AV `function` param."""
    opts, quote = _raw_options_payload(), _quote_payload()

    def get(url, params=None, timeout=None, **kw):
        fn = (params or {}).get("function")
        if fn == "REALTIME_OPTIONS":
            return _Resp(opts)
        if fn == "GLOBAL_QUOTE":
            return _Resp(quote)
        return _Resp({"error": f"unexpected function {fn}"})

    return get


# --------------------------------------------------------------------------- #
# 1. live_chain builds real OptionQuotes with greeks
# --------------------------------------------------------------------------- #
def test_live_chain_builds_option_quotes_with_greeks(monkeypatch):
    monkeypatch.setattr(httpx, "get", _router())
    chain = live_chain(AlphaVantage(key="k"), "SPY", asof=_ASOF)

    assert chain, "live chain must not be empty"
    assert all(q.underlying == _UNDERLYING for q in chain)
    assert all(q.asof == _ASOF for q in chain)
    assert all(q.expiry > _ASOF for q in chain)          # no expired contracts
    # greeks carried through (needed for strike selection)
    atm_call = min((q for q in chain if q.kind.value == "C"),
                   key=lambda q: abs(q.strike - _UNDERLYING))
    assert 0.0 < atm_call.delta < 1.0
    assert atm_call.iv == pytest.approx(0.20)
    assert atm_call.open_interest == 5000


def test_live_chain_empty_without_underlying(monkeypatch):
    """No trustworthy underlying quote -> empty chain -> 'do not open'."""
    opts = _raw_options_payload()

    def get(url, params=None, timeout=None, **kw):
        fn = (params or {}).get("function")
        if fn == "REALTIME_OPTIONS":
            return _Resp(opts)
        return _Resp({"Global Quote": {}})  # no price

    monkeypatch.setattr(httpx, "get", get)
    assert live_chain(AlphaVantage(key="k"), "SPY", asof=_ASOF) == []


def test_live_chain_empty_on_av_error(monkeypatch):
    def get(url, params=None, timeout=None, **kw):
        return _Resp({"Note": "rate limited"})

    monkeypatch.setattr(httpx, "get", get)
    assert live_chain(AlphaVantage(key="k"), "SPY", asof=_ASOF) == []


# --------------------------------------------------------------------------- #
# 2. THE REGRESSION: open + immediate mark from the SAME live source shows
#    only entry slippage, never a phantom vintage gap.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("strategy", ["long_call", "short_straddle",
                                      "bull_put_spread", "covered_call"])
def test_open_then_mark_same_source_no_phantom_pnl(tmp_path, monkeypatch, strategy):
    from optdesk.strategies.library import STRATEGIES

    monkeypatch.setattr(httpx, "get", _router())
    av = AlphaVantage(key="k")
    chain = live_chain(av, "SPY", asof=_ASOF)
    spec = STRATEGIES[strategy](chain, _UNDERLYING, {})
    assert spec is not None, f"{strategy} should build from a liquid live chain"

    pb = PaperBroker(state_dir=tmp_path, starting_cash=100_000.0)
    pos = pb.open(spec, chain, qty=1)
    basis = abs(pos.cost_basis)

    # mark from the SAME AV source, during market hours
    out = pb.mark_live(av, when=_OPEN_TS)
    assert out["live"] is True, out
    marked = pb.positions()[0]

    # the only difference open->mark is the spread we crossed to enter, a few
    # dollars per contract. A vintage gap would be hundreds-to-thousands.
    assert marked.upnl <= 0.5, f"{strategy}: unexpected phantom gain {marked.upnl}"
    tol = max(60.0, 0.05 * basis)   # entry slippage ceiling
    assert abs(marked.upnl) < tol, (
        f"{strategy}: open->mark uPnL {marked.upnl:.2f} exceeds slippage "
        f"tolerance {tol:.2f} on basis {basis:.2f} — phantom P&L is back")


# --------------------------------------------------------------------------- #
# 3. Autopilot opens from the live chain; opens NOTHING without one.
# --------------------------------------------------------------------------- #
def _promoted(strategy="long_call"):
    return {"id": f"{strategy}@t", "strategy": strategy, "tickers": ["SPY"],
            "params": {}, "holdout_score": 5.0, "holdout_return": 0.1,
            "promoted_at": "2026-07-01T00:00:00", "realized_pnl": 0.0,
            "closed_trades": 0, "consecutive_losses": 0, "active": True}


def _pilot_with_live(tmp_path, monkeypatch, chain_fn):
    from tests.test_autopilot import FakeStore
    from optdesk.auto.pilot import AutoConfig, AutoPilot

    monkeypatch.setattr(httpx, "get", _router())
    broker = PaperBroker(state_dir=tmp_path, starting_cash=100_000.0)
    pilot = AutoPilot(
        store=FakeStore(),
        config=AutoConfig(research_interval_hr=99, trade_interval_min=0,
                          require_vrp_for_short_premium=False,
                          avoid_earnings_short_premium=False),
        state_path=tmp_path / "auto.json",
        broker_factory=lambda: broker,
        av_factory=lambda: AlphaVantage(key="k"),
        live_chain_fn=chain_fn,
        now_fn=lambda: _OPEN_TS,
    )
    pilot._state["enabled"] = True
    pilot._state["promoted"] = [_promoted("long_call")]
    return pilot, broker


def test_autopilot_opens_from_live_chain(tmp_path, monkeypatch):
    live = live_chain(AlphaVantage(key="k"), "SPY", asof=_ASOF) if False else None
    # build the chain via the router so it has greeks
    monkeypatch.setattr(httpx, "get", _router())
    live = live_chain(AlphaVantage(key="k"), "SPY", asof=_ASOF)
    assert live

    pilot, broker = _pilot_with_live(tmp_path, monkeypatch, lambda tk: live)
    pilot.run_trade_cycle(_OPEN_TS)

    opens = [p for p in broker.positions() if p.status == "OPEN"]
    assert len(opens) == 1 and opens[0].ticker == "SPY"
    # and it is priced consistently: an immediate mark shows only slippage
    broker.mark_live(AlphaVantage(key="k"), when=_OPEN_TS)
    assert abs(broker.positions()[0].upnl) < max(60.0, 0.05 * abs(opens[0].cost_basis))


def test_autopilot_opens_nothing_without_live_chain(tmp_path, monkeypatch):
    pilot, broker = _pilot_with_live(tmp_path, monkeypatch, lambda tk: [])
    pilot.run_trade_cycle(_OPEN_TS)
    assert [p for p in broker.positions() if p.status == "OPEN"] == []


# --------------------------------------------------------------------------- #
# 4. Account reset: flat book, cash restored, epoch set; promoted kept.
# --------------------------------------------------------------------------- #
def test_reset_clears_book_sets_epoch(tmp_path, monkeypatch):
    from optdesk.strategies.library import STRATEGIES

    monkeypatch.setattr(httpx, "get", _router())
    av = AlphaVantage(key="k")
    chain = live_chain(av, "SPY", asof=_ASOF)
    pb = PaperBroker(state_dir=tmp_path, starting_cash=100_000.0)
    pb.open(STRATEGIES["long_call"](chain, _UNDERLYING, {}), chain, qty=1)
    assert pb.positions() and pb.equity()["cash"] < 100_000.0

    eq = pb.reset()
    assert eq["cash"] == 100_000.0
    assert pb.positions() == []
    assert pb.history() == []
    assert pb.epoch is not None
    # a reload sees the reset persisted
    pb2 = PaperBroker(state_dir=tmp_path, starting_cash=100_000.0)
    assert pb2.positions() == [] and pb2.epoch == pb.epoch


def test_pilot_reset_keeps_promoted(tmp_path):
    from optdesk.auto.pilot import AutoConfig, AutoPilot
    from tests.test_autopilot import FakeStore

    pilot = AutoPilot(store=FakeStore(), config=AutoConfig(),
                      state_path=tmp_path / "auto.json",
                      now_fn=lambda: _OPEN_TS)
    pilot._state["promoted"] = [_promoted("short_straddle")]
    pilot._state["managed"] = {"SPY|x": {"config_id": "y"}}
    pilot._state["breaker"] = {"tripped": True, "reason": "loss", "at": "t"}
    pilot._state["day_anchor"] = {"date": "2026-07-06", "equity": 90_000.0}

    pilot.reset_trading_state()

    assert len(pilot._state["promoted"]) == 1          # KEPT
    assert pilot._state["managed"] == {}               # cleared
    assert pilot._state["day_anchor"] is None          # cleared
    assert pilot._state["breaker"]["tripped"] is False  # un-tripped


def test_reset_clears_equity_curve_and_daypnl(tmp_path):
    """The desk's equity history reads the append-only ledger; after a reset
    it must start a clean curve (epoch-filtered), or a stale DAY P&L / old
    drawdown lingers even though the book is flat."""
    from optdesk.journal import get_ledger

    led = get_ledger(tmp_path / "ledger.db")
    # pre-reset marks (the phantom drawdown)
    led.record_mark("2026-07-06T14:00:00+00:00", 104_933.0, 104_933.0, 0.0, 0, True)
    led.record_mark("2026-07-06T15:00:00+00:00", 100_067.0, 100_067.0, 0.0, 0, True)

    pb = PaperBroker(state_dir=tmp_path, starting_cash=100_000.0)
    assert len(pb.ledger.equity_series()) == 2          # full audit trail intact

    pb.reset()
    # after reset, marks arrive fresh
    pb.ledger.record_mark(pb.epoch, 100_000.0, 100_000.0, 0.0, 0, False)

    curve = pb.ledger.equity_series(since=pb.epoch)
    assert len(curve) == 1 and curve[0]["equity"] == 100_000.0
    # audit trail still has everything (nothing deleted)
    assert len(pb.ledger.equity_series()) == 3


def test_greeks_endpoint_uses_live_chain(tmp_path, monkeypatch):
    """Greeks must be computed from the live chain (same source as opens/marks)
    or every live-opened leg shows 'unmatched' and the strip reads 0."""
    from fastapi.testclient import TestClient
    from optdesk.api import main
    from optdesk.strategies.library import STRATEGIES
    import optdesk.live.market_hours as mh

    monkeypatch.setattr(httpx, "get", _router())
    av = AlphaVantage(key="k")
    chain = live_chain(av, "SPY", asof=_ASOF)
    pb = PaperBroker(state_dir=tmp_path, starting_cash=100_000.0)
    pb.open(STRATEGIES["long_call"](chain, _UNDERLYING, {}), chain, qty=2)

    monkeypatch.setattr(main, "_paper",
                        lambda: PaperBroker(state_dir=tmp_path, starting_cash=100_000.0))
    monkeypatch.setattr(main, "_alpha_vantage", lambda: av)
    monkeypatch.setattr(mh, "market_open", lambda now=None: True)
    client = TestClient(main.app)

    g = client.get("/api/paper/greeks").json()
    assert g["unmatched_legs"] == 0, "live-opened legs must match the live greeks chain"
    assert abs(g["totals"]["delta"]) > 0.0, "a long call must carry non-zero delta"
    assert g["totals"]["theta"] != 0.0, "a long option must carry theta"


def test_match_quote_never_crosses_expiry():
    """The mark matcher must not price an Aug leg off a June contract — that
    cross-expiry match is what produced impossible negative long-option marks."""
    from datetime import date as _d
    from optdesk.paper.broker import _match_quote
    from optdesk.contracts import OptionQuote, OptionType, Leg, Action

    june = OptionQuote("X", _d(2026, 6, 1), _d(2026, 6, 26), 240.0, OptionType.CALL,
                       1.0, 1.2, 1.1, 0, 0, 0.2, 0.5, 0.0, 0.0, 0.0, 0.0, 240.0)
    aug_leg = Leg(Action.BUY, OptionType.CALL, 240.0, _d(2026, 8, 14))
    assert _match_quote([june], aug_leg) is None       # different expiry -> no match
    same_leg = Leg(Action.BUY, OptionType.CALL, 240.0, _d(2026, 6, 26))
    assert _match_quote([june], same_leg) is june      # same expiry -> matches


def test_store_fallback_holds_last_mark_never_negative(tmp_path, monkeypatch):
    """A live-opened long call whose expiry isn't in the store must HOLD its
    last live mark under the store fallback — never mis-price to a negative
    value (the impossible '-103% on basis' bug)."""
    from optdesk.strategies.library import STRATEGIES
    from optdesk.data.loader import ChainStore

    monkeypatch.setattr(httpx, "get", _router())
    av = AlphaVantage(key="k")
    chain = live_chain(av, "SPY", asof=_ASOF)
    pb = PaperBroker(state_dir=tmp_path, starting_cash=100_000.0)
    pb.open(STRATEGIES["long_call"](chain, _UNDERLYING, {}), chain, qty=3)
    pb.mark_live(av, when=_OPEN_TS)
    last = pb.positions()[0].current_value
    assert last > 0

    # mark against a store that has no SPY Aug contracts -> must hold, not fabricate
    pb.mark(ChainStore())
    held = pb.positions()[0].current_value
    assert held == last, "store fallback must hold the last mark, not re-price"
    assert held >= 0, "a long call can never mark negative"
