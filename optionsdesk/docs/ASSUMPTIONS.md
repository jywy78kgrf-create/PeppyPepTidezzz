# Modeling assumptions & known limitations

A backtest is only defensible if its assumptions are explicit. These are ours.
Each one biases results in a known direction; read this before trusting a number.

## Execution model
- **T+1 fills (default).** Signals are generated from a day's end-of-day chain
  and fill on the ticker's NEXT trading day at that day's quotes (`fill_lag: 1`).
  Legs are re-located by exact strike/expiry; if any leg is unquotable at fill
  time, the signal is abandoned. Set `fill_lag: 0` to reproduce the older,
  flattering same-close behavior. Sizing/budgeting happens at fill time with
  fill-day equity.
- **Spread crossing.** Every entry/exit pays `slippage_frac_of_spread` (default
  25%) of the quoted bid/ask spread, floored at `min_slippage`, plus
  per-contract commission and exchange fees on every leg, both sides.
  Marks for open positions use the mid.
- **No market impact / size limits.** Fills assume your size doesn't move the
  market and ignores quoted depth. At 1–50 contracts on liquid names this is
  reasonable; at institutional size it is not.

## Options mechanics
- **Early assignment IS modeled (extrinsic trigger).** A short leg that is ITM
  with a live quote whose extrinsic value (mid − intrinsic) falls below
  `assign_extrinsic` (default $0.03/share) is assigned: the whole position
  closes (`closed_reason: "assigned"`), assigned legs at intrinsic, the rest at
  market, plus the assignment fee. Dividend-capture assignment is approximated
  by this extrinsic rule, not by an ex-div calendar (no dividend data).
- **Expiry at intrinsic.** Positions reaching expiry settle at intrinsic value
  computed from the last-seen underlying close (cash-settled approximation;
  no pin risk, no assignment fees).
- **Greeks from data; Black-Scholes fallback.** Data-supplied greeks are used
  as-is. Missing greeks are recomputed with Black-Scholes from the quoted IV —
  European, no dividend yield term unless configured.

## Costs & carry
- **Reg-T-style margin at open.** Capital-at-risk for credit structures is
  max(modelled max loss, a Reg-T-style requirement): defined-risk spreads carry
  width − credit; naked shorts carry premium + max(20%·U − OTM, 10%·U for
  calls / 10%·K for puts). Computed once at open — real margin re-marks daily
  with the underlying, so a position moving against you would demand more
  margin than modeled here.
- **Cost of carry** accrues daily at `financing_apr` on that capital-at-risk.
- **No borrow costs / dividends** on the underlying (relevant only to covered
  calls, which here approximate the option overlay, not full stock carry).

## Data & survivorship
- **Universe honesty.** Delisted tickers stay in the universe; their positions
  are force-closed at intrinsic on the delist date and metrics report how many
  delisted names traded. However: if the *source data itself* was assembled
  from currently-listed names (a fixed 112-ticker universe), the universe has
  survivorship bias the engine cannot remove. Results generalize to "this
  universe as it existed," not "stocks in general."
- **Derived listing dates.** Listed/delisted are inferred from each ticker's
  observed date span (gap > 15 days from the dataset's end = delisted).
- **Quote quality.** Bid/ask are as recorded EOD. Stale or crossed quotes in
  the source pass through the spread-crossing cost model unfiltered.

## Signal gates (equity filters)
- **On by default** (`use_signals: true`) when equity OHLCV data exists; pure
  pass-through otherwise, and per-ticker pass-through for tickers without
  equity data. Bullish structures require close > SMA50, bearish the reverse;
  short-premium entries require the 20d realized-vol percentile below
  `rv_entry_max_pct` (default 0.85), long-premium above `rv_entry_min_pct`
  (default 0.10). **No lookahead:** the gate's decision for day D uses equity
  data through D−1 only (indicators are shifted one day).

## Learning loop
- **Walk-forward, accept-on-OOS.** Parameters are searched on an in-sample
  fold and accepted only when the out-of-sample objective improves. Repeated
  acceptance decisions against the same OOS window mean best-params are still
  *selected on* that window — treat OOS scores as optimistic. The final
  holdout evaluation (never touched during search) is the number to trust.
- **No regime awareness.** 4.5 years is one macro regime sample. A strategy
  tuned on 2021–2026 embeds that period's vol structure.

## AutoPilot
- **Paper only, off by default.** The autonomous loop drives the paper broker
  exclusively; it cannot place real orders. The kill switch must be engaged by
  a human, and the −3% daily circuit breaker disables it without asking.
- **Decisions on EOD chains, management on live marks.** New positions are
  constructed from the latest end-of-day chain (the semantics the backtester
  was validated under); exits are evaluated against live Alpha Vantage marks.
  If your historical store is stale, the pilot is trading yesterday's chain —
  keep the data current.
- **Promotion is holdout-gated, not backtest-gated.** A config trades only if
  the learner's untouched final holdout cleared the bar — but a good holdout
  on 4.5 years still guarantees nothing about next week. That is precisely
  what the paper phase exists to measure.

## Paper & live
- **Paper == backtest accounting** (same fill/cost model) by construction, so
  paper results are comparable to backtests — and share the same limitations.
- **Live marks are quotes, not fills.** When an Alpha Vantage key is configured
  the paper book marks from realtime option quotes (LIVE pill); otherwise from
  the latest end-of-day chain (EOD pill). A live mark says what the book is
  worth, not what you could necessarily execute at.
- **Live trading is a seam, not a promise.** The IBKR adapter maps legs to
  combo orders but has never placed a real order; validate in IB's paper
  environment first, with tiny size.

> None of this is investment advice. The desk is a research instrument; every
> number it produces inherits every assumption above.
