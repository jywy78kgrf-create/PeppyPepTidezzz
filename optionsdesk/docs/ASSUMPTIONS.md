# Modeling assumptions & known limitations

A backtest is only defensible if its assumptions are explicit. These are ours.
Each one biases results in a known direction; read this before trusting a number.

## Execution model
- **EOD fills.** Signals are generated from a day's end-of-day chain and filled
  the same day at that chain's quotes. There is no intraday timing. Real fills
  would occur the next session; in trending markets this flatters entries
  slightly. (Roadmap: optional next-day-open fill mode.)
- **Spread crossing.** Every entry/exit pays `slippage_frac_of_spread` (default
  25%) of the quoted bid/ask spread, floored at `min_slippage`, plus
  per-contract commission and exchange fees on every leg, both sides.
  Marks for open positions use the mid.
- **No market impact / size limits.** Fills assume your size doesn't move the
  market and ignores quoted depth. At 1–50 contracts on liquid names this is
  reasonable; at institutional size it is not.

## Options mechanics
- **European-style management.** Early assignment is NOT modeled. Short ITM
  options near ex-dividend or deep ITM would sometimes be assigned early in
  reality; positions here are held to the managed exit. This flatters short
  premium strategies slightly.
- **Expiry at intrinsic.** Positions reaching expiry settle at intrinsic value
  computed from the last-seen underlying close (cash-settled approximation;
  no pin risk, no assignment fees).
- **Greeks from data; Black-Scholes fallback.** Data-supplied greeks are used
  as-is. Missing greeks are recomputed with Black-Scholes from the quoted IV —
  European, no dividend yield term unless configured.

## Costs & carry
- **Cost of carry** accrues daily at `financing_apr` on capital-at-risk (net
  debit paid, or modeled max-loss margin for credit structures). This is a
  simplification of actual Reg-T/portfolio-margin requirements — real margin on
  undefined-risk structures varies daily with the underlying.
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

## Learning loop
- **Walk-forward, accept-on-OOS.** Parameters are searched on an in-sample
  fold and accepted only when the out-of-sample objective improves. Repeated
  acceptance decisions against the same OOS window mean best-params are still
  *selected on* that window — treat OOS scores as optimistic. The final
  holdout evaluation (never touched during search) is the number to trust.
- **No regime awareness.** 4.5 years is one macro regime sample. A strategy
  tuned on 2021–2026 embeds that period's vol structure.

## Paper & live
- **Paper == backtest accounting** (same fill/cost model) by construction, so
  paper results are comparable to backtests — and share the same limitations.
- **Live trading is a seam, not a promise.** The IBKR adapter maps legs to
  combo orders but has never placed a real order; validate in IB's paper
  environment first, with tiny size.

> None of this is investment advice. The desk is a research instrument; every
> number it produces inherits every assumption above.
