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

from typing import Any, Optional

import httpx
import pandas as pd

from ..config import SETTINGS

_BASE_URL = "https://www.alphavantage.co/query"


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

    # ------------------------------------------------------------------ #
    # Endpoints
    # ------------------------------------------------------------------ #
    def quote(self, symbol: str) -> dict[str, Any]:
        """Latest quote for ``symbol`` via GLOBAL_QUOTE."""
        data = self._get({"function": "GLOBAL_QUOTE", "symbol": symbol})
        if "error" in data:
            return data
        raw = data.get("Global Quote", {}) or {}
        if not raw:
            return {"error": f"no quote for {symbol}", "symbol": symbol}
        return {
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

    def realtime_options(self, symbol: str) -> list[dict[str, Any]]:
        """Realtime option chain via REALTIME_OPTIONS (premium endpoint)."""
        data = self._get(
            {"function": "REALTIME_OPTIONS", "symbol": symbol, "require_greeks": "true"}
        )
        if "error" in data:
            return [data]
        contracts = data.get("data") or data.get("options") or []
        if not isinstance(contracts, list):
            return [{"error": "unexpected options payload", "symbol": symbol}]
        return contracts

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
