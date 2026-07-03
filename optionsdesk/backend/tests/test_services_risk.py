"""
Regression tests for the services layer: learn loop walk-forward hygiene,
risk sizing/budgeting, API serialization + streaming, paper broker parity and
state robustness, and the broker/live-data seams.

Self-contained (no conftest.py): run from optionsdesk/backend with

    python -m pytest tests/test_services_risk.py -q

Sample data is generated on demand if the chain store is empty.
"""
from __future__ import annotations

import json
import math
import time
from datetime import date, timedelta

import numpy as np
import pytest

from optdesk.contracts import BacktestMetrics, BacktestResult, StrategySpec
from optdesk.data.loader import ChainStore
from optdesk.learn.loop import LearningLoop, _HOLDOUT_FRAC, _OBJECTIVES
from optdesk.risk import PositionSizer, RiskBudget, RiskConfig, unit_risk_for


# --------------------------------------------------------------------------- #
# Shared helpers (no conftest — everything lives here)
# --------------------------------------------------------------------------- #
def _store() -> ChainStore:
    store = ChainStore()
    if not store.tickers():
        from optdesk.data import make_sample

        make_sample.main()
        store = ChainStore()
    assert store.tickers(), "sample data generation failed"
    return store


def _spec(ticker: str = "T", max_loss: float = 1000.0, **kw) -> StrategySpec:
    sp = StrategySpec(name="test", ticker=ticker, asof=date(2023, 1, 2), legs=[])
    sp.max_loss = max_loss
    for k, v in kw.items():
        setattr(sp, k, v)
    return sp


class _OpenPos:
    """Minimal open-position stand-in for RiskBudget (duck-typed)."""

    def __init__(self, ticker: str, capital_at_risk: float):
        self.spec = _spec(ticker)
        self.capital_at_risk = capital_at_risk


class _StubBT:
    """Scriptable backtester: returns metrics from a callable, records calls."""

    def __init__(self, metrics_fn):
        self.metrics_fn = metrics_fn
        self.calls: list[tuple[date, date]] = []

    def run(self, name, params, tickers, start, end, **kw):
        self.calls.append((start, end))
        m = self.metrics_fn(len(self.calls), start, end)
        return BacktestResult(config_name=name, metrics=m, params=dict(params))


# --------------------------------------------------------------------------- #
# 1. learn/loop.py — walk-forward hygiene
# --------------------------------------------------------------------------- #
def test_folds_are_strictly_ordered_no_overlap():
    """IS ends strictly before OOS starts; OOS ends strictly before holdout."""
    start, end = date(2023, 1, 2), date(2023, 12, 27)
    s_start, s_end, h_start, h_end = LearningLoop._holdout_split(start, end)
    is_start, is_end, oos_start, oos_end = LearningLoop._fold(s_start, s_end)
    assert is_start == start
    assert is_end < oos_start, "OOS must start strictly after IS ends"
    assert oos_end == s_end
    assert h_start is not None and oos_end < h_start, "holdout must follow OOS"
    assert h_end == end
    # holdout is ~15% of the span
    frac = (h_end - h_start).days / (end - start).days
    assert abs(frac - _HOLDOUT_FRAC) < 0.05


def test_holdout_skipped_for_tiny_ranges():
    s_start, s_end, h_start, h_end = LearningLoop._holdout_split(
        date(2023, 1, 2), date(2023, 1, 10)
    )
    assert (h_start, h_end) == (None, None)
    assert (s_start, s_end) == (date(2023, 1, 2), date(2023, 1, 10))


def test_learn_determinism_same_seed_identical_history():
    store = _store()
    kw = dict(strategy_name="bull_put_spread", tickers=["AAPL"],
              start=date(2023, 2, 1), end=date(2023, 4, 30),
              n_iter=2, objective="sortino", seed=11)
    out1 = LearningLoop(store).run(**kw)
    out2 = LearningLoop(store).run(**kw)
    h1 = [(it.iteration, it.params, it.oos_score, it.is_score, it.accepted)
          for it in out1["history"]]
    h2 = [(it.iteration, it.params, it.oos_score, it.is_score, it.accepted)
          for it in out2["history"]]
    assert h1 == h2
    assert out1["best_params"] == out2["best_params"]
    assert out1["holdout"] == out2["holdout"]


def test_zero_trade_candidates_score_neutral_not_crash():
    store = _store()
    loop = LearningLoop(store)
    loop._bt = _StubBT(lambda n, s, e: BacktestMetrics(start=s, end=e, n_trades=0))
    out = loop.run("bull_put_spread", ["AAPL"], date(2023, 1, 2),
                   date(2023, 12, 27), n_iter=3, seed=1)
    scores = [it.oos_score for it in out["history"]]
    assert scores == [0.0] * len(scores), "zero-trade folds must score neutrally"
    # only the baseline is 'accepted'; no candidate improves on a 0 score
    assert [it.accepted for it in out["history"]] == [True, False, False]


def test_infinite_objective_never_accepted():
    """A candidate scoring +inf (e.g. profit_factor with no losers) is rejected."""
    store = _store()
    loop = LearningLoop(store)

    def metrics(n, s, e):
        pf = 1.0 if n <= 2 else float("inf")  # baseline finite, candidates inf
        return BacktestMetrics(start=s, end=e, n_trades=3, profit_factor=pf)

    loop._bt = _StubBT(metrics)
    out = loop.run("bull_put_spread", ["AAPL"], date(2023, 1, 2),
                   date(2023, 12, 27), n_iter=3, objective="profit_factor", seed=1)
    assert not any(it.accepted for it in out["history"][1:])
    assert out["best_params"] == out["history"][0].params


def test_calmar_objective_uses_drawdown_magnitude():
    """Engine reports max_drawdown as a NEGATIVE number; calmar must use |dd|."""
    m = BacktestMetrics(cagr=0.10, max_drawdown=-0.20)
    assert _OBJECTIVES["calmar"](m) == pytest.approx(0.5)
    flat = BacktestMetrics(cagr=0.10, max_drawdown=0.0)
    assert _OBJECTIVES["calmar"](flat) == pytest.approx(0.10)


def test_holdout_never_touched_during_search_and_reported():
    """No backtest during the search may extend past the search range; the
    holdout window is evaluated exactly once, after the loop, on best_params."""
    store = _store()
    start, end = date(2023, 1, 2), date(2023, 12, 27)
    s_start, s_end, h_start, h_end = LearningLoop._holdout_split(start, end)

    loop = LearningLoop(store)
    loop._bt = _StubBT(
        lambda n, s, e: BacktestMetrics(start=s, end=e, n_trades=2, sortino=0.1)
    )
    out = loop.run("bull_put_spread", ["AAPL"], start, end, n_iter=3, seed=5)

    calls = loop._bt.calls
    search_calls, holdout_calls = calls[:-1], calls[-1:]
    assert all(e <= s_end for (_, e) in search_calls), \
        "a search backtest touched dates beyond the search range (leakage)"
    assert holdout_calls == [(h_start, h_end)], \
        "holdout must be evaluated exactly once, as the final backtest"

    h = out["holdout"]
    assert set(h.keys()) >= {"start", "end", "score", "summary", "note"}
    assert h["start"] == h_start.isoformat() and h["end"] == h_end.isoformat()
    assert isinstance(h["summary"], dict) and "n_trades" in h["summary"]
    assert out["folds"]["holdout"] == [h["start"], h["end"]]
    # pre-existing keys remain intact
    assert {"best_params", "history", "best", "objective", "folds"} <= set(out.keys())


def test_holdout_note_when_range_too_short():
    store = _store()
    loop = LearningLoop(store)
    loop._bt = _StubBT(lambda n, s, e: BacktestMetrics(start=s, end=e))
    out = loop.run("bull_put_spread", ["AAPL"], date(2023, 3, 1),
                   date(2023, 3, 15), n_iter=1, seed=1)
    assert out["holdout"]["summary"] is None
    assert "too short" in out["holdout"]["note"]
    assert out["folds"]["holdout"] is None


# --------------------------------------------------------------------------- #
# 2. risk/budget.py — UNKNOWN-sector lumping
# --------------------------------------------------------------------------- #
def _wide_cfg(**kw) -> RiskConfig:
    base = dict(per_sector_frac=0.10, portfolio_risk_frac=1.0,
                max_position_frac=1.0, per_ticker_frac=1.0, max_concurrent=10)
    base.update(kw)
    return RiskConfig(**base)


def test_unknown_sector_positions_do_not_share_a_bucket():
    """3 open UNKNOWN-sector positions must NOT consume a shared sector budget."""
    cfg = _wide_cfg()  # sector cap = 10% of 100k = 10_000
    budget = RiskBudget(cfg, {})  # empty map -> every ticker is UNKNOWN
    opens = [_OpenPos("AAA", 4000.0), _OpenPos("BBB", 4000.0), _OpenPos("CCC", 4000.0)]
    dec = budget.fit(_spec("DDD"), desired=5, unit_risk=1000.0, equity=100_000.0,
                     open_positions=opens, explain=True)
    assert dec.contracts == 5, f"sector cap spuriously bound: {dec}"
    assert dec.reason == "ok"
    assert dec.caps["sector_remaining"] == pytest.approx(10_000.0), \
        "unknown-sector names leaked into DDD's sector bucket"


def test_unknown_sector_ticker_still_capped_against_itself():
    """The private __<ticker> bucket still caps repeat exposure to one name."""
    cfg = _wide_cfg()
    budget = RiskBudget(cfg, {})
    opens = [_OpenPos("AAA", 9_500.0)]  # AAA already near its own sector cap
    dec = budget.fit(_spec("AAA"), desired=5, unit_risk=1000.0, equity=100_000.0,
                     open_positions=opens, explain=True)
    assert dec.contracts == 0


def test_known_shared_sector_cap_still_binds():
    cfg = _wide_cfg()
    budget = RiskBudget(cfg, {"AAA": "Tech", "BBB": "Tech", "DDD": "Tech"})
    opens = [_OpenPos("AAA", 6000.0), _OpenPos("BBB", 6000.0)]
    dec = budget.fit(_spec("DDD"), desired=5, unit_risk=1000.0, equity=100_000.0,
                     open_positions=opens, explain=True)
    assert dec.contracts == 0
    assert dec.reason == "capped_by_sector"


def test_nan_and_empty_sectors_treated_as_unknown():
    cfg = _wide_cfg()
    budget = RiskBudget(cfg, {"AAA": "nan", "BBB": ""})
    opens = [_OpenPos("AAA", 9000.0), _OpenPos("BBB", 9000.0)]
    dec = budget.fit(_spec("CCC"), desired=3, unit_risk=1000.0, equity=100_000.0,
                     open_positions=opens, explain=True)
    assert dec.contracts == 3, "nan/empty sectors must not form a shared bucket"


# --------------------------------------------------------------------------- #
# 3. risk/sizing.py — unit_risk_for branches + kelly
# --------------------------------------------------------------------------- #
def test_unit_risk_branch_normal_max_loss_used_as_is():
    cfg = RiskConfig()  # default_unit_risk_frac = 0.05 -> fallback 5_000 @ 100k
    assert unit_risk_for(_spec(max_loss=500.0), 100_000.0, cfg) == 500.0
    assert unit_risk_for(_spec(max_loss=24_999.0), 100_000.0, cfg) == 24_999.0
    # boundary: exactly 5x the fallback is still "plausible"
    assert unit_risk_for(_spec(max_loss=25_000.0), 100_000.0, cfg) == 25_000.0


def test_unit_risk_branch_pathological_capped_at_5x_fallback():
    cfg = RiskConfig()
    cap5 = 5 * 0.05 * 100_000.0  # 25_000
    assert unit_risk_for(_spec(max_loss=25_001.0), 100_000.0, cfg) == cap5
    assert unit_risk_for(_spec(max_loss=90_000.0), 100_000.0, cfg) == cap5
    # no cliff: risk is monotone non-decreasing in max_loss around the cap
    below = unit_risk_for(_spec(max_loss=24_999.0), 100_000.0, cfg)
    above = unit_risk_for(_spec(max_loss=25_001.0), 100_000.0, cfg)
    assert above >= below


def test_unit_risk_branch_fallback_for_undefined_risk():
    cfg = RiskConfig()
    for ml in (float("inf"), float("nan"), 0.0, -3.0):
        assert unit_risk_for(_spec(max_loss=ml), 100_000.0, cfg) == 5_000.0
    # floored at $1 for tiny equity
    assert unit_risk_for(_spec(max_loss=0.0), 1.0, cfg) == 1.0


def test_kelly_pop_zero_falls_back_to_fixed_fraction():
    cfg = RiskConfig(method="kelly", risk_per_trade=0.02)
    sizer = PositionSizer(cfg)
    sp = _spec(max_loss=1000.0, pop=0.0, max_profit=500.0)
    assert sizer.desired_contracts(sp, 100_000.0, 1000.0) == 2  # floor(2000/1000)


def test_kelly_negative_edge_gives_zero_contracts():
    cfg = RiskConfig(method="kelly")
    sizer = PositionSizer(cfg)
    sp = _spec(max_loss=1000.0, pop=0.10, max_profit=100.0)  # b=0.1, f* < 0
    assert sizer.desired_contracts(sp, 100_000.0, 1000.0) == 0


def test_kelly_reward_risk_capped_by_kelly_b_cap():
    cfg = RiskConfig(method="kelly", kelly_b_cap=4.0)
    sizer = PositionSizer(cfg)
    inf_profit = _spec(max_loss=1000.0, pop=0.6, max_profit=float("inf"))
    at_cap = _spec(max_loss=1000.0, pop=0.6, max_profit=4000.0)  # b exactly 4
    beyond = _spec(max_loss=1000.0, pop=0.6, max_profit=40_000.0)  # would be b=40
    n_inf = sizer.desired_contracts(inf_profit, 100_000.0, 1000.0)
    assert n_inf == sizer.desired_contracts(at_cap, 100_000.0, 1000.0)
    assert n_inf == sizer.desired_contracts(beyond, 100_000.0, 1000.0)
    assert n_inf > 0


# --------------------------------------------------------------------------- #
# 4. api/main.py — serialization, streaming, error codes
# --------------------------------------------------------------------------- #
def _client():
    from fastapi.testclient import TestClient
    from optdesk.api.main import app

    _store()  # ensure data exists before the app touches the store
    return TestClient(app)


def test_serialize_coerces_numpy_scalars_to_json_safe():
    from optdesk.api.main import serialize

    payload = {
        "i": np.int64(7),
        "f": np.float64(1.5),
        "inf": np.float64(float("inf")),
        "b": np.bool_(True),
        "nested": [{"x": np.int64(3)}],
    }
    out = serialize(payload)
    text = json.dumps(out)  # must not raise
    round_trip = json.loads(text)
    assert round_trip == {"i": 7, "f": 1.5, "inf": None, "b": True,
                          "nested": [{"x": 3}]}


def test_learn_endpoint_end_to_end_json_clean_with_holdout():
    client = _client()
    r = client.post("/api/learn", json={
        "strategy": "bull_put_spread", "tickers": ["AAPL"],
        "start": "2023-02-01", "end": "2023-05-31",
        "n_iter": 2, "objective": "sortino", "seed": 3,
    })
    assert r.status_code == 200, r.text
    body = r.json()  # raises if the payload were not valid JSON
    json.dumps(body)
    assert set(body["folds"].keys()) == {"in_sample", "out_of_sample", "holdout"}
    h = body["holdout"]
    assert set(h.keys()) >= {"start", "end", "score", "summary", "note"}
    assert body["folds"]["out_of_sample"][1] < h["start"], \
        "holdout must begin strictly after the search's OOS fold"
    assert len(body["history"]) == 2


def test_backtest_unknown_strategy_returns_400():
    client = _client()
    r = client.post("/api/backtest", json={
        "strategy": "no_such_strategy", "tickers": ["AAPL"],
        "start": "2023-02-01", "end": "2023-03-01",
    })
    assert r.status_code == 400
    assert "no_such_strategy" in r.json()["detail"]


def test_learn_stream_emits_events_incrementally():
    """First streamed event must arrive well before the full run completes."""
    import asyncio

    from optdesk.api.main import learn_stream

    _store()
    resp = learn_stream("bull_put_spread", "AAPL", "2023-02-01", "2023-05-31",
                        n_iter=3, objective="sortino", seed=7)

    async def consume():
        t0 = time.time()
        arrivals, chunks = [], []
        async for chunk in resp.body_iterator:
            arrivals.append(time.time() - t0)
            chunks.append(chunk)
        return arrivals, chunks, time.time() - t0

    arrivals, chunks, total = asyncio.run(consume())
    data_events = [c for c in chunks if c.startswith("data:")]
    done_events = [c for c in chunks if c.startswith("event: done")]
    assert len(data_events) == 3  # one per iteration (n_iter=3 -> iters 0..2)
    assert len(done_events) == 1
    assert "holdout" in done_events[0]
    # streaming for real: the first event lands before the run is ~2/3 done
    assert arrivals[0] < total * 0.67, (
        f"first event at {arrivals[0]:.2f}s of a {total:.2f}s run — buffered?")


# --------------------------------------------------------------------------- #
# 5. paper/broker.py — round-trip parity + state robustness
# --------------------------------------------------------------------------- #
def _credit_spread_chain():
    from optdesk.strategies.library import STRATEGIES

    store = _store()
    ticker = "AAPL"
    day = store.trading_dates(ticker)[60]
    chain = store.chain(ticker, day)
    spec = STRATEGIES["bull_put_spread"](chain, chain[0].underlying, {})
    assert spec is not None, "sample chain could not build a bull put spread"
    return spec, chain


def test_paper_round_trip_parity(tmp_path):
    """Open -> mark -> close reconciles: cash delta == realized P&L, and no
    money is created or destroyed beyond the modeled spread + commissions."""
    from optdesk.paper.broker import PaperBroker

    spec, chain = _credit_spread_chain()
    start_cash = 100_000.0
    pb = PaperBroker(state_dir=tmp_path, starting_cash=start_cash)

    pos = pb.open(spec, chain, qty=1)
    assert pos.cost_basis < 0, "a credit spread should collect net premium"
    eq_open = pb.equity()
    # at entry the position is marked flat, so total equity == starting cash
    assert eq_open["total"] == pytest.approx(start_cash, abs=0.01)

    pb.mark(chain)  # mark off the same chain we opened on
    closed = pb.close(0)
    eq = pb.equity()

    cash_delta = eq["cash"] - start_cash
    assert cash_delta == pytest.approx(closed.upnl, abs=1e-6), \
        "cash change must equal the realized P&L exactly"
    assert eq["total"] == pytest.approx(eq["cash"], abs=1e-9), \
        "no open positions may contribute to equity after the close"
    # same-day round trip loses only modeled costs (spread crossing + fees):
    # bounded by the full bid/ask spread + commissions on 2 legs, both sides
    cost_model = pb.cost
    per_side_comm = 2 * (cost_model.commission_per_contract
                         + cost_model.exchange_fee_per_contract)
    assert closed.upnl <= 0.0
    assert abs(closed.upnl) < abs(pos.cost_basis) + 2 * per_side_comm + 100.0


def test_paper_state_survives_reload(tmp_path):
    from optdesk.paper.broker import PaperBroker

    spec, chain = _credit_spread_chain()
    pb = PaperBroker(state_dir=tmp_path, starting_cash=50_000.0)
    pb.open(spec, chain, qty=1)
    cash_before = pb.equity()["cash"]

    pb2 = PaperBroker(state_dir=tmp_path, starting_cash=50_000.0)
    assert len(pb2.positions()) == 1
    assert pb2.equity()["cash"] == pytest.approx(cash_before)


def test_paper_recovers_from_corrupt_state_file(tmp_path):
    from optdesk.paper.broker import PaperBroker

    state = tmp_path / "paper.json"
    state.write_text("{ this is not json !!!")
    pb = PaperBroker(state_dir=tmp_path, starting_cash=100_000.0)  # must not raise
    assert pb.positions() == []
    assert pb.equity()["cash"] == pytest.approx(100_000.0)
    backups = list(tmp_path.glob("paper.json.corrupt-*"))
    assert backups, "corrupt state file must be preserved as a backup"
    # and the fresh state file is valid JSON again
    assert json.loads(state.read_text())["cash"] == pytest.approx(100_000.0)


def test_paper_recovers_from_structurally_invalid_state(tmp_path):
    """Valid JSON with the wrong shape must also be handled, not crash."""
    from optdesk.paper.broker import PaperBroker

    (tmp_path / "paper.json").write_text(json.dumps({"positions": [{"bogus": 1}]}))
    pb = PaperBroker(state_dir=tmp_path, starting_cash=100_000.0)
    assert pb.positions() == []
    assert pb.equity()["cash"] == pytest.approx(100_000.0)


# --------------------------------------------------------------------------- #
# 6. brokers/ibkr.py + live/alpha_vantage.py — seams stay safe offline
# --------------------------------------------------------------------------- #
def test_ibkr_imports_cleanly_and_place_guard_raises():
    import dataclasses

    from optdesk.brokers.ibkr import IBKRBroker
    from optdesk.config import SETTINGS

    settings = dataclasses.replace(SETTINGS, live_trading_enabled=False)
    broker = IBKRBroker(settings)
    st = broker.status()  # never raises
    assert set(st.keys()) >= {"connected", "live_enabled", "ib_insync_installed"}
    assert st["connected"] is False

    with pytest.raises(RuntimeError, match="live trading disabled"):
        broker.place(_spec("AAPL"), qty=1)
    assert broker.connect() is False  # refuses to connect while live-disabled
    assert broker.account()["connected"] is False


def test_ibkr_combo_mapping_offline():
    from optdesk.brokers.ibkr import IBKRBroker
    from optdesk.contracts import Action, Leg, OptionType

    broker = IBKRBroker()
    sp = _spec("AAPL")
    sp.legs = [
        Leg(Action.SELL, OptionType.PUT, 100.0, date(2023, 6, 16)),
        Leg(Action.BUY, OptionType.PUT, 95.0, date(2023, 6, 16)),
    ]
    bag = broker.combo_contract(sp)
    assert bag["secType"] == "BAG"
    assert [l["action"] for l in bag["comboLegs"]] == ["SELL", "BUY"]
    with pytest.raises(ValueError):
        broker.combo_contract(sp, leg_conids=[1])  # wrong arity


def test_alpha_vantage_no_key_returns_error_without_network(monkeypatch):
    import httpx

    from optdesk.live.alpha_vantage import AlphaVantage

    def _no_network(*a, **kw):  # any HTTP attempt is a test failure
        raise AssertionError("network call attempted without an API key")

    monkeypatch.setattr(httpx, "get", _no_network)
    av = AlphaVantage(key="")
    assert av.configured is False
    assert "error" in av.quote("AAPL")
    assert "error" in av.realtime_options("AAPL")[0]
    assert av.daily("AAPL").empty


def test_alpha_vantage_http_calls_use_explicit_timeout(monkeypatch):
    import httpx

    from optdesk.live.alpha_vantage import AlphaVantage

    seen: dict = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"Global Quote": {"01. symbol": "AAPL", "05. price": "1.0"}}

    def fake_get(url, params=None, timeout=None, **kw):
        seen["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr(httpx, "get", fake_get)
    av = AlphaVantage(key="dummy", timeout=9.5)
    out = av.quote("AAPL")
    assert seen["timeout"] == 9.5, "httpx call must carry an explicit timeout"
    assert out["symbol"] == "AAPL"


def test_unit_risk_branch_risk_basis_preferred():
    """Builders that declare meta['risk_basis'] (covered_call, short_straddle)
    size on it regardless of max_loss — including max_loss = inf."""
    cfg = RiskConfig()
    sp = _spec(max_loss=float("inf"))
    sp.meta["risk_basis"] = 1_728.0
    assert unit_risk_for(sp, 100_000.0, cfg) == 1_728.0
    sp2 = _spec(max_loss=18_000.0)          # stock-to-zero style
    sp2.meta["risk_basis"] = 2_000.0
    assert unit_risk_for(sp2, 100_000.0, cfg) == 2_000.0
    # degenerate risk_basis values fall through to the max_loss branches
    for bad in (0.0, -1.0, float("nan"), float("inf")):
        sp3 = _spec(max_loss=500.0)
        sp3.meta["risk_basis"] = bad
        assert unit_risk_for(sp3, 100_000.0, cfg) == 500.0


def test_covered_call_and_straddle_declare_risk_basis():
    """covered_call must be sizeable (it produced 0 trades everywhere before
    risk_basis existed) and short_straddle must report honest unbounded
    max_loss while sizing on a finite 2-sigma basis."""
    from optdesk.backtest.engine import _underlying
    from optdesk.strategies.library import STRATEGIES

    store = _store()
    tk = store.tickers()[0]
    day = store.trading_dates(tk)[5]
    chain = store.chain(tk, day)
    und = _underlying(chain)

    cc = STRATEGIES["covered_call"](chain, und, {})
    assert cc is not None
    rb = cc.meta["risk_basis"]
    assert 0 < rb < cc.max_loss          # far below stock-to-zero

    ss = STRATEGIES["short_straddle"](chain, und, {})
    assert ss is not None
    assert ss.max_loss == float("inf")   # honest: undefined risk
    assert 0 < ss.meta["risk_basis"] < float("inf")
