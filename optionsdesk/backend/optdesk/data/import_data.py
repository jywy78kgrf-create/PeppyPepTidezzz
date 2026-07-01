"""
Importer: convert raw option history into the desk's per-ticker Parquet store +
a derived universe file. Handles two layouts automatically:

  * **Meridian** (~/.meridian-data/historical): per-symbol equity OHLCV CSVs and
    option chains as one gzipped JSON per symbol per day:
        historical/<TICKER>.csv
        historical/options/<TICKER>/<YYYY-MM-DD>.json.gz
  * **Generic**: any folder of flat CSV/JSON files with a ticker column.

It auto-detects columns across common vendor spellings, normalizes option type /
IV units, pulls the underlying close from the equity CSV when the chain lacks
it, derives listed/delisted from each ticker's date span, and writes:

    data/chains/<TICKER>.parquet
    data/universe/universe.csv

Recommended flow (verify the schema on ONE file before the full run):

    # 1. inspect: reads a single option file, prints its structure + mapping
    python -m optdesk.data.import_data --src ~/.meridian-data --inspect

    # 2. full import (wipes the synthetic sample first)
    python -m optdesk.data.import_data --src ~/.meridian-data --wipe-sample

Inside Docker (raw data bind-mounted at /app/data/raw):
    docker compose exec backend python -m optdesk.data.import_data \
        --src /app/data/raw --wipe-sample
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

from ..config import CHAINS_DIR, DATA_DIR, UNIVERSE_DIR

# canonical column -> accepted source aliases (lowercased, stripped)
ALIASES: dict[str, set[str]] = {
    "ticker": {"ticker", "symbol", "root", "underlying_symbol", "act_symbol",
               "undsymbol", "optionroot", "underlyingsymbol", "sym"},
    "asof": {"asof", "date", "quote_date", "quotedate", "trade_date", "tradedate",
             "data_date", "datadate", "observation_date", "dt", "as_of_date"},
    "expiry": {"expiry", "expiration", "exp_date", "expiration_date", "expirationdate",
               "expirdate", "exdate", "expiry_date", "expiration_dt"},
    "strike": {"strike", "strike_price", "strikeprice", "k"},
    "option_type": {"option_type", "type", "cp", "cp_flag", "call_put", "callput",
                    "right", "pc", "put_call", "opttype", "option_right", "kind"},
    "bid": {"bid", "bid_price", "best_bid", "bidprice"},
    "ask": {"ask", "ask_price", "best_ask", "offer", "askprice"},
    "last": {"last", "last_price", "close", "mark", "lastprice", "trade_price",
             "close_price"},
    "volume": {"volume", "vol", "trade_volume", "tradevolume"},
    "open_interest": {"open_interest", "oi", "openinterest", "open_int"},
    "implied_volatility": {"implied_volatility", "iv", "impliedvol", "impl_volatility",
                           "mid_iv", "ivol", "volatility", "sigma"},
    "delta": {"delta", "mid_delta", "greeks_delta"},
    "gamma": {"gamma", "mid_gamma", "greeks_gamma"},
    "theta": {"theta", "mid_theta", "greeks_theta"},
    "vega": {"vega", "mid_vega", "greeks_vega"},
    "rho": {"rho", "mid_rho", "greeks_rho"},
    "underlying_close": {"underlying_close", "underlying", "spot", "stock_price",
                         "underlying_price", "undprice", "active_underlying_price",
                         "close_underlying", "stkpx", "underlyinglast", "underlying_last"},
}
REQUIRED = ("expiry", "strike", "option_type")  # ticker/asof come from the path
GREEKS = ("delta", "gamma", "theta", "vega", "rho", "implied_volatility")


# --------------------------------------------------------------------------- #
# Column mapping helpers
# --------------------------------------------------------------------------- #
def _canon(df: pd.DataFrame) -> pd.DataFrame:
    """Rename source columns to canonical names, deterministically and without
    collisions (e.g. records carrying BOTH ``last`` and ``mark`` must not both
    map onto ``last`` and create a duplicate column)."""
    lower = {str(c).lower().strip(): c for c in df.columns}
    rename: dict[str, str] = {}
    for canon, aliases in ALIASES.items():
        if canon in lower:            # canonical column already present — keep it
            continue
        for a in sorted(aliases):     # sorted -> deterministic pick
            if a in lower:
                rename[lower[a]] = canon
                break
    return df.rename(columns=rename)


def _records_from_json(obj) -> list:
    """Extract a list of contract records from any common JSON shape."""
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for key in ("options", "chains", "data", "results", "rows", "contracts",
                    "optionChain", "quotes"):
            v = obj.get(key)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):  # e.g. {"calls":[...], "puts":[...]}
                out = []
                for side, arr in v.items():
                    if isinstance(arr, list):
                        for r in arr:
                            if isinstance(r, dict) and "option_type" not in r and "type" not in r:
                                r = {**r, "option_type": side}
                            out.append(r)
                if out:
                    return out
        # {"calls":[...], "puts":[...]} at top level
        out = []
        for side in ("calls", "puts", "call", "put"):
            arr = obj.get(side)
            if isinstance(arr, list):
                for r in arr:
                    if isinstance(r, dict):
                        out.append({**r, "option_type": side})
        if out:
            return out
    return []


def _norm_option_type(s: pd.Series) -> pd.Series:
    def one(v):
        t = str(v).strip().upper()
        if t.startswith("C") or t == "0":
            return "C"
        if t.startswith("P") or t == "1":
            return "P"
        return "P"
    return s.map(one)


def _fix_iv(df: pd.DataFrame) -> pd.DataFrame:
    if "implied_volatility" in df:
        iv = pd.to_numeric(df["implied_volatility"], errors="coerce")
        med = iv.median(skipna=True)
        if pd.notna(med) and med > 3.0:
            iv = iv / 100.0
        df["implied_volatility"] = iv
    return df


def _read_gz_json(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- #
# Layout detection + Meridian walker
# --------------------------------------------------------------------------- #
def _find_options_dir(src: Path) -> Path | None:
    for cand in (src / "historical" / "options", src / "options", src):
        if cand.is_dir() and any(cand.glob("*/*.json*")):
            return cand
    return None


def _equity_close_map(src: Path, ticker: str) -> dict:
    """date(str) -> close from the per-symbol equity OHLCV CSV, if present."""
    for cand in (src / "historical" / f"{ticker}.csv", src / f"{ticker}.csv"):
        if cand.exists():
            try:
                e = _canon(pd.read_csv(cand))
                dcol = "asof" if "asof" in e else next(
                    (c for c in e.columns if str(c).lower() in ("date", "dt")), None)
                ccol = "last" if "last" in e else next(
                    (c for c in e.columns if str(c).lower() in
                     ("close", "adj_close", "close_price", "underlying_close")), None)
                if dcol and ccol:
                    d = pd.to_datetime(e[dcol], errors="coerce").dt.date.astype(str)
                    return dict(zip(d, pd.to_numeric(e[ccol], errors="coerce")))
            except Exception:  # noqa: BLE001
                return {}
    return {}


def inspect(src: Path) -> None:
    """Print the structure of one equity CSV + one option file, and the mapping."""
    opt_dir = _find_options_dir(src)
    if not opt_dir:
        sys.exit(f"Could not find an options/ directory under {src}")
    sym_dirs = sorted([d for d in opt_dir.iterdir() if d.is_dir()])
    print(f"options dir: {opt_dir}\nsymbols: {len(sym_dirs)} "
          f"(e.g. {[d.name for d in sym_dirs[:6]]})")
    if not sym_dirs:
        sys.exit("No per-symbol subdirectories found.")
    files = sorted(sym_dirs[0].glob("*.json*"))
    print(f"{sym_dirs[0].name}: {len(files)} day files "
          f"(e.g. {[f.name for f in files[:3]]})\n")

    f = files[0]
    obj = _read_gz_json(f) if f.suffix == ".gz" else json.loads(f.read_text())
    print(f"--- {f} ---")
    print("top-level type:", type(obj).__name__)
    if isinstance(obj, dict):
        print("top-level keys:", list(obj.keys())[:20])
    recs = _records_from_json(obj)
    print(f"detected {len(recs)} contract records")
    if recs:
        r0 = recs[0]
        print("first record keys:", list(r0.keys()) if isinstance(r0, dict) else type(r0))
        print("first record sample:", json.dumps(r0, default=str)[:500])
        df = _canon(pd.json_normalize(recs))
        found = [c for c in ALIASES if c in df.columns]
        missing_req = [c for c in REQUIRED if c not in df.columns]
        print("\nMAPPED canonical cols:", found)
        print("MISSING required   :", missing_req or "none ✓")
        print("MISSING greeks     :", [g for g in GREEKS if g not in df.columns] or "none ✓")
    eq = _equity_close_map(src, sym_dirs[0].name)
    print(f"\nequity close map for {sym_dirs[0].name}: {len(eq)} dates "
          f"({'ok ✓' if eq else 'NOT FOUND — underlying will fall back to chain field'})")


def gather_meridian(src: Path, opt_dir: Path, limit: int | None = None):
    """Yield (ticker, DataFrame) per symbol from the Meridian layout."""
    sym_dirs = sorted([d for d in opt_dir.iterdir() if d.is_dir()])
    for i, sd in enumerate(sym_dirs):
        ticker = sd.name.upper()
        eq = _equity_close_map(src, sd.name)
        frames = []
        for f in sorted(sd.glob("*.json*")):
            asof = f.name.split(".")[0]  # "2021-11-10.json.gz" -> "2021-11-10"
            try:
                obj = _read_gz_json(f) if f.suffix == ".gz" else json.loads(f.read_text())
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {ticker}/{f.name}: {exc}")
                continue
            recs = _records_from_json(obj)
            if not recs:
                continue
            df = _canon(pd.json_normalize(recs))
            if any(c not in df.columns for c in REQUIRED):
                continue
            df["ticker"] = ticker
            if "asof" not in df.columns:
                df["asof"] = asof
            if "underlying_close" not in df.columns or df["underlying_close"].isna().all():
                df["underlying_close"] = eq.get(asof, float("nan"))
            frames.append(df)
        if not frames:
            print(f"  - {ticker}: no usable chains")
            continue
        out = pd.concat(frames, ignore_index=True)
        print(f"  + {ticker}: {len(out):,} rows from {len(frames)} days")
        yield ticker, out
        if limit and i + 1 >= limit:
            return


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df["asof"] = pd.to_datetime(df["asof"], errors="coerce").dt.date
    df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce").dt.date
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce")
    df["option_type"] = _norm_option_type(df["option_type"])
    for c in ("bid", "ask", "last", "volume", "open_interest", *GREEKS,
              "underlying_close"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = _fix_iv(df)
    keep = [c for c in ("ticker", "asof", "expiry", "strike", "option_type",
                        "bid", "ask", "last", "volume", "open_interest",
                        *GREEKS, "underlying_close") if c in df.columns]
    df = df[keep]
    return df.dropna(subset=["asof", "expiry", "strike"])


def derive_universe(spans: dict[str, tuple], global_last, gap_days: int) -> pd.DataFrame:
    rows = []
    for tk, (first, last) in sorted(spans.items()):
        delisted = last if (global_last - last) > timedelta(days=gap_days) else ""
        rows.append(dict(ticker=tk, listed=first, delisted=delisted, sector="UNKNOWN"))
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Import raw options data into the desk store.")
    ap.add_argument("--src", type=Path, default=DATA_DIR / "raw",
                    help="root of your raw data (e.g. ~/.meridian-data)")
    ap.add_argument("--inspect", action="store_true",
                    help="read ONE option file and print its structure + mapping, then exit")
    ap.add_argument("--wipe-sample", action="store_true",
                    help="remove the synthetic AAPL/MSFT/XYZ sample store first")
    ap.add_argument("--limit", type=int, default=None,
                    help="import only the first N symbols (for a quick test run)")
    ap.add_argument("--delist-gap-days", type=int, default=15,
                    help="gap after which a vanished ticker is marked delisted")
    args = ap.parse_args()
    src = args.src.expanduser()

    if args.inspect:
        inspect(src)
        return

    opt_dir = _find_options_dir(src)
    if not opt_dir:
        sys.exit(f"Could not find an options/ directory under {src}. "
                 "Point --src at the folder that contains historical/options/.")

    CHAINS_DIR.mkdir(parents=True, exist_ok=True)
    UNIVERSE_DIR.mkdir(parents=True, exist_ok=True)
    if args.wipe_sample:
        for tk in ("AAPL", "MSFT", "XYZ"):
            f = CHAINS_DIR / f"{tk}.parquet"
            if f.exists():
                f.unlink()
                print(f"removed sample {f.name}")

    print(f"Importing from {opt_dir} ...\n")
    spans: dict[str, tuple] = {}
    global_last = None
    n = 0
    for ticker, raw in gather_meridian(src, opt_dir, limit=args.limit):
        df = _normalize(raw)
        if df.empty:
            continue
        df = df.sort_values(["asof", "expiry", "strike"])
        df.to_parquet(CHAINS_DIR / f"{ticker}.parquet", index=False)
        first, last = df["asof"].min(), df["asof"].max()
        spans[ticker] = (first, last)
        global_last = last if global_last is None else max(global_last, last)
        n += 1

    if not spans:
        sys.exit("No tickers imported — run with --inspect and send me the output.")
    uni = derive_universe(spans, global_last, args.delist_gap_days)
    uni.to_csv(UNIVERSE_DIR / "universe.csv", index=False)
    delisted = (uni["delisted"].astype(str).str.len() > 0).sum()
    print(f"\nWrote {n} ticker file(s) to {CHAINS_DIR}")
    print(f"Universe: {len(uni)} tickers ({delisted} derived delisted) "
          f"-> {UNIVERSE_DIR / 'universe.csv'}")
    print("\nRestart the backend to load it:  docker compose restart backend")


if __name__ == "__main__":
    main()
