"""
Black-Scholes pricing and greeks.

Single source of truth for option valuation in the desk. The backtester and
strategies recompute any missing greek here from ``OptionQuote.iv`` when the
stored data has NaN/0, so every downstream consumer sees a consistent model.

All times are in years, rates/vols are decimals (0.045 = 4.5%). Greeks are
returned in the conventional market scaling:
  delta  -- per $1 of underlying
  gamma  -- per $1 of underlying (per unit delta)
  theta  -- per *calendar day* (annual theta / 365)
  vega   -- per 1 vol point (per 0.01 of sigma)
  rho    -- per 1 rate point (per 0.01 of r)
"""
from __future__ import annotations

import math

from ..contracts import OptionType

_SQRT2PI = math.sqrt(2.0 * math.pi)
_MIN_T = 1.0 / (365.0 * 24.0)  # ~1 hour floor to avoid div-by-zero


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via erf (no scipy dependency on the hot path)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / _SQRT2PI


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float) -> tuple[float, float]:
    """Black-Scholes d1/d2 helper."""
    vol_t = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / vol_t
    d2 = d1 - vol_t
    return d1, d2


def _is_call(kind: OptionType) -> bool:
    return kind == OptionType.CALL


def bs_price(S: float, K: float, T: float, r: float, sigma: float, kind: OptionType) -> float:
    """Black-Scholes price of a European option.

    Degenerate inputs (non-positive time/vol/price) collapse to discounted
    intrinsic value so callers never receive NaN.
    """
    call = _is_call(kind)
    if S <= 0.0 or K <= 0.0:
        return 0.0
    if T <= _MIN_T or sigma <= 0.0:
        intrinsic = max(0.0, (S - K)) if call else max(0.0, (K - S))
        return intrinsic
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    disc = math.exp(-r * T)
    if call:
        return S * _norm_cdf(d1) - K * disc * _norm_cdf(d2)
    return K * disc * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def greeks(S: float, K: float, T: float, r: float, sigma: float, kind: OptionType) -> dict:
    """Full first/second-order greeks for one option.

    Returns keys ``delta, gamma, theta, vega, rho`` in market scaling. Degenerate
    inputs return zeros (with delta pinned to the intrinsic boundary) so the
    backtester can always mark a position.
    """
    call = _is_call(kind)
    if S <= 0.0 or K <= 0.0 or T <= _MIN_T or sigma <= 0.0:
        if call:
            delta = 1.0 if S > K else 0.0
        else:
            delta = -1.0 if S < K else 0.0
        return {"delta": delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

    d1, d2 = _d1_d2(S, K, T, r, sigma)
    sqrt_t = math.sqrt(T)
    disc = math.exp(-r * T)
    pdf = _norm_pdf(d1)

    gamma = pdf / (S * sigma * sqrt_t)
    vega = S * pdf * sqrt_t / 100.0  # per 1 vol point
    if call:
        delta = _norm_cdf(d1)
        theta_annual = -S * pdf * sigma / (2.0 * sqrt_t) - r * K * disc * _norm_cdf(d2)
        rho = K * T * disc * _norm_cdf(d2) / 100.0
    else:
        delta = _norm_cdf(d1) - 1.0
        theta_annual = -S * pdf * sigma / (2.0 * sqrt_t) + r * K * disc * _norm_cdf(-d2)
        rho = -K * T * disc * _norm_cdf(-d2) / 100.0
    theta = theta_annual / 365.0  # per calendar day
    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega, "rho": rho}


def implied_vol(price: float, S: float, K: float, T: float, r: float,
                kind: OptionType, *, tol: float = 1e-6, max_iter: int = 100) -> float:
    """Invert Black-Scholes for implied volatility.

    Newton-Raphson seeded by the Brenner-Subrahmanyam ATM approximation, with a
    bisection fallback for robustness. Returns 0.0 if the price is below
    intrinsic or inputs are degenerate.
    """
    call = _is_call(kind)
    if price <= 0.0 or S <= 0.0 or K <= 0.0 or T <= _MIN_T:
        return 0.0
    disc = math.exp(-r * T)
    intrinsic = max(0.0, S - K * disc) if call else max(0.0, K * disc - S)
    if price <= intrinsic + 1e-12:
        return 0.0

    # Brenner-Subrahmanyam seed.
    sigma = max(1e-3, math.sqrt(2.0 * math.pi / T) * price / S)
    for _ in range(max_iter):
        model = bs_price(S, K, T, r, sigma, kind)
        diff = model - price
        if abs(diff) < tol:
            return sigma
        d1, _ = _d1_d2(S, K, T, r, sigma)
        vega_raw = S * _norm_pdf(d1) * math.sqrt(T)  # raw d(price)/d(sigma)
        if vega_raw < 1e-10:
            break
        sigma -= diff / vega_raw
        if sigma <= 1e-6 or sigma > 10.0:
            break

    # Bisection fallback on a wide bracket.
    lo, hi = 1e-4, 10.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        model = bs_price(S, K, T, r, mid, kind)
        if abs(model - price) < tol:
            return mid
        if model > price:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)
