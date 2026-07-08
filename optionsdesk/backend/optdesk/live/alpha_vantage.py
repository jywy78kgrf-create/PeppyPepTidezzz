"""
Alpha Vantage live-data client (premium tier).

Thin httpx wrapper over the endpoints the desk needs: a stock quote
(``GLOBAL_QUOTE``), a realtime options chain (``REALTIME_OPTIONS``, premium),
and a daily price history (``TIME_SERIES_DAILY``).  The API key is read from
settings/env and never hardcoded.  When no key is configured every method
returns a clear ``{"error": ...}`` dict instead of raising, so callers degrade
gracefully offline.
"""
from __future__ import annotations

import datetime as _dt
import threading
import time as _time
from typing import Any, Optional

import httpx
import pandas as pd

from ..config import SETTINGS

_BASE_URL = "https://www.alphavantage.co/query"

# Short-TTL response cache shared across AlphaVantage instances. The desk marks
# the book AND computes greeks every ~30s, each needing the same realtime chain
# per ticker — without this they'd double-fetch (and each poll re-fetch),
# hammering the API (slow responses -> "STALE", wasted quota). A few seconds of
# staleness in a mark is immaterial; option prices don't move that fast.
_CACHE_TTL_S = 60.0
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _cache_get(key: str) -> Any:
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and (_time.time() - hit[0]) < _CACHE_TTL_S:
            return hit[1]
    return None


def _cache_put(key: str, value: Any) -> None:
    with _cache_lock:
        _cache[key] = (_time.time(), value)


def _is_throttle(msg: Any) -> bool:
    """True if an AV error message reads like a transient rate-limit/throttle
    (worth retrying) rather than a hard error (bad symbol, no key, premium)."""
    m = str(msg).lower()
    return any(s in m for s in (
        "please retry", "rate limit", "per minute", "higher api call",
        "thank you for using alpha vantage",
    ))


class AlphaVantage:
    """Client for Alpha Vantage REST endpoints used by the desk."""

    def __init__(
        self,
        key: str = SETTINGS.alpha_vantage_key,
        premium: bool = True,
        base_url: str = _BASE_URL,
        timeout: float = 15.0,
    ) -> None:
        self.key = key or ""
        self.premium = premium
        self.base_url = base_url
        self.timeout = timeout

    # ------------------------------------------------------------------ #
    @property
    def configured(self) -> bool:
        return bool(self.key)

    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        """Issue a GET; return parsed JSON or an ``{"error": ...}`` dict."""
        if not self.configured:
            return {"error": "alpha_vantage_key not configured"}
        q = dict(params)
        q["apikey"] = self.key
        try:
            resp = httpx.get(self.base_url, params=q, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            return {"error": f"http error: {exc!r}"}
        except ValueError as exc:  # non-JSON body
            return {"error": f"bad response: {exc!r}"}
        # Alpha Vantage signals throttling/limits inside a 200 body.
        if isinstance(data, dict):
            if "Error Message" in data:
                return {"error": data["Error Message"]}
            if "Note" in data:
                return {"error": data["Note"]}  # rate-limit note
            if "Information" in data:
                return {"error": data["Information"]}
        return data

    def _get_with_retry(self, params: dict[str, Any],
                        attempts: int = 3) -> dict[str, Any]:
        """``_get`` that retries TRANSIENT throttles with short backoff.

        The API key is often shared with other apps that briefly saturate the
        per-minute rate cap; AV answers "...Please retry" during those bursts.
        Retrying a beat later rides through the burst instead of dropping to an
        EOD mark. Non-throttle errors (bad symbol, no key, premium wall) are
        returned immediately — no point retrying those."""
        data: dict[str, Any] = {}
        for i in range(max(1, attempts)):
            data = self._get(params)
            if "error" not in data or not _is_throttle(data["error"]):
                return data
            if i < attempts - 1:
                _time.sleep(0.6 * (i + 1))  # 0.6s, 1.2s
        return data

    # ------------------------------------------------------------------ #
    # Endpoints
    # ------------------------------------------------------------------ #
    def quote(self, symbol: str) -> dict[str, Any]:
        """Latest quote for ``symbol`` via GLOBAL_QUOTE (short-TTL cached)."""
        ck = f"quote:{symbol.upper()}"
        cached = _cache_get(ck)
        if cached is not None:
            return cached
        data = self._get_with_retry({"function": "GLOBAL_QUOTE", "symbol": symbol})
        if "error" in data:
            return data
        raw = data.get("Global Quote", {}) or {}
        if not raw:
            return {"error": f"no quote for {symbol}", "symbol": symbol}
        out = {
            "symbol": raw.get("01. symbol", symbol),
            "price": _to_float(raw.get("05. price")),
            "open": _to_float(raw.get("02. open")),
            "high": _to_float(raw.get("03. high")),
            "low": _to_float(raw.get("04. low")),
            "volume": _to_int(raw.get("06. volume")),
            "prev_close": _to_float(raw.get("08. previous close")),
            "change": _to_float(raw.get("09. change")),
            "change_pct": raw.get("10. change percent"),
            "latest_trading_day": raw.get("07. latest trading day"),
        }
        _cache_put(ck, out)
        return out

    def realtime_options(self, symbol: str) -> list[dict[str, Any]]:
        """Realtime option chain via REALTIME_OPTIONS (premium endpoint).

        Returns a list of *normalized* contract dicts with keys:
        ``expiry`` (``YYYY-MM-DD`` str), ``strike`` (float), ``option_type``
        (``"C"``/``"P"``), ``bid``/``ask``/``last`` (floats) — plus ``mark``
        and ``symbol`` passthroughs.  Premium-required / rate-limit notes (and
        any transport failure) surface as ``[{"error": ...}]`` instead of
        raising, so callers can degrade gracefully.
        """
        ck = f"rtopts:{symbol.upper()}"
        cached = _cache_get(ck)
        if cached is not None:
            return cached
        data = self._get_with_retry(
            {"function": "REALTIME_OPTIONS", "symbol": symbol, "require_greeks": "true"}
        )
        if "error" in data:
            return [data]  # errors are NOT cached — retry next call
        contracts = data.get("data") or data.get("options") or []
        if not isinstance(contracts, list):
            return [{"error": "unexpected options payload", "symbol": symbol}]
        out: list[dict[str, Any]] = []
        for raw in contracts:
            row = _normalize_contract(raw, symbol)
            if row is not None:
                out.append(row)
        _cache_put(ck, out)
        return out

    def daily(self, symbol: str, outputsize: str = "compact") -> pd.DataFrame:
        """Daily OHLCV history as a DataFrame (empty frame on error)."""
        data = self._get(
            {
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "outputsize": outputsize,
            }
        )
        if "error" in data:
            return pd.DataFrame()
        series = data.get("Time Series (Daily)", {}) or {}
        if not series:
            return pd.DataFrame()
        rows = []
        for day, vals in series.items():
            rows.append(
                {
                    "date": pd.to_datetime(day).date(),
                    "open": _to_float(vals.get("1. open")),
                    "high": _to_float(vals.get("2. high")),
                    "low": _to_float(vals.get("3. low")),
                    "close": _to_float(vals.get("4. close")),
                    "volume": _to_int(vals.get("5. volume")),
                }
            )
        df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
        return df


def _normalize_contract(raw: Any, symbol: str) -> Optional[dict[str, Any]]:
    """Map one raw REALTIME_OPTIONS row onto the desk's canonical contract.

    AV spells the fields ``expiration`` / ``type`` ("call"/"put") with string
    numbers; we emit ``expiry`` (YYYY-MM-DD str), ``option_type`` ("C"/"P"),
    and float ``strike``/``bid``/``ask``/``last``.  Rows missing an expiry or
    an option type are dropped (unusable for leg matching).
    """
    if not isinstance(raw, dict):
        return None
    expiry = str(raw.get("expiration") or raw.get("expiry") or "").strip()[:10]
    kind = str(raw.get("type") or raw.get("option_type") or "").strip().upper()[:1]
    try:
        expiry = _dt.date.fromisoformat(expiry).isoformat()
    except ValueError:
        return None
    if kind not in ("C", "P"):
        return None
    return {
        "symbol": str(raw.get("symbol") or symbol).upper(),
        "expiry": expiry,
        "strike": _to_float(raw.get("strike")),
        "option_type": kind,
        "bid": _to_float(raw.get("bid")),
        "ask": _to_float(raw.get("ask")),
        "last": _to_float(raw.get("last")),
        "mark": _to_float(raw.get("mark")),
        # greeks & IV (present when require_greeks=true) — needed to build a
        # live OptionQuote chain the strategy builders can select strikes from
        "volume": _to_int(raw.get("volume")),
        "open_interest": _to_int(raw.get("open_interest")),
        "iv": _to_float(raw.get("implied_volatility")),
        "delta": _to_float(raw.get("delta")),
        "gamma": _to_float(raw.get("gamma")),
        "theta": _to_float(raw.get("theta")),
        "vega": _to_float(raw.get("vega")),
        "rho": _to_float(raw.get("rho")),
    }


def live_chain(av: "AlphaVantage", symbol: str,
               asof: Optional[_dt.date] = None) -> list:
    """Build a live ``list[OptionQuote]`` for ``symbol`` from Alpha Vantage.

    This is the SAME price source the paper book marks against, so a position
    opened from this chain and then marked live shows only real post-entry
    P&L — never the vintage gap you'd get opening from a stale historical
    chain and marking live.

    Returns ``[]`` on any error (no key, rate limit, empty chain, no
    underlying quote). Callers MUST treat ``[]`` as "do not open" — opening on
    anything other than this live chain reintroduces the marking mismatch.
    """
    from ..contracts import OptionQuote, OptionType

    rows = av.realtime_options(symbol)
    if not rows or (isinstance(rows[0], dict) and "error" in rows[0]):
        return []
    q = av.quote(symbol)
    underlying = float(q.get("price") or 0.0) if isinstance(q, dict) else 0.0
    if underlying <= 0:
        return []  # no trustworthy underlying -> can't size or select strikes

    asof = asof or _dt.datetime.now(_dt.timezone.utc).date()
    out: list = []
    for r in rows:
        try:
            expiry = _dt.date.fromisoformat(str(r["expiry"]))
            strike = float(r["strike"])
        except (KeyError, TypeError, ValueError):
            continue
        if strike <= 0 or expiry <= asof:
            continue  # expired/same-day contracts are unusable
        out.append(OptionQuote(
            ticker=symbol.upper(),
            asof=asof,
            expiry=expiry,
            strike=strike,
            kind=OptionType.CALL if r["option_type"] == "C" else OptionType.PUT,
            bid=_to_float(r.get("bid")),
            ask=_to_float(r.get("ask")),
            last=_to_float(r.get("last")),
            volume=_to_int(r.get("volume")),
            open_interest=_to_int(r.get("open_interest")),
            iv=_to_float(r.get("iv")),
            delta=_to_float(r.get("delta")),
            gamma=_to_float(r.get("gamma")),
            theta=_to_float(r.get("theta")),
            vega=_to_float(r.get("vega")),
            rho=_to_float(r.get("rho")),
            underlying=underlying,
        ))
    return out


def _to_float(v: Optional[Any]) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _to_int(v: Optional[Any]) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _parse_earnings_csv(text: str) -> dict[str, list[str]]:
    """Parse EARNINGS_CALENDAR CSV into {SYMBOL: [reportDate, ...]} (ISO)."""
    import csv as _csv
    import io as _io

    out: dict[str, list[str]] = {}
    reader = _csv.DictReader(_io.StringIO(text))
    for row in reader:
        sym = (row.get("symbol") or "").strip().upper()
        rd = (row.get("reportDate") or "").strip()[:10]
        if not sym or not rd:
            continue
        try:
            _dt.date.fromisoformat(rd)
        except ValueError:
            continue
        out.setdefault(sym, []).append(rd)
    return out


def fetch_earnings_calendar(av: "AlphaVantage",
                            horizon: str = "3month") -> dict[str, Any]:
    """Upcoming earnings report dates for the whole market.

    Alpha Vantage's EARNINGS_CALENDAR returns CSV (not JSON), so it gets its
    own fetch path. Returns {"earnings": {SYMBOL: [YYYY-MM-DD, ...]}} or
    {"error": ...} — callers treat errors as unknowable and fail OPEN.
    """
    if not av.configured:
        return {"error": "alpha_vantage_key not configured"}
    try:
        resp = httpx.get(av.base_url, params={
            "function": "EARNINGS_CALENDAR", "horizon": horizon,
            "apikey": av.key,
        }, timeout=av.timeout)
        resp.raise_for_status()
        text = resp.text
    except httpx.HTTPError as exc:
        return {"error": f"http error: {exc!r}"}
    if text.lstrip().startswith("{"):  # JSON body = throttle/limit note
        return {"error": text[:200]}
    return {"earnings": _parse_earnings_csv(text)}


def bulk_quotes(av: "AlphaVantage", symbols: list[str]) -> dict[str, Any]:
    """Realtime quotes for up to ~100 symbols in ONE call (premium
    REALTIME_BULK_QUOTES) — the rate-limit-friendly way to feed a ticker tape.

    Returns {"quotes": [{ticker, price, change, change_pct}]} or {"error": ...}.
    """
    if not symbols:
        return {"quotes": []}
    data = av._get({"function": "REALTIME_BULK_QUOTES",
                    "symbol": ",".join(s.upper() for s in symbols[:100])})
    if "error" in data:
        return data
    rows = data.get("data")
    if not isinstance(rows, list):
        return {"error": "unexpected REALTIME_BULK_QUOTES payload"}
    quotes = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or "").upper()
        price = _to_float(r.get("close") or r.get("price"))
        if not sym or price <= 0:
            continue
        change = _to_float(r.get("change"))
        pct_raw = str(r.get("change_percent") or "").rstrip("%")
        pct = _to_float(pct_raw)
        prev = _to_float(r.get("previous_close"))
        if pct == 0.0 and prev > 0:
            pct = (price - prev) / prev * 100.0
        quotes.append({"ticker": sym, "price": round(price, 2),
                       "change": round(change, 2), "change_pct": round(pct, 2)})
    return {"quotes": quotes}
