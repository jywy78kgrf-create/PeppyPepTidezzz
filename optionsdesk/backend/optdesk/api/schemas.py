"""Pydantic request/response models for the FastAPI layer."""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #
class BacktestRequest(BaseModel):
    strategy: str
    params: dict[str, Any] = Field(default_factory=dict)
    tickers: list[str]
    start: date
    end: date
    capital: Optional[float] = None
    risk: Optional[dict[str, Any]] = None  # RiskConfig fields; None -> defaults


class SizeRequest(BaseModel):
    """Preview position sizing for a strategy on a given day."""
    strategy: str
    ticker: str
    date: Optional[date] = None
    equity: Optional[float] = None
    params: dict[str, Any] = Field(default_factory=dict)
    risk: Optional[dict[str, Any]] = None


class LearnRequest(BaseModel):
    strategy: str
    tickers: list[str]
    start: date
    end: date
    n_iter: int = 12
    objective: str = "sortino"
    seed: int = 7


class PaperOpenRequest(BaseModel):
    ticker: str
    date: date
    strategy: str
    qty: int = 1
    params: Optional[dict[str, Any]] = None


class PaperCloseRequest(BaseModel):
    idx: int


# --------------------------------------------------------------------------- #
# Responses (loose; most payloads are serialized dataclasses)
# --------------------------------------------------------------------------- #
class HealthResponse(BaseModel):
    status: str
    version: str
    data_ready: bool
    tickers: list[str]


class UniverseResponse(BaseModel):
    tickers: list[str]
    delisted: list[str]
    sectors: dict[str, str]


class SuggestionsResponse(BaseModel):
    asof: str
    ticker: str
    suggestions: list[dict[str, Any]]


class BrokersStatusResponse(BaseModel):
    ibkr: dict[str, Any]
    alpha_vantage: dict[str, Any]
