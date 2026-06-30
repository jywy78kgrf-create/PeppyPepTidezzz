"""
Payoff / P&L helpers shared by the strategy library and the backtester.

Two layers:
  * pure-payoff math at expiry (intrinsic value of a leg / spec), and
  * mark-to-market valuation of a leg from a live chain (with a Black-Scholes
    fallback when the contract is not quoted on a given day).

A *leg value* here is the per-share option price for that single contract; the
caller (engine/portfolio) applies the 100x multiplier and the BUY/SELL sign.
"""
from __future__ import annotations

from datetime import date

from ..contracts import Action, Leg, OptionQuote, OptionType, StrategySpec
from . import greeks as g

CONTRACT_MULTIPLIER = 100


def intrinsic(kind: OptionType, strike: float, underlying: float) -> float:
    """Per-share intrinsic value of an option at a given underlying."""
    if kind == OptionType.CALL:
        return max(0.0, underlying - strike)
    return max(0.0, strike - underlying)


def leg_sign(action: Action) -> int:
    """+1 if the position is long (we own it), -1 if short."""
    return 1 if action == Action.BUY else -1


def leg_intrinsic_value(leg: Leg, underlying: float) -> float:
    """Signed per-share intrinsic value of a leg (long positive, short negative)."""
    return leg_sign(leg.action) * intrinsic(leg.kind, leg.strike, underlying) * leg.quantity


def spec_payoff_at_expiry(spec: StrategySpec, underlying: float) -> float:
    """Total payoff (per spread, x100) of all legs if expiry were `underlying`.

    Pure intrinsic value of the position; does not include the premium paid or
    received at open. Used to draw payoff diagrams and reason about max P&L.
    """
    total = 0.0
    for leg in spec.legs:
        total += leg_intrinsic_value(leg, underlying) * CONTRACT_MULTIPLIER
    return total


def find_quote(chain: list[OptionQuote], kind: OptionType, strike: float,
               expiry: date) -> OptionQuote | None:
    """Locate the quote matching a leg's (kind, strike, expiry), or None."""
    for q in chain:
        if q.kind == kind and abs(q.strike - strike) < 1e-6 and q.expiry == expiry:
            return q
    return None


def effective_iv(q: OptionQuote, r: float) -> float:
    """IV to use for a quote: stored iv, else inverted from the mid price."""
    if q.iv and q.iv > 0.0:
        return q.iv
    T = max(q.dte, 0) / 365.0
    price = q.mid if q.mid > 0 else q.last
    if price <= 0 or T <= 0 or q.underlying <= 0:
        return 0.0
    return g.implied_vol(price, q.underlying, q.strike, T, r, q.kind)


def quote_theo_price(q: OptionQuote, asof: date, underlying: float, r: float) -> float:
    """Black-Scholes theoretical per-share price for a quote on `asof`.

    Used as a fallback mark when a contract is not quoted on a later date.
    """
    T = max((q.expiry - asof).days, 0) / 365.0
    sigma = effective_iv(q, r)
    if T <= 0.0 or sigma <= 0.0:
        return intrinsic(q.kind, q.strike, underlying)
    return g.bs_price(underlying, q.strike, T, r, sigma, q.kind)


def mark_leg(leg: Leg, chain: list[OptionQuote], asof: date, underlying: float,
             r: float) -> float:
    """Signed per-share mark of a leg from a chain (long positive, short negative).

    Prefers the live quote mid; falls back to a Black-Scholes theo from a
    surviving same-strike quote, then to intrinsic value. This keeps a position
    markable even when a specific contract stops printing.
    """
    sign = leg_sign(leg.action)
    q = find_quote(chain, leg.kind, leg.strike, leg.expiry)
    if q is not None and q.mid > 0.0:
        price = q.mid
    elif q is not None:
        price = quote_theo_price(q, asof, underlying, r)
    else:
        # No exact contract; reprice via any same-kind quote's vol surface proxy.
        proxy = _nearest_same_kind(chain, leg.kind, leg.strike)
        if proxy is not None:
            sigma = effective_iv(proxy, r)
            T = max((leg.expiry - asof).days, 0) / 365.0
            price = (g.bs_price(underlying, leg.strike, T, r, sigma, leg.kind)
                     if T > 0 and sigma > 0 else intrinsic(leg.kind, leg.strike, underlying))
        else:
            price = intrinsic(leg.kind, leg.strike, underlying)
    return sign * price * leg.quantity


def _nearest_same_kind(chain: list[OptionQuote], kind: OptionType,
                       strike: float) -> OptionQuote | None:
    """Closest-strike quote of the same kind, for vol-surface fallback."""
    best: OptionQuote | None = None
    best_d = float("inf")
    for q in chain:
        if q.kind != kind:
            continue
        d = abs(q.strike - strike)
        if d < best_d:
            best_d, best = d, q
    return best


def spec_mark(spec: StrategySpec, chain: list[OptionQuote], asof: date,
              underlying: float, r: float) -> float:
    """Net signed mark (x100) of all legs of a spec from a chain."""
    total = 0.0
    for leg in spec.legs:
        total += mark_leg(leg, chain, asof, underlying, r) * CONTRACT_MULTIPLIER
    return total
