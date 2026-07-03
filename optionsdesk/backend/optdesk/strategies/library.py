"""
Strategy library — concrete leg builders over a real option chain.

Each builder takes a chain snapshot, the underlying price, and a params dict and
returns a fully-populated :class:`StrategySpec` (with max_loss/max_profit/pop/
expected_edge/rationale/tags) or ``None`` when the chain cannot support the
structure (e.g. no strike near the target delta).

Strike selection is delta-driven and expiry selection is DTE-driven so the same
builder adapts to any underlying. Probability-of-profit uses an N(d2)-style
estimate from Black-Scholes; expected edge compares the credit/debit actually
collectable (crossing the spread) against the model-fair value of the structure.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date

from ..config import SETTINGS
from ..contracts import (
    Action,
    Leg,
    OptionQuote,
    OptionType,
    StrategySpec,
)
from ..quant import greeks as g
from ..quant.pricing import CONTRACT_MULTIPLIER, effective_iv

Builder = Callable[[list[OptionQuote], float, dict], "StrategySpec | None"]

# --------------------------------------------------------------------------- #
# Default tuning knobs (overridable per call via params).
# --------------------------------------------------------------------------- #
DEFAULTS: dict = {
    "target_dte": 35,        # preferred days-to-expiry for the near leg
    "calendar_back_dte": 65,  # back-month for calendars
    "short_delta": 0.30,     # |delta| of the short option in credit spreads
    "wing_delta": 0.16,      # |delta| of the protective/long wing
    "long_delta": 0.50,      # |delta| for directional long options
    "min_open_interest": 10,
    "r": SETTINGS.risk_free_apr,
}


# --------------------------------------------------------------------------- #
# Chain selection helpers
# --------------------------------------------------------------------------- #
def _params(p: dict | None) -> dict:
    """Merge user params over library defaults (non-mutating)."""
    merged = dict(DEFAULTS)
    if p:
        merged.update(p)
    return merged


def _expiries(chain: list[OptionQuote]) -> list[date]:
    """Sorted unique expiries present in the chain."""
    return sorted({q.expiry for q in chain})


def _nearest_expiry(chain: list[OptionQuote], target_dte: int) -> date | None:
    """Expiry whose DTE is closest to ``target_dte`` (prefer >= a few days out)."""
    exps = _expiries(chain)
    if not exps:
        return None
    asof = chain[0].asof
    viable = [(e, (e - asof).days) for e in exps if (e - asof).days >= 1]
    if not viable:
        return None
    return min(viable, key=lambda ed: abs(ed[1] - target_dte))[0]


def _legs_for(chain: list[OptionQuote], kind: OptionType, expiry: date) -> list[OptionQuote]:
    """Quotes of one kind for one expiry, sorted by strike."""
    return sorted((q for q in chain if q.kind == kind and q.expiry == expiry),
                  key=lambda q: q.strike)


def _delta_of(q: OptionQuote, r: float) -> float:
    """Quote delta, recomputed from IV when the stored greek is absent."""
    if q.delta and abs(q.delta) > 1e-9:
        return q.delta
    T = max(q.dte, 0) / 365.0
    sigma = effective_iv(q, r)
    if T <= 0 or sigma <= 0 or q.underlying <= 0:
        return 0.0
    return g.greeks(q.underlying, q.strike, T, r, sigma, q.kind)["delta"]


def _pick_by_delta(quotes: list[OptionQuote], target_abs_delta: float,
                   r: float) -> OptionQuote | None:
    """Quote whose |delta| is closest to a target."""
    best, best_d = None, float("inf")
    for q in quotes:
        d = abs(abs(_delta_of(q, r)) - target_abs_delta)
        if d < best_d:
            best_d, best = d, q
    return best


def _atm(quotes: list[OptionQuote], underlying: float) -> OptionQuote | None:
    """Closest-to-the-money quote."""
    if not quotes:
        return None
    return min(quotes, key=lambda q: abs(q.strike - underlying))


def _liquid(q: OptionQuote, min_oi: int) -> bool:
    """Crude liquidity gate: some OI and a two-sided market."""
    return q.open_interest >= min_oi and q.ask > 0.0


def _pop_from_d2(underlying: float, strike: float, T: float, r: float,
                 sigma: float, profit_if_above: bool) -> float:
    """Risk-neutral P(profit) proxy = N(±d2) for finishing the right side of K."""
    if T <= 0 or sigma <= 0 or underlying <= 0:
        return 0.5
    d2 = (math.log(underlying / strike) + (r - 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    n = 0.5 * (1.0 + math.erf(d2 / math.sqrt(2.0)))
    return n if profit_if_above else (1.0 - n)


# --------------------------------------------------------------------------- #
# Credit / debit accounting at construction
# --------------------------------------------------------------------------- #
def _net_premium(legs: list[Leg], chain: list[OptionQuote]) -> float:
    """Signed net premium per spread (x100). Positive = net credit received.

    Uses mid prices: SELL collects mid, BUY pays mid.
    """
    from ..quant.pricing import find_quote

    total = 0.0
    for leg in legs:
        q = find_quote(chain, leg.kind, leg.strike, leg.expiry)
        if q is None:
            continue
        px = q.mid if q.mid > 0 else q.last
        sign = -1.0 if leg.action == Action.BUY else 1.0  # credit positive
        total += sign * px * leg.quantity * CONTRACT_MULTIPLIER
    return total


def _theo_net(legs: list[Leg], chain: list[OptionQuote], underlying: float,
              r: float) -> float:
    """Model-fair net credit (x100) using Black-Scholes mids — for edge calc."""
    from ..quant.pricing import find_quote

    total = 0.0
    for leg in legs:
        q = find_quote(chain, leg.kind, leg.strike, leg.expiry)
        if q is None:
            continue
        T = max((leg.expiry - chain[0].asof).days, 0) / 365.0
        sigma = effective_iv(q, r)
        theo = g.bs_price(underlying, leg.strike, T, r, sigma, leg.kind) if (T > 0 and sigma > 0) \
            else max(0.0, (underlying - leg.strike) if leg.kind == OptionType.CALL
                     else (leg.strike - underlying))
        sign = -1.0 if leg.action == Action.BUY else 1.0
        total += sign * theo * leg.quantity * CONTRACT_MULTIPLIER
    return total


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def bull_put_spread(chain: list[OptionQuote], underlying: float,
                    params: dict) -> StrategySpec | None:
    """Sell a ~0.30-delta put, buy a lower put (same near-month) for a net credit.

    Bullish/neutral; profits if the underlying stays above the short strike.
    """
    p = _params(params)
    exp = _nearest_expiry(chain, p["target_dte"])
    if exp is None:
        return None
    puts = [q for q in _legs_for(chain, OptionType.PUT, exp) if _liquid(q, p["min_open_interest"])]
    short = _pick_by_delta(puts, p["short_delta"], p["r"])
    if short is None:
        return None
    lower = [q for q in puts if q.strike < short.strike]
    long_ = _pick_by_delta(lower, p["wing_delta"], p["r"]) or (lower[-1] if lower else None)
    if long_ is None or long_.strike >= short.strike:
        return None
    legs = [
        Leg(Action.SELL, OptionType.PUT, short.strike, exp),
        Leg(Action.BUY, OptionType.PUT, long_.strike, exp),
    ]
    width = (short.strike - long_.strike) * CONTRACT_MULTIPLIER
    credit = _net_premium(legs, chain)
    max_profit = max(0.0, credit)
    max_loss = max(0.0, width - max_profit)
    T = max((exp - chain[0].asof).days, 0) / 365.0
    sigma = effective_iv(short, p["r"])
    pop = _pop_from_d2(underlying, short.strike, T, p["r"], sigma, profit_if_above=True)
    return _finalize("bull_put_spread", chain, legs, credit, max_profit, max_loss, pop,
                     underlying, p,
                     rationale=(f"Sell {short.strike:.1f}P / buy {long_.strike:.1f}P @ {exp} "
                                f"for {credit/100:.2f} credit; bullish, defined risk."),
                     tags=["bullish", "credit", "defined-risk", "theta"])


def bear_call_spread(chain: list[OptionQuote], underlying: float,
                     params: dict) -> StrategySpec | None:
    """Sell a ~0.30-delta call, buy a higher call for a net credit (bearish/neutral)."""
    p = _params(params)
    exp = _nearest_expiry(chain, p["target_dte"])
    if exp is None:
        return None
    calls = [q for q in _legs_for(chain, OptionType.CALL, exp) if _liquid(q, p["min_open_interest"])]
    short = _pick_by_delta(calls, p["short_delta"], p["r"])
    if short is None:
        return None
    higher = [q for q in calls if q.strike > short.strike]
    long_ = _pick_by_delta(higher, p["wing_delta"], p["r"]) or (higher[-1] if higher else None)
    if long_ is None or long_.strike <= short.strike:
        return None
    legs = [
        Leg(Action.SELL, OptionType.CALL, short.strike, exp),
        Leg(Action.BUY, OptionType.CALL, long_.strike, exp),
    ]
    width = (long_.strike - short.strike) * CONTRACT_MULTIPLIER
    credit = _net_premium(legs, chain)
    max_profit = max(0.0, credit)
    max_loss = max(0.0, width - max_profit)
    T = max((exp - chain[0].asof).days, 0) / 365.0
    sigma = effective_iv(short, p["r"])
    pop = _pop_from_d2(underlying, short.strike, T, p["r"], sigma, profit_if_above=False)
    return _finalize("bear_call_spread", chain, legs, credit, max_profit, max_loss, pop,
                     underlying, p,
                     rationale=(f"Sell {short.strike:.1f}C / buy {long_.strike:.1f}C @ {exp} "
                                f"for {credit/100:.2f} credit; bearish, defined risk."),
                     tags=["bearish", "credit", "defined-risk", "theta"])


def iron_condor(chain: list[OptionQuote], underlying: float,
                params: dict) -> StrategySpec | None:
    """Combine a bull put spread and a bear call spread — neutral, range-bound."""
    p = _params(params)
    put_side = bull_put_spread(chain, underlying, params)
    call_side = bear_call_spread(chain, underlying, params)
    if put_side is None or call_side is None:
        return None
    legs = put_side.legs + call_side.legs
    credit = _net_premium(legs, chain)
    short_put = max(l.strike for l in put_side.legs)
    long_put = min(l.strike for l in put_side.legs)
    short_call = min(l.strike for l in call_side.legs)
    long_call = max(l.strike for l in call_side.legs)
    put_width = (short_put - long_put) * CONTRACT_MULTIPLIER
    call_width = (long_call - short_call) * CONTRACT_MULTIPLIER
    max_profit = max(0.0, credit)
    max_loss = max(0.0, max(put_width, call_width) - max_profit)
    # POP ~ stay between the short strikes.
    pop = max(0.0, put_side.pop + call_side.pop - 1.0)
    return _finalize("iron_condor", chain, legs, credit, max_profit, max_loss, pop,
                     underlying, p,
                     rationale=(f"Iron condor {long_put:.0f}/{short_put:.0f}P - "
                                f"{short_call:.0f}/{long_call:.0f}C; neutral, range-bound."),
                     tags=["neutral", "credit", "defined-risk", "theta", "range"])


def long_call(chain: list[OptionQuote], underlying: float,
              params: dict) -> StrategySpec | None:
    """Buy a ~0.50-delta call — bullish, defined risk, positive gamma/vega."""
    p = _params(params)
    exp = _nearest_expiry(chain, p["target_dte"])
    if exp is None:
        return None
    calls = [q for q in _legs_for(chain, OptionType.CALL, exp) if _liquid(q, p["min_open_interest"])]
    pick = _pick_by_delta(calls, p["long_delta"], p["r"]) or _atm(calls, underlying)
    if pick is None:
        return None
    legs = [Leg(Action.BUY, OptionType.CALL, pick.strike, exp)]
    debit = _net_premium(legs, chain)  # negative (we pay)
    max_loss = abs(debit)
    max_profit = float("inf")
    T = max((exp - chain[0].asof).days, 0) / 365.0
    sigma = effective_iv(pick, p["r"])
    be = pick.strike + max_loss / CONTRACT_MULTIPLIER
    pop = _pop_from_d2(underlying, be, T, p["r"], sigma, profit_if_above=True)
    return _finalize("long_call", chain, legs, debit, max_profit, max_loss, pop,
                     underlying, p,
                     rationale=f"Buy {pick.strike:.1f}C @ {exp} for {max_loss/100:.2f} debit; bullish.",
                     tags=["bullish", "debit", "long-vol", "convex"])


def long_put(chain: list[OptionQuote], underlying: float,
             params: dict) -> StrategySpec | None:
    """Buy a ~0.50-delta put — bearish, defined risk, positive gamma/vega."""
    p = _params(params)
    exp = _nearest_expiry(chain, p["target_dte"])
    if exp is None:
        return None
    puts = [q for q in _legs_for(chain, OptionType.PUT, exp) if _liquid(q, p["min_open_interest"])]
    pick = _pick_by_delta(puts, p["long_delta"], p["r"]) or _atm(puts, underlying)
    if pick is None:
        return None
    legs = [Leg(Action.BUY, OptionType.PUT, pick.strike, exp)]
    debit = _net_premium(legs, chain)
    max_loss = abs(debit)
    max_profit = max(0.0, pick.strike * CONTRACT_MULTIPLIER - max_loss)
    T = max((exp - chain[0].asof).days, 0) / 365.0
    sigma = effective_iv(pick, p["r"])
    be = pick.strike - max_loss / CONTRACT_MULTIPLIER
    pop = _pop_from_d2(underlying, be, T, p["r"], sigma, profit_if_above=False)
    return _finalize("long_put", chain, legs, debit, max_profit, max_loss, pop,
                     underlying, p,
                     rationale=f"Buy {pick.strike:.1f}P @ {exp} for {max_loss/100:.2f} debit; bearish.",
                     tags=["bearish", "debit", "long-vol", "convex"])


def covered_call(chain: list[OptionQuote], underlying: float,
                 params: dict) -> StrategySpec | None:
    """Sell an OTM (~0.30-delta) call against long stock.

    Modelled here as the short-call overlay (the 100 shares of underlying are
    accounted separately by the broker/portfolio); risk is capped to the long
    stock side so we report the option-overlay economics.
    """
    p = _params(params)
    exp = _nearest_expiry(chain, p["target_dte"])
    if exp is None:
        return None
    calls = [q for q in _legs_for(chain, OptionType.CALL, exp) if _liquid(q, p["min_open_interest"])]
    short = _pick_by_delta(calls, p["short_delta"], p["r"])
    if short is None:
        return None
    legs = [Leg(Action.SELL, OptionType.CALL, short.strike, exp)]
    credit = _net_premium(legs, chain)
    max_profit = max(0.0, credit + (short.strike - underlying) * CONTRACT_MULTIPLIER)
    max_loss = max(0.0, underlying * CONTRACT_MULTIPLIER - credit)  # stock to zero
    T = max((exp - chain[0].asof).days, 0) / 365.0
    sigma = effective_iv(short, p["r"])
    pop = _pop_from_d2(underlying, short.strike - credit / CONTRACT_MULTIPLIER, T, p["r"],
                       sigma, profit_if_above=True)
    spec = _finalize("covered_call", chain, legs, credit, max_profit, max_loss, pop,
                     underlying, p,
                     rationale=(f"Sell {short.strike:.1f}C @ {exp} vs 100 shares for "
                                f"{credit/100:.2f} credit; income on a long-stock holding."),
                     tags=["neutral", "income", "covered", "theta"])
    # stock-to-zero is the honest max loss but useless as a sizing basis —
    # every sizer starves it to 0 contracts. The desk simulates the overlay
    # (short call) only, so size on a 2-sigma adverse rally net of the
    # strike's OTM cushion. Farther-OTM strikes -> smaller basis; the
    # optimizer can trade that off against premium.
    move2 = 2.0 * underlying * sigma * math.sqrt(max(T, 1e-6))
    cushion = max(short.strike - underlying, 0.0)
    spec.meta["risk_basis"] = round(
        max((move2 - cushion) * CONTRACT_MULTIPLIER - credit, 50.0), 2)
    return spec


def calendar_call(chain: list[OptionQuote], underlying: float,
                  params: dict) -> StrategySpec | None:
    """Sell a near-month ATM call, buy a same-strike back-month call (long vega/theta)."""
    p = _params(params)
    near = _nearest_expiry(chain, p["target_dte"])
    back = _nearest_expiry(chain, p["calendar_back_dte"])
    if near is None or back is None or back <= near:
        # widen the back month until it's strictly later
        later = [e for e in _expiries(chain) if near is not None and e > near]
        back = later[len(later) // 2] if later else None
    if near is None or back is None or back <= near:
        return None
    near_calls = _legs_for(chain, OptionType.CALL, near)
    atm = _atm([q for q in near_calls if _liquid(q, p["min_open_interest"])], underlying)
    if atm is None:
        return None
    strike = atm.strike
    legs = [
        Leg(Action.SELL, OptionType.CALL, strike, near),
        Leg(Action.BUY, OptionType.CALL, strike, back),
    ]
    net = _net_premium(legs, chain)  # net debit -> negative
    debit = abs(min(0.0, net))
    max_loss = debit if debit > 0 else abs(net)
    max_profit = debit  # heuristic: near-leg premium decays into the long back leg
    pop = 0.55  # calendars profit in a band around the strike; conservative proxy
    return _finalize("calendar_call", chain, legs, net, max_profit, max_loss, pop,
                     underlying, p,
                     rationale=(f"Calendar at {strike:.1f}C: sell {near} / buy {back} for "
                                f"{abs(net)/100:.2f} debit; long vega, theta harvest."),
                     tags=["neutral", "debit", "long-vega", "calendar"])


def short_straddle(chain: list[OptionQuote], underlying: float,
                   params: dict) -> StrategySpec | None:
    """Sell an ATM call and ATM put — short vol, large credit, undefined risk."""
    p = _params(params)
    exp = _nearest_expiry(chain, p["target_dte"])
    if exp is None:
        return None
    calls = [q for q in _legs_for(chain, OptionType.CALL, exp) if _liquid(q, p["min_open_interest"])]
    puts = [q for q in _legs_for(chain, OptionType.PUT, exp) if _liquid(q, p["min_open_interest"])]
    c = _atm(calls, underlying)
    pu = _atm(puts, underlying)
    if c is None or pu is None:
        return None
    legs = [
        Leg(Action.SELL, OptionType.CALL, c.strike, exp),
        Leg(Action.SELL, OptionType.PUT, pu.strike, exp),
    ]
    credit = _net_premium(legs, chain)
    max_profit = max(0.0, credit)
    # Undefined risk: max_loss is honestly unbounded (displayed as such);
    # sizing uses a 2-sigma adverse move via meta["risk_basis"] below.
    T = max((exp - chain[0].asof).days, 0) / 365.0
    sigma = effective_iv(c, p["r"])
    move = underlying * sigma * math.sqrt(max(T, 1e-6))
    max_loss = float("inf")
    risk_basis = round(max(2.0 * move * CONTRACT_MULTIPLIER - max_profit, 50.0), 2)
    # P(profit) = P(finish inside the breakeven band) = P(below upper BE) +
    # P(above lower BE) - 1 (same inclusion-exclusion as the iron condor).
    pop = max(0.0,
              _pop_from_d2(underlying, c.strike + credit / CONTRACT_MULTIPLIER, T, p["r"],
                           sigma, profit_if_above=False) +
              _pop_from_d2(underlying, pu.strike - credit / CONTRACT_MULTIPLIER, T, p["r"],
                           sigma, profit_if_above=True) - 1.0)
    spec = _finalize("short_straddle", chain, legs, credit, max_profit, max_loss, pop,
                     underlying, p,
                     rationale=(f"Sell {c.strike:.1f} straddle @ {exp} for {credit/100:.2f} "
                                f"credit; short vol, undefined risk."),
                     tags=["neutral", "credit", "short-vol", "undefined-risk", "theta"])
    spec.meta["risk_basis"] = risk_basis
    return spec


def long_strangle(chain: list[OptionQuote], underlying: float,
                  params: dict) -> StrategySpec | None:
    """Buy an OTM call and OTM put — long vol, profits on a large move either way."""
    p = _params(params)
    exp = _nearest_expiry(chain, p["target_dte"])
    if exp is None:
        return None
    calls = [q for q in _legs_for(chain, OptionType.CALL, exp) if _liquid(q, p["min_open_interest"])]
    puts = [q for q in _legs_for(chain, OptionType.PUT, exp) if _liquid(q, p["min_open_interest"])]
    c = _pick_by_delta([q for q in calls if q.strike > underlying], p["short_delta"], p["r"])
    pu = _pick_by_delta([q for q in puts if q.strike < underlying], p["short_delta"], p["r"])
    if c is None or pu is None:
        return None
    legs = [
        Leg(Action.BUY, OptionType.CALL, c.strike, exp),
        Leg(Action.BUY, OptionType.PUT, pu.strike, exp),
    ]
    debit = _net_premium(legs, chain)  # negative
    max_loss = abs(debit)
    max_profit = float("inf")
    T = max((exp - chain[0].asof).days, 0) / 365.0
    sigma = effective_iv(c, p["r"])
    up_be = c.strike + max_loss / CONTRACT_MULTIPLIER
    dn_be = pu.strike - max_loss / CONTRACT_MULTIPLIER
    pop = (_pop_from_d2(underlying, up_be, T, p["r"], sigma, profit_if_above=True) +
           _pop_from_d2(underlying, dn_be, T, p["r"], sigma, profit_if_above=False))
    pop = min(1.0, pop)
    return _finalize("long_strangle", chain, legs, debit, max_profit, max_loss, pop,
                     underlying, p,
                     rationale=(f"Buy {pu.strike:.1f}P + {c.strike:.1f}C @ {exp} for "
                                f"{max_loss/100:.2f} debit; long vol, breakout."),
                     tags=["neutral", "debit", "long-vol", "convex", "breakout"])


# --------------------------------------------------------------------------- #
# Finalizer — common scoring fields
# --------------------------------------------------------------------------- #
def _finalize(name: str, chain: list[OptionQuote], legs: list[Leg], net_premium: float,
              max_profit: float, max_loss: float, pop: float, underlying: float,
              p: dict, *, rationale: str, tags: list[str]) -> StrategySpec:
    """Attach max P&L, POP, and a model edge to a spec.

    expected_edge = collectable premium (mid) minus model-fair value, expressed
    as the dollar mispricing the desk captures by putting the trade on. For a
    credit structure a positive edge means we collect more than fair; for a debit
    structure it means we pay less than fair.
    """
    asof = chain[0].asof
    theo = _theo_net(legs, chain, underlying, p["r"])
    edge = net_premium - theo  # credit collected beyond fair (signed)
    pop = float(min(1.0, max(0.0, pop)))
    spec = StrategySpec(
        name=name,
        ticker=chain[0].ticker,
        asof=asof,
        legs=legs,
        rationale=rationale,
        tags=list(tags),
        expected_edge=round(float(edge), 4),
        max_loss=round(float(max_loss), 4),
        max_profit=(float("inf") if max_profit == float("inf") else round(float(max_profit), 4)),
        pop=round(pop, 4),
    )
    spec.meta["net_premium"] = round(float(net_premium), 4)
    spec.meta["underlying"] = round(float(underlying), 4)
    spec.meta["theo_net"] = round(float(theo), 4)
    return spec


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
STRATEGIES: dict[str, Builder] = {
    "bull_put_spread": bull_put_spread,
    "bear_call_spread": bear_call_spread,
    "iron_condor": iron_condor,
    "long_call": long_call,
    "long_put": long_put,
    "covered_call": covered_call,
    "calendar_call": calendar_call,
    "short_straddle": short_straddle,
    "long_strangle": long_strangle,
}
