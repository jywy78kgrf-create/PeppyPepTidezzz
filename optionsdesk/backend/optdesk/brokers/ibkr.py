"""
Interactive Brokers seam.

This module is the wiring for eventual live trading via ``ib_insync``.  It is
written so it *imports cleanly whether or not ib_insync is installed* and runs
in a disconnected "stub" mode by default.  ``place()`` refuses to transmit an
order unless live trading is explicitly enabled in settings AND a real
connection has been established.

The non-trivial part is mapping a ``StrategySpec`` (a set of option ``Leg``s)
onto an IB option combo (``BAG``) contract, which is implemented here and unit-
testable without a live gateway.
"""
from __future__ import annotations

from typing import Any, Optional

from ..config import SETTINGS, Settings
from ..contracts import Action, Leg, OptionType, StrategySpec
from .base import BrokerBase

# ib_insync is optional. Guard the import so the module always loads.
try:  # pragma: no cover - depends on environment
    from ib_insync import IB, ComboLeg, Contract, Option, Order  # type: ignore

    IB_AVAILABLE = True
except Exception:  # noqa: BLE001 - any import failure means "not available"
    IB = ComboLeg = Contract = Option = Order = None  # type: ignore
    IB_AVAILABLE = False


class IBKRBroker(BrokerBase):
    """IB adapter; disconnected stub unless ib_insync + live trading are on."""

    def __init__(self, settings: Settings = SETTINGS, exchange: str = "SMART", currency: str = "USD") -> None:
        self.settings = settings
        self.exchange = exchange
        self.currency = currency
        self._ib: Optional[Any] = None
        self._connected = False

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def connect(self) -> bool:
        """Connect to TWS/Gateway if possible; otherwise stay in stub mode."""
        if not IB_AVAILABLE:
            self._connected = False
            return False
        if not self.settings.live_trading_enabled:
            # Refuse silently to connect when live trading is disabled; callers
            # check is_connected() before relying on a session.
            self._connected = False
            return False
        try:  # pragma: no cover - requires a running gateway
            self._ib = IB()
            self._ib.connect(
                self.settings.ibkr_host,
                self.settings.ibkr_port,
                clientId=self.settings.ibkr_client_id,
            )
            self._connected = bool(self._ib.isConnected())
        except Exception:  # noqa: BLE001
            self._ib = None
            self._connected = False
        return self._connected

    def is_connected(self) -> bool:
        if self._ib is None:
            return False
        try:  # pragma: no cover
            return bool(self._ib.isConnected())
        except Exception:  # noqa: BLE001
            return False

    def disconnect(self) -> None:
        if self._ib is not None:
            try:  # pragma: no cover
                self._ib.disconnect()
            finally:
                self._connected = False

    # ------------------------------------------------------------------ #
    # Contract mapping (testable offline)
    # ------------------------------------------------------------------ #
    def option_contract(self, ticker: str, leg: Leg) -> Any:
        """Build an IB ``Option`` contract for a single leg.

        Returns a real ``Option`` when ib_insync is present, else a plain dict
        with the equivalent fields so the mapping can be inspected/tested.
        """
        right = "C" if leg.kind == OptionType.CALL else "P"
        expiry = leg.expiry.strftime("%Y%m%d")
        if IB_AVAILABLE:  # pragma: no cover - exercised only with ib_insync
            return Option(
                symbol=ticker,
                lastTradeDateOrContractMonth=expiry,
                strike=float(leg.strike),
                right=right,
                exchange=self.exchange,
                currency=self.currency,
            )
        return {
            "secType": "OPT",
            "symbol": ticker,
            "lastTradeDateOrContractMonth": expiry,
            "strike": float(leg.strike),
            "right": right,
            "exchange": self.exchange,
            "currency": self.currency,
        }

    def combo_contract(self, spec: StrategySpec, leg_conids: Optional[list[int]] = None) -> Any:
        """Map a multi-leg ``StrategySpec`` to an IB combo (``BAG``) contract.

        ``leg_conids`` are the resolved contract ids for each leg.  When absent
        (offline), placeholder ids are emitted so the structure is still
        complete and inspectable.
        """
        conids = leg_conids or list(range(1, len(spec.legs) + 1))
        if len(conids) != len(spec.legs):
            raise ValueError("leg_conids length must match number of legs")

        combo_legs = []
        for leg, conid in zip(spec.legs, conids):
            action = "BUY" if leg.action == Action.BUY else "SELL"
            ratio = max(1, abs(leg.quantity))
            if IB_AVAILABLE:  # pragma: no cover
                cl = ComboLeg()
                cl.conId = int(conid)
                cl.ratio = ratio
                cl.action = action
                cl.exchange = self.exchange
                combo_legs.append(cl)
            else:
                combo_legs.append(
                    {"conId": int(conid), "ratio": ratio, "action": action, "exchange": self.exchange}
                )

        if IB_AVAILABLE:  # pragma: no cover
            bag = Contract()
            bag.symbol = spec.ticker
            bag.secType = "BAG"
            bag.currency = self.currency
            bag.exchange = self.exchange
            bag.comboLegs = combo_legs
            return bag
        return {
            "secType": "BAG",
            "symbol": spec.ticker,
            "currency": self.currency,
            "exchange": self.exchange,
            "comboLegs": combo_legs,
        }

    # ------------------------------------------------------------------ #
    # Trading
    # ------------------------------------------------------------------ #
    def place(self, spec: StrategySpec, qty: int = 1) -> dict:
        """Transmit a combo order. Raises unless live + connected."""
        if not self.settings.live_trading_enabled:
            raise RuntimeError(
                "live trading disabled (set OPTDESK_LIVE=1 / "
                "SETTINGS.live_trading_enabled to enable)"
            )
        if not IB_AVAILABLE:
            raise RuntimeError("ib_insync is not installed; cannot place live orders")
        if not self.is_connected():
            raise RuntimeError("IBKR not connected; call connect() first")

        # Resolve real conIds for each leg, then build + transmit the combo.
        conids: list[int] = []
        for leg in spec.legs:  # pragma: no cover - needs live gateway
            details = self._ib.reqContractDetails(self.option_contract(spec.ticker, leg))
            if not details:
                raise RuntimeError(f"could not qualify leg {leg.strike} {leg.kind.value}")
            conids.append(details[0].contract.conId)

        bag = self.combo_contract(spec, conids)  # pragma: no cover
        net_action = "BUY"
        order = Order(action=net_action, orderType="MKT", totalQuantity=int(qty), transmit=True)
        trade = self._ib.placeOrder(bag, order)
        return {
            "status": "submitted",
            "ticker": spec.ticker,
            "strategy": spec.name,
            "qty": qty,
            "order_id": getattr(getattr(trade, "order", None), "orderId", None),
        }

    def positions(self) -> list[dict]:
        if not self.is_connected():
            return []
        out: list[dict] = []
        for p in self._ib.positions():  # pragma: no cover
            out.append(
                {
                    "symbol": getattr(p.contract, "symbol", None),
                    "secType": getattr(p.contract, "secType", None),
                    "position": p.position,
                    "avgCost": p.avgCost,
                }
            )
        return out

    def account(self) -> dict:
        if not self.is_connected():
            return {
                "connected": False,
                "live_enabled": self.settings.live_trading_enabled,
                "ib_insync_installed": IB_AVAILABLE,
            }
        summary = {v.tag: v.value for v in self._ib.accountSummary()}  # pragma: no cover
        summary["connected"] = True
        return summary

    # ------------------------------------------------------------------ #
    def status(self) -> dict:
        """Lightweight status for the API (never raises)."""
        return {
            "connected": self.is_connected(),
            "live_enabled": self.settings.live_trading_enabled,
            "ib_insync_installed": IB_AVAILABLE,
            "host": self.settings.ibkr_host,
            "port": self.settings.ibkr_port,
        }
