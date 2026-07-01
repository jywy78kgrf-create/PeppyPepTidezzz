"""
Equity-derived entry signals (trend + realized-vol regime gate).

The backtest engine consults a :class:`SignalGate` before building a strategy
spec for a ticker on a day.  Rules (Phase-2 contract, all data from the
per-ticker OHLCV Parquet store read via ``optdesk.data.loader.EquityStore``):

* direction — strategy name maps to a bias:
    bullish  (bull_put_spread, long_call, covered_call, calendar_call):
             requires close > SMA50
    bearish  (bear_call_spread, long_put): requires close < SMA50
    neutral  (iron_condor, short_straddle, long_strangle): no trend filter
* vol regime — 20d realized-vol percentile over a rolling 1y window:
    short-premium (iron_condor, short_straddle, bull_put_spread,
                   bear_call_spread, covered_call):
             requires rv20_pct <= params.get("rv_entry_max_pct", 0.85)
    long-premium (long_call, long_put, long_strangle, calendar_call):
             requires rv20_pct >= params.get("rv_entry_min_pct", 0.10)

NO LOOKAHEAD: the gate's decision for day D uses only equity rows dated
strictly BEFORE D (i.e. data through D-1).  ``indicator_frame`` itself is
unshifted (row d holds indicators computed from closes through d); the gate
applies the shift by reading the last row with date < D.

Fail-open philosophy: the gate is a *filter*, so absence of information never
blocks a trade — a ticker with no equity file passes through entirely, and a
day whose indicator is NaN (not enough history) passes that rule.
``build_default_gate`` returns None (global pass-through) when NO requested
ticker has equity data at all.

Percentile convention: mid-rank (average of strict and weak rank) within the
rolling window, so an all-tied window (e.g. constant realized vol) scores 0.5
instead of a degenerate 0.0/1.0 that would spuriously trip a threshold.
"""
from __future__ import annotations

import math
from bisect import bisect_left
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from ..data.loader import EquityStore

__all__ = ["SignalGate", "build_default_gate", "indicator_frame"]

TRADING_DAYS_PER_YEAR = 252

# --------------------------------------------------------------------------- #
# Default rule tables (overridable via params — see SignalGate.__init__)
# --------------------------------------------------------------------------- #
BULLISH, BEARISH, NEUTRAL = "bullish", "bearish", "neutral"

DEFAULT_BIAS: dict[str, str] = {
    "bull_put_spread": BULLISH,
    "long_call": BULLISH,
    "covered_call": BULLISH,
    "calendar_call": BULLISH,
    "bear_call_spread": BEARISH,
    "long_put": BEARISH,
    "iron_condor": NEUTRAL,
    "short_straddle": NEUTRAL,
    "long_strangle": NEUTRAL,
}

DEFAULT_SHORT_PREMIUM = frozenset({
    "iron_condor", "short_straddle", "bull_put_spread", "bear_call_spread",
    "covered_call",
})
DEFAULT_LONG_PREMIUM = frozenset({
    "long_call", "long_put", "long_strangle", "calendar_call",
})

_SMA_FAST = 50
_SMA_SLOW = 200
_RV_WINDOW = 20          # 20d realized vol
_RV_PCT_WINDOW = 252     # rolling ~1y percentile window
_RV_PCT_MIN_OBS = 40     # rv20 observations needed before the percentile prints


# --------------------------------------------------------------------------- #
# Indicators
# --------------------------------------------------------------------------- #
def _midrank_pct(window: np.ndarray) -> float:
    """Mid-rank percentile of the window's LAST value within the window."""
    x = window[-1]
    strict = float((window < x).mean())
    weak = float((window <= x).mean())
    return 0.5 * (strict + weak)


def indicator_frame(ticker: str,
                    equity_store: Optional[EquityStore] = None) -> pd.DataFrame:
    """Indicator frame for ``ticker``: DataFrame[date, close, sma50, sma200,
    rv20, rv20_pct], date ascending.

    Row ``d`` is computed from closes through ``d`` (UNSHIFTED — callers that
    must avoid lookahead, like :class:`SignalGate`, read the last row dated
    strictly before their decision day).

    * ``rv20``: annualised std-dev of 20 daily log returns.
    * ``rv20_pct``: mid-rank percentile of rv20 within a rolling 252-obs
      window (min 40 observations; NaN before that).

    Raises FileNotFoundError when the ticker has no equity file.
    """
    store = equity_store if equity_store is not None else EquityStore()
    df = store.ohlcv(ticker)
    close = pd.to_numeric(df["close"], errors="coerce")
    out = pd.DataFrame({"date": df["date"], "close": close})
    out["sma50"] = close.rolling(_SMA_FAST, min_periods=_SMA_FAST).mean()
    out["sma200"] = close.rolling(_SMA_SLOW, min_periods=_SMA_SLOW).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        logret = np.log(close / close.shift(1))
    out["rv20"] = (logret.rolling(_RV_WINDOW, min_periods=_RV_WINDOW).std(ddof=0)
                   * math.sqrt(TRADING_DAYS_PER_YEAR))
    out["rv20_pct"] = out["rv20"].rolling(
        _RV_PCT_WINDOW, min_periods=_RV_PCT_MIN_OBS
    ).apply(_midrank_pct, raw=True)
    return out.reset_index(drop=True)


def _has_equity(store: EquityStore, ticker: str) -> bool:
    """Cheap existence check (no data load) with a duck-typed fallback."""
    edir = getattr(store, "equity_dir", None)
    if edir is not None:
        return (Path(edir) / f"{ticker.upper()}.parquet").exists()
    try:  # pragma: no cover - non-EquityStore duck types
        store.ohlcv(ticker.upper())
        return True
    except Exception:  # noqa: BLE001
        return False


def _isnum(v) -> bool:
    try:
        return v is not None and math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------------------------- #
# Gate
# --------------------------------------------------------------------------- #
class SignalGate:
    """Per-(ticker, day, strategy) entry filter over equity indicators.

    Indicators are computed lazily per ticker on first use and cached for the
    life of the gate (the engine builds one gate per backtest run).
    """

    def __init__(self, tickers: list[str], params: Optional[dict] = None,
                 equity_store: Optional[EquityStore] = None) -> None:
        p = dict(params or {})
        self._store = equity_store if equity_store is not None else EquityStore()
        self._tickers = [t.upper() for t in tickers]
        self._rv_max = float(p.get("rv_entry_max_pct", 0.85))
        self._rv_min = float(p.get("rv_entry_min_pct", 0.10))
        self._bias: dict[str, str] = dict(DEFAULT_BIAS)
        override = p.get("bias_map")
        if isinstance(override, dict):
            self._bias.update({str(k): str(v) for k, v in override.items()})
        self._short_premium = frozenset(p.get("short_premium", DEFAULT_SHORT_PREMIUM))
        self._long_premium = frozenset(p.get("long_premium", DEFAULT_LONG_PREMIUM))
        # ticker -> (sorted dates, indicator frame) | None (no equity data)
        self._cache: dict[str, Optional[tuple[list[date], pd.DataFrame]]] = {}

    # -- data access ---------------------------------------------------- #
    def _indicators(self, ticker: str) -> Optional[tuple[list[date], pd.DataFrame]]:
        tk = ticker.upper()
        if tk not in self._cache:
            try:
                frame = indicator_frame(tk, self._store)
            except Exception:  # noqa: BLE001 - missing/unreadable => pass-through
                frame = None
            if frame is None or frame.empty:
                self._cache[tk] = None
            else:
                self._cache[tk] = (list(frame["date"]), frame)
        return self._cache[tk]

    def _row_before(self, ticker: str, day: date) -> Optional[pd.Series]:
        """Last indicator row dated STRICTLY before ``day`` (data through D-1)."""
        entry = self._indicators(ticker)
        if entry is None:
            return None
        dates, frame = entry
        idx = bisect_left(dates, day) - 1
        if idx < 0:
            return None
        return frame.iloc[idx]

    # -- decision --------------------------------------------------------- #
    def allow(self, ticker: str, day: date, strategy: str) -> bool:
        """True when ``strategy`` may open on ``ticker`` on ``day``.

        Uses only equity data through ``day - 1``; passes through (True) when
        the ticker has no equity data or an indicator has not warmed up yet.
        """
        if self._indicators(ticker) is None:
            return True  # per-ticker pass-through: no equity data
        row = self._row_before(ticker, day)
        if row is None:
            return True  # no history strictly before `day`

        close, sma50, rv_pct = row["close"], row["sma50"], row["rv20_pct"]

        # 1) trend rule (bullish/bearish only; NaN indicator passes through)
        bias = self._bias.get(strategy)
        if _isnum(close) and _isnum(sma50):
            if bias == BULLISH and not close > sma50:
                return False
            if bias == BEARISH and not close < sma50:
                return False

        # 2) vol-regime rule (NaN percentile passes through)
        if _isnum(rv_pct):
            if strategy in self._short_premium and rv_pct > self._rv_max:
                return False
            if strategy in self._long_premium and rv_pct < self._rv_min:
                return False
        return True


def build_default_gate(tickers: list[str], params: Optional[dict] = None,
                       equity_store: Optional[EquityStore] = None,
                       ) -> Optional[SignalGate]:
    """Build the default :class:`SignalGate` for a backtest run.

    Returns None (global pass-through) when NO requested ticker has equity
    data.  ``params`` is the engine's run cfg; only the signal keys
    (rv_entry_max_pct, rv_entry_min_pct, bias_map, short_premium,
    long_premium) are read.  ``equity_store`` is injectable for tests and
    defaults to the shared data/equity Parquet store.
    """
    store = equity_store if equity_store is not None else EquityStore()
    tks = [t.upper() for t in (tickers or [])]
    if not any(_has_equity(store, tk) for tk in tks):
        return None
    return SignalGate(tks, params, equity_store=store)
