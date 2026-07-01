"""
Position and cash accounting for the event-driven backtester.

The portfolio owns cash, a set of open :class:`OpenPosition` objects, and the
list of completed :class:`Trade` round-trips. It mirrors broker mechanics:
crossing the bid/ask spread on entry/exit, per-leg/per-side commissions and
exchange fees, and daily cost-of-carry on the capital tied up (net debit paid or
margin posted for credit structures).

The engine drives this object day by day; all fill pricing and cost modelling
lives here so paper trading can reuse the same math.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from ..contracts import (
    Action,
    CostModel,
    Fill,
    Leg,
    OptionQuote,
    OptionType,
    StrategySpec,
    Trade,
)
from ..quant.pricing import (
    CONTRACT_MULTIPLIER,
    find_quote,
    intrinsic,
    mark_leg,
    quote_theo_price,
)


# --------------------------------------------------------------------------- #
# Reg-T-style margin
# --------------------------------------------------------------------------- #
def margin_requirement(legs: list[Leg], underlying: float,
                       fills: list[Fill]) -> float:
    """Reg-T-style initial margin (dollars) for a set of option legs at open.

    Semantics (computed once at open; no daily re-mark):

    * Each SHORT leg paired with a same-kind LONG leg (expiry >= short's,
      quantity available) is *defined-risk*: the pair requires
      ``width - net credit`` (floored at 0) — i.e. the spread's max loss, so
      defined-risk structures keep their width-minus-credit requirement.
      Pairing greedily prefers the long leg that minimises the width.
    * Each remaining (naked) short leg requires, per share,
      ``premium + max(0.20 * U - OTM_amount, 0.10 * U for calls / 0.10 * K
      for puts)``, times 100 x quantity.
    * Long legs not used as offsets require nothing (their debit is cash paid).

    ``fills`` supply the actual per-share premiums (matched to legs by
    action/kind/strike/expiry; unmatched legs count a premium of 0).
    """
    u = max(0.0, float(underlying or 0.0))
    prem: dict[tuple, float] = {}
    for f in fills:
        prem[(f.action, f.kind, f.strike, f.expiry)] = f.price

    def _prem(leg: Leg) -> float:
        return prem.get((leg.action, leg.kind, leg.strike, leg.expiry), 0.0)

    shorts = [[leg, leg.quantity] for leg in legs if leg.action == Action.SELL]
    longs = [[leg, leg.quantity] for leg in legs if leg.action == Action.BUY]

    total = 0.0
    for srec in shorts:
        s, s_qty = srec[0], srec[1]

        def _width(l: Leg) -> float:
            if s.kind == OptionType.CALL:
                return max(0.0, l.strike - s.strike)
            return max(0.0, s.strike - l.strike)

        # Pair against long legs of the same kind that define the risk,
        # tightest (smallest-width) offset first.
        candidates = sorted(
            (lrec for lrec in longs
             if lrec[0].kind == s.kind and lrec[1] > 0 and lrec[0].expiry >= s.expiry),
            key=lambda lrec: _width(lrec[0]))
        for lrec in candidates:
            if s_qty <= 0:
                break
            l, l_qty = lrec[0], lrec[1]
            take = min(s_qty, l_qty)
            width = _width(l)
            pair_credit = max(0.0, _prem(s) - _prem(l))
            total += max(0.0, (width - pair_credit)) * CONTRACT_MULTIPLIER * take
            s_qty -= take
            lrec[1] -= take

        if s_qty > 0:  # naked remainder: full Reg-T formula
            if s.kind == OptionType.CALL:
                otm = max(0.0, s.strike - u)
                base = max(0.20 * u - otm, 0.10 * u)
            else:
                otm = max(0.0, u - s.strike)
                base = max(0.20 * u - otm, 0.10 * s.strike)
            total += (_prem(s) + base) * CONTRACT_MULTIPLIER * s_qty
        srec[1] = s_qty

    return round(max(0.0, total), 4)


@dataclass(slots=True)
class OpenPosition:
    """A live spread being managed by the backtester."""
    spec: StrategySpec
    opened: date
    open_fills: list[Fill]
    entry_cash: float        # signed cash flow at open (credit +, debit -), net of costs
    capital_at_risk: float   # debit paid or margin held (>=0), basis for carry & exits
    target_value: float      # net mark that triggers a profit-target close
    stop_value: float        # net mark that triggers a stop-loss close
    holding_cost: float = 0.0
    last_marked: date | None = None

    @property
    def legs(self) -> list[Leg]:
        return self.spec.legs


class Portfolio:
    """Cash + open positions + closed trades, with broker-accurate fills."""

    def __init__(self, starting_cash: float, cost_model: CostModel,
                 r: float, max_concurrent: int = 5):
        """Initialise an empty book.

        Args:
            starting_cash: opening equity.
            cost_model: commissions/fees/slippage/financing parameters.
            r: risk-free rate for theo fallbacks (and carry uses financing_apr).
            max_concurrent: cap on simultaneously open positions.
        """
        self.cash = float(starting_cash)
        self.cost = cost_model
        self.r = r
        self.max_concurrent = max_concurrent
        self.open_positions: list[OpenPosition] = []
        self.trades: list[Trade] = []
        self._exposure_days = 0
        self._total_days = 0

    # ------------------------------------------------------------------ #
    # Fill pricing
    # ------------------------------------------------------------------ #
    def _fill_price(self, q: OptionQuote, action: Action) -> tuple[float, float]:
        """Executable price for a leg and the per-share slippage paid.

        Buys lift toward the ask, sells hit toward the bid, by a width-aware
        fraction of the quoted spread (quant.pricing.slippage_fraction: wide
        markets pay closer to the far touch), floored at ``min_slippage``.
        Falls back to last when a side is missing.
        """
        from ..quant.pricing import slippage_fraction

        mid = q.mid if q.mid > 0 else q.last
        spread = q.spread
        slip = max(self.cost.min_slippage, slippage_fraction(mid, spread, self.cost) * spread)
        if action == Action.BUY:
            price = mid + slip
            if q.ask > 0:
                price = min(price, q.ask) if q.ask >= mid else price
        else:
            price = max(0.01, mid - slip)
            if q.bid > 0:
                price = max(price, q.bid) if q.bid <= mid else price
        return round(price, 4), round(slip, 4)

    def _leg_costs(self, qty: int) -> float:
        """Commission + exchange fee for one leg, one side."""
        per = self.cost.commission_per_contract + self.cost.exchange_fee_per_contract
        return per * max(1, qty)

    # ------------------------------------------------------------------ #
    # Open
    # ------------------------------------------------------------------ #
    def can_open(self) -> bool:
        """True if below the concurrency cap."""
        return len(self.open_positions) < self.max_concurrent

    def open(self, spec: StrategySpec, chain: list[OptionQuote], asof: date,
             profit_target: float, stop_mult: float) -> OpenPosition | None:
        """Open a spec at executable prices; book cash and costs.

        Returns the :class:`OpenPosition`, or None if any leg is unquotable.
        ``profit_target`` is the fraction of the entry credit/debit to capture;
        ``stop_mult`` is the multiple of capital-at-risk that triggers a stop.
        """
        fills: list[Fill] = []
        signed_cash = 0.0  # + received, - paid (premium only)
        total_costs = 0.0
        for leg in spec.legs:
            q = find_quote(chain, leg.kind, leg.strike, leg.expiry)
            if q is None or (q.mid <= 0 and q.last <= 0):
                return None
            price, slip = self._fill_price(q, leg.action)
            commission = self._leg_costs(leg.quantity)
            sign = -1.0 if leg.action == Action.BUY else 1.0
            notional = price * leg.quantity * CONTRACT_MULTIPLIER
            signed_cash += sign * notional
            total_costs += commission + slip * leg.quantity * CONTRACT_MULTIPLIER
            fills.append(Fill(asof, leg.action, leg.kind, leg.strike, leg.expiry,
                              leg.quantity, price, commission, slip))

        # Capital at risk: debit paid, or — for credit structures —
        # max(modelled max_loss, Reg-T-style margin at open). Defined-risk
        # spreads keep width-credit; naked shorts get the Reg-T formula.
        if signed_cash < 0:
            capital_at_risk = abs(signed_cash)
        else:
            u = next((qq.underlying for qq in chain if qq.underlying > 0),
                     spec.meta.get("underlying", 0.0)) or 0.0
            reg_t = margin_requirement(spec.legs, u, fills)
            ml = spec.max_loss if math.isfinite(spec.max_loss) else 0.0
            capital_at_risk = max(ml, reg_t)

        entry_cash = signed_cash - total_costs
        self.cash += entry_cash

        # Managed-exit thresholds on the *net mark to close* (signed mark of legs).
        # Net liquidation mark at open == -signed_cash convention: a credit (+cash)
        # is a liability to buy back (negative mark); a debit is an asset.
        entry_mark = self._net_mark(spec, chain, asof)
        if signed_cash > 0:  # credit: profit as the buyback value shrinks toward 0
            # entry_mark < 0; target sits between entry_mark and 0 and the
            # engine triggers on value RISING through it (value >= target).
            target_value = entry_mark * (1.0 - profit_target)
            stop_value = entry_mark - stop_mult * capital_at_risk
        else:  # debit: profit as the asset value rises
            target_value = entry_mark + profit_target * capital_at_risk
            # Stop after losing stop_mult x capital-at-risk. A debit structure's
            # mark cannot go below 0, so clamp: for stop_mult >= 1 the stop can
            # only fire at total loss (value == 0); expiry/close_dte handle the rest.
            if entry_mark > 0:
                stop_value = max(entry_mark - stop_mult * capital_at_risk, 0.0)
            else:
                stop_value = -capital_at_risk

        pos = OpenPosition(
            spec=spec, opened=asof, open_fills=fills, entry_cash=entry_cash,
            capital_at_risk=capital_at_risk, target_value=target_value,
            stop_value=stop_value, last_marked=asof,
        )
        self.open_positions.append(pos)
        return pos

    # ------------------------------------------------------------------ #
    # Marking & carry
    # ------------------------------------------------------------------ #
    def _net_mark(self, spec: StrategySpec, chain: list[OptionQuote], asof: date,
                  underlying: float | None = None) -> float:
        """Signed mark-to-market (x100) of the spec's legs (long +, short -)."""
        u = underlying
        if u is None:
            u = next((q.underlying for q in chain if q.underlying > 0), 0.0)
        total = 0.0
        for leg in spec.legs:
            total += mark_leg(leg, chain, asof, u, self.r) * CONTRACT_MULTIPLIER
        return total

    def position_value(self, pos: OpenPosition, chain: list[OptionQuote],
                       asof: date, underlying: float | None = None) -> float:
        """Current liquidation value (signed mark) of an open position.

        ``underlying`` is a fallback spot (e.g. the engine's last-seen price)
        for days when the chain snapshot is empty.
        """
        u = next((q.underlying for q in chain if q.underlying > 0), None)
        if u is None and underlying is not None and underlying > 0:
            u = underlying
        return self._net_mark(pos.spec, chain, asof, underlying=u)

    def remark_margin(self, pos: OpenPosition, underlying: float) -> float:
        """Re-mark a credit position's margin to today's underlying (Reg-T
        re-marks daily; a naked short moving against you demands more margin,
        so carry accrues on the live requirement, not the open-day one).

        Defined-risk spreads are unaffected (width - credit is spot-invariant).
        The stop threshold stays anchored to the OPEN capital-at-risk — margin
        drift changes financing, not the exit plan. Returns the new figure.
        """
        if underlying <= 0 or total_open_premium(pos) <= 0:
            return pos.capital_at_risk  # debit structures carry the debit paid
        req = margin_requirement(pos.spec.legs, underlying, pos.open_fills)
        ml = pos.spec.max_loss
        floor = ml if (ml and math.isfinite(ml) and ml > 0) else 0.0
        pos.capital_at_risk = max(req, floor)
        return pos.capital_at_risk

    def accrue_carry(self, pos: OpenPosition, asof: date) -> float:
        """Accrue one day of financing on capital-at-risk; returns the charge."""
        if pos.last_marked is None:
            pos.last_marked = asof
            return 0.0
        days = (asof - pos.last_marked).days
        if days <= 0:
            return 0.0
        daily_rate = self.cost.financing_apr / 365.0
        charge = pos.capital_at_risk * daily_rate * days
        pos.holding_cost += charge
        self.cash -= charge
        pos.last_marked = asof
        return charge

    # ------------------------------------------------------------------ #
    # Close
    # ------------------------------------------------------------------ #
    def close(self, pos: OpenPosition, chain: list[OptionQuote], asof: date,
              reason: str, *, at_intrinsic: bool = False,
              underlying: float | None = None,
              intrinsic_legs: frozenset | None = None,
              assign_fee_contracts: int = 0) -> Trade:
        """Close a position, book exit cash/costs, and record the round-trip.

        ``at_intrinsic`` forces expiry/delisting settlement at intrinsic value
        (no spread crossing for the option, but exchange/assignment fees still
        apply on real trades).

        ``intrinsic_legs`` (a set of ``(kind, strike, expiry)`` keys) settles
        just those legs at intrinsic while the rest cross the spread — used for
        early assignment, where the assigned short leg settles at intrinsic and
        the remaining legs are liquidated at market.  ``assign_fee_contracts``
        charges ``CostModel.assignment_fee`` per assigned contract.
        """
        u = underlying
        if u is None:
            u = next((q.underlying for q in chain if q.underlying > 0),
                     pos.spec.meta.get("underlying", 0.0))

        fills: list[Fill] = []
        signed_cash = 0.0
        total_costs = 0.0
        for leg in pos.spec.legs:
            close_action = Action.SELL if leg.action == Action.BUY else Action.BUY
            q = find_quote(chain, leg.kind, leg.strike, leg.expiry)
            settle_intrinsic = at_intrinsic or (
                intrinsic_legs is not None
                and (leg.kind, leg.strike, leg.expiry) in intrinsic_legs)
            if settle_intrinsic or q is None:
                price = intrinsic(leg.kind, leg.strike, u)
                slip = 0.0
            else:
                price, slip = self._fill_price(q, close_action)
            commission = self._leg_costs(leg.quantity)
            # Closing a long => SELL (receive); closing a short => BUY (pay).
            sign = 1.0 if close_action == Action.SELL else -1.0
            notional = price * leg.quantity * CONTRACT_MULTIPLIER
            signed_cash += sign * notional
            total_costs += commission + slip * leg.quantity * CONTRACT_MULTIPLIER
            fills.append(Fill(asof, close_action, leg.kind, leg.strike, leg.expiry,
                              leg.quantity, round(price, 4), commission, slip))

        if assign_fee_contracts > 0:
            total_costs += self.cost.assignment_fee * assign_fee_contracts

        exit_cash = signed_cash - total_costs
        self.cash += exit_cash

        open_costs = sum(f.commission + f.slippage * f.quantity * CONTRACT_MULTIPLIER
                         for f in pos.open_fills)
        # Gross P&L = premium received/paid at open + close, before frictions.
        open_premium = sum(_premium_signed(f) for f in pos.open_fills)
        close_premium = sum(_premium_signed(f) for f in fills)
        gross_pnl = open_premium + close_premium
        costs = open_costs + total_costs + pos.holding_cost
        pnl = gross_pnl - costs

        trade = Trade(
            spec_name=pos.spec.name, ticker=pos.spec.ticker, opened=pos.opened,
            closed=asof, open_fills=pos.open_fills, close_fills=fills,
            pnl=round(pnl, 4), holding_cost=round(pos.holding_cost, 4),
            gross_pnl=round(gross_pnl, 4), costs=round(costs, 4), closed_reason=reason,
        )
        self.trades.append(trade)
        if pos in self.open_positions:
            self.open_positions.remove(pos)
        return trade

    # ------------------------------------------------------------------ #
    def equity(self, chains: dict[str, list[OptionQuote]], asof: date,
               underlyings: dict[str, float] | None = None) -> float:
        """Total equity: cash plus liquidation value of all open positions.

        ``underlyings`` optionally maps ticker -> last-seen spot, used to mark
        positions whose ticker printed no chain on ``asof``.
        """
        eq = self.cash
        for pos in self.open_positions:
            tk = pos.spec.ticker
            chain = chains.get(tk, [])
            u = underlyings.get(tk) if underlyings else None
            eq += self.position_value(pos, chain, asof, underlying=u)
        return eq


def _premium_signed(fill: Fill) -> float:
    """Cash impact (premium only, no fees) of a fill: SELL +, BUY -."""
    sign = 1.0 if fill.action == Action.SELL else -1.0
    return sign * fill.price * fill.quantity * CONTRACT_MULTIPLIER


def total_open_premium(pos: OpenPosition) -> float:
    """Net premium booked at open (for diagnostics)."""
    return sum(_premium_signed(f) for f in pos.open_fills)
