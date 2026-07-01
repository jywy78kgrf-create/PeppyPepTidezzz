"""
Paper-trading broker.

Persists open/closed positions as JSON under ``config.STATE_DIR`` and accounts
for fills using the *same* cross-the-spread + commission concept the
backtester uses (see ``CostModel``).  Because the fill maths matches, paper
P&L reconciles with backtest P&L for identical legs and quotes.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional, Union

from ..config import STATE_DIR
from ..contracts import (
    Action,
    CostModel,
    Leg,
    OptionQuote,
    OptionType,
    PaperPosition,
    StrategySpec,
)
from ..data.loader import ChainStore

# A quote source is either a live ChainStore or a flat list/iterable of quotes.
QuoteSource = Union[ChainStore, Iterable[OptionQuote]]

CONTRACT_MULT = 100  # shares per option contract


def _fill_price(quote: OptionQuote, action: Action, cost: CostModel) -> float:
    """Executable per-share price: cross a fraction of the spread, adversely.

    BUY pays above mid, SELL receives below mid — identical to the backtester's
    slippage model.
    """
    mid = quote.mid
    slip = max(cost.min_slippage, cost.slippage_frac_of_spread * quote.spread)
    return round(mid + slip if action == Action.BUY else mid - slip, 4)


def _leg_commission(leg: Leg, cost: CostModel) -> float:
    """Commission + exchange fee for one leg (per contract, per side)."""
    n = abs(leg.quantity)
    return n * (cost.commission_per_contract + cost.exchange_fee_per_contract)


def _match_quote(chain: list[OptionQuote], leg: Leg) -> Optional[OptionQuote]:
    """Find the quote matching a leg's strike/expiry/kind (nearest strike)."""
    candidates = [
        q for q in chain if q.kind == leg.kind and q.expiry == leg.expiry
    ]
    if not candidates:
        candidates = [q for q in chain if q.kind == leg.kind]
    if not candidates:
        return None
    return min(candidates, key=lambda q: abs(q.strike - leg.strike))


class PaperBroker:
    """File-backed paper broker mirroring backtest fill/cost accounting."""

    def __init__(
        self,
        state_dir: Path = STATE_DIR,
        cost_model: CostModel = CostModel(),
        starting_cash: float = 100_000.0,
    ) -> None:
        self.path = Path(state_dir) / "paper.json"
        self.cost = cost_model
        self._starting_cash = starting_cash
        self._cash = starting_cash
        self._positions: list[PaperPosition] = []
        self._load()

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        if not self.path.exists():
            self._save()
            return
        try:
            data = json.loads(self.path.read_text())
            cash = float(data.get("cash", self._starting_cash))
            starting = float(data.get("starting_cash", self._starting_cash))
            positions = [self._pos_from_dict(p) for p in data.get("positions", [])]
        except Exception:  # noqa: BLE001 - corrupt/partial state must not crash the API
            # Preserve the unreadable file for forensics, then start fresh.
            self._backup_corrupt()
            self._save()
            return
        self._cash = cash
        self._starting_cash = starting
        self._positions = positions

    def _backup_corrupt(self) -> None:
        """Move an unreadable state file aside as ``paper.json.corrupt-<ts>``."""
        try:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            self.path.replace(self.path.with_name(f"{self.path.name}.corrupt-{ts}"))
        except OSError:
            pass  # best effort; a fresh _save() will overwrite in place

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "cash": round(self._cash, 4),
            "starting_cash": round(self._starting_cash, 4),
            "positions": [self._pos_to_dict(p) for p in self._positions],
        }
        self.path.write_text(json.dumps(data, indent=2, default=str))

    @staticmethod
    def _pos_to_dict(p: PaperPosition) -> dict:
        return {
            "ticker": p.ticker,
            "spec_name": p.spec_name,
            "opened": p.opened.isoformat(),
            "legs": p.legs,
            "cost_basis": round(p.cost_basis, 4),
            "current_value": round(p.current_value, 4),
            "upnl": round(p.upnl, 4),
            "status": p.status,
        }

    @staticmethod
    def _pos_from_dict(d: dict) -> PaperPosition:
        return PaperPosition(
            ticker=d["ticker"],
            spec_name=d["spec_name"],
            opened=datetime.fromisoformat(d["opened"]),
            legs=d["legs"],
            cost_basis=float(d["cost_basis"]),
            current_value=float(d["current_value"]),
            upnl=float(d["upnl"]),
            status=d.get("status", "OPEN"),
        )

    # ------------------------------------------------------------------ #
    # Trading API
    # ------------------------------------------------------------------ #
    def open(self, spec: StrategySpec, chain: list[OptionQuote], qty: int = 1) -> PaperPosition:
        """Open a position from a spec, filling each leg at executable prices."""
        legs_state: list[dict] = []
        net_cash_flow = 0.0  # +received, -paid (per-share * mult, signed by action)
        commission = 0.0

        for leg in spec.legs:
            q = _match_quote(chain, leg)
            if q is None:
                raise ValueError(
                    f"no quote for leg {leg.kind.value} {leg.strike} {leg.expiry}"
                )
            price = _fill_price(q, leg.action, self.cost)
            comm = _leg_commission(leg, self.cost) * qty
            commission += comm
            contracts = leg.quantity * qty
            sign = -1.0 if leg.action == Action.BUY else 1.0  # buy spends cash
            net_cash_flow += sign * price * contracts * CONTRACT_MULT
            legs_state.append(
                {
                    "action": leg.action.value,
                    "kind": leg.kind.value,
                    "strike": leg.strike,
                    "expiry": leg.expiry.isoformat(),
                    "quantity": contracts,
                    "open_price": price,
                }
            )

        # cost_basis = net debit paid to enter (positive => we paid).
        cost_basis = round(-net_cash_flow + commission, 4)
        self._cash -= cost_basis
        pos = PaperPosition(
            ticker=spec.ticker,
            spec_name=spec.name,
            opened=datetime.utcnow(),
            legs=legs_state,
            cost_basis=cost_basis,
            current_value=cost_basis,  # marked flat at entry
            upnl=0.0,
            status="OPEN",
        )
        self._positions.append(pos)
        self._save()
        return pos

    def positions(self) -> list[PaperPosition]:
        """Return all positions (open and closed)."""
        return list(self._positions)

    def mark(self, source: QuoteSource) -> None:
        """Refresh current_value / upnl for open positions from fresh quotes."""
        for pos in self._positions:
            if pos.status != "OPEN":
                continue
            chain = self._chain_for(source, pos)
            value = self._liquidation_value(pos, chain)
            pos.current_value = round(value, 4)
            pos.upnl = round(value - pos.cost_basis, 4)
        self._save()

    def close(self, idx: int) -> PaperPosition:
        """Close the position at ``idx`` at its last-marked liquidation value."""
        if idx < 0 or idx >= len(self._positions):
            raise IndexError(f"position index {idx} out of range")
        pos = self._positions[idx]
        if pos.status != "OPEN":
            return pos
        # Realise the currently-marked value back into cash.
        self._cash += pos.current_value
        pos.status = "CLOSED"
        pos.upnl = round(pos.current_value - pos.cost_basis, 4)
        self._save()
        return pos

    def equity(self) -> dict:
        """Account snapshot: cash, unrealised P&L, and total equity."""
        upnl = sum(p.upnl for p in self._positions if p.status == "OPEN")
        open_value = sum(p.current_value for p in self._positions if p.status == "OPEN")
        return {
            "cash": round(self._cash, 2),
            "open_value": round(open_value, 2),
            "upnl": round(upnl, 2),
            "total": round(self._cash + open_value, 2),
            "starting_cash": round(self._starting_cash, 2),
        }

    # ------------------------------------------------------------------ #
    # Marking internals
    # ------------------------------------------------------------------ #
    def _liquidation_value(self, pos: PaperPosition, chain: list[OptionQuote]) -> float:
        """What we'd net by closing now (exit fills cross the spread again)."""
        value = 0.0
        commission = 0.0
        for ls in pos.legs:
            leg = Leg(
                action=Action(ls["action"]),
                kind=OptionType(ls["kind"]),
                strike=float(ls["strike"]),
                expiry=date.fromisoformat(ls["expiry"]),
                quantity=int(ls["quantity"]),
            )
            q = _match_quote(chain, leg)
            if q is None:
                # No quote: assume held at open price (zero mark-to-market change).
                value += (
                    (-1.0 if leg.action == Action.SELL else 1.0)
                    * float(ls["open_price"]) * abs(leg.quantity) * CONTRACT_MULT
                )
                continue
            # Closing reverses the open action.
            close_action = Action.SELL if leg.action == Action.BUY else Action.BUY
            price = _fill_price(q, close_action, self.cost)
            commission += (
                self.cost.commission_per_contract + self.cost.exchange_fee_per_contract
            ) * abs(leg.quantity)
            sign = 1.0 if close_action == Action.SELL else -1.0  # sell brings cash in
            value += sign * price * abs(leg.quantity) * CONTRACT_MULT
        return value - commission

    @staticmethod
    def _chain_for(source: QuoteSource, pos: PaperPosition) -> list[OptionQuote]:
        """Resolve the relevant chain for a position from the quote source."""
        if isinstance(source, ChainStore):
            dates = source.trading_dates(pos.ticker)
            if not dates:
                return []
            return source.chain(pos.ticker, dates[-1])
        return [q for q in source if q.ticker.upper() == pos.ticker.upper()]
