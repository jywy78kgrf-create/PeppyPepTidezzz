# Data contract — how to hand the desk your 112 tickers

The backtester and learning loop read a **survivorship-aware** options store.
You supply two things: per-ticker option chains, and a universe/calendar file.

## 1. Option chains — `data/chains/<TICKER>.parquet`

One Parquet (preferred) or CSV file per ticker. One row = one contract on one
observation date. Required columns (exact names, lowercase):

| column                | type     | notes                                  |
|-----------------------|----------|----------------------------------------|
| `asof`                | date     | observation date (`YYYY-MM-DD`)        |
| `expiry`              | date     | option expiry (`YYYY-MM-DD`)           |
| `strike`              | float    | strike price                           |
| `option_type`         | str      | `C` or `P` (also accepts call/put)     |
| `bid`                 | float    |                                        |
| `ask`                 | float    |                                        |
| `last`                | float    |                                        |
| `volume`              | int      |                                        |
| `open_interest`       | int      |                                        |
| `implied_volatility`  | float    | decimal, e.g. 0.32 (also accepts %)    |
| `delta`               | float    |                                        |
| `gamma`               | float    |                                        |
| `theta`               | float    | per-day                                |
| `vega`                | float    | per 1 vol point                        |
| `rho`                 | float    |                                        |
| `underlying_close`    | float    | underlying price on `asof`             |

Extra columns are ignored. Greeks may be left blank for any row — the engine
recomputes missing greeks from a Black–Scholes model (`quant/greeks.py`).

## 2. Universe / calendar — `data/universe/universe.csv`

Drives **survivorship handling**. One row per ticker:

| column        | type | notes                                              |
|---------------|------|----------------------------------------------------|
| `ticker`      | str  |                                                    |
| `listed`      | date | first tradeable date in your data                  |
| `delisted`    | date | delist date, or blank if still active              |
| `sector`      | str  | optional, used for grouping/diversification        |

If a ticker delisted mid-history, **keep it in the data**. The backtester
counts delisted names (`delisted_included` in metrics) so results are not
silently survivorship-biased. Dropping dead names is the #1 way backtests lie.

## Loading

```python
from optdesk.data.loader import ChainStore
store = ChainStore()              # reads data/chains + data/universe
chain = store.chain("AAPL", "2023-06-15")   # -> list[OptionQuote] with greeks
dates = store.trading_dates("AAPL")
```

## Don't have it formatted yet?

Run `python -m optdesk.data.make_sample` to generate a small synthetic store
(3 tickers, full greeks) so the whole pipeline runs end-to-end before your real
data lands. Replace `data/chains` with your files and everything else is
unchanged.
