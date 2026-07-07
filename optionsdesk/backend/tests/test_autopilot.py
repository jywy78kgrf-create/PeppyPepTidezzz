"""AutoPilot safety + closed-loop behavior, fully faked (no real learn/AV)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from optdesk.auto.pilot import AutoConfig, AutoPilot
from optdesk.contracts import PaperPosition


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeBroker:
    """Minimal PaperBroker stand-in with scriptable marks."""

    def __init__(self, total: float = 100_000.0):
        self._positions: list[PaperPosition] = []
        self.total = total
        self.opened_specs: list = []
        self.closed_idx: list[int] = []

    def mark_live(self, av, store=None):
        return {"live": False}

    def snapshot(self, live=False, force=False):
        return None

    def positions(self):
        return list(self._positions)

    def equity(self):
        return {"total": self.total, "cash": self.total, "upnl": 0.0}

    def open(self, spec, chain, qty=1):
        pos = PaperPosition(
            ticker=spec.ticker, spec_name=spec.name,
            opened=datetime(2026, 7, 1, 12, 0, 0),
            legs=[], cost_basis=100.0 * qty, current_value=100.0 * qty,
            upnl=0.0, status="OPEN",
        )
        self._positions.append(pos)
        self.opened_specs.append((spec, qty))
        return pos

    def close(self, idx):
        pos = self._positions[idx]
        pos.status = "CLOSED"
        self.closed_idx.append(idx)
        return pos


class FakeStore:
    """Two tickers, ten trading days, one liquid put chain per day."""

    def __init__(self):
        from optdesk.contracts import OptionQuote, OptionType
        # 60 trading days ending well before expiry (research needs >= 40)
        self.days = [date(2026, 4, 1) + timedelta(days=i) for i in range(60)]
        self.expiry = date(2026, 7, 17)
        self._q = OptionQuote
        self._ot = OptionType

    def tickers(self):
        return ["AAA", "BBB"]

    def trading_dates(self, tk):
        return list(self.days)

    def chain(self, tk, asof):
        def mk(k, kind, dl):
            return self._q(tk, asof, self.expiry, k, kind, 1.0, 1.2, 1.1,
                           500, 5000, 0.3, dl, 0.02, -0.03, 0.1, 0.01, 100.0)
        # liquid strikes on BOTH sides so every strategy builder can construct
        return [
            mk(95.0, self._ot.PUT, -0.30), mk(90.0, self._ot.PUT, -0.15),
            mk(85.0, self._ot.PUT, -0.08),
            mk(105.0, self._ot.CALL, 0.30), mk(110.0, self._ot.CALL, 0.15),
            mk(115.0, self._ot.CALL, 0.08), mk(100.0, self._ot.CALL, 0.50),
        ]

    @property
    def universe(self):
        import pandas as pd
        return pd.DataFrame({"ticker": ["AAA", "BBB"], "sector": ["Tech", "Tech"]})


def good_learn(strategy, tickers, start, end):
    return {"best_params": {"short_delta": 0.3},
            "holdout": {"score": 1.2, "summary": {"total_return": 0.04}}}


def bad_learn(strategy, tickers, start, end):
    return {"best_params": {}, "holdout": {"score": 0.05,
                                           "summary": {"total_return": -0.01}}}


def make_pilot(tmp_path: Path, broker: FakeBroker, learn=good_learn,
               cfg: AutoConfig | None = None) -> AutoPilot:
    store = FakeStore()
    # opens now come from a LIVE chain provider (not the historical store);
    # the fake feeds the store's own chain through that seam so the trade
    # cycle behaves as before without any real Alpha Vantage traffic.
    return AutoPilot(
        store=store,
        config=cfg or AutoConfig(research_interval_hr=0, trade_interval_min=0),
        state_path=tmp_path / "auto.json",
        broker_factory=lambda: broker,
        av_factory=lambda: None,
        learn_fn=learn,
        live_chain_fn=lambda tk: store.chain(tk, store.trading_dates(tk)[-1]),
        now_fn=lambda: datetime(2026, 7, 1, 14, 0, 0),
    )


# --------------------------------------------------------------------------- #
# Kill switch & no-ops
# --------------------------------------------------------------------------- #
def test_disabled_pilot_does_nothing(tmp_path):
    broker = FakeBroker()
    pilot = make_pilot(tmp_path, broker)
    pilot.tick()
    assert broker.opened_specs == [] and broker.closed_idx == []
    assert pilot.status()["enabled"] is False


def test_disable_takes_effect_before_next_tick(tmp_path):
    broker = FakeBroker()
    pilot = make_pilot(tmp_path, broker)
    pilot.enable()
    pilot.disable("test kill")
    pilot.tick()
    assert broker.opened_specs == []
    assert pilot.status()["enabled"] is False


# --------------------------------------------------------------------------- #
# Research -> promotion bar
# --------------------------------------------------------------------------- #
def test_promotion_requires_holdout_bar(tmp_path):
    pilot = make_pilot(tmp_path, FakeBroker(), learn=bad_learn)
    pilot.enable()
    entry = pilot.run_research_batch()
    assert entry is None
    assert pilot.status()["promoted"] == []


def test_promotion_on_good_holdout(tmp_path):
    pilot = make_pilot(tmp_path, FakeBroker(), learn=good_learn)
    pilot.enable()
    entry = pilot.run_research_batch()
    assert entry is not None and entry["holdout_score"] == 1.2
    assert len(pilot.status()["promoted"]) == 1


# --------------------------------------------------------------------------- #
# Trade cycle: opens bounded, managed, cooldown
# --------------------------------------------------------------------------- #
def test_opens_capped_and_managed(tmp_path):
    broker = FakeBroker()
    cfg = AutoConfig(research_interval_hr=0, trade_interval_min=0,
                     max_opens_per_cycle=1)
    pilot = make_pilot(tmp_path, broker, cfg=cfg)
    pilot.enable()
    pilot.run_research_batch()
    pilot.run_trade_cycle()
    assert len(broker.opened_specs) == 1  # capped per cycle
    assert pilot.status()["managed_positions"] == 1
    # second cycle: same ticker on cooldown, other ticker opens
    pilot.run_trade_cycle()
    assert len(broker.opened_specs) == 2
    tickers = {s.ticker for s, _ in broker.opened_specs}
    assert tickers == {"AAA", "BBB"}


def test_never_touches_user_positions(tmp_path):
    broker = FakeBroker()
    user_pos = PaperPosition(ticker="ZZZ", spec_name="manual",
                             opened=datetime(2026, 6, 1), legs=[],
                             cost_basis=50.0, current_value=10_000.0,
                             upnl=9_950.0, status="OPEN")
    broker._positions.append(user_pos)
    pilot = make_pilot(tmp_path, broker, learn=bad_learn)
    pilot.enable()
    pilot.run_trade_cycle()
    assert broker.closed_idx == []  # huge upnl but unmanaged -> untouched


# --------------------------------------------------------------------------- #
# Exits: target / stop / dte via managed records
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("upnl,expected", [(999_999.0, "target"),
                                           (-999_999.0, "stop")])
def test_exit_target_and_stop(tmp_path, upnl, expected):
    broker = FakeBroker()
    pilot = make_pilot(tmp_path, broker)
    pilot.enable()
    pilot.run_research_batch()
    pilot.run_trade_cycle()
    pos = broker.positions()[0]
    pos.upnl = upnl
    pilot.run_trade_cycle()
    assert pos.status == "CLOSED"
    acts = [a for a in pilot.activity() if a["kind"] == "close"]
    assert acts and expected in acts[0]["detail"]


def test_exit_close_dte(tmp_path):
    broker = FakeBroker()
    pilot = make_pilot(tmp_path, broker)
    pilot.enable()
    pilot.run_research_batch()
    pilot.run_trade_cycle()
    # jump past close_by (expiry 2026-07-17, close_dte 7 -> 07-10) to the
    # next MONDAY 10:00 ET — trade cycles are market-hours gated
    pilot.now_fn = lambda: datetime(2026, 7, 13, 14, 0, 0)
    pilot.run_trade_cycle()
    assert broker.positions()[0].status == "CLOSED"


# --------------------------------------------------------------------------- #
# Circuit breaker + feedback demotion
# --------------------------------------------------------------------------- #
def test_circuit_breaker_trips_and_disables(tmp_path):
    broker = FakeBroker(total=100_000.0)
    pilot = make_pilot(tmp_path, broker)
    pilot.enable()
    pilot.run_trade_cycle()          # anchors the day at 100k
    broker.total = 90_000.0          # -10% intraday
    pilot.run_trade_cycle()
    st = pilot.status()
    assert st["breaker"]["tripped"] is True
    assert st["enabled"] is False
    n_opened = len(broker.opened_specs)
    pilot.tick()                     # tripped -> full no-op
    assert len(broker.opened_specs) == n_opened
    pilot.enable()                   # human re-enable clears the breaker
    assert pilot.status()["breaker"]["tripped"] is False


def test_demotion_after_consecutive_losses(tmp_path):
    broker = FakeBroker()
    cfg = AutoConfig(research_interval_hr=0, trade_interval_min=0,
                     demote_after_losses=2, ticker_cooldown_hr=0,
                     max_opens_per_cycle=1)
    pilot = make_pilot(tmp_path, broker, cfg=cfg)
    pilot.enable()
    pilot.run_research_batch()
    for _ in range(2):  # open -> force a losing stop -> close
        pilot.run_trade_cycle()
        open_pos = [p for p in broker.positions() if p.status == "OPEN"]
        assert open_pos, "expected an open position"
        open_pos[0].upnl = -999_999.0
        pilot.run_trade_cycle()
    promoted = pilot.status()["promoted"][0]
    assert promoted["active"] is False
    assert promoted["closed_trades"] == 2


def test_state_persists_across_instances(tmp_path):
    broker = FakeBroker()
    pilot = make_pilot(tmp_path, broker)
    pilot.enable()
    pilot.run_research_batch()
    pilot2 = make_pilot(tmp_path, FakeBroker())
    st = pilot2.status()
    assert st["enabled"] is True
    assert len(st["promoted"]) == 1


# --------------------------------------------------------------------------- #
# Quant-critique upgrades: promotion robustness + VRP gate
# --------------------------------------------------------------------------- #
def test_promotion_rejected_on_too_few_holdout_trades(tmp_path):
    def thin_learn(strategy, tickers, start, end):
        return {"best_params": {}, "holdout": {"score": 2.0, "summary": {
            "total_return": 0.05, "n_trades": 2, "max_drawdown": -0.02}}}
    pilot = make_pilot(tmp_path, FakeBroker(), learn=thin_learn)
    pilot.enable()
    assert pilot.run_research_batch() is None
    assert pilot.status()["promoted"] == []


def test_promotion_rejected_on_deep_holdout_drawdown(tmp_path):
    def dd_learn(strategy, tickers, start, end):
        return {"best_params": {}, "holdout": {"score": 2.0, "summary": {
            "total_return": 0.05, "n_trades": 20, "max_drawdown": -0.40}}}
    pilot = make_pilot(tmp_path, FakeBroker(), learn=dd_learn)
    pilot.enable()
    assert pilot.run_research_batch() is None


def test_promotion_accepts_robust_holdout(tmp_path):
    def robust_learn(strategy, tickers, start, end):
        return {"best_params": {}, "holdout": {"score": 1.0, "summary": {
            "total_return": 0.03, "n_trades": 25, "max_drawdown": -0.06}}}
    pilot = make_pilot(tmp_path, FakeBroker(), learn=robust_learn)
    pilot.enable()
    assert pilot.run_research_batch() is not None


def test_vrp_gate_blocks_short_premium_when_negative(tmp_path):
    """With IV (0.3 in the fake chain) below a forced realized vol, short
    premium must be skipped; long premium is unaffected."""
    pilot = make_pilot(tmp_path, FakeBroker())
    # monkeypatch the vrp helper the pilot imports lazily
    import optdesk.signals.equity as sig
    orig = sig.vrp
    sig.vrp = lambda chain, tk, day, **kw: -0.10
    try:
        assert pilot._vrp_ok([], "AAA", date(2026, 6, 1), "bull_put_spread") is False
        assert pilot._vrp_ok([], "AAA", date(2026, 6, 1), "long_call") is True
        sig.vrp = lambda chain, tk, day, **kw: 0.08
        assert pilot._vrp_ok([], "AAA", date(2026, 6, 1), "bull_put_spread") is True
        sig.vrp = lambda chain, tk, day, **kw: None  # unknowable -> pass-through
        assert pilot._vrp_ok([], "AAA", date(2026, 6, 1), "short_straddle") is True
    finally:
        sig.vrp = orig


# --------------------------------------------------------------------------- #
# Research telemetry (the UI's engine view)
# --------------------------------------------------------------------------- #
def test_research_status_idle_shape(tmp_path):
    pilot = make_pilot(tmp_path, FakeBroker())
    st = pilot.research_status()
    assert st["current"]["active"] is False
    assert st["last"] is None
    assert st["batches_done"] == 0
    # 9 strategies x ceil(2 tickers / 6 per batch) = 9 batches per sweep
    assert st["sweep_total"] > 0


def test_research_batch_finalizes_telemetry(tmp_path):
    pilot = make_pilot(tmp_path, FakeBroker(), learn=good_learn)
    pilot._state["enabled"] = True
    pilot.run_research_batch()
    st = pilot.research_status()
    assert st["current"]["active"] is False       # never left armed
    last = st["last"]
    assert last is not None
    assert last["strategy"] and last["tickers"]
    assert last["verdict"] == "promoted"          # good_learn clears the bar
    assert st["batches_done"] == 1


def test_research_verdict_rejected(tmp_path):
    pilot = make_pilot(tmp_path, FakeBroker(), learn=bad_learn)
    pilot._state["enabled"] = True
    pilot.run_research_batch()
    last = pilot.research_status()["last"]
    assert last["verdict"] is not None and last["verdict"].startswith("rejected")


def test_on_research_iter_appends_only_while_active(tmp_path):
    pilot = make_pilot(tmp_path, FakeBroker())

    class It:
        iteration, oos_score, is_score, accepted = 1, 0.5, 0.6, True
        metrics = {"n_trades": 7}

    pilot._on_research_iter(It())                 # engine idle -> ignored
    assert pilot.research_status()["current"].get("iterations") == []
    pilot._research_live = {"active": True, "iterations": []}
    pilot._on_research_iter(It())
    cur = pilot.research_status()["current"]
    assert len(cur["iterations"]) == 1
    assert cur["iterations"][0]["n_trades"] == 7
    assert cur["trades_simulated"] == 7


# --------------------------------------------------------------------------- #
# Trading and research are independent heartbeats (no starvation)
# --------------------------------------------------------------------------- #
def test_trade_tick_does_not_run_research(tmp_path):
    """A trade-cycle tick must NEVER trigger a research batch — otherwise a
    long batch blocks trading (the delayed-trades bug)."""
    broker = FakeBroker()
    calls = []

    def learn(s, t, st, e):
        calls.append(1)
        return good_learn(s, t, st, e)

    pilot = make_pilot(tmp_path, broker, learn=learn)
    pilot.enable()
    pilot.tick()
    assert calls == [], "trade tick must not invoke research"


def test_research_tick_runs_research_only(tmp_path):
    broker = FakeBroker()
    calls = []

    def learn(s, t, st, e):
        calls.append(1)
        return good_learn(s, t, st, e)

    pilot = make_pilot(tmp_path, broker, learn=learn)
    pilot.enable()
    pilot.research_tick()
    assert calls == [1]
    # research must not open trades either
    assert broker.opened_specs == []


def test_trade_tick_opens_promoted_without_waiting_on_research(tmp_path):
    """Once a config is promoted, the trade heartbeat opens it immediately —
    it does not wait behind a research batch."""
    broker = FakeBroker()
    pilot = make_pilot(tmp_path, broker)
    pilot.enable()
    pilot.run_research_batch()          # populate a promoted config
    assert pilot._state["promoted"], "good_learn should have promoted one"
    pilot.tick()                        # trade cycle fires on its own
    assert broker.opened_specs, "trade tick should open from the promoted config"
