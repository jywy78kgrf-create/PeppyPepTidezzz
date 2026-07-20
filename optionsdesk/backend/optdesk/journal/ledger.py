"""
Ledger — the permanent, append-only record of the forward paper test.

The JSON state files (paper.json / autopilot.json) are the *operational*
store: they hold the live book and roll old entries off. This SQLite ledger is
the *audit* store: every fill, mark, promotion, demotion and autopilot event
is written once and never rewritten, so months of forward history survive
restarts, log rollover, and state-file surgery. WAL mode; a single file under
STATE_DIR (already volume-mounted in Docker).

Design rule: the ledger must NEVER break trading. Every public method swallows
its own errors (reported to stderr) — an audit-trail failure is loud but not
fatal.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ..config import STATE_DIR

_SCHEMA = """
CREATE TABLE IF NOT EXISTS marks (
    ts TEXT NOT NULL,
    equity REAL NOT NULL,
    cash REAL NOT NULL,
    upnl REAL NOT NULL,
    open_positions INTEGER NOT NULL DEFAULT 0,
    live INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_marks_ts ON marks(ts);

CREATE TABLE IF NOT EXISTS trades (
    ticker TEXT NOT NULL,
    opened TEXT NOT NULL,
    strategy TEXT NOT NULL,
    config_id TEXT,
    qty INTEGER NOT NULL DEFAULT 1,
    cost_basis REAL NOT NULL,
    legs TEXT NOT NULL,
    closed TEXT,
    close_value REAL,
    pnl REAL,
    close_reason TEXT,
    PRIMARY KEY (ticker, opened)
);

CREATE TABLE IF NOT EXISTS events (
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);

CREATE TABLE IF NOT EXISTS promotions (
    ts TEXT NOT NULL,
    action TEXT NOT NULL,          -- promoted | demoted
    config_id TEXT NOT NULL,
    strategy TEXT NOT NULL,
    tickers TEXT NOT NULL,
    params TEXT NOT NULL,
    holdout_score REAL,
    holdout_return REAL
);
"""


class Ledger:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path or STATE_DIR / "ledger.db")
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        except Exception as exc:  # noqa: BLE001 - audit must not break trading
            self._warn(f"ledger init failed: {exc}")
            self._conn = None

    # ------------------------------------------------------------------ #
    @staticmethod
    def _warn(msg: str) -> None:
        print(f"[ledger] {msg}", file=sys.stderr)

    def _exec(self, sql: str, params: tuple = ()) -> bool:
        if self._conn is None:
            return False
        try:
            with self._lock:
                self._conn.execute(sql, params)
                self._conn.commit()
            return True
        except Exception as exc:  # noqa: BLE001
            self._warn(f"write failed: {exc}")
            return False

    def _query(self, sql: str, params: tuple = ()) -> list[tuple]:
        if self._conn is None:
            return []
        try:
            with self._lock:
                cur = self._conn.execute(sql, params)
                return cur.fetchall()
        except Exception as exc:  # noqa: BLE001
            self._warn(f"query failed: {exc}")
            return []

    # ------------------------------------------------------------------ #
    # Writers (append-only)
    # ------------------------------------------------------------------ #
    def record_mark(self, ts: str, equity: float, cash: float, upnl: float,
                    open_positions: int = 0, live: bool = False) -> None:
        self._exec(
            "INSERT INTO marks (ts, equity, cash, upnl, open_positions, live) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts, float(equity), float(cash), float(upnl),
             int(open_positions), 1 if live else 0))

    def record_open(self, *, ticker: str, opened: str, strategy: str,
                    qty: int, cost_basis: float, legs: list[dict],
                    config_id: Optional[str] = None) -> None:
        self._exec(
            "INSERT OR REPLACE INTO trades "
            "(ticker, opened, strategy, config_id, qty, cost_basis, legs) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ticker.upper(), opened, strategy, config_id, int(qty),
             float(cost_basis), json.dumps(legs, default=str)))

    def record_close(self, *, ticker: str, opened: str, close_value: float,
                     pnl: float, reason: str, closed: Optional[str] = None) -> None:
        self._exec(
            "UPDATE trades SET closed = ?, close_value = ?, pnl = ?, "
            "close_reason = ? WHERE ticker = ? AND opened = ?",
            (closed or datetime.utcnow().isoformat(), float(close_value),
             float(pnl), reason, ticker.upper(), opened))

    def record_event(self, ts: str, kind: str, detail: str) -> None:
        self._exec("INSERT INTO events (ts, kind, detail) VALUES (?, ?, ?)",
                   (ts, kind, detail))

    def record_promotion(self, *, ts: str, action: str, config: dict) -> None:
        self._exec(
            "INSERT INTO promotions (ts, action, config_id, strategy, tickers, "
            "params, holdout_score, holdout_return) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, action, str(config.get("id")), str(config.get("strategy")),
             ",".join(config.get("tickers") or []),
             json.dumps(config.get("params") or {}, default=str),
             config.get("holdout_score"), config.get("holdout_return")))

    # ------------------------------------------------------------------ #
    # Readers
    # ------------------------------------------------------------------ #
    def equity_series(self, limit: int = 100_000,
                      since: Optional[str] = None) -> list[dict]:
        where = "WHERE ts >= ?" if since else ""
        params: tuple = (since, int(limit)) if since else (int(limit),)
        rows = self._query(
            f"SELECT ts, equity, cash, upnl, live FROM marks {where} "
            "ORDER BY ts DESC LIMIT ?", params)
        return [{"ts": r[0], "equity": r[1], "cash": r[2], "upnl": r[3],
                 "live": bool(r[4])} for r in reversed(rows)]

    def trades(self, limit: int = 1000, closed_only: bool = False,
               since: Optional[str] = None) -> list[dict]:
        clauses = []
        params: list = []
        if closed_only:
            clauses.append("closed IS NOT NULL")
        if since:
            clauses.append("opened >= ?")
            params.append(since)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(int(limit))
        rows = self._query(
            f"SELECT ticker, opened, strategy, config_id, qty, cost_basis, "
            f"legs, closed, close_value, pnl, close_reason FROM trades {where} "
            f"ORDER BY opened DESC LIMIT ?", tuple(params))
        out = []
        for r in rows:
            try:
                legs = json.loads(r[6])
            except (TypeError, ValueError):
                legs = []
            out.append({"ticker": r[0], "opened": r[1], "strategy": r[2],
                        "config_id": r[3], "qty": r[4], "cost_basis": r[5],
                        "legs": legs, "closed": r[7], "close_value": r[8],
                        "pnl": r[9], "close_reason": r[10]})
        return out

    def events(self, limit: int = 500) -> list[dict]:
        rows = self._query("SELECT ts, kind, detail FROM events "
                           "ORDER BY ts DESC LIMIT ?", (int(limit),))
        return [{"ts": r[0], "kind": r[1], "detail": r[2]} for r in rows]

    def promotions(self, limit: int = 200) -> list[dict]:
        rows = self._query(
            "SELECT ts, action, config_id, strategy, tickers, params, "
            "holdout_score, holdout_return FROM promotions "
            "ORDER BY ts DESC LIMIT ?", (int(limit),))
        return [{"ts": r[0], "action": r[1], "config_id": r[2], "strategy": r[3],
                 "tickers": r[4].split(",") if r[4] else [],
                 "params": r[5], "holdout_score": r[6], "holdout_return": r[7]}
                for r in rows]

    def realized(self, since: Optional[str] = None) -> tuple[float, int]:
        """Permanent cumulative realized P&L: (sum of closed-trade pnl, count).

        This is the source of truth for realized P&L — it survives book resets
        and file corruption. Optionally filtered to trades opened at/after
        ``since`` (the account epoch)."""
        clauses = ["closed IS NOT NULL", "pnl IS NOT NULL"]
        params: list = []
        if since:
            clauses.append("opened >= ?")
            params.append(since)
        where = "WHERE " + " AND ".join(clauses)
        rows = self._query(
            f"SELECT COALESCE(SUM(pnl), 0), COUNT(*) FROM trades {where}",
            tuple(params))
        if not rows:
            return 0.0, 0
        return float(rows[0][0] or 0.0), int(rows[0][1] or 0)

    def stats(self) -> dict[str, Any]:
        def one(sql: str) -> int:
            rows = self._query(sql)
            return int(rows[0][0]) if rows else 0
        return {
            "marks": one("SELECT COUNT(*) FROM marks"),
            "trades": one("SELECT COUNT(*) FROM trades"),
            "closed_trades": one("SELECT COUNT(*) FROM trades WHERE closed IS NOT NULL"),
            "events": one("SELECT COUNT(*) FROM events"),
            "promotions": one("SELECT COUNT(*) FROM promotions"),
            "path": str(self.path),
            "available": self._conn is not None,
        }


# --------------------------------------------------------------------------- #
# One cached Ledger per db path — the ledger co-locates with whichever state
# dir its writer uses (broker: next to paper.json; pilot: next to
# autopilot.json), so isolated/temp state dirs get isolated ledgers.
_ledgers: dict[str, Ledger] = {}
_singleton_lock = threading.Lock()


def get_ledger(path: Optional[Path] = None) -> Ledger:
    key = str(path or STATE_DIR / "ledger.db")
    with _singleton_lock:
        if key not in _ledgers:
            _ledgers[key] = Ledger(Path(key))
        return _ledgers[key]
