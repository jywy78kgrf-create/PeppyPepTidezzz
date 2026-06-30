# ATLAS — Automated Options Trading & Learning Desk

An agentic options desk that **suggests** strategies, **backtests** them with
honest cost accounting (spread, commissions, slippage, cost-of-carry,
survivorship), **learns** from results in a recursive walk-forward loop, then
graduates winners into **paper trading** — wired to step up to **IBKR live**.
Live market data via **Alpha Vantage** (premium tier).

```
                 ┌─────────────────────────────────────────────┐
   your data ──▶ │  data layer (survivorship-aware ChainStore)  │
  112 tickers    └───────────────┬─────────────────────────────┘
  4.5y greeks                    │
                 ┌───────────────▼───────────┐   ┌──────────────────┐
                 │  strategy library +       │   │ quant: BS greeks │
                 │  suggester (ranked specs) │◀──│ pricing / payoff │
                 └───────────────┬───────────┘   └──────────────────┘
                 ┌───────────────▼───────────┐
                 │  event-driven backtester  │  spread • commission •
                 │  (real cost model)        │  slippage • carry • survivorship
                 └───────────────┬───────────┘
                 ┌───────────────▼───────────┐   recursive self-improvement
                 │  learning loop            │   walk-forward IS/OOS, accept
                 │  (walk-forward search)    │   only if OOS objective improves
                 └───────────────┬───────────┘
        ┌────────────────────────┼────────────────────────┐
        ▼                        ▼                         ▼
 ┌─────────────┐        ┌────────────────┐        ┌────────────────┐
 │ paper desk  │        │ Alpha Vantage  │        │ IBKR seam      │
 │ (live uPnL) │        │ live quotes    │        │ (ib_insync)    │
 └─────────────┘        └────────────────┘        └────────────────┘
        ▲
        └────────────  FastAPI  ◀──  React/Three.js desk UI
```

## Layout

```
optionsdesk/
  backend/optdesk/
    contracts.py        shared domain types (the spine)
    config.py           settings (env-overridable)
    data/               ChainStore loader + synthetic sample generator
    quant/              Black-Scholes greeks, pricing, payoff
    strategies/         strategy library + ranked suggester
    backtest/           event-driven engine + portfolio accounting
    learn/              recursive walk-forward learning loop
    paper/              paper-trading broker (persisted)
    brokers/            broker base + IBKR live seam
    live/               Alpha Vantage premium client
    api/                FastAPI app (frontend talks to this)
  frontend/             Vite + React + Three.js animated desk UI
  data/                 your option chains + universe (see docs/DATA_CONTRACT.md)
  docs/                 DATA_CONTRACT.md, ARCHITECTURE.md
```

## Quick start

```bash
# 1. backend
cd optionsdesk/backend
pip install -r requirements.txt
python -m optdesk.data.make_sample        # synthetic store so it runs now
python smoke_test.py                       # backtest + 2-iter learn, exits 0
bash run_api.sh                            # FastAPI on :8000

# 2. frontend (separate shell)
cd optionsdesk/frontend
npm install && npm run dev                 # desk UI on :5173
```

## Bringing your own data

Format your 112 tickers per **`docs/DATA_CONTRACT.md`** and drop them in
`data/chains/<TICKER>.parquet` + `data/universe/universe.csv`. Nothing else
changes — keep delisted names in place so the backtest stays survivorship-honest.

## Going live (later)

`pip install ib_insync`, run IB Gateway/TWS, set `OPTDESK_LIVE=1` and IBKR_* env
vars. The `brokers/ibkr.py` seam maps strategy legs to IB option combos. Paper
trading uses the identical fill/cost accounting as the backtester, so promotion
is apples-to-apples.

> Research / educational tooling. Options trading carries substantial risk;
> backtested performance is not indicative of future results. Review every
> model and cost assumption before risking capital.
