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
    risk/               position sizing + portfolio risk budgeting
    learn/              recursive walk-forward learning loop
    paper/              paper-trading broker (persisted)
    brokers/            broker base + IBKR live seam
    live/               Alpha Vantage premium client
    api/                FastAPI app (frontend talks to this)
  frontend/             Vite + React + Three.js animated desk UI
  data/                 your option chains + universe (see docs/DATA_CONTRACT.md)
  docs/                 DATA_CONTRACT.md, ARCHITECTURE.md
```

## Quick start — Docker (recommended)

One command brings up the API and the desk UI (nginx serves the SPA and
reverse-proxies `/api` to the backend, so it's a single origin):

```bash
cd optionsdesk
cp .env.example .env          # optional: add ALPHAVANTAGE_API_KEY etc.
docker compose up --build
# open http://localhost:8080   (API also exposed on :8000)
```

The backend seeds a synthetic store on first boot so the desk works immediately.
`./data` is bind-mounted — drop your real chains in and restart, no rebuild. The
paper-trading book persists in the `paperstate` volume.

## Quick start — local (no Docker)

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

## Position sizing & risk budgeting

Every backtested/paper position is sized to a **risk budget**, not a flat lot.
`optdesk/risk/` provides:

- **Sizing rules** (`PositionSizer`): `fixed`, `fixed_fraction` (risk N% of equity
  per trade), `kelly` (fractional Kelly from POP × reward:risk — refuses
  negative-edge trades), and `risk_parity` (equal risk per slot).
- **Portfolio caps** (`RiskBudget`): total capital-at-risk, single-position,
  per-ticker, and per-sector concentration limits, plus a concurrency cap. A
  new position is trimmed to fit every live cap; the binding cap is reported.

Pass a `risk` block to a backtest, or preview sizing directly:

```bash
curl -s localhost:8000/api/risk/config
curl -s -X POST localhost:8000/api/risk/size \
  -H 'content-type: application/json' \
  -d '{"strategy":"iron_condor","ticker":"AAPL","equity":100000,
       "risk":{"method":"fixed_fraction","risk_per_trade":0.02,"per_ticker_frac":0.12}}'
# -> {"sizing":{"contracts":4,"unit_risk":474.5,"position_risk":1898.0,"reason":"ok",...}}
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

## Trusting the numbers

Every modeling assumption (execution, assignment, carry, survivorship, the
learning loop's optimism) is documented in **`docs/ASSUMPTIONS.md`** with the
direction it biases results. The backend ships a pytest suite (`backend/tests/`)
covering greeks parity, cost-accounting identity, exit-trigger direction,
survivorship force-close, and risk-cap enforcement:

```bash
cd optionsdesk/backend && python -m pytest tests -q
```

> Research / educational tooling. Options trading carries substantial risk;
> backtested performance is not indicative of future results. Review every
> model and cost assumption before risking capital.
