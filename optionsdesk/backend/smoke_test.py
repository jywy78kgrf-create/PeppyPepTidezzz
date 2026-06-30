#!/usr/bin/env python
"""
End-to-end smoke test for the ATLAS options desk.

Builds the sample store if chains are missing, runs a 1-ticker backtest and a
2-iteration learning loop, prints metrics, and exits 0 on success / non-zero on
failure.  Run from optionsdesk/backend:

    python smoke_test.py
"""
from __future__ import annotations

import sys
import traceback
from datetime import date


def _ensure_data() -> "object":
    from optdesk.data.loader import ChainStore

    store = ChainStore()
    if not store.tickers():
        print("[smoke] no chains found -> generating sample store")
        from optdesk.data import make_sample

        make_sample.main()
        store = ChainStore()
    if not store.tickers():
        raise RuntimeError("sample store generation produced no tickers")
    return store


def main() -> int:
    try:
        store = _ensure_data()
        tickers = store.tickers()
        ticker = tickers[0]
        dates = store.trading_dates(ticker)
        start, end = dates[0], dates[-1]
        print(f"[smoke] ticker={ticker} dates={start}..{end} ({len(dates)} days)")

        # --- 1) suggester smoke (best-effort) ----------------------------
        from optdesk.strategies.suggester import StrategySuggester

        chain = store.chain(ticker, dates[len(dates) // 4])
        specs = StrategySuggester().suggest(chain, dates[len(dates) // 4], top_k=3)
        print(f"[smoke] suggester returned {len(specs)} specs")
        strat = specs[0].name if specs else "bull_put_spread"

        # --- 2) backtest -------------------------------------------------
        from optdesk.backtest.engine import Backtester

        bt = Backtester(store)
        result = bt.run(strat, {}, [ticker], start, end)
        m = result.metrics
        print(
            f"[smoke] backtest {strat}: trades={m.n_trades} "
            f"sortino={m.sortino:.3f} sharpe={m.sharpe:.3f} "
            f"total_return={m.total_return:.4f} maxdd={m.max_drawdown:.4f}"
        )

        # --- 3) learn (2 iterations) -------------------------------------
        from optdesk.learn.loop import LearningLoop

        loop = LearningLoop(store)
        seen: list[int] = []
        out = loop.run(
            strat, [ticker], start, end, n_iter=2, objective="sortino",
            on_iter=lambda it: seen.append(it.iteration),
        )
        print(
            f"[smoke] learn: iterations={len(out['history'])} "
            f"streamed={len(seen)} best_oos="
            f"{out['history'][-1].oos_score if out['history'] else 'n/a'}"
        )
        print(f"[smoke] best_params={out['best_params']}")

        # --- 4) paper broker round-trip ----------------------------------
        from optdesk.paper.broker import PaperBroker
        from optdesk.strategies.library import STRATEGIES

        spec = None
        if strat in STRATEGIES:
            spec = STRATEGIES[strat](chain, chain[0].underlying, {})
        if spec is None and specs:
            spec = specs[0]
        if spec is not None:
            pb = PaperBroker(starting_cash=100_000.0)
            pos = pb.open(spec, chain, qty=1)
            pb.mark(store)
            eq = pb.equity()
            print(
                f"[smoke] paper: opened {pos.spec_name} basis={pos.cost_basis:.2f} "
                f"upnl={pos.upnl:.2f} total_equity={eq['total']:.2f}"
            )

        print("[smoke] PASS")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[smoke] FAIL: {exc!r}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
