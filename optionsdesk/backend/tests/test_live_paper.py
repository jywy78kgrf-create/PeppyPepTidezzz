"""
Phase-2 live paper trading tests: Alpha Vantage realtime parsing, live
mark-to-mid with historical fallback, persisted equity history snapshots
(throttle + force + backward compat), and the /api/paper/* surface.

Self-contained (no conftest.py): run from optionsdesk/backend with

    python -m pytest tests/test_live_paper.py -q

All Alpha Vantage traffic is mocked by monkeypatching httpx — NO network.
Sample chain data is generated on demand if the store is empty.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from optdesk.data.loader import ChainStore
from optdesk.live.alpha_vantage import AlphaVantage
from optdesk.paper.broker import PaperBroker


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def _store() -> ChainStore:
    store = ChainStore()
    if not store.tickers():
        from optdesk.data import make_sample

        make_sample.main()
        store = ChainStore()
    assert store.tickers(), "sample data generation failed"
    return store


class _Resp:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _fake_get(payload: dict):
    """httpx.get replacement returning a canned JSON body (records calls)."""
    calls: list[dict] = []

    def get(url, params=None, timeout=None, **kw):
        calls.append({"url": url, "params": dict(params or {}), "timeout": timeout})
        return _Resp(payload)

    get.calls = calls
    return get


def _no_network(*a, **kw):
    raise AssertionError("network call attempted — test must be offline")


# Canned REALTIME_OPTIONS body in Alpha Vantage's actual field spelling.
_AV_PAYLOAD = {
    "endpoint": "Realtime Options",
    "message": "success",
    "data": [
        {
            "contractID": "AAPL240614C00100000",
            "symbol": "AAPL",
            "expiration": "2024-06-14",
            "strike": "100.00",
            "type": "call",
            "last": "4.95",
            "mark": "5.00",
            "bid": "4.80",
            "ask": "5.20",
        },
        {
            "contractID": "AAPL240614P00095000",
            "symbol": "AAPL",
            "expiration": "2024-06-14",
            "strike": "95.0",
            "type": "put",
            "last": "1.10",
            "bid": "1.00",
            "ask": "1.20",
        },
        # zero bid/ask -> mid falls back to last
        {
            "symbol": "AAPL",
            "expiration": "2024-06-14",
            "strike": "90.0",
            "type": "put",
            "last": "0.55",
            "bid": "0",
            "ask": "0",
        },
        # unusable rows must be dropped, not crash
        {"symbol": "AAPL", "expiration": "not-a-date", "strike": "1", "type": "call"},
        {"symbol": "AAPL", "expiration": "2024-06-14", "strike": "80.0", "type": ""},
    ],
}


def _position_dict(ticker: str = "AAPL") -> dict:
    """A two-leg short put spread + long call, opened for a $350 debit."""
    return {
        "ticker": ticker,
        "spec_name": "test_combo",
        "opened": "2024-06-01T00:00:00",
        "legs": [
            {"action": "SELL", "kind": "P", "strike": 95.0,
             "expiry": "2024-06-14", "quantity": 1, "open_price": 1.5},
            {"action": "BUY", "kind": "C", "strike": 100.0,
             "expiry": "2024-06-14", "quantity": 1, "open_price": 5.0},
        ],
        "cost_basis": 350.0,
        "current_value": 350.0,
        "upnl": 0.0,
        "status": "OPEN",
    }


def _broker_with_position(tmp_path, ticker: str = "AAPL") -> PaperBroker:
    pb = PaperBroker(state_dir=tmp_path, starting_cash=10_000.0)
    pb._positions.append(pb._pos_from_dict(_position_dict(ticker)))
    pb._save()
    return pb


def _open_real_position(tmp_path) -> tuple[PaperBroker, ChainStore]:
    """Open a real bull put spread off the sample store."""
    from optdesk.strategies.library import STRATEGIES

    store = _store()
    # open off the LATEST chain so the position's contracts are present when the
    # store-fallback marks against that same latest chain (no cross-expiry match)
    day = store.trading_dates("AAPL")[-1]
    chain = store.chain("AAPL", day)
    spec = STRATEGIES["bull_put_spread"](chain, chain[0].underlying, {})
    assert spec is not None
    pb = PaperBroker(state_dir=tmp_path, starting_cash=100_000.0)
    pb.open(spec, chain, qty=1)
    return pb, store


# --------------------------------------------------------------------------- #
# 1. AlphaVantage.realtime_options — normalization from a canned payload
# --------------------------------------------------------------------------- #
def test_realtime_options_normalizes_canned_payload(monkeypatch):
    fake = _fake_get(_AV_PAYLOAD)
    monkeypatch.setattr(httpx, "get", fake)
    rows = AlphaVantage(key="k").realtime_options("AAPL")

    assert len(rows) == 3, "malformed rows must be dropped"
    call = rows[0]
    assert call["expiry"] == "2024-06-14" and isinstance(call["expiry"], str)
    assert call["strike"] == pytest.approx(100.0) and isinstance(call["strike"], float)
    assert call["option_type"] == "C"
    assert (call["bid"], call["ask"], call["last"]) == (4.80, 5.20, 4.95)
    put = rows[1]
    assert put["option_type"] == "P" and put["strike"] == pytest.approx(95.0)
    for r in rows:
        for k in ("bid", "ask", "last", "strike"):
            assert isinstance(r[k], float)
    # request really went to the REALTIME_OPTIONS function with the api key
    assert fake.calls[0]["params"]["function"] == "REALTIME_OPTIONS"
    assert fake.calls[0]["params"]["apikey"] == "k"


def test_realtime_options_rate_limit_and_premium_notes_are_errors(monkeypatch):
    note = "Thank you for using Alpha Vantage! Our standard API rate limit is 25 requests per day."
    monkeypatch.setattr(httpx, "get", _fake_get({"Note": note}))
    rows = AlphaVantage(key="k").realtime_options("AAPL")
    assert rows == [{"error": note}]

    info = "This is a premium endpoint. Subscribe to unlock."
    monkeypatch.setattr(httpx, "get", _fake_get({"Information": info}))
    rows = AlphaVantage(key="k").realtime_options("AAPL")
    assert rows == [{"error": info}]


def test_realtime_options_without_key_errors_without_network(monkeypatch):
    monkeypatch.setattr(httpx, "get", _no_network)
    av = AlphaVantage(key="")
    rows = av.realtime_options("AAPL")
    assert len(rows) == 1 and "error" in rows[0]


# --------------------------------------------------------------------------- #
# 2. PaperBroker.mark_live — leg matching, mid marks, snapshots
# --------------------------------------------------------------------------- #
from datetime import datetime as _dt
_OPEN_TS = _dt(2026, 7, 1, 14, 0)  # Wed 10:00 ET — market open


def test_mark_live_matches_legs_and_marks_at_mid(tmp_path, monkeypatch):
    monkeypatch.setattr(httpx, "get", _fake_get(_AV_PAYLOAD))
    pb = _broker_with_position(tmp_path)

    out = pb.mark_live(AlphaVantage(key="k"), when=_OPEN_TS)
    assert out == {"live": True, "marked": 1}

    pos = pb.positions()[0]
    # short 95P at mid (1.00+1.20)/2 = 1.10 -> -110; long 100C at mid 5.00 -> +500
    assert pos.current_value == pytest.approx(390.0)
    assert pos.upnl == pytest.approx(390.0 - 350.0)
    # a live snapshot was recorded
    pts = pb.history()
    assert len(pts) == 1 and pts[-1]["live"] is True
    assert pts[-1]["equity"] == pytest.approx(10_000.0 + 390.0)


def test_mark_live_unmatched_leg_held_at_open_price(tmp_path, monkeypatch):
    # only the put is quoted live; the 100C leg is absent from the chain
    payload = {"data": [d for d in _AV_PAYLOAD["data"] if d.get("type") == "put"]}
    monkeypatch.setattr(httpx, "get", _fake_get(payload))
    pb = _broker_with_position(tmp_path)

    out = pb.mark_live(AlphaVantage(key="k"), when=_OPEN_TS)
    assert out["live"] is True
    assert out["marked"] == 0, "a position with an unmatched leg is not fully live-marked"
    pos = pb.positions()[0]
    # put at live mid -110; call held at its open price +500
    assert pos.current_value == pytest.approx(-110.0 + 500.0)


def test_mark_live_av_error_falls_back_to_historical(tmp_path, monkeypatch):
    monkeypatch.setattr(httpx, "get", _fake_get({"Note": "rate limited"}))
    pb, store = _open_real_position(tmp_path)

    out = pb.mark_live(AlphaVantage(key="k"), store=store, when=_OPEN_TS)
    assert out["live"] is False
    assert "rate limited" in out["reason"]
    v_fallback = pb.positions()[0].current_value
    # fallback must equal a direct historical mark off the latest chain
    pb.mark(store)
    assert pb.positions()[0].current_value == pytest.approx(v_fallback)
    # and the snapshot recorded is an EOD (non-live) point
    assert pb.history() and pb.history()[-1]["live"] is False


def test_mark_live_without_key_falls_back_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(httpx, "get", _no_network)
    pb, store = _open_real_position(tmp_path)
    out = pb.mark_live(AlphaVantage(key=""), store=store, when=_OPEN_TS)
    assert out["live"] is False and "reason" in out
    assert pb.positions()[0].upnl != 0.0  # historical mark actually happened


def test_mark_live_never_raises_and_holds_when_unpriceable(tmp_path, monkeypatch):
    monkeypatch.setattr(httpx, "get", _no_network)
    _store()  # chains exist, but not for this ticker
    pb = _broker_with_position(tmp_path, ticker="ZZZZ")
    before = pb.positions()[0].current_value
    out = pb.mark_live(AlphaVantage(key=""), store=ChainStore(), when=_OPEN_TS)  # must not raise
    assert out["live"] is False
    # unknown ticker can't be priced -> position is HELD at its last mark, no crash
    assert pb.positions()[0].status == "OPEN"
    assert pb.positions()[0].current_value == before


# --------------------------------------------------------------------------- #
# 2b. Exit costs — closing crosses the spread + pays commission (a mid "win"
#     can still book a loss once the real round-trip cost is charged)
# --------------------------------------------------------------------------- #
def test_close_charges_exit_costs_not_free_mid(tmp_path, monkeypatch):
    """After a live mark, liquidation_value is strictly below the mid mark, and
    closing realises the liquidation value — not the free mid."""
    monkeypatch.setattr(httpx, "get", _fake_get(_AV_PAYLOAD))
    pb = _broker_with_position(tmp_path)
    cash0 = pb.equity()["cash"]
    # mirror a real open so the ledger has a row for record_close to update
    pos0 = pb.positions()[0]
    pb.ledger.record_open(ticker=pos0.ticker, opened=pos0.opened.isoformat(),
                          strategy=pos0.spec_name, qty=1,
                          cost_basis=pos0.cost_basis, legs=pos0.legs)

    pb.mark_live(AlphaVantage(key="k"), when=_OPEN_TS)
    pos = pb.positions()[0]
    # mid mark: short 95P -110 + long 100C +500 = 390
    assert pos.current_value == pytest.approx(390.0)
    # liquidation crosses the spread on BOTH legs + pays 2*(0.65+0.05) fees:
    #   close 95P (BUY):  mid 1.10 + slip 0.083 = 1.183  -> -118.30
    #   close 100C (SELL): mid 5.00 - slip 0.115 = 4.885 -> +488.50
    #   value 370.20 - commission 1.40 = 368.80
    assert pos.liquidation_value == pytest.approx(368.80, abs=0.01)
    assert pos.liquidation_value < pos.current_value, "exit is never free"

    closed = pb.close(0)
    # realised at the liquidation value, not the 390 mid
    assert closed.upnl == pytest.approx(368.80 - 350.0, abs=0.01)
    assert pb.equity()["cash"] == pytest.approx(cash0 + 368.80, abs=0.01)
    # the ledger books the same net-of-cost realised P&L
    realized, n = pb.ledger.realized()
    assert n == 1 and realized == pytest.approx(368.80 - 350.0, abs=0.01)


def test_close_without_mark_falls_back_to_mid(tmp_path):
    """A position never marked (no liquidation_value) still closes — at its
    current_value — rather than crashing."""
    pb = _broker_with_position(tmp_path)
    assert pb.positions()[0].liquidation_value is None
    cash0 = pb.equity()["cash"]
    closed = pb.close(0)
    assert closed.upnl == pytest.approx(0.0)  # current_value 350 == cost_basis
    assert pb.equity()["cash"] == pytest.approx(cash0 + 350.0)


def test_liquidation_value_survives_reload(tmp_path, monkeypatch):
    """liquidation_value persists in paper.json so a restart doesn't drop back
    to a free-mid close."""
    monkeypatch.setattr(httpx, "get", _fake_get(_AV_PAYLOAD))
    pb = _broker_with_position(tmp_path)
    pb.mark_live(AlphaVantage(key="k"), when=_OPEN_TS)
    liq = pb.positions()[0].liquidation_value
    assert liq is not None
    pb2 = PaperBroker(state_dir=tmp_path, starting_cash=10_000.0)
    assert pb2.positions()[0].liquidation_value == pytest.approx(liq)


# --------------------------------------------------------------------------- #
# 3. History snapshots — append, throttle, force, persistence
# --------------------------------------------------------------------------- #
def test_snapshot_appends_then_throttles_then_forces(tmp_path):
    pb = PaperBroker(state_dir=tmp_path, starting_cash=5_000.0)
    p1 = pb.snapshot(live=True)
    assert p1 is not None
    assert set(p1.keys()) == {"ts", "equity", "cash", "upnl", "live"}
    assert p1["live"] is True and p1["equity"] == pytest.approx(5_000.0)

    assert pb.snapshot() is None, "a second snapshot within 5 min must be throttled"
    assert len(pb.history()) == 1

    p3 = pb.snapshot(force=True)
    assert p3 is not None and len(pb.history()) == 2

    # age the last point past the throttle window -> next snapshot appends
    old = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
    pb._history[-1]["ts"] = old
    assert pb.snapshot() is not None
    assert len(pb.history()) == 3


def test_mark_records_a_snapshot(tmp_path):
    pb, store = _open_real_position(tmp_path)
    assert pb.history() == []
    pb.mark(store)
    pts = pb.history()
    assert len(pts) == 1 and pts[0]["live"] is False
    assert pts[0]["cash"] == pb.equity()["cash"]


def test_history_persists_across_reload(tmp_path):
    pb = PaperBroker(state_dir=tmp_path, starting_cash=7_500.0)
    pb.snapshot(live=True)
    pb2 = PaperBroker(state_dir=tmp_path, starting_cash=7_500.0)
    assert pb2.history() == pb.history()
    assert pb2.history()[0]["equity"] == pytest.approx(7_500.0)


# --------------------------------------------------------------------------- #
# 4. Backward compat — old/corrupt state files load cleanly
# --------------------------------------------------------------------------- #
def test_old_state_without_history_field_loads_cleanly(tmp_path):
    """Pre-phase-2 paper.json (no 'history' key) must load without loss."""
    old_state = {
        "cash": 42_000.0,
        "starting_cash": 40_000.0,
        "positions": [_position_dict()],
    }
    (tmp_path / "paper.json").write_text(json.dumps(old_state))
    pb = PaperBroker(state_dir=tmp_path, starting_cash=99.0)
    assert pb.history() == []
    assert pb.equity()["cash"] == pytest.approx(42_000.0)
    assert len(pb.positions()) == 1
    assert not list(tmp_path.glob("paper.json.corrupt-*")), \
        "an old-format file must NOT be treated as corrupt"
    pb.snapshot()  # upgrading in place works
    assert json.loads((tmp_path / "paper.json").read_text())["history"]


def test_corrupt_history_field_loads_cleanly(tmp_path):
    """A wrong-typed or partially-garbage history must not nuke good state."""
    good_point = {"ts": "2026-06-30T12:00:00+00:00", "equity": 1.0,
                  "cash": 1.0, "upnl": 0.0, "live": True}
    state = {
        "cash": 10_000.0,
        "starting_cash": 10_000.0,
        "positions": [_position_dict()],
        "history": [42, "junk", {"bogus": 1}, {"ts": "x", "equity": None,
                    "cash": 0, "upnl": 0}, good_point],
    }
    (tmp_path / "paper.json").write_text(json.dumps(state))
    pb = PaperBroker(state_dir=tmp_path, starting_cash=10_000.0)
    assert pb.history() == [good_point], "only the well-formed point survives"
    assert len(pb.positions()) == 1
    assert not list(tmp_path.glob("paper.json.corrupt-*"))

    # history that is not even a list -> empty history, state intact
    state["history"] = "total garbage"
    (tmp_path / "paper.json").write_text(json.dumps(state))
    pb = PaperBroker(state_dir=tmp_path, starting_cash=10_000.0)
    assert pb.history() == []
    assert pb.equity()["cash"] == pytest.approx(10_000.0)


# --------------------------------------------------------------------------- #
# 5. API — /api/paper/positions, /api/paper/mark, /api/paper/history
# --------------------------------------------------------------------------- #
def _client(tmp_path, monkeypatch, av: AlphaVantage):
    from fastapi.testclient import TestClient
    from optdesk.api import main

    _store()  # ensure chain data exists before the app touches the store
    monkeypatch.setattr(
        main, "_paper",
        lambda: PaperBroker(state_dir=tmp_path, starting_cash=100_000.0),
    )
    monkeypatch.setattr(main, "_alpha_vantage", lambda: av)
    return TestClient(main.app)


def _open_via_api(client) -> None:
    day = _store().trading_dates("AAPL")[60]
    r = client.post("/api/paper/open", json={
        "ticker": "AAPL", "date": day.isoformat(),
        "strategy": "bull_put_spread", "qty": 1,
    })
    assert r.status_code == 200, r.text


def test_api_paper_endpoints_contract_shapes_no_key(tmp_path, monkeypatch):
    """Whole flow offline (no AV key): open -> positions -> mark -> history."""
    monkeypatch.setattr(httpx, "get", _no_network)
    client = _client(tmp_path, monkeypatch, AlphaVantage(key=""))
    _open_via_api(client)

    r = client.get("/api/paper/positions")
    assert r.status_code == 200, r.text
    body = r.json()
    json.dumps(body)  # payload must be JSON-clean
    assert {"positions", "equity", "live", "asof"} <= set(body.keys())
    assert body["live"] is False, "no AV key -> historical marking"
    assert isinstance(body["asof"], str) and body["asof"]
    assert len(body["positions"]) == 1
    assert {"cash", "upnl", "total", "realized"} <= set(body["equity"].keys())

    r = client.post("/api/paper/mark")
    assert r.status_code == 200
    marked = r.json()
    assert {"positions", "equity", "live", "asof"} <= set(marked.keys())
    assert marked["live"] is False

    r = client.get("/api/paper/history")
    assert r.status_code == 200
    pts = r.json()["points"]
    assert pts, "marking must have recorded at least one history point"
    for p in pts:
        assert set(p.keys()) == {"ts", "equity", "cash", "upnl", "live"}
        assert p["live"] is False


def test_api_paper_mark_goes_live_when_key_configured(tmp_path, monkeypatch):
    # the API route uses the real clock; force "market open" so the test
    # doesn't depend on the day/hour the suite runs
    import optdesk.live.market_hours as mh
    monkeypatch.setattr(mh, "market_open", lambda now=None: True)
    client = _client(tmp_path, monkeypatch, AlphaVantage(key="k"))
    _open_via_api(client)

    # canned realtime chain covering exactly the opened position's legs
    pb = PaperBroker(state_dir=tmp_path, starting_cash=100_000.0)
    legs = pb.positions()[0].legs
    payload = {"data": [
        {"symbol": "AAPL", "expiration": ls["expiry"], "strike": str(ls["strike"]),
         "type": "call" if ls["kind"] == "C" else "put",
         "bid": "1.00", "ask": "1.20", "last": "1.10"}
        for ls in legs
    ]}
    monkeypatch.setattr(httpx, "get", _fake_get(payload))

    r = client.post("/api/paper/mark")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["live"] is True
    # every leg marked at mid 1.10: value = sum(+-1.10 * qty * 100)
    expected = sum(
        (1.0 if ls["action"] == "BUY" else -1.0) * 1.10 * abs(ls["quantity"]) * 100
        for ls in legs
    )
    pos = body["positions"][0]
    assert pos["current_value"] == pytest.approx(expected)
    assert pos["upnl"] == pytest.approx(expected - pos["cost_basis"])

    pts = client.get("/api/paper/history").json()["points"]
    assert pts[-1]["live"] is True


def test_api_paper_positions_realized_tracks_closed_pnl(tmp_path, monkeypatch):
    monkeypatch.setattr(httpx, "get", _no_network)
    client = _client(tmp_path, monkeypatch, AlphaVantage(key=""))
    _open_via_api(client)

    r = client.post("/api/paper/close", json={"idx": 0})
    assert r.status_code == 200, r.text
    closed_upnl = r.json()["position"]["upnl"]

    body = client.get("/api/paper/positions").json()
    assert body["equity"]["realized"] == pytest.approx(closed_upnl, abs=0.01)
    assert body["equity"]["upnl"] == pytest.approx(0.0), "no open positions remain"


# --------------------------------------------------------------------------- #
# Market-hours gate
# --------------------------------------------------------------------------- #
def test_market_open_regular_hours_and_weekend():
    from datetime import datetime
    from optdesk.live.market_hours import market_open
    # July (EDT, UTC-4): Wed 2026-07-01
    assert market_open(datetime(2026, 7, 1, 13, 30)) is True    # 09:30 ET open
    assert market_open(datetime(2026, 7, 1, 13, 29)) is False   # 09:29 ET
    assert market_open(datetime(2026, 7, 1, 19, 59)) is True    # 15:59 ET
    assert market_open(datetime(2026, 7, 1, 20, 0)) is False    # 16:00 ET close
    # weekend — Sat 2026-07-04 mid-day ET
    assert market_open(datetime(2026, 7, 4, 17, 0)) is False
    # January (EST, UTC-5): Wed 2026-01-07 14:30 UTC = 09:30 ET
    assert market_open(datetime(2026, 1, 7, 14, 30)) is True
    assert market_open(datetime(2026, 1, 7, 14, 29)) is False


def test_mark_live_eod_off_hours_and_throttles(tmp_path, monkeypatch):
    """Off-hours the book still marks from AV's EOD quotes (labeled live=False),
    then throttles: the second call within 15 min holds without touching AV."""
    fake = _fake_get(_AV_PAYLOAD)
    monkeypatch.setattr(httpx, "get", fake)
    pb = _broker_with_position(tmp_path)  # AAPL legs match _AV_PAYLOAD
    out = pb.mark_live(AlphaVantage(key="k"), when=_dt(2026, 7, 4, 17, 0))  # Saturday
    assert out["live"] is False           # EOD label off-hours
    assert out.get("marked") == 1         # marked from AV EOD quotes
    n_after_first = len(fake.calls)
    assert n_after_first > 0              # AV WAS called for the EOD mark

    # a second mark right away holds the EOD value — no new AV traffic
    out2 = pb.mark_live(AlphaVantage(key="k"), when=_dt(2026, 7, 4, 17, 5))
    assert out2["live"] is False
    assert len(fake.calls) == n_after_first, "off-hours mark must throttle AV"


def test_trade_cycle_paused_when_market_closed(tmp_path):
    """Pilot must not mark/open/close outside RTH (Saturday tick)."""
    from datetime import datetime
    from tests.test_autopilot import FakeBroker, make_pilot

    broker = FakeBroker()
    pilot = make_pilot(tmp_path, broker)
    pilot._state["enabled"] = True
    pilot._state["promoted"] = [{
        "id": "x", "strategy": "bull_put_spread", "tickers": ["AAA"],
        "params": {}, "holdout_score": 1.0, "holdout_return": 0.05,
        "promoted_at": "2026-07-01T00:00:00", "realized_pnl": 0.0,
        "closed_trades": 0, "consecutive_losses": 0, "active": True,
    }]
    pilot.run_trade_cycle(datetime(2026, 7, 4, 17, 0))  # Saturday
    assert broker.opened_specs == [] and broker.closed_idx == []


# --------------------------------------------------------------------------- #
# Transient-throttle retry (shared key briefly saturated by other apps)
# --------------------------------------------------------------------------- #
def test_realtime_options_retries_transient_throttle(monkeypatch):
    import optdesk.live.alpha_vantage as avmod
    avmod._cache.clear()
    monkeypatch.setattr(avmod._time, "sleep", lambda *_a, **_k: None)  # no real delay
    seq = [{"Error Message": "Invalid API call. Please retry or visit the documentation"},
           _AV_PAYLOAD]
    calls = {"n": 0}

    def get(url, params=None, timeout=None, **kw):
        i = min(calls["n"], len(seq) - 1)
        calls["n"] += 1
        return _Resp(seq[i])

    monkeypatch.setattr(httpx, "get", get)
    rows = AlphaVantage(key="k").realtime_options("AAPL")
    assert calls["n"] >= 2, "a 'Please retry' throttle must be retried"
    assert len(rows) == 3 and "error" not in rows[0], "retry then succeeded"


def test_realtime_options_does_not_retry_hard_error(monkeypatch):
    import optdesk.live.alpha_vantage as avmod
    avmod._cache.clear()
    monkeypatch.setattr(avmod._time, "sleep", lambda *_a, **_k: None)
    calls = {"n": 0}

    def get(url, params=None, timeout=None, **kw):
        calls["n"] += 1
        return _Resp({"Information": "This is a premium endpoint. Subscribe to unlock."})

    monkeypatch.setattr(httpx, "get", get)
    rows = AlphaVantage(key="k").realtime_options("AAPL")
    assert calls["n"] == 1, "a premium/entitlement wall is a hard error — no retry"
    assert "error" in rows[0]


# --------------------------------------------------------------------------- #
# Book-file durability + realized-from-ledger (the account-reset bug)
# --------------------------------------------------------------------------- #
def test_concurrent_saves_never_corrupt_the_book(tmp_path):
    """Many brokers writing the same paper.json concurrently must never
    produce a corrupt file (the bug that reset the account to $100k)."""
    import threading
    errors = []

    def worker(n):
        try:
            for _ in range(25):
                pb = PaperBroker(state_dir=tmp_path, starting_cash=100_000.0)
                pb._cash = 100_000.0 + n
                pb._save()
                json.loads((tmp_path / "paper.json").read_text())  # must parse
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [], errors
    assert not list(tmp_path.glob(".paper-*.tmp")), "temp files leaked"
    assert isinstance(json.loads((tmp_path / "paper.json").read_text()), dict)


def test_realized_survives_book_reset_via_ledger(tmp_path):
    """Realized P&L is read from the permanent ledger, so wiping the working
    book (reset/corruption) does NOT blank it."""
    pb = PaperBroker(state_dir=tmp_path, starting_cash=100_000.0)
    for tk, pnl in [("MRVL", 6826.47), ("MS", -1844.75), ("NVDA", 431.0)]:
        pb.ledger.record_open(ticker=tk, opened=f"2026-07-15T14:00:00{tk}",
                              strategy="long_call", qty=1, cost_basis=1000, legs=[])
        pb.ledger.record_close(ticker=tk, opened=f"2026-07-15T14:00:00{tk}",
                               close_value=1000 + pnl, pnl=pnl, reason="x")
    # wipe the working book (as corruption/reset would)
    pb._positions = []
    pb._cash = 100_000.0
    assert pb.equity()["realized"] == pytest.approx(6826.47 - 1844.75 + 431.0, abs=0.01)


def test_reconcile_restores_cash_from_ledger(tmp_path):
    pb = PaperBroker(state_dir=tmp_path, starting_cash=100_000.0)
    pb.ledger.record_open(ticker="MRVL", opened="o1", strategy="long_call",
                          qty=1, cost_basis=1000, legs=[])
    pb.ledger.record_close(ticker="MRVL", opened="o1", close_value=7826, pnl=6826.47, reason="target")
    pb._positions.append(pb._pos_from_dict(_position_dict("MPC")))  # one open, basis 350
    pb._cash = 100_000.0 - 350.0
    out = pb.reconcile_from_ledger()
    assert out["cash"] == pytest.approx(100_000.0 + 6826.47 - 350.0, abs=0.01)
    assert out["reconciled_realized"] == pytest.approx(6826.47, abs=0.01)
    # idempotent
    assert pb.reconcile_from_ledger()["cash"] == pytest.approx(out["cash"], abs=0.01)
