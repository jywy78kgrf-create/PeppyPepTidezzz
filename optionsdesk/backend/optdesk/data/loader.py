"""
ChainStore — survivorship-aware loader over per-ticker option files.

Normalizes heterogeneous column naming/units into the canonical OptionQuote
contract and exposes date-sliced chain access for the backtester.
"""
from __future__ import annotations

import functools
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from ..config import CHAINS_DIR, UNIVERSE_DIR
from ..contracts import OptionQuote, OptionType

# accepted aliases -> canonical column
_ALIASES = {
    "asof": {"asof", "date", "quote_date", "observation_date"},
    "expiry": {"expiry", "expiration", "exp_date", "expiration_date"},
    "strike": {"strike", "strike_price"},
    "option_type": {"option_type", "type", "cp", "call_put", "right"},
    "bid": {"bid"},
    "ask": {"ask"},
    "last": {"last", "last_price", "close"},
    "volume": {"volume", "vol"},
    "open_interest": {"open_interest", "oi"},
    "implied_volatility": {"implied_volatility", "iv", "impliedvol"},
    "delta": {"delta"},
    "gamma": {"gamma"},
    "theta": {"theta"},
    "vega": {"vega"},
    "rho": {"rho"},
    "underlying_close": {"underlying_close", "underlying", "spot", "stock_price"},
}


def _canon_columns(df: pd.DataFrame) -> pd.DataFrame:
    lower = {c.lower().strip(): c for c in df.columns}
    rename: dict[str, str] = {}
    for canon, aliases in _ALIASES.items():
        for a in aliases:
            if a in lower:
                rename[lower[a]] = canon
                break
    return df.rename(columns=rename)


def _to_option_type(v) -> OptionType:
    s = str(v).strip().upper()
    if s in ("C", "CALL"):
        return OptionType.CALL
    return OptionType.PUT


def _norm_iv(v: float) -> float:
    if v is None or pd.isna(v):
        return 0.0
    v = float(v)
    return v / 100.0 if v > 3.0 else v  # 32 -> 0.32, 0.32 stays


class ChainStore:
    def __init__(self, chains_dir: Path = CHAINS_DIR, universe_dir: Path = UNIVERSE_DIR):
        self.chains_dir = Path(chains_dir)
        self.universe_dir = Path(universe_dir)
        self._universe = self._load_universe()

    # ------------------------------------------------------------------ #
    def _load_universe(self) -> pd.DataFrame:
        f = self.universe_dir / "universe.csv"
        if not f.exists():
            return pd.DataFrame(columns=["ticker", "listed", "delisted", "sector"])
        u = pd.read_csv(f)
        u.columns = [c.lower() for c in u.columns]
        for col in ("listed", "delisted"):
            if col in u:
                u[col] = pd.to_datetime(u[col], errors="coerce").dt.date
        return u

    def tickers(self) -> list[str]:
        files = list(self.chains_dir.glob("*.parquet")) + list(self.chains_dir.glob("*.csv"))
        return sorted({f.stem.upper() for f in files})

    @property
    def universe(self) -> pd.DataFrame:
        return self._universe

    def delisted_tickers(self) -> list[str]:
        u = self._universe
        if "delisted" not in u or u.empty:
            return []
        return sorted(u.loc[u["delisted"].notna(), "ticker"].str.upper().tolist())

    # ------------------------------------------------------------------ #
    @functools.lru_cache(maxsize=128)
    def _frame(self, ticker: str) -> pd.DataFrame:
        for ext in (".parquet", ".csv"):
            f = self.chains_dir / f"{ticker.upper()}{ext}"
            if f.exists():
                df = pd.read_parquet(f) if ext == ".parquet" else pd.read_csv(f)
                df = _canon_columns(df)
                df["asof"] = pd.to_datetime(df["asof"], errors="coerce").dt.date
                df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce").dt.date
                for c in ("delta", "gamma", "theta", "vega", "rho", "implied_volatility"):
                    if c not in df:
                        df[c] = float("nan")
                return df
        raise FileNotFoundError(f"No chain file for {ticker} in {self.chains_dir}")

    def trading_dates(self, ticker: str) -> list[date]:
        df = self._frame(ticker)
        return sorted(df["asof"].dropna().unique().tolist())

    def chain(self, ticker: str, asof: date | str) -> list[OptionQuote]:
        if isinstance(asof, str):
            asof = datetime.strptime(asof, "%Y-%m-%d").date()
        df = self._frame(ticker)
        day = df[df["asof"] == asof]
        out: list[OptionQuote] = []
        for r in day.itertuples(index=False):
            d = r._asdict()
            out.append(OptionQuote(
                ticker=ticker.upper(),
                asof=d["asof"],
                expiry=d["expiry"],
                strike=float(d["strike"]),
                kind=_to_option_type(d["option_type"]),
                bid=float(d.get("bid", 0) or 0),
                ask=float(d.get("ask", 0) or 0),
                last=float(d.get("last", 0) or 0),
                volume=int(d.get("volume", 0) or 0),
                open_interest=int(d.get("open_interest", 0) or 0),
                iv=_norm_iv(d.get("implied_volatility")),
                delta=float(d.get("delta") or 0),
                gamma=float(d.get("gamma") or 0),
                theta=float(d.get("theta") or 0),
                vega=float(d.get("vega") or 0),
                rho=float(d.get("rho") or 0),
                underlying=float(d.get("underlying_close", 0) or 0),
            ))
        return out

    def is_active(self, ticker: str, asof: date) -> bool:
        u = self._universe
        row = u[u["ticker"].str.upper() == ticker.upper()] if not u.empty else u
        if row.empty:
            return True
        r = row.iloc[0]
        if pd.notna(r.get("listed")) and asof < r["listed"]:
            return False
        if pd.notna(r.get("delisted")) and asof > r["delisted"]:
            return False
        return True
