"""
Tests for the Phase-2 signals module (optdesk/signals) and the learn-loop
regime analytics (optdesk/learn/loop.py "regimes" key).

Self-contained: equity fixtures are tiny Parquet files (columns
[date, open, high, low, close, adj_close, volume]) written into pytest tmp
dirs and read through ``EquityStore(equity_dir=tmpdir)`` — no dependency on
real data.  Option-chain fixtures reuse the FakeStore pattern from
test_quant_backtest.py.

Covers (per the Phase-2 contract):
  * bullish strategy blocked below SMA50, allowed above; bearish mirrored;
    neutral strategies trend-free.
  * short-premium blocked at high 20d-realized-vol percentile
    (rv_entry_max_pct); long-premium blocked at low percentile
    (rv_entry_min_pct); both thresholds overridable via params.
  * per-ticker pass-through when equity data is missing; gate is None when
    NO ticker has equity data.
  * NO LOOKAHEAD: the gate's answer for day D is unchanged when every equity
    row dated >= D is deleted (decisions use data through D-1 only).
  * learn-loop "regimes": {low,mid,high: {days,total_return,sharpe,
    max_drawdown}} shape, tercile partition of the best-params run's
    equity-curve days, null when no equity data, and determinism
    (same seed -> identical result including regimes).
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd
import pytest

from optdesk.contracts import BacktestMetrics, BacktestResult, EquityPoint, OptionQuote, OptionType
from optdesk.data.loader import EquityStore
from optdesk.learn.loop import LearningLoop, _regime_stats
from optdesk.signals import SignalGate, build_default_gate, indicator_frame

C, P = OptionType.CALL, OptionType.PUT


# --------------------------------------------------------------------------- #
# Fixture helpers
# --------------------------------------------------------------------------- #
def write_equity(dirpath, ticker: str, closes, start: date = date(2023, 1, 2)):
    """Write a per-ticker OHLCV Parquet fixture (importer's exact columns)."""
    dates = pd.bdate_range(start, periods=len(closes))
    df = pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": closes,
        "high": [c * 1.005 for c in closes],
        "low": [c * 0.995 for c in closes],
        "close": closes,
        "adj_close": closes,
        "volume": [1_000_000] * len(closes),
    })
    df.to_parquet(dirpath / f"{ticker.upper()}.parquet", index=False)
    return [d.date() for d in dates]


def steady_riser(n: int, rate: float = 1.002) -> list[float]:
    """Monotonic uptrend with constant log-return (rv20 == 0, pct == 0.5)."""
    return [100.0 * (rate ** i) for i in range(n)]


def steady_faller(n_flat: int = 60, n_down: int = 40) -> list[float]:
    """Flat then sliding well below its own SMA50."""
    return [100.0] * n_flat + [100.0 - 0.8 * i for i in range(1, n_down + 1)]


def vol_spike(n_calm: int = 200, n_wild: int = 21) -> list[float]:
    """Long calm uptrend then violent +-swings (rv pct >> 0.85 at the end,
    close still above SMA50 so the vol rule is isolated from the trend rule)."""
    closes = [100.0 * (1.001 ** i) for i in range(n_calm)]
    lvl = closes[-1]
    for i in range(n_wild):
        closes.append(lvl * (1.06 if i % 2 == 0 else 0.98))
    return closes


def vol_crush(n: int = 120) -> list[float]:
    """Decaying oscillation: realized vol strictly shrinking (rv pct ~ 0)."""
    closes, amp = [], 0.05
    for i in range(n):
        amp *= 0.96
        closes.append(100.0 * (1 + (amp if i % 2 == 0 else -amp)))
    return closes


def day_after(days: list[date]) -> date:
    return days[-1] + timedelta(days=1)


# --------------------------------------------------------------------------- #
# indicator_frame
# --------------------------------------------------------------------------- #
def test_indicator_frame_columns_and_warmup(tmp_path):
    days = write_equity(tmp_path, "UP", steady_riser(120))
    store = EquityStore(equity_dir=tmp_path)
    f = indicator_frame("UP", store)
    assert list(f.columns) == ["date", "close", "sma50", "sma200", "rv20", "rv20_pct"]
    assert list(f["date"]) == days
    assert f["sma50"].isna().sum() == 49          # warm-up: NaN before 50 obs
    assert f["sma200"].isna().all()               # only 120 rows
    assert f["rv20"].notna().iloc[-1]
    # constant growth => rv20 ~ 0 and an all-tied window mid-ranks to 0.5
    assert f["rv20"].iloc[-1] == pytest.approx(0.0, abs=1e-9)
    assert f["rv20_pct"].iloc[-1] == pytest.approx(0.5, abs=0.2)
    assert f["close"].iloc[-1] > f["sma50"].iloc[-1]


# --------------------------------------------------------------------------- #
# Trend rule
# --------------------------------------------------------------------------- #
def test_bullish_blocked_below_sma50(tmp_path):
    days = write_equity(tmp_path, "DN", steady_faller())
    store = EquityStore(equity_dir=tmp_path)
    f = indicator_frame("DN", store)
    assert f["close"].iloc[-1] < f["sma50"].iloc[-1]  # premise: below SMA50
    gate = SignalGate(["DN"], {}, equity_store=store)
    d = day_after(days)
    # long_call is bullish + long-premium; the falling tail RAISES rv pct, so
    # the vol rule (pct >= 0.10) passes and the trend rule is the blocker.
    assert f["rv20_pct"].iloc[-1] >= 0.10
    assert gate.allow("DN", d, "long_call") is False
    assert gate.allow("DN", d, "bull_put_spread") is False   # bullish too
    assert gate.allow("DN", d, "long_put") is True           # bearish: close < SMA50


def test_bullish_allowed_above_sma50_and_bearish_blocked(tmp_path):
    days = write_equity(tmp_path, "UP", steady_riser(120))
    store = EquityStore(equity_dir=tmp_path)
    f = indicator_frame("UP", store)
    assert f["close"].iloc[-1] > f["sma50"].iloc[-1]  # premise: above SMA50
    gate = SignalGate(["UP"], {}, equity_store=store)
    d = day_after(days)
    for bullish in ("long_call", "bull_put_spread", "covered_call", "calendar_call"):
        assert gate.allow("UP", d, bullish) is True, bullish
    for bearish in ("long_put", "bear_call_spread"):
        assert gate.allow("UP", d, bearish) is False, bearish


def test_neutral_strategies_have_no_trend_filter(tmp_path):
    days = write_equity(tmp_path, "DN", steady_faller())
    store = EquityStore(equity_dir=tmp_path)
    f = indicator_frame("DN", store)
    assert f["close"].iloc[-1] < f["sma50"].iloc[-1]
    pct = f["rv20_pct"].iloc[-1]
    assert 0.10 <= pct <= 0.85  # premise: vol rule passes for both premia
    gate = SignalGate(["DN"], {}, equity_store=store)
    d = day_after(days)
    for neutral in ("iron_condor", "short_straddle", "long_strangle"):
        assert gate.allow("DN", d, neutral) is True, neutral


# --------------------------------------------------------------------------- #
# Vol-regime rule
# --------------------------------------------------------------------------- #
def test_short_premium_blocked_at_high_rv_percentile(tmp_path):
    days = write_equity(tmp_path, "SPK", vol_spike())
    store = EquityStore(equity_dir=tmp_path)
    f = indicator_frame("SPK", store)
    assert f["rv20_pct"].iloc[-1] > 0.85          # premise: high-vol regime
    assert f["close"].iloc[-1] > f["sma50"].iloc[-1]  # trend rule not the blocker
    gate = SignalGate(["SPK"], {}, equity_store=store)
    d = day_after(days)
    for short_prem in ("iron_condor", "short_straddle", "bull_put_spread",
                       "bear_call_spread", "covered_call"):
        assert gate.allow("SPK", d, short_prem) is False, short_prem
    # long premium WANTS high vol-of-entry percentile
    assert gate.allow("SPK", d, "long_strangle") is True
    assert gate.allow("SPK", d, "long_call") is True


def test_long_premium_blocked_at_low_rv_percentile(tmp_path):
    days = write_equity(tmp_path, "CRS", vol_crush())
    store = EquityStore(equity_dir=tmp_path)
    f = indicator_frame("CRS", store)
    assert f["rv20_pct"].iloc[-1] < 0.10          # premise: vol crushed
    gate = SignalGate(["CRS"], {}, equity_store=store)
    d = day_after(days)
    assert gate.allow("CRS", d, "long_strangle") is False  # neutral: vol is the blocker
    assert gate.allow("CRS", d, "iron_condor") is True     # short premium loves it


def test_rv_thresholds_overridable_via_params(tmp_path):
    days = write_equity(tmp_path, "SPK", vol_spike())
    store = EquityStore(equity_dir=tmp_path)
    d = day_after(days)
    strict = SignalGate(["SPK"], {"rv_entry_max_pct": 0.85}, equity_store=store)
    lax = SignalGate(["SPK"], {"rv_entry_max_pct": 0.999}, equity_store=store)
    assert strict.allow("SPK", d, "iron_condor") is False
    assert lax.allow("SPK", d, "iron_condor") is True
    # min side
    write_equity(tmp_path, "CRS", vol_crush())
    hungry = SignalGate(["CRS"], {"rv_entry_min_pct": 0.0}, equity_store=store)
    assert hungry.allow("CRS", d, "long_strangle") is True


# --------------------------------------------------------------------------- #
# Pass-through semantics
# --------------------------------------------------------------------------- #
def test_missing_equity_ticker_passes_through(tmp_path):
    days = write_equity(tmp_path, "HAS", steady_faller())
    store = EquityStore(equity_dir=tmp_path)
    gate = build_default_gate(["HAS", "MISS"], {}, equity_store=store)
    assert gate is not None
    d = day_after(days)
    # HAS is filtered normally...
    assert gate.allow("HAS", d, "long_call") is False
    # ...but the equity-less ticker is never blocked, any strategy, any day.
    for strat in ("long_call", "iron_condor", "long_put", "short_straddle"):
        assert gate.allow("MISS", d, strat) is True, strat
        assert gate.allow("MISS", date(1990, 1, 2), strat) is True


def test_gate_none_when_no_ticker_has_equity(tmp_path):
    store = EquityStore(equity_dir=tmp_path)  # empty dir
    assert build_default_gate(["AAA", "BBB"], {}, equity_store=store) is None
    assert build_default_gate([], {}, equity_store=store) is None


def test_no_history_before_day_passes_through(tmp_path):
    days = write_equity(tmp_path, "UP", steady_riser(120))
    store = EquityStore(equity_dir=tmp_path)
    gate = SignalGate(["UP"], {}, equity_store=store)
    # decision on (or before) the very first equity date: nothing strictly
    # before it -> pass-through, never an exception
    assert gate.allow("UP", days[0], "long_put") is True
    assert gate.allow("UP", days[0] - timedelta(days=30), "long_put") is True


# --------------------------------------------------------------------------- #
# NO LOOKAHEAD: day-D decision must not read rows dated >= D
# --------------------------------------------------------------------------- #
def test_no_lookahead_day_d_decision_survives_deleting_rows_from_d(tmp_path):
    """The gate's answer for day D is UNCHANGED when all equity rows >= D are
    deleted — i.e. the decision uses data through D-1 only.  The fixture makes
    the day-D row decision-flipping: a 50% crash prints ON day D, so any
    implementation that peeks at row D (close < SMA50, rv exploding) would
    block bullish/short-premium entries that the D-1 view allows."""
    full_dir = tmp_path / "full"
    trunc_dir = tmp_path / "trunc"
    full_dir.mkdir()
    trunc_dir.mkdir()

    rise = steady_riser(100, rate=1.003)
    crashed = rise + [rise[-1] * 0.5]              # 50% crash on the final bar
    all_days = write_equity(full_dir, "NL", crashed)
    D = all_days[-1]                                # decision day == crash day
    write_equity(trunc_dir, "NL", rise)             # every row >= D deleted

    g_full = SignalGate(["NL"], {}, equity_store=EquityStore(equity_dir=full_dir))
    g_trunc = SignalGate(["NL"], {}, equity_store=EquityStore(equity_dir=trunc_dir))

    strategies = ["bull_put_spread", "bear_call_spread", "iron_condor",
                  "long_call", "long_put", "covered_call", "calendar_call",
                  "short_straddle", "long_strangle"]
    for s in strategies:
        assert g_full.allow("NL", D, s) == g_trunc.allow("NL", D, s), s

    # Premise checks: through D-1 the trend is UP (bullish allowed) while the
    # row AT D — if leaked — flips it (close far below SMA50).
    assert g_full.allow("NL", D, "long_call") is True
    f = indicator_frame("NL", EquityStore(equity_dir=full_dir))
    row_at_d = f.iloc[-1]
    assert row_at_d["date"] == D
    assert row_at_d["close"] < row_at_d["sma50"], \
        "fixture must make the day-D row decision-flipping"
    # And the day AFTER D the crash is legitimately visible (no over-shift).
    assert g_full.allow("NL", D + timedelta(days=1), "long_call") is False


# --------------------------------------------------------------------------- #
# Learn-loop regimes: unit level
# --------------------------------------------------------------------------- #
def _growing_vol_closes(n: int = 160) -> list[float]:
    closes, lvl = [], 100.0
    for i in range(n):
        amp = 0.001 + 0.0006 * i        # daily swing grows over time
        lvl *= (1 + amp) if i % 2 == 0 else (1 - 0.8 * amp)
        closes.append(lvl)
    return closes


def _loop_with_equity(equity_dir) -> LearningLoop:
    loop = LearningLoop.__new__(LearningLoop)   # only _regimes is exercised
    loop._equity = EquityStore(equity_dir=equity_dir)
    return loop


def _curve_result(days: list[date], equities: list[float]) -> BacktestResult:
    curve = [EquityPoint(asof=d, equity=e, cash=e, open_positions=0)
             for d, e in zip(days, equities)]
    return BacktestResult(config_name="x", metrics=BacktestMetrics(),
                          equity_curve=curve)


def test_regimes_shape_and_tercile_partition(tmp_path):
    days = write_equity(tmp_path, "EQT", _growing_vol_closes(), start=date(2023, 1, 2))
    loop = _loop_with_equity(tmp_path)
    curve_days = days[60:150]                     # rv20 defined on every day
    equities = [100_000.0 * (1 + 0.001 * i) for i in range(len(curve_days))]
    reg = loop._regimes(_curve_result(curve_days, equities), ["EQT", "NOEQ"])
    assert reg is not None
    assert set(reg) == {"low", "mid", "high"}
    for k in ("low", "mid", "high"):
        assert set(reg[k]) == {"days", "total_return", "sharpe", "max_drawdown"}
        assert reg[k]["days"] >= 0
        assert reg[k]["max_drawdown"] <= 0.0
        for v in reg[k].values():
            assert math.isfinite(v)
    # every return day is classified, split into near-equal terciles
    total = sum(reg[k]["days"] for k in reg)
    assert total == len(curve_days) - 1
    assert max(reg[k]["days"] for k in reg) - min(reg[k]["days"] for k in reg) <= 2


def test_regimes_null_cases(tmp_path):
    days = write_equity(tmp_path, "EQT", _growing_vol_closes())
    loop_no_data = _loop_with_equity(tmp_path / "nothing_here")
    curve_days = days[60:80]
    equities = [100_000.0] * len(curve_days)
    res = _curve_result(curve_days, equities)
    # no equity data at all -> null
    assert loop_no_data._regimes(res, ["EQT"]) is None
    loop = _loop_with_equity(tmp_path)
    # equity exists but curve too short -> null
    assert loop._regimes(_curve_result(curve_days[:1], equities[:1]), ["EQT"]) is None
    # equity exists but never overlaps the run range -> null
    far = [date(1999, 1, 4) + timedelta(days=i) for i in range(10)]
    assert loop._regimes(_curve_result(far, [100_000.0] * 10), ["EQT"]) is None


def test_regime_stats_math():
    assert _regime_stats([]) == {"days": 0, "total_return": 0.0,
                                 "sharpe": 0.0, "max_drawdown": 0.0}
    s = _regime_stats([0.10, -0.50])
    assert s["days"] == 2
    assert s["total_return"] == pytest.approx(1.10 * 0.50 - 1.0, abs=1e-9)
    assert s["max_drawdown"] == pytest.approx(-0.50)
    flat = _regime_stats([0.0, 0.0, 0.0])
    assert flat["sharpe"] == 0.0 and flat["max_drawdown"] == 0.0


# --------------------------------------------------------------------------- #
# Learn-loop regimes: end-to-end through run() with a real Backtester
# --------------------------------------------------------------------------- #
def _q(ticker, asof, expiry, strike, kind, mid, underlying, delta):
    return OptionQuote(ticker=ticker, asof=asof, expiry=expiry, strike=strike,
                       kind=kind, bid=round(max(0.01, mid - 0.05), 4),
                       ask=round(mid + 0.05, 4), last=mid, volume=500,
                       open_interest=1000, iv=0.30, delta=delta, gamma=0.0,
                       theta=0.0, vega=0.0, rho=0.0, underlying=underlying)


class FakeChainStore:
    """Minimal ChainStore stand-in: {ticker: {date: chain}}."""

    def __init__(self, chains):
        self._chains = chains

    def trading_dates(self, ticker):
        if ticker not in self._chains:
            raise FileNotFoundError(ticker)
        return sorted(self._chains[ticker])

    def chain(self, ticker, asof):
        if ticker not in self._chains:
            raise FileNotFoundError(ticker)
        return self._chains[ticker].get(asof, [])

    def is_active(self, ticker, asof):
        return True

    def delisted_tickers(self):
        return []

    @property
    def universe(self):
        return None


RUN_START, RUN_END = date(2023, 3, 1), date(2023, 5, 31)
EXP = date(2023, 7, 21)


def _fake_chain_store() -> tuple[FakeChainStore, list[date]]:
    days = [d.date() for d in pd.bdate_range(RUN_START, RUN_END)]
    chains = {}
    for i, d in enumerate(days):
        mid90 = round(2.0 + 0.6 * math.sin(i / 5.0), 2)
        mid80 = round(0.8 + 0.25 * math.sin(i / 5.0), 2)
        chains[d] = [_q("EQT", d, EXP, 90.0, P, mid90, 100.0, -0.30),
                     _q("EQT", d, EXP, 80.0, P, mid80, 100.0, -0.16)]
    return FakeChainStore({"EQT": chains}), days


def _run_loop(tmp_path, with_equity: bool, seed: int = 3) -> tuple[dict, list[date]]:
    store, days = _fake_chain_store()
    if with_equity:
        # equity history starts ~60 bdays before the run so rv20 is warm
        n = len(pd.bdate_range(date(2022, 12, 1), RUN_END))
        write_equity(tmp_path, "EQT", _growing_vol_closes(n), start=date(2022, 12, 1))
    loop = LearningLoop(store, equity_store=EquityStore(equity_dir=tmp_path))
    out = loop.run("bull_put_spread", ["EQT"], RUN_START, RUN_END,
                   n_iter=2, objective="sortino", seed=seed)
    return out, days


def test_loop_run_regimes_shape_and_existing_keys(tmp_path):
    out, days = _run_loop(tmp_path, with_equity=True)
    # every pre-existing key survives (purely additive change)
    assert {"best_params", "history", "best", "objective", "folds",
            "holdout"} <= set(out)
    reg = out["regimes"]
    assert reg is not None
    assert set(reg) == {"low", "mid", "high"}
    for k in ("low", "mid", "high"):
        assert set(reg[k]) == {"days", "total_return", "sharpe", "max_drawdown"}
    # regimes decompose the best-params (OOS) run: its curve days minus the
    # first (returns start on day 2), all classified since rv20 is warm
    s_start, s_end, _, _ = LearningLoop._holdout_split(RUN_START, RUN_END)
    _, _, oos_start, oos_end = LearningLoop._fold(s_start, s_end)
    oos_days = [d for d in days if oos_start <= d <= oos_end]
    assert sum(reg[k]["days"] for k in reg) == len(oos_days) - 1


def test_loop_run_regimes_null_without_equity(tmp_path):
    out, _ = _run_loop(tmp_path, with_equity=False)
    assert out["regimes"] is None
    assert {"best_params", "history", "best", "objective", "folds",
            "holdout"} <= set(out)


def test_loop_determinism_same_seed_same_result_including_regimes(tmp_path):
    out1, _ = _run_loop(tmp_path, with_equity=True, seed=11)
    out2, _ = _run_loop(tmp_path, with_equity=True, seed=11)
    h1 = [(it.iteration, it.params, it.oos_score, it.is_score, it.accepted)
          for it in out1["history"]]
    h2 = [(it.iteration, it.params, it.oos_score, it.is_score, it.accepted)
          for it in out2["history"]]
    assert h1 == h2
    assert out1["best_params"] == out2["best_params"]
    assert out1["holdout"] == out2["holdout"]
    assert out1["regimes"] == out2["regimes"]
    assert out1["regimes"] is not None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
