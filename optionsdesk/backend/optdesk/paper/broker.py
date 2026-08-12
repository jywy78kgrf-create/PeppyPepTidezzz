"""
Paper-trading broker.

Persists open/closed positions as JSON under ``config.STATE_DIR`` and accounts
for fills using the *same* cross-the-spread + commission concept the
backtester uses (see ``CostModel``).  Because the fill maths matches, paper
P&L reconciles with backtest P&L for identical legs and quotes.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Union

from ..config import STATE_DIR

# One write-lock per state file, shared across every PaperBroker instance in
# the process. The API creates a fresh broker per request and the autopilot has
# its own — without this they wrote the SAME temp file concurrently and
# clobbered each other into a corrupt paper.json, which then reset the account
# to a fresh $100k. Serialized writes + a unique temp file per write fix it.
_SAVE_LOCKS: dict[str, threading.Lock] = {}
_SAVE_LOCKS_GUARD = threading.Lock()


def _save_lock_for(path: Path) -> threading.Lock:
    key = str(path)
    with _SAVE_LOCKS_GUARD:
        lk = _SAVE_LOCKS.get(key)
        if lk is None:
            lk = threading.Lock()
            _SAVE_LOCKS[key] = lk
        return lk
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
SNAPSHOT_THROTTLE_S = 300  # min seconds between history points (unless forced)


def _parse_ts(v: Any) -> Optional[datetime]:
    """ISO timestamp -> aware UTC datetime (None if unparseable)."""
    try:
        dt = datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _live_mid(contract: dict) -> float:
    """Mark price for a normalized realtime contract: mid, else last."""
    bid, ask = float(contract.get("bid") or 0.0), float(contract.get("ask") or 0.0)
    if bid > 0 and ask > 0:
        return 0.5 * (bid + ask)
    return float(contract.get("last") or 0.0)


def _fill_price(quote: OptionQuote, action: Action, cost: CostModel) -> float:
    """Executable per-share price: cross a fraction of the spread, adversely.

    BUY pays above mid, SELL receives below mid — identical to the backtester's
    slippage model.
    """
    from ..quant.pricing import slippage_fraction

    mid = quote.mid
    frac = slippage_fraction(mid, quote.spread, cost)
    slip = max(cost.min_slippage, frac * quote.spread)
    return round(mid + slip if action == Action.BUY else mid - slip, 4)


def _live_fill_price(contract: dict, action: Action, cost: CostModel) -> float:
    """Executable per-share price from a normalized realtime contract — same
    adverse spread-crossing as ``_fill_price`` but for the live dict form.
    Used to charge a realistic EXIT fill when closing a paper position."""
    from ..quant.pricing import slippage_fraction

    mid = _live_mid(contract)
    bid = float(contract.get("bid") or 0.0)
    ask = float(contract.get("ask") or 0.0)
    spread = max(0.0, ask - bid)
    frac = slippage_fraction(mid, spread, cost)
    slip = max(cost.min_slippage, frac * spread)
    return round(mid + slip if action == Action.BUY else mid - slip, 4)


def _leg_commission(leg: Leg, cost: CostModel) -> float:
    """Commission + exchange fee for one leg (per contract, per side)."""
    n = abs(leg.quantity)
    return n * (cost.commission_per_contract + cost.exchange_fee_per_contract)


def _match_quote(chain: list[OptionQuote], leg: Leg) -> Optional[OptionQuote]:
    """Find the quote matching a leg's kind + EXPIRY (nearest strike within it).

    Never matches across expiries: a live-opened Aug leg has no business being
    priced off a June contract of the same strike — that mismatch produced
    impossible (negative) long-option marks. No same-expiry quote -> None, and
    the caller holds the position at its last mark.
    """
    candidates = [
        q for q in chain if q.kind == leg.kind and q.expiry == leg.expiry
    ]
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
        self._ledger = None  # lazy; co-located with the state dir
        self.cost = cost_model
        self._starting_cash = starting_cash
        self._cash = starting_cash
        self._positions: list[PaperPosition] = []
        self._history: list[dict] = []
        # ISO timestamp of the last account reset; the desk shows only ledger
        # trades opened at/after it, so a fresh start isn't polluted by prior
        # runs (the append-only ledger itself is never deleted).
        self._epoch: Optional[str] = None
        # in-memory: last time we pulled AV quotes to mark (throttles off-hours
        # marking so we don't poll AV all night — EOD prices don't change).
        self._last_av_mark: Optional[datetime] = None
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
        self._epoch = data.get("epoch")
        # history is additive state: a missing or corrupt field must never
        # invalidate an otherwise-good (pre-history) paper.json.
        self._history = self._history_from(data)

    @property
    def epoch(self) -> Optional[str]:
        """ISO timestamp of the last reset, or None. Ledger reads filter to it."""
        return self._epoch

    def reset(self, starting_cash: Optional[float] = None) -> dict:
        """Start a fresh forward test: flat book, cash restored, equity curve
        cleared. Sets a new epoch so the desk's ledger views show only trades
        from here on; the append-only ledger itself is preserved for audit and
        gets a 'reset' event. Returns the new equity snapshot."""
        cash = float(starting_cash if starting_cash is not None else self._starting_cash)
        self._starting_cash = cash
        self._cash = cash
        self._positions = []
        self._history = []
        self._epoch = datetime.now(timezone.utc).isoformat()
        self._save()
        try:  # audit breadcrumb; never fatal
            self.ledger.record_event(self._epoch, "reset",
                                     f"account reset to {cash:,.0f}")
        except Exception:  # noqa: BLE001
            pass
        return self.equity()

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
            "epoch": self._epoch,
            "positions": [self._pos_to_dict(p) for p in self._positions],
            "history": self._history,
        }
        payload = json.dumps(data, indent=2, default=str)
        # Serialize writes per file AND use a UNIQUE temp file per write, so
        # concurrent brokers can never clobber a shared temp into a corrupt
        # paper.json (the bug that was resetting the account). os.replace is
        # atomic — a crash mid-write leaves the previous good file intact.
        with _save_lock_for(self.path):
            fd, tmpname = tempfile.mkstemp(
                dir=str(self.path.parent), prefix=".paper-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as fh:
                    fh.write(payload)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmpname, self.path)
            except Exception:
                try:
                    os.unlink(tmpname)
                except OSError:
                    pass
                raise

    @staticmethod
    def _history_from(data: dict) -> list[dict]:
        """Sanitize the persisted history list; never raises.

        Old state files (pre-history) simply lack the key; hand-edited or
        corrupt fields may hold the wrong types.  Anything unusable is dropped
        point-by-point so good positions/cash are still honoured.
        """
        raw = data.get("history", [])
        if not isinstance(raw, list):
            return []
        points: list[dict] = []
        for p in raw:
            if not isinstance(p, dict):
                continue
            try:
                points.append({
                    "ts": str(p["ts"]),
                    "equity": float(p["equity"]),
                    "cash": float(p["cash"]),
                    "upnl": float(p["upnl"]),
                    "live": bool(p.get("live", False)),
                })
            except (KeyError, TypeError, ValueError):
                continue
        return points

    @staticmethod
    def _pos_to_dict(p: PaperPosition) -> dict:
        return {
            "ticker": p.ticker,
            "spec_name": p.spec_name,
            "opened": p.opened.isoformat(),
            "legs": p.legs,
            "cost_basis": round(p.cost_basis, 4),
            "current_value": round(p.current_value, 4),
            "liquidation_value": (round(p.liquidation_value, 4)
                                  if p.liquidation_value is not None else None),
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
            liquidation_value=(float(d["liquidation_value"])
                               if d.get("liquidation_value") is not None else None),
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
        try:  # permanent audit copy (never fatal)
            self.ledger.record_open(
                ticker=pos.ticker, opened=pos.opened.isoformat(),
                strategy=spec.name, qty=qty, cost_basis=pos.cost_basis,
                legs=legs_state,
                config_id=(spec.meta or {}).get("config_id"))
        except Exception:  # noqa: BLE001
            pass
        return pos

    @property
    def ledger(self):
        """Append-only audit ledger living next to this broker's state file."""
        if self._ledger is None:
            from ..journal import get_ledger
            self._ledger = get_ledger(self.path.parent / "ledger.db")
        return self._ledger

    def positions(self) -> list[PaperPosition]:
        """Return all positions (open and closed)."""
        return list(self._positions)

    def mark(self, source: QuoteSource) -> None:
        """Refresh current_value / upnl for open positions from fresh quotes.

        Historical (end-of-day) marking: exit fills cross the spread. Records
        a (throttled) equity history snapshot with ``live=False``.
        """
        for pos in self._positions:
            if pos.status != "OPEN":
                continue
            chain = self._chain_for(source, pos)
            value = self._liquidation_value(pos, chain)
            if value is None:
                # the store can't price every leg (e.g. a live-opened position
                # whose expiry isn't in the store) — HOLD the last mark rather
                # than fabricate one.
                continue
            pos.current_value = round(value, 4)
            pos.upnl = round(value - pos.cost_basis, 4)
            # historical marks already cross the spread + charge exit
            # commission, so the mark IS the liquidation value.
            pos.liquidation_value = round(value, 4)
        self._save()
        self.snapshot(live=False)

    def mark_live(self, av, store: Optional[ChainStore] = None,
                  when: Optional[datetime] = None) -> dict:
        """Mark open positions from Alpha Vantage realtime option chains.

        Fetches ``av.realtime_options`` once per distinct position ticker,
        matches each leg by ``(expiry, strike, type)`` and marks it at the
        quote mid (no spread crossing — a mark, not an exit fill).  Records a
        ``live=True`` snapshot and returns ``{"live": True, "marked": n}``
        where ``n`` counts open positions with every leg matched live.

        Marks come from AV realtime quotes both during AND after market hours:
        off-hours the endpoint returns the last session's CLOSING option prices,
        which is the correct EOD mark for positions opened from a live chain
        (the historical store lacks their contracts entirely). Marks are labeled
        ``live=True`` only during regular hours, ``live=False`` (EOD) otherwise.
        Off-hours marking is throttled to every 15 min (prices are static) so we
        don't poll AV all night. ``when`` overrides the clock for tests.

        On any AV error (no key / premium note / rate limit / transport) it
        falls back to the latest historical chain via ``store`` — which now only
        re-prices positions whose exact contracts it holds, never mis-matching a
        different expiry (that produced impossible negative long-option marks).
        This method NEVER raises — it sits directly on the API path.
        """
        try:
            from ..live.market_hours import market_open
            live_now = bool(market_open(when))
            open_pos = [p for p in self._positions if p.status == "OPEN"]
            if not open_pos:
                self.snapshot(live=live_now)
                return {"live": live_now, "marked": 0}
            if not getattr(av, "configured", False):
                return self._mark_fallback(store, "alpha_vantage_key not configured")
            # off-hours throttle: EOD prices don't move, so refresh at most every
            # 15 min; between refreshes hold the last mark (no overnight polling).
            now_ts = datetime.now(timezone.utc)
            if not live_now and self._last_av_mark is not None and (
                    now_ts - self._last_av_mark).total_seconds() < 900:
                self.snapshot(live=False)
                return {"live": False, "marked": 0, "reason": "holding EOD mark"}
            # Fetch every position ticker's chain CONCURRENTLY — one slow
            # sequential fetch per ticker was making the mark take 10-25s and
            # miss the client's timeout ("STALE"). Wall time is now the single
            # slowest fetch, not their sum.
            tickers = sorted({p.ticker.upper() for p in open_pos})

            def _fetch(tk: str):
                rows = av.realtime_options(tk)
                err = next(
                    (r["error"] for r in rows if isinstance(r, dict) and "error" in r),
                    None,
                )
                return tk, rows, err

            chains: dict[str, list[dict]] = {}
            if len(tickers) == 1:
                results = [_fetch(tickers[0])]
            else:
                import concurrent.futures as _cf
                with _cf.ThreadPoolExecutor(max_workers=min(8, len(tickers))) as ex:
                    results = list(ex.map(_fetch, tickers))
            for tk, rows, err in results:
                if err is not None:
                    return self._mark_fallback(store, f"{tk}: {err}")
                chains[tk] = [r for r in rows if isinstance(r, dict)]
            marked = 0
            for pos in open_pos:
                chain = chains.get(pos.ticker.upper(), [])
                value, all_matched = self._live_value(pos, chain)
                pos.current_value = round(value, 4)
                pos.upnl = round(value - pos.cost_basis, 4)
                # net-of-exit-cost proceeds, so a close charges a real fill.
                liq, _ = self._live_liquidation(pos, chain)
                pos.liquidation_value = round(liq, 4)
                if all_matched:
                    marked += 1
            self._last_av_mark = now_ts
            self._save()
            self.snapshot(live=live_now)
            return {"live": live_now, "marked": marked}
        except Exception as exc:  # noqa: BLE001 - marking must never crash the API
            return self._mark_fallback(store, f"live marking failed: {exc}")

    def _mark_fallback(self, store: Optional[ChainStore], reason: str) -> dict:
        """Historical-chain fallback for ``mark_live``; also never raises."""
        try:
            self.mark(store if store is not None else ChainStore())
        except Exception as exc:  # noqa: BLE001 - e.g. no chain file for a ticker
            try:
                self.snapshot(live=False)
            except Exception:  # noqa: BLE001 - truly last-ditch (disk full etc.)
                pass
            return {"live": False, "reason": f"{reason}; historical fallback failed: {exc}"}
        return {"live": False, "reason": reason}

    def _live_value(self, pos: PaperPosition, contracts: list[dict]) -> tuple[float, bool]:
        """Value a position off normalized realtime contracts, marked at mid.

        Legs match on exact ``(expiry, strike, type)``.  An unmatched leg is
        held at its open price (flat mark — same convention as the historical
        path).  Returns ``(value, every_leg_matched)``.
        """
        index: dict[tuple[str, float, str], dict] = {}
        for c in contracts:
            try:
                key = (str(c["expiry"]), round(float(c["strike"]), 4),
                       str(c["option_type"]).upper())
            except (KeyError, TypeError, ValueError):
                continue
            index[key] = c
        value = 0.0
        all_matched = True
        for ls in pos.legs:
            qty = abs(int(ls["quantity"]))
            # Long legs are assets (+mid); short legs are liabilities (-mid).
            sign = -1.0 if ls["action"] == Action.SELL.value else 1.0
            c = index.get((str(ls["expiry"]), round(float(ls["strike"]), 4),
                           str(ls["kind"]).upper()))
            if c is None:
                all_matched = False
                value += sign * float(ls["open_price"]) * qty * CONTRACT_MULT
                continue
            value += sign * _live_mid(c) * qty * CONTRACT_MULT
        return value, all_matched

    def _live_liquidation(self, pos: PaperPosition,
                          contracts: list[dict]) -> tuple[float, bool]:
        """Net proceeds if the position were closed NOW off live contracts.

        Mirrors ``_live_value`` but the CLOSING side crosses the spread
        adversely (via ``_live_fill_price``) and pays exit commission per
        contract — so a close realises a real round-trip fill, never a free
        mid. This is what makes a paper win/loss honest: a small-premium credit
        trade can round-trip into the red once the exit half-spread + fees are
        charged. Unmatched legs are held flat at their open price (same
        convention as the mid mark). Returns ``(value, every_leg_matched)``.
        """
        index: dict[tuple[str, float, str], dict] = {}
        for c in contracts:
            try:
                key = (str(c["expiry"]), round(float(c["strike"]), 4),
                       str(c["option_type"]).upper())
            except (KeyError, TypeError, ValueError):
                continue
            index[key] = c
        value = 0.0
        commission = 0.0
        all_matched = True
        for ls in pos.legs:
            qty = abs(int(ls["quantity"]))
            opened_buy = ls["action"] != Action.SELL.value
            # Closing reverses the open: a long leg is SOLD, a short is BOUGHT.
            close_action = Action.SELL if opened_buy else Action.BUY
            # Every leg costs commission + exchange fee to close, matched or not.
            commission += (self.cost.commission_per_contract
                           + self.cost.exchange_fee_per_contract) * qty
            c = index.get((str(ls["expiry"]), round(float(ls["strike"]), 4),
                           str(ls["kind"]).upper()))
            if c is None:
                all_matched = False
                # can't price the exit fill — hold this leg flat at open price.
                value += (1.0 if opened_buy else -1.0) * float(
                    ls["open_price"]) * qty * CONTRACT_MULT
                continue
            price = _live_fill_price(c, close_action, self.cost)
            # SELL to close brings cash in (+); BUY to close costs cash (-).
            sign = 1.0 if close_action == Action.SELL else -1.0
            value += sign * price * qty * CONTRACT_MULT
        return value - commission, all_matched

    # ------------------------------------------------------------------ #
    # Equity history
    # ------------------------------------------------------------------ #
    def snapshot(self, live: bool = False, force: bool = False) -> Optional[dict]:
        """Append an equity history point ``{ts, equity, cash, upnl, live}``.

        Throttled: if the latest point is younger than 5 minutes the call is
        a no-op returning None — unless ``force=True``.  Persists on append.
        """
        now = datetime.now(timezone.utc)
        if not force and self._history:
            last = _parse_ts(self._history[-1].get("ts"))
            if last is not None and (now - last).total_seconds() < SNAPSHOT_THROTTLE_S:
                return None
        eq = self.equity()
        point = {
            "ts": now.isoformat(),
            "equity": eq["total"],
            "cash": eq["cash"],
            "upnl": eq["upnl"],
            "live": bool(live),
        }
        self._history.append(point)
        self._save()
        try:  # permanent audit copy (never fatal)
            self.ledger.record_mark(
                point["ts"], point["equity"], point["cash"], point["upnl"],
                open_positions=sum(1 for p in self._positions
                                   if p.status == "OPEN"),
                live=bool(live))
        except Exception:  # noqa: BLE001
            pass
        return point

    def history(self) -> list[dict]:
        """All persisted equity snapshots, oldest first."""
        return [dict(p) for p in self._history]

    def close(self, idx: int, reason: str = "manual",
              floor: Optional[float] = None) -> PaperPosition:
        """Close the position at ``idx`` at its last-marked liquidation value.

        ``floor`` (optional) is a minimum realistic liquidation value — e.g. a
        long option's intrinsic value net of exit costs. A stored mark BELOW the
        floor is stale/bad, so we realise the floor instead of booking a phantom
        loss. This is the guard for the bug where a deep-ITM call was closed for
        far less than its intrinsic off a months-old historical mark."""
        if idx < 0 or idx >= len(self._positions):
            raise IndexError(f"position index {idx} out of range")
        pos = self._positions[idx]
        if pos.status != "OPEN":
            return pos
        # Realise the EXIT-fill value (spread crossed + exit commission), not
        # the free mid: a paper close pays the same round-trip costs a real one
        # would, so a "winning" mid-mark can still book a loss. Falls back to
        # the mid mark only if the position was never marked live/historically.
        proceeds = (pos.liquidation_value
                    if pos.liquidation_value is not None else pos.current_value)
        if floor is not None and proceeds < float(floor):
            proceeds = float(floor)  # never realise below intrinsic (stale mark)
        self._cash += proceeds
        pos.current_value = round(proceeds, 4)
        pos.status = "CLOSED"
        pos.upnl = round(proceeds - pos.cost_basis, 4)
        self._save()
        try:  # permanent audit copy (never fatal)
            self.ledger.record_close(
                ticker=pos.ticker, opened=pos.opened.isoformat()
                if hasattr(pos.opened, "isoformat") else str(pos.opened),
                close_value=proceeds, pnl=pos.upnl, reason=reason)
        except Exception:  # noqa: BLE001
            pass
        return pos

    def equity(self) -> dict:
        """Account snapshot: cash, unrealised/realised P&L, and total equity.

        ``realized`` is read from the append-only LEDGER (the permanent record),
        not from closed positions in the working book — so a book reset or a
        recovered file can never blank your realized P&L. Falls back to the
        in-book sum if the ledger is unavailable.
        """
        upnl = sum(p.upnl for p in self._positions if p.status == "OPEN")
        open_value = sum(p.current_value for p in self._positions if p.status == "OPEN")
        try:
            realized, _ = self.ledger.realized(since=self._epoch)
        except Exception:  # noqa: BLE001 - never let audit read break equity
            realized = sum(p.upnl for p in self._positions if p.status == "CLOSED")
        return {
            "cash": round(self._cash, 2),
            "open_value": round(open_value, 2),
            "upnl": round(upnl, 2),
            "realized": round(realized, 2),
            "total": round(self._cash + open_value, 2),
            "starting_cash": round(self._starting_cash, 2),
        }

    def reconcile_from_ledger(self) -> dict:
        """Restore account cash to reflect the permanent realized P&L.

        After a book reset/corruption, cash was wiped to ``starting_cash`` even
        though real closed-trade P&L is recorded in the ledger. Recompute:
        ``cash = starting_cash + ledger_realized - cost of current open book``.
        Idempotent — always derives the same value from the ledger + open
        positions, so it's safe to run more than once."""
        realized, n = self.ledger.realized(since=self._epoch)
        open_cost = sum(p.cost_basis for p in self._positions if p.status == "OPEN")
        self._cash = round(self._starting_cash + realized - open_cost, 4)
        self._save()
        return {"reconciled_realized": round(realized, 2),
                "closed_trades": n, "cash": round(self._cash, 2),
                "equity": self.equity()}

    # ------------------------------------------------------------------ #
    # Marking internals
    # ------------------------------------------------------------------ #
    def _liquidation_value(self, pos: PaperPosition, chain: list[OptionQuote]) -> Optional[float]:
        """What we'd net by closing now (exit fills cross the spread again).

        Returns None if ANY leg has no same-expiry quote in ``chain`` — the
        position can't be honestly priced from this source, so the caller holds
        its last mark instead of fabricating a value from partial/mismatched
        quotes.
        """
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
                return None  # can't price this leg -> caller holds last mark
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
        """Resolve the relevant chain for a position from the quote source.
        A ticker the store doesn't have -> empty chain -> caller holds last mark."""
        if isinstance(source, ChainStore):
            try:
                dates = source.trading_dates(pos.ticker)
                if not dates:
                    return []
                return source.chain(pos.ticker, dates[-1])
            except FileNotFoundError:
                return []
        return [q for q in source if q.ticker.upper() == pos.ticker.upper()]
