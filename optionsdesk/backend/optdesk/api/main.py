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
import math
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
    SizeRequest,
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
    """Recursively convert dataclasses/dates/enums into JSON-safe values.

    Non-finite floats (inf/-inf/NaN) are converted to ``None`` — they are not
    valid JSON, and emitting them makes the browser's ``response.json()`` throw
    (e.g. a long call's unlimited ``max_profit`` or an infinite ``profit_factor``
    when there were no losing trades).

    numpy scalars (``np.int64``/``np.float64``/``np.bool_``) are coerced to
    native Python via ``.item()`` — ``json.dumps`` rejects ``np.int64``, and
    learn-loop param mutation / pandas-backed data can leak them into payloads.
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: serialize(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, (_dt.date, _dt.datetime)):
        return obj.isoformat()
    if isinstance(obj, float):  # includes np.float64 (a float subclass)
        return float(obj) if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [serialize(v) for v in obj]
    if hasattr(obj, "value") and isinstance(getattr(obj, "value"), (str, int)):
        return obj.value  # Enum
    if hasattr(obj, "item") and not isinstance(obj, (str, bytes)):
        try:
            return serialize(obj.item())  # numpy scalar -> native Python
        except Exception:  # noqa: BLE001 - non-scalar .item(); pass through
            return obj
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
# when scanning the whole universe, cap how many names we touch so the endpoint
# stays responsive (each name = one chain read + suggest).
_SUGGEST_SCAN_CAP = 60


@app.get("/api/suggestions")
def suggestions(
    ticker: str | None = Query(None, description="a ticker, or omit / 'ALL' to scan the universe"),
    date: str | None = Query(None, description="defaults to latest trading date"),
    top_k: int = Query(6, ge=1, le=25),
) -> dict:
    from ..strategies.suggester import StrategySuggester

    s = store()
    suggester = StrategySuggester(SETTINGS)

    # ---- whole-universe scan (default / "ALL"): best ideas across all names ---
    if not ticker or ticker.upper() == "ALL":
        universe = s.tickers()[:_SUGGEST_SCAN_CAP]
        pooled: list = []
        latest = None
        for tk in universe:
            try:
                dates = s.trading_dates(tk)
                if not dates:
                    continue
                asof = _parse_date(date) if date else dates[-1]
                chain = s.chain(tk, asof)
                if not chain:
                    continue
                pooled.extend(suggester.suggest(chain, asof, top_k=2))
                latest = asof if latest is None else max(latest, asof)
            except Exception:  # noqa: BLE001 - one bad name can't sink the scan
                continue
        pooled.sort(key=lambda sp: sp.score, reverse=True)
        return {
            "asof": latest.isoformat() if latest else "",
            "ticker": "ALL",
            "scanned": len(universe),
            "suggestions": [serialize(sp) for sp in pooled[:top_k]],
        }

    # ---- single ticker -------------------------------------------------------
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
    specs = suggester.suggest(chain, asof, top_k=top_k)
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
            req.strategy, req.params, req.tickers, req.start, req.end,
            capital=req.capital, risk=req.risk,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"backtest failed: {exc}") from exc

    summary = result.to_summary()
    summary["equity_curve"] = _sample(
        [serialize(p) for p in result.equity_curve], MAX_CURVE_POINTS
    )
    summary["trades"] = _sample(
        [serialize(t) for t in result.trades], MAX_TRADES
    )
    return serialize(summary)


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
    return serialize({
        "best": out["best"],
        "best_params": out["best_params"],
        "objective": out.get("objective", req.objective),
        "folds": out.get("folds"),
        "holdout": out.get("holdout"),
        "regimes": out.get("regimes"),
        "history": [it for it in out["history"]],
    })


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
    """Server-sent events: one event per learning iteration as it completes.

    The loop runs in a worker thread that pushes serialized events through a
    queue; the response generator yields them as they arrive.  This streams
    for real — the first iteration reaches the client while the search is
    still running, instead of every event being buffered until the whole loop
    has finished.
    """
    import queue
    import threading

    from ..learn.loop import LearningLoop

    tick_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    s_start, s_end = _parse_date(start), _parse_date(end)

    def gen() -> Iterable[str]:
        q: queue.Queue = queue.Queue()
        sentinel = object()  # marks worker completion

        def on_iter(it) -> None:
            q.put("data: " + json.dumps(serialize(it)) + "\n\n")

        def work() -> None:
            loop = LearningLoop(store(), SETTINGS)
            try:
                out = loop.run(
                    strategy, tick_list, s_start, s_end,
                    n_iter=n_iter, objective=objective, seed=seed, on_iter=on_iter,
                )
                q.put("event: done\ndata: " + json.dumps(serialize(
                    {"best": out["best"], "best_params": out["best_params"],
                     "holdout": out.get("holdout"),
                     "regimes": out.get("regimes")}
                )) + "\n\n")
            except Exception as exc:  # noqa: BLE001
                q.put("data: " + json.dumps({"error": str(exc)}) + "\n\n")
            finally:
                q.put(sentinel)

        threading.Thread(target=work, daemon=True).start()
        while True:
            item = q.get()
            if item is sentinel:
                break
            yield item

    return StreamingResponse(gen(), media_type="text/event-stream")


# --------------------------------------------------------------------------- #
# Risk: sizing config + per-trade preview
# --------------------------------------------------------------------------- #
@app.get("/api/risk/config")
def risk_config() -> dict:
    """Default position-sizing / risk-budget configuration."""
    from ..risk import RiskConfig

    return RiskConfig().to_dict()


@app.post("/api/risk/size")
def risk_size(req: SizeRequest) -> dict:
    """Preview how many contracts a strategy would trade under a risk config.

    Returns the desired vs budget-capped lots and the binding concentration cap,
    so the desk can show *why* a position is the size it is.
    """
    from ..risk import PositionSizer, RiskBudget, RiskConfig, unit_risk_for
    from ..strategies.library import STRATEGIES
    from ..strategies.suggester import StrategySuggester

    s = store()
    asof = req.date or (s.trading_dates(req.ticker)[-1] if s.trading_dates(req.ticker) else None)
    if asof is None:
        raise HTTPException(404, f"no data for {req.ticker}")
    chain = s.chain(req.ticker, asof)
    if not chain:
        raise HTTPException(404, f"no chain for {req.ticker} on {asof}")

    spec = None
    if req.strategy in STRATEGIES:
        spec = STRATEGIES[req.strategy](chain, chain[0].underlying, req.params or {})
    if spec is None:
        ranked = StrategySuggester(SETTINGS).suggest(chain, asof, top_k=10, params=req.params)
        spec = next((sp for sp in ranked if sp.name == req.strategy), ranked[0] if ranked else None)
    if spec is None:
        raise HTTPException(400, f"could not build strategy {req.strategy}")

    rc = RiskConfig.from_dict(req.risk)
    equity = float(req.equity or SETTINGS.starting_capital)
    unit_risk = unit_risk_for(spec, equity, rc)
    desired = PositionSizer(rc).desired_contracts(spec, equity, unit_risk)
    decision = RiskBudget(rc, _sector_map_from_store(s)).fit(
        spec, desired, unit_risk, equity, [], explain=True
    )
    return {
        "asof": asof.isoformat(),
        "strategy": spec.name,
        "ticker": spec.ticker,
        "equity": equity,
        "method": rc.method,
        "spec": serialize(spec),
        "sizing": serialize(decision),
    }


def _sector_map_from_store(s: ChainStore) -> dict[str, str]:
    u = s.universe
    out: dict[str, str] = {}
    if u is not None and not u.empty and "sector" in u and "ticker" in u:
        for _, row in u.iterrows():
            if isinstance(row.get("ticker"), str):
                out[row["ticker"].upper()] = str(row.get("sector") or "UNKNOWN")
    return out


# --------------------------------------------------------------------------- #
# Paper trading
# --------------------------------------------------------------------------- #
def _paper():
    from ..paper.broker import PaperBroker

    return PaperBroker(starting_cash=SETTINGS.starting_capital)


def _alpha_vantage():
    """AV client factory (module-level seam so tests can monkeypatch it)."""
    from ..live.alpha_vantage import AlphaVantage

    return AlphaVantage()


def _paper_book(pb, live: bool) -> dict:
    """Contract shape shared by GET /paper/positions and POST /paper/mark."""
    return serialize({
        "positions": [p for p in pb.positions()],
        "equity": pb.equity(),
        "live": bool(live),
        "asof": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    })


def _mark_and_book(pb) -> dict:
    """Mark the paper book (live when an AV key is configured, else the
    latest historical chain) and return the contract-shaped payload.

    ``mark_live`` snapshots equity history internally and never raises."""
    res = pb.mark_live(_alpha_vantage(), store=store())
    return _paper_book(pb, res.get("live", False))


@app.get("/api/paper/positions")
def paper_positions() -> dict:
    return _mark_and_book(_paper())


@app.post("/api/paper/mark")
def paper_mark() -> dict:
    return _mark_and_book(_paper())


@app.get("/api/paper/history")
def paper_history() -> dict:
    return serialize({"points": _paper().history()})


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


@app.get("/api/paper/greeks")
def paper_greeks() -> dict:
    """Aggregate greeks of the OPEN paper book, marked off each ticker's latest
    chain. Delta is share-equivalent (delta x 100 x contracts, signed); theta
    is $/day; vega is $ per vol point. The book-level view a desk actually
    watches — you can be short vega five different ways and not know it
    position-by-position."""
    from datetime import date as _date

    pb = _paper()
    s = store()
    totals = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    by_ticker: dict[str, dict] = {}
    unmatched = 0

    for pos in pb.positions():
        if pos.status != "OPEN":
            continue
        tk = pos.ticker.upper()
        try:
            dates = s.trading_dates(tk)
            chain = s.chain(tk, dates[-1]) if dates else []
        except FileNotFoundError:
            chain = []
        lookup = {(q.kind.value, round(q.strike, 4), q.expiry.isoformat()): q
                  for q in chain}
        row = by_ticker.setdefault(tk, {"delta": 0.0, "gamma": 0.0,
                                        "theta": 0.0, "vega": 0.0})
        for leg in pos.legs:
            q = lookup.get((leg["kind"], round(float(leg["strike"]), 4),
                            str(leg["expiry"])[:10]))
            if q is None:
                unmatched += 1
                continue
            sign = -1.0 if leg["action"] == "SELL" else 1.0
            mult = sign * int(leg["quantity"]) * 100.0
            row["delta"] += q.delta * mult
            row["gamma"] += q.gamma * mult
            row["theta"] += q.theta * mult
            row["vega"] += q.vega * mult
        for k in totals:
            totals[k] += row[k]

    return serialize({
        "asof": _date.today().isoformat(),
        "totals": {k: round(v, 2) for k, v in totals.items()},
        "by_ticker": {t: {k: round(v, 2) for k, v in row.items()}
                      for t, row in by_ticker.items()},
        "unmatched_legs": unmatched,
    })


# --------------------------------------------------------------------------- #
# AutoPilot — autonomous research/promote/paper-trade loop (paper ONLY)
# --------------------------------------------------------------------------- #
@app.on_event("startup")
def _start_autopilot() -> None:
    """Start the heartbeat thread; the pilot stays idle until enabled."""
    from ..auto import get_pilot
    get_pilot()


@app.get("/api/auto/status")
def auto_status() -> dict:
    from ..auto import get_pilot
    return serialize(get_pilot().status())


@app.post("/api/auto/enable")
def auto_enable() -> dict:
    from ..auto import get_pilot
    pilot = get_pilot()
    status = pilot.enable()
    # kick an immediate cycle in the background so enabling feels alive
    import threading
    threading.Thread(target=pilot.tick, daemon=True).start()
    return serialize(status)


@app.post("/api/auto/disable")
def auto_disable() -> dict:
    from ..auto import get_pilot
    return serialize(get_pilot().disable("kill switch (user)"))


@app.get("/api/auto/activity")
def auto_activity(limit: int = Query(50, ge=1, le=200)) -> dict:
    from ..auto import get_pilot
    return {"events": serialize(get_pilot().activity(limit))}


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
