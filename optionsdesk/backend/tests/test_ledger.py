"""Ledger: the permanent forward-test record must capture everything and
never break trading."""
from __future__ import annotations

import threading
from datetime import datetime

from optdesk.journal.ledger import Ledger


def make(tmp_path) -> Ledger:
    return Ledger(path=tmp_path / "ledger.db")


def test_marks_roundtrip_and_order(tmp_path):
    led = make(tmp_path)
    for i in range(5):
        led.record_mark(f"2026-07-0{i + 1}T12:00:00", 100_000 + i, 90_000, i * 10.0,
                        open_positions=i, live=i % 2 == 0)
    pts = led.equity_series()
    assert len(pts) == 5
    assert pts[0]["ts"] < pts[-1]["ts"]  # oldest first
    assert pts[-1]["equity"] == 100_004
    assert pts[0]["live"] is True


def test_trade_lifecycle_with_attribution(tmp_path):
    led = make(tmp_path)
    led.record_open(ticker="NVDA", opened="2026-07-01T14:00:00",
                    strategy="bull_put_spread", qty=2, cost_basis=-420.0,
                    legs=[{"kind": "P", "strike": 95.0}],
                    config_id="bull_put_spread@x")
    led.record_close(ticker="NVDA", opened="2026-07-01T14:00:00",
                     close_value=-180.0, pnl=240.0, reason="target",
                     closed="2026-07-09T14:00:00")
    trades = led.trades()
    assert len(trades) == 1
    t = trades[0]
    assert t["config_id"] == "bull_put_spread@x"
    assert t["close_reason"] == "target" and t["pnl"] == 240.0
    assert t["legs"][0]["strike"] == 95.0
    assert led.trades(closed_only=True)[0]["ticker"] == "NVDA"


def test_events_uncapped_beyond_activity_limit(tmp_path):
    """The in-memory activity feed rolls at 200; the ledger must not."""
    led = make(tmp_path)
    for i in range(450):
        led.record_event(f"2026-07-01T00:{i // 60:02d}:{i % 60:02d}",
                         "open", f"event {i}")
    assert led.stats()["events"] == 450
    assert len(led.events(limit=1000)) == 450


def test_promotions_recorded(tmp_path):
    led = make(tmp_path)
    cfg = {"id": "ic@1", "strategy": "iron_condor", "tickers": ["SPY", "QQQ"],
           "params": {"short_delta": 0.16}, "holdout_score": 0.9,
           "holdout_return": 0.02}
    led.record_promotion(ts="2026-07-01T10:00:00", action="promoted", config=cfg)
    led.record_promotion(ts="2026-07-05T10:00:00", action="demoted", config=cfg)
    promos = led.promotions()
    assert [p["action"] for p in promos] == ["demoted", "promoted"]
    assert promos[0]["tickers"] == ["SPY", "QQQ"]


def test_survives_reopen(tmp_path):
    led = make(tmp_path)
    led.record_mark("2026-07-01T12:00:00", 100_000, 100_000, 0.0)
    led2 = make(tmp_path)  # fresh handle on the same file
    assert led2.stats()["marks"] == 1


def test_thread_safety_smoke(tmp_path):
    led = make(tmp_path)

    def writer(k: int) -> None:
        for i in range(50):
            led.record_event(f"2026-07-01T00:00:{i:02d}", "t", f"{k}-{i}")

    threads = [threading.Thread(target=writer, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert led.stats()["events"] == 200


def test_broker_writes_through_to_ledger(tmp_path):
    """A real broker open/close/snapshot must land in its co-located ledger."""
    from datetime import date
    from optdesk.contracts import (Action, Leg, OptionQuote, OptionType,
                                   StrategySpec)
    from optdesk.paper.broker import PaperBroker

    q = OptionQuote("T", date(2026, 7, 1), date(2026, 8, 21), 95.0,
                    OptionType.PUT, 2.0, 2.2, 2.1, 100, 1000, 0.3, -0.3,
                    0.02, -0.03, 0.1, 0.01, 100.0)
    spec = StrategySpec(name="naked_put", ticker="T", asof=date(2026, 7, 1),
                        legs=[Leg(Action.SELL, OptionType.PUT, 95.0,
                                  date(2026, 8, 21))],
                        max_loss=9300.0, max_profit=210.0, pop=0.7,
                        meta={"config_id": "cfg@test"})
    pb = PaperBroker(state_dir=tmp_path, starting_cash=100_000)
    pb.open(spec, [q], qty=1)
    pb.snapshot(live=False, force=True)
    idx = next(i for i, p in enumerate(pb.positions()) if p.status == "OPEN")
    pb.close(idx, reason="stop")

    led = pb.ledger  # co-located: tmp_path/ledger.db
    assert str(tmp_path) in str(led.path)
    st = led.stats()
    assert st["trades"] == 1 and st["closed_trades"] == 1 and st["marks"] >= 1
    t = led.trades()[0]
    assert t["config_id"] == "cfg@test" and t["close_reason"] == "stop"
