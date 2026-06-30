# Architecture notes

## Design principles
1. **One contract spine.** `contracts.py` defines every type that crosses a
   subsystem boundary. Subsystems depend on contracts, not on each other's
   internals — so the quant engine, services, and UI evolve independently.
2. **Honest backtests or none.** Every backtest charges the bid/ask spread,
   per-contract commission + exchange fees, modelled slippage, and a daily
   cost-of-carry on held debit/margin. Delisted tickers stay in the universe
   and are force-closed at intrinsic on their delist date; metrics report how
   many delisted names were included. A backtest that silently drops dead
   names is a marketing deck, not a research tool.
3. **Paper == backtest accounting.** The paper desk reuses the same fill/cost
   model, so a strategy's paper P&L is directly comparable to its backtest.
4. **The IBKR seam is wired, not live.** `brokers/ibkr.py` imports cleanly with
   or without `ib_insync` and refuses to place orders unless live trading is
   explicitly enabled and connected — live trading is a config flip, not a
   rewrite.

## The recursive learning loop
`learn/loop.py` runs walk-forward optimization:
- The history is split into in-sample / out-of-sample folds.
- Parameters start from library defaults; the search **mutates the current
  best** and explores neighbors (evolutionary / bandit style).
- A candidate is **accepted only if it improves the out-of-sample objective**
  (Sortino by default), which guards against in-sample overfitting.
- Each iteration is a `LearnIteration` record; the UI streams these so you watch
  the objective climb as the desk improves itself.

## Data flow
`ChainStore` → `StrategySuggester` ranks `StrategySpec`s → `Backtester` simulates
→ `LearningLoop` tunes → `PaperBroker` forward-tests → `IBKRBroker` (future) for
live. `AlphaVantage` supplies live quotes/chains for the paper + live stages.
The FastAPI layer exposes all of this to the React desk.

## Extending
- **New strategy:** add a builder to `strategies/library.py` and register it in
  `STRATEGIES`. The suggester, backtester, learner, paper desk, and API pick it
  up with no other changes.
- **New broker:** subclass `brokers/base.BrokerBase`.
- **New data source:** conform it to `docs/DATA_CONTRACT.md` or add a loader that
  yields `OptionQuote`s.
