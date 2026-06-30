"""
FastAPI application for the ATLAS options desk.

Wires the data store, suggester, backtester, learning loop, paper broker and
live-data / IBKR seams behind a small REST surface.  Backtest and learn run
synchronously but responses sample/trim the equity curve and trade list so
payloads stay small.  CORS is wide open for local dev.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import json
from typing import Any, Iterable, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from ..config import SETTINGS
from ..contracts import StrategySpec
from ..data.loader import ChainStore
from .schemas import (
    BacktestRequest,
    LearnRequest,
    PaperCloseRequest,
    PaperOpenRequest,
)

VERSION = "0.1.0"
MAX_CURVE_POINTS = 250
MAX_TRADES = 200

app = FastAPI(title="ATLAS Options Desk", version=VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared singletons (lazily created so import never fails if data is missing).
_store: Optional[ChainStore] = None


def store() -> ChainStore:
    global _store
    if _store is None:
        _store = ChainStore()
    return _store


# --------------------------------------------------------------------------- #
# Serialization helpers
# --------------------------------------------------------------------------- #
def serialize(obj: Any) -> Any:
    """Recursively convert dataclasses/dates/enums into JSON-safe values."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: serialize(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, (_dt.date, _dt.datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [serialize(v) for v in obj]
    if hasattr(obj, "value") and isinstance(getattr(obj, "value"), (str, int)):
        return obj.value  # Enum
    return obj


def _sample(seq: list, cap: int) -> list:
    """Evenly downsample a list to at most ``cap`` items (keep endpoints)."""
    n = len(seq)
    if n <= cap:
        return list(seq)
    step = n / cap
    idxs = sorted({int(i * step) for i in range(cap)} | {0, n - 1})
    return [seq[i] for i in idxs if i < n]


# --------------------------------------------------------------------------- #
# Health & universe
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health() -> dict:
    tk = store().tickers()
    return {
        "status": "ok",
        "version": VERSION,
        "data_ready": bool(tk),
        "tickers": tk,
    }


@app.get("/api/universe")
def universe() -> dict:
    s = store()
    sectors: dict[str, str] = {}
    u = s.universe
    if not u.empty and "sector" in u:
        for _, row in u.iterrows():
            sectors[str(row["ticker"]).upper()] = str(row.get("sector", ""))
    return {
        "tickers": s.tickers(),
        "delisted": s.delisted_tickers(),
        "sectors": sectors,
    }


# --------------------------------------------------------------------------- #
# Suggestions
# --------------------------------------------------------------------------- #
@app.get("/api/suggestions")
def suggestions(
    ticker: str = Query(...),
    date: str | None = Query(None, description="defaults to latest trading date for the ticker"),
    top_k: int = Query(5, ge=1, le=25),
) -> dict:
    from ..strategies.suggester import StrategySuggester

    s = store()
    if date:
        asof = _parse_date(date)
    else:
        dates = s.trading_dates(ticker)
        if not dates:
            raise HTTPException(404, f"no data for {ticker}")
        asof = dates[-1]
    chain = s.chain(ticker, asof)
    if not chain:
        raise HTTPException(404, f"no chain for {ticker} on {asof.isoformat()}")
    specs = StrategySuggester(SETTINGS).suggest(chain, asof, top_k=top_k)
    return {
        "asof": asof.isoformat(),
        "ticker": ticker.upper(),
        "suggestions": [serialize(sp) for sp in specs],
    }


# --------------------------------------------------------------------------- #
# Backtest
# --------------------------------------------------------------------------- #
@app.post("/api/backtest")
def backtest(req: BacktestRequest) -> dict:
    from ..backtest.engine import Backtester

    bt = Backtester(store(), settings=SETTINGS)
    try:
        result = bt.run(
            req.strategy, req.params, req.tickers, req.start, req.end, capital=req.capital
        )
    except TypeError:
        # Engine may not accept capital kwarg; retry without it.
        result = bt.run(req.strategy, req.params, req.tickers, req.start, req.end)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"backtest failed: {exc}") from exc

    summary = result.to_summary()
    summary["equity_curve"] = _sample(
        [serialize(p) for p in result.equity_curve], MAX_CURVE_POINTS
    )
    summary["trades"] = _sample(
        [serialize(t) for t in result.trades], MAX_TRADES
    )
    return summary


# --------------------------------------------------------------------------- #
# Learn
# --------------------------------------------------------------------------- #
@app.post("/api/learn")
def learn(req: LearnRequest) -> dict:
    from ..learn.loop import LearningLoop

    loop = LearningLoop(store(), SETTINGS)
    try:
        out = loop.run(
            req.strategy, req.tickers, req.start, req.end,
            n_iter=req.n_iter, objective=req.objective, seed=req.seed,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"learn failed: {exc}") from exc
    return {
        "best": out["best"],
        "best_params": out["best_params"],
        "objective": out.get("objective", req.objective),
        "folds": out.get("folds"),
        "history": [serialize(it) for it in out["history"]],
    }


@app.get("/api/learn/stream")
def learn_stream(
    strategy: str,
    tickers: str,
    start: str,
    end: str,
    n_iter: int = 12,
    objective: str = "sortino",
    seed: int = 7,
) -> StreamingResponse:
    """Server-sent events: one event per learning iteration as it completes."""
    from ..learn.loop import LearningLoop

    tick_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    s_start, s_end = _parse_date(start), _parse_date(end)

    def gen() -> Iterable[str]:
        events: list[str] = []

        def on_iter(it) -> None:
            events.append("data: " + json.dumps(serialize(it)) + "\n\n")

        loop = LearningLoop(store(), SETTINGS)
        try:
            out = loop.run(
                strategy, tick_list, s_start, s_end,
                n_iter=n_iter, objective=objective, seed=seed, on_iter=on_iter,
            )
        except Exception as exc:  # noqa: BLE001
            yield "data: " + json.dumps({"error": str(exc)}) + "\n\n"
            return
        yield from events
        yield "event: done\ndata: " + json.dumps(
            {"best": out["best"], "best_params": out["best_params"]}
        ) + "\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# --------------------------------------------------------------------------- #
# Paper trading
# --------------------------------------------------------------------------- #
def _paper():
    from ..paper.broker import PaperBroker

    return PaperBroker(starting_cash=SETTINGS.starting_capital)


@app.get("/api/paper/positions")
def paper_positions() -> dict:
    pb = _paper()
    pb.mark(store())
    return {
        "positions": [serialize(p) for p in pb.positions()],
        "equity": pb.equity(),
    }


@app.post("/api/paper/open")
def paper_open(req: PaperOpenRequest) -> dict:
    from ..strategies.library import STRATEGIES
    from ..strategies.suggester import StrategySuggester

    s = store()
    asof = req.date
    chain = s.chain(req.ticker, asof)
    if not chain:
        raise HTTPException(404, f"no chain for {req.ticker} on {asof.isoformat()}")
    underlying = chain[0].underlying

    spec: Optional[StrategySpec] = None
    if req.strategy in STRATEGIES:
        spec = STRATEGIES[req.strategy](chain, underlying, req.params or {})
    if spec is None:
        # Fall back to the suggester's best matching strategy.
        ranked = StrategySuggester(SETTINGS).suggest(chain, asof, top_k=10, params=req.params)
        for sp in ranked:
            if sp.name == req.strategy:
                spec = sp
                break
        if spec is None and ranked:
            spec = ranked[0]
    if spec is None:
        raise HTTPException(400, f"could not build strategy {req.strategy}")

    pb = _paper()
    try:
        pos = pb.open(spec, chain, qty=req.qty)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"open failed: {exc}") from exc
    return {"position": serialize(pos), "equity": pb.equity()}


@app.post("/api/paper/close")
def paper_close(req: PaperCloseRequest) -> dict:
    pb = _paper()
    pb.mark(store())
    try:
        pos = pb.close(req.idx)
    except IndexError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"position": serialize(pos), "equity": pb.equity()}


# --------------------------------------------------------------------------- #
# Live data & broker status
# --------------------------------------------------------------------------- #
@app.get("/api/live/quote")
def live_quote(ticker: str) -> dict:
    from ..live.alpha_vantage import AlphaVantage

    return AlphaVantage().quote(ticker)


@app.get("/api/brokers/status")
def brokers_status() -> dict:
    from ..brokers.ibkr import IBKRBroker
    from ..live.alpha_vantage import AlphaVantage

    return {
        "ibkr": IBKRBroker(SETTINGS).status(),
        "alpha_vantage": {"configured": AlphaVantage().configured},
    }


# --------------------------------------------------------------------------- #
def _parse_date(s: str) -> _dt.date:
    try:
        return _dt.date.fromisoformat(s)
    except ValueError as exc:
        raise HTTPException(400, f"bad date {s!r}; use YYYY-MM-DD") from exc
