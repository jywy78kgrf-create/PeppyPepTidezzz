"""
Equity importer: convert the per-symbol equity OHLCV CSVs into a Parquet store
the desk can use for underlying-based signals (trend, moving averages, realized
vol, charting).

    historical/<TICKER>.csv   ->   data/equity/<TICKER>.parquet

This is independent of the options import — run it any time, before or after.
It's fast and light (112 small CSVs, not 130k gzip files).

    python -m optdesk.data.import_equity --src ~/.meridian-data
    docker compose exec backend python -m optdesk.data.import_equity --src /app/data/raw
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from ..config import DATA_DIR, EQUITY_DIR

ALIASES = {
    "date": {"date", "asof", "dt", "timestamp", "day"},
    "open": {"open", "o", "open_price"},
    "high": {"high", "h", "high_price"},
    "low": {"low", "l", "low_price"},
    "close": {"close", "c", "close_price", "last"},
    "adj_close": {"adj_close", "adjclose", "adjusted_close", "adj close"},
    "volume": {"volume", "vol", "v"},
}
ORDER = ["date", "open", "high", "low", "close", "adj_close", "volume"]


def _canon(df: pd.DataFrame) -> pd.DataFrame:
    lower = {str(c).lower().strip(): c for c in df.columns}
    rename = {}
    for canon, aliases in ALIASES.items():
        if canon in lower:
            continue
        for a in sorted(aliases):
            if a in lower:
                rename[lower[a]] = canon
                break
    return df.rename(columns=rename)


def _equity_dir(src: Path) -> Path | None:
    for cand in (src / "historical", src):
        if cand.is_dir() and any(
            f.suffix.lower() == ".csv" for f in cand.glob("*.csv")
        ):
            return cand
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Import equity OHLCV into a Parquet store.")
    ap.add_argument("--src", type=Path, default=DATA_DIR / "raw",
                    help="root of your raw data (e.g. ~/.meridian-data)")
    args = ap.parse_args()
    src = args.src.expanduser()

    edir = _equity_dir(src)
    if not edir:
        sys.exit(f"No equity CSVs found under {src} (looked in ./ and ./historical).")

    EQUITY_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(edir.glob("*.csv"))
    print(f"Found {len(files)} equity CSV(s) in {edir}\n")

    n = 0
    for f in files:
        ticker = f.stem.upper()
        try:
            df = _canon(pd.read_csv(f))
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {ticker}: {exc}")
            continue
        if "date" not in df.columns or "close" not in df.columns:
            print(f"  ! {ticker}: missing date/close (cols: {list(df.columns)[:10]})")
            continue
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        for c in ("open", "high", "low", "close", "adj_close", "volume"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.reindex(columns=ORDER).dropna(subset=["date", "close"])
        df.to_parquet(EQUITY_DIR / f"{ticker}.parquet", index=False)
        n += 1
    print(f"\nWrote {n} equity file(s) to {EQUITY_DIR}")


if __name__ == "__main__":
    main()
