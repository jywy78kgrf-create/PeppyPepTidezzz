"""
ChainStore — survivorship-aware loader over per-ticker option files.

Scales to real-size data (1–2M rows per ticker): instead of loading whole
per-ticker frames into memory, `chain()` reads only the requested day via
Parquet predicate pushdown. The importer writes one row-group per trading day,
so a day slice touches a single row-group (~a few thousand rows) regardless of
file size. A small LRU keeps recently used day-chains hot; `trading_dates()`
reads just the `asof` column once per ticker.

Normalizes heterogeneous column naming/units into the canonical OptionQuote
contract.
"""
from __future__ import annotations

import functools
from collections import OrderedDict
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ..config import CHAINS_DIR, EQUITY_DIR, UNIVERSE_DIR
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

# how many (ticker, day) chain slices to keep hot. The backtester touches each
# (ticker, day) once, so this mainly serves the API/suggester; keep it small —
# real chains run ~1-2k contracts/day, so 64 slices stays under ~50MB.
_CHAIN_CACHE_MAX = 64


def _canon_columns(df: pd.DataFrame) -> pd.DataFrame:
    lower = {c.lower().strip(): c for c in df.columns}
    rename: dict[str, str] = {}
    for canon, aliases in _ALIASES.items():
        if canon in lower:
            continue  # canonical name already present — never collide onto it
        for a in sorted(aliases):
            if a in lower:
                rename[lower[a]] = canon
                break
    return df.rename(columns=rename)


def _to_option_type(v) -> OptionType:
    s = str(v).strip().upper()
    if s in ("C", "CALL"):
        return OptionType.CALL
    return OptionType.PUT


def _norm_iv(v) -> float:
    if v is None or pd.isna(v):
        return 0.0
    v = float(v)
    return v / 100.0 if v > 3.0 else v  # 32 -> 0.32, 0.32 stays


def _as_date(v) -> date | None:
    """Coerce str/date/datetime/Timestamp to date (None on failure)."""
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    try:
        return pd.Timestamp(v).date()
    except (ValueError, TypeError):
        return None


def _f(v) -> float:
    """NaN-safe float coercion."""
    try:
        if v is None or pd.isna(v):
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


class ChainStore:
    def __init__(self, chains_dir: Path = CHAINS_DIR, universe_dir: Path = UNIVERSE_DIR):
        self.chains_dir = Path(chains_dir)
        self.universe_dir = Path(universe_dir)
        self._universe = self._load_universe()
        self._dates_cache: dict[str, list[date]] = {}
        self._chain_cache: OrderedDict[tuple[str, date], list[OptionQuote]] = OrderedDict()
        self._csv_cache: dict[str, pd.DataFrame] = {}
        # per-ticker parquet handle + row-group index:
        #   (asof -> [row-group idx], {row groups spanning >1 day})
        self._pf_cache: dict[str, pq.ParquetFile] = {}
        self._rg_index: dict[str, tuple[dict[date, list[int]], set[int]] | None] = {}

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
        return sorted({f.stem.upper() for f in files if not f.stem.startswith(".")})

    @property
    def universe(self) -> pd.DataFrame:
        return self._universe

    def delisted_tickers(self) -> list[str]:
        u = self._universe
        if "delisted" not in u or u.empty:
            return []
        return sorted(u.loc[u["delisted"].notna(), "ticker"].str.upper().tolist())

    # ------------------------------------------------------------------ #
    def _path(self, ticker: str) -> Path:
        for ext in (".parquet", ".csv"):
            f = self.chains_dir / f"{ticker.upper()}{ext}"
            if f.exists():
                return f
        raise FileNotFoundError(f"No chain file for {ticker} in {self.chains_dir}")

    def _csv_frame(self, ticker: str) -> pd.DataFrame:
        """Small-file CSV fallback (kept fully in memory; fine at CSV scale)."""
        tk = ticker.upper()
        if tk not in self._csv_cache:
            df = _canon_columns(pd.read_csv(self._path(tk)))
            df["asof"] = pd.to_datetime(df["asof"], errors="coerce").dt.date
            self._csv_cache[tk] = df
        return self._csv_cache[tk]

    # ------------------------------------------------------------------ #
    def trading_dates(self, ticker: str) -> list[date]:
        tk = ticker.upper()
        if tk in self._dates_cache:
            return self._dates_cache[tk]
        f = self._path(tk)
        if f.suffix == ".parquet":
            col = pq.read_table(f, columns=["asof"])["asof"]
            vals = (_as_date(v) for v in col.unique().to_pylist())
        else:
            vals = iter(self._csv_frame(tk)["asof"].dropna().unique().tolist())
        dates = sorted({d for d in vals if d is not None})
        self._dates_cache[tk] = dates
        return dates

    def chain(self, ticker: str, asof: date | str) -> list[OptionQuote]:
        if isinstance(asof, str):
            asof = date.fromisoformat(asof)
        tk = ticker.upper()
        key = (tk, asof)
        cached = self._chain_cache.get(key)
        if cached is not None:
            self._chain_cache.move_to_end(key)
            return cached

        f = self._path(tk)
        if f.suffix == ".parquet":
            df = self._read_day(tk, f, asof)
        else:
            df = self._csv_frame(tk)
            df = df[df["asof"] == asof]

        quotes = self._build_quotes(tk, asof, df)
        self._chain_cache[key] = quotes
        if len(self._chain_cache) > _CHAIN_CACHE_MAX:
            self._chain_cache.popitem(last=False)
        return quotes

    def _parquet_file(self, ticker: str, path: Path) -> pq.ParquetFile:
        pf = self._pf_cache.get(ticker)
        if pf is None:
            pf = pq.ParquetFile(path)
            self._pf_cache[ticker] = pf
        return pf

    def _row_group_index(self, ticker: str,
                         pf: pq.ParquetFile) -> tuple[dict[date, list[int]], set[int]] | None:
        """Map each trading date to its row-group indices from row-group
        statistics (the importer writes one day per row group), plus the set of
        row groups spanning more than one day (need row filtering after read).
        Returns None when statistics are unusable (fallback: filtered read)."""
        if ticker in self._rg_index:
            return self._rg_index[ticker]
        md = pf.metadata
        result: tuple[dict[date, list[int]], set[int]] | None
        try:
            asof_pos = md.schema.to_arrow_schema().get_field_index("asof")
            index: dict[date, list[int]] = {}
            multi: set[int] = set()
            for rg in range(md.num_row_groups):
                stats = md.row_group(rg).column(asof_pos).statistics
                if stats is None or not stats.has_min_max:
                    raise ValueError("missing statistics")
                lo, hi = _as_date(stats.min), _as_date(stats.max)
                if lo is None or hi is None:
                    raise ValueError("unparseable statistics")
                if lo == hi:
                    index.setdefault(lo, []).append(rg)
                else:
                    multi.add(rg)
                    d = lo
                    one = pd.Timedelta(days=1).to_pytimedelta()
                    while d <= hi:
                        index.setdefault(d, []).append(rg)
                        d = d + one
            result = (index, multi)
        except (ValueError, KeyError, OverflowError):
            result = None
        self._rg_index[ticker] = result
        return result

    def _read_day(self, ticker: str, path: Path, asof: date) -> pd.DataFrame:
        """Read one day's rows: direct row-group read via the asof index when
        possible, else a predicate-pushdown filtered read."""
        pf = self._parquet_file(ticker, path)
        rg_index = self._row_group_index(ticker, pf)
        if rg_index is not None:
            index, multi = rg_index
            rgs = index.get(asof)
            if not rgs:
                return pd.DataFrame()
            df = _canon_columns(pf.read_row_groups(rgs).to_pandas())
            if not any(rg in multi for rg in rgs):
                return df  # exact day-per-row-group layout: no filtering needed
            # group spans multiple days (e.g. sample generator) — filter rows;
            # asof may be str (importer), datetime.date, or Timestamp.
            mask = pd.to_datetime(df["asof"], errors="coerce").dt.date == asof
            return df[mask]
        # fallback: schema-aware filtered read
        asof_type = pq.read_schema(path).field("asof").type
        fval: object = (asof.isoformat()
                        if pa.types.is_string(asof_type) or pa.types.is_large_string(asof_type)
                        else asof)
        return _canon_columns(pq.read_table(path, filters=[("asof", "==", fval)]).to_pandas())

    _NUM_COLS = ("strike", "bid", "ask", "last", "volume", "open_interest",
                 "implied_volatility", "delta", "gamma", "theta", "vega", "rho",
                 "underlying_close")

    def _build_quotes(self, ticker: str, asof: date,
                      df: pd.DataFrame) -> list[OptionQuote]:
        """Vectorized OptionQuote construction (hot path of every backtest)."""
        if df.empty:
            return []
        expiry = pd.to_datetime(df["expiry"], errors="coerce").dt.date
        valid = expiry.notna()
        if not valid.all():
            df = df[valid]
            expiry = expiry[valid]
        if df.empty:
            return []

        cols: dict[str, list[float]] = {}
        for c in self._NUM_COLS:
            if c in df.columns:
                cols[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).tolist()
            else:
                cols[c] = [0.0] * len(df)
        iv = [v / 100.0 if v > 3.0 else v for v in cols["implied_volatility"]]
        is_call = (df["option_type"].astype(str).str.strip().str.upper()
                   .str.startswith("C")).tolist()

        return [
            OptionQuote(
                ticker=ticker, asof=asof, expiry=e,
                strike=k, kind=OptionType.CALL if c else OptionType.PUT,
                bid=b, ask=a, last=l,
                volume=int(v), open_interest=int(oi),
                iv=s, delta=dl, gamma=g, theta=t, vega=vg, rho=r,
                underlying=u,
            )
            for e, k, c, b, a, l, v, oi, s, dl, g, t, vg, r, u in zip(
                expiry.tolist(), cols["strike"], is_call, cols["bid"], cols["ask"],
                cols["last"], cols["volume"], cols["open_interest"], iv,
                cols["delta"], cols["gamma"], cols["theta"], cols["vega"],
                cols["rho"], cols["underlying_close"],
            )
        ]

    # ------------------------------------------------------------------ #
    def has_equity(self, ticker: str) -> bool:
        return (EQUITY_DIR / f"{ticker.upper()}.parquet").exists()

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


class EquityStore:
    """Reader over the per-ticker equity OHLCV Parquet store (import_equity)."""

    def __init__(self, equity_dir: Path = EQUITY_DIR):
        self.equity_dir = Path(equity_dir)

    def tickers(self) -> list[str]:
        return sorted(f.stem.upper() for f in self.equity_dir.glob("*.parquet"))

    @functools.lru_cache(maxsize=128)
    def ohlcv(self, ticker: str) -> pd.DataFrame:
        """Daily OHLCV frame (date ascending). Equity frames are small."""
        f = self.equity_dir / f"{ticker.upper()}.parquet"
        if not f.exists():
            raise FileNotFoundError(f"No equity file for {ticker}")
        df = pd.read_parquet(f)
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
        return df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    def close_series(self, ticker: str) -> pd.Series:
        df = self.ohlcv(ticker)
        return pd.Series(df["close"].values, index=df["date"])
