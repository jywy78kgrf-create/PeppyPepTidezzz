"""
AutoPilot — the autonomous loop: research -> promote -> paper-trade -> manage
-> learn from results. PAPER TRADING ONLY: this module drives PaperBroker and
never imports or touches the IBKR adapter.

Safety model (all persisted in STATE_DIR/autopilot.json):
  * KILL SWITCH: ``enabled`` defaults to False; every tick checks it first.
    Disabling takes effect before the next action.
  * CIRCUIT BREAKER: if book equity falls more than ``daily_loss_limit_frac``
    below the day's anchor, the pilot trips, disables itself, and stays off
    until a human re-enables it.
  * BOUNDED ACTIONS: max open positions, max opens per cycle, per-ticker
    cooldown, and the desk's PositionSizer/RiskBudget caps on every open.
  * DEMOTION: a promoted config that keeps losing live (consecutive losing
    closes) is demoted — realized results feed back into what gets traded.

Decisions are made on the latest end-of-day chain (the same semantics the
backtester is validated under); live Alpha Vantage quotes are used to mark and
manage open positions.
"""
from __future__ import annotations

import json
import math
import threading
import traceback
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from ..config import SETTINGS, STATE_DIR
from ..contracts import StrategySpec
from ..data.loader import ChainStore
from ..risk import PositionSizer, RiskBudget, RiskConfig, unit_risk_for

ACTIVITY_CAP = 200


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class AutoConfig:
    """Autopilot knobs. Conservative by default — this is a probe, not a bot
    trying to look busy."""
    trade_interval_min: int = 5          # manage/open cadence
    research_interval_hr: float = 6.0    # how often a research batch runs
    research_batch_tickers: int = 6      # tickers per research batch
    learn_iters: int = 6                 # learning-loop iterations per batch
    lookback_days: int = 540             # history window for research

    # promotion bar
    min_holdout_score: float = 0.30      # objective (sortino) on the holdout
    require_positive_holdout_return: bool = True
    min_holdout_trades: int = 8          # fewer trades = promotion on noise
    max_holdout_drawdown: float = 0.15   # reject configs that cratered in holdout
    max_promoted: int = 5

    # entry edge: short premium only when implied > realized vol (VRP > 0)
    require_vrp_for_short_premium: bool = True

    # never sell premium through an earnings report (the classic blowup).
    # Fail-open: if the calendar can't be fetched, entries are NOT blocked.
    avoid_earnings_short_premium: bool = True
    earnings_buffer_days: int = 1        # also avoid reports just past expiry

    # trading guardrails
    max_open_positions: int = 5
    max_opens_per_cycle: int = 2
    ticker_cooldown_hr: float = 24.0
    profit_target: float = 0.50          # fraction of max profit to capture
    stop_mult: float = 1.0               # stop at 1x total position risk
    close_dte: int = 7

    # self-protection
    daily_loss_limit_frac: float = 0.03  # trip breaker at -3% on the day
    demote_after_losses: int = 3         # consecutive losing closes -> demote


def _env_config() -> AutoConfig:
    """Default AutoConfig with .env overrides for the knobs people actually
    tune, so cadence/limits changes don't require a code edit + rebuild."""
    import os
    cfg = AutoConfig()

    def _num(name: str, current, cast):
        raw = os.getenv(name)
        if raw:
            try:
                return cast(raw)
            except ValueError:
                pass
        return current

    cfg.research_interval_hr = _num("AUTO_RESEARCH_HR", cfg.research_interval_hr, float)
    cfg.trade_interval_min = _num("AUTO_TRADE_MIN", cfg.trade_interval_min, int)
    cfg.daily_loss_limit_frac = _num("AUTO_DAY_LOSS_FRAC", cfg.daily_loss_limit_frac, float)
    cfg.min_holdout_score = _num("AUTO_MIN_HOLDOUT", cfg.min_holdout_score, float)
    cfg.max_open_positions = _num("AUTO_MAX_OPEN", cfg.max_open_positions, int)
    return cfg


# --------------------------------------------------------------------------- #
# AutoPilot
# --------------------------------------------------------------------------- #
class AutoPilot:
    """One instance per process; drive it with ``tick(now)`` (the scheduler
    thread does this every ~30s) or call the phases directly in tests."""

    def __init__(
        self,
        store: Optional[ChainStore] = None,
        settings=SETTINGS,
        config: Optional[AutoConfig] = None,
        state_path: Optional[Path] = None,
        broker_factory: Optional[Callable] = None,
        av_factory: Optional[Callable] = None,
        learn_fn: Optional[Callable] = None,
        now_fn: Callable[[], datetime] = datetime.utcnow,
    ) -> None:
        self.settings = settings
        self.cfg = config or _env_config()
        self.now_fn = now_fn
        # _lock guards STATE mutations only and is never held across a long
        # operation (a research batch runs for minutes) — the kill switch must
        # respond instantly. _tick_gate serializes tick bodies instead (the
        # heartbeat thread and an enable-kicked thread must not overlap).
        self._lock = threading.RLock()
        self._tick_gate = threading.Lock()
        self._store = store
        self._state_path = Path(state_path or STATE_DIR / "autopilot.json")
        self._broker_factory = broker_factory or self._default_broker_factory
        self._av_factory = av_factory or self._default_av_factory
        self._learn_fn = learn_fn  # (strategy, tickers, start, end) -> result dict
        self._state = self._load()
        # earnings calendar cache: (fetch_date, {SYMBOL: [iso dates]} | None)
        self._earnings_cache: tuple[Optional[date], Optional[dict]] = (None, None)
        # live research telemetry — ephemeral (never persisted), read by the
        # UI's engine view. Guarded by _lock; writes are all short.
        self._research_live: dict = {"active": False}
        self._research_last: Optional[dict] = None

    # ------------------------------------------------------------------ #
    # Lazy default dependencies (kept out of __init__ so tests never touch them)
    # ------------------------------------------------------------------ #
    def _default_broker_factory(self):
        from ..paper.broker import PaperBroker
        return PaperBroker(starting_cash=self.settings.starting_capital)

    def _default_av_factory(self):
        from ..live.alpha_vantage import AlphaVantage
        return AlphaVantage()

    @property
    def store(self) -> ChainStore:
        if self._store is None:
            self._store = ChainStore()
        return self._store

    def _learn(self, strategy: str, tickers: list[str], start: date, end: date,
               on_iter: Optional[Callable] = None) -> dict:
        if self._learn_fn is not None:
            # injected stubs (tests) keep the plain 4-arg signature
            return self._learn_fn(strategy, tickers, start, end)
        from ..learn.loop import LearningLoop
        return LearningLoop(self.store, self.settings).run(
            strategy, tickers, start, end,
            n_iter=self.cfg.learn_iters, objective="sortino", seed=11,
            on_iter=on_iter,
        )

    def _on_research_iter(self, it) -> None:
        """LearningLoop callback: append one iteration to live telemetry."""
        metrics = getattr(it, "metrics", None) or {}
        rec = {
            "iteration": getattr(it, "iteration", None),
            "oos_score": getattr(it, "oos_score", None),
            "is_score": getattr(it, "is_score", None),
            "accepted": bool(getattr(it, "accepted", False)),
            "n_trades": metrics.get("n_trades"),
            "at": self.now_fn().isoformat(),
        }
        with self._lock:
            if self._research_live.get("active"):
                self._research_live.setdefault("iterations", []).append(rec)

    def research_status(self) -> dict:
        """Snapshot of what the research engine is doing right now — the
        UI's window into the number-crunching. Cheap; lock held briefly."""
        import math

        from ..strategies.library import STRATEGIES

        try:
            n_universe = len(self.store.tickers())
        except Exception:  # noqa: BLE001 - telemetry must never raise
            n_universe = 0
        per = max(1, self.cfg.research_batch_tickers)
        sweep_total = (len(STRATEGIES) * math.ceil(n_universe / per)
                       if n_universe else 0)
        now = self.now_fn()
        with self._lock:
            cur = dict(self._research_live)
            cur["iterations"] = [dict(r) for r in cur.get("iterations", [])]
            last = dict(self._research_last) if self._research_last else None
            cursor = int(self._state["research_cursor"])
            enabled = bool(self._state["enabled"])
        if cur.get("active") and cur.get("started_at"):
            try:
                started = datetime.fromisoformat(cur["started_at"])
                cur["elapsed_s"] = round((now - started).total_seconds(), 1)
            except ValueError:
                cur["elapsed_s"] = None
        cur["trades_simulated"] = int(
            sum(r.get("n_trades") or 0 for r in cur["iterations"]))
        return {
            "enabled": enabled,
            "current": cur,
            "last": last,
            "batches_done": cursor,
            "sweep_total": sweep_total,
            "sweep_done": (cursor % sweep_total) if sweep_total else 0,
            "sweep_number": (cursor // sweep_total + 1) if sweep_total else 0,
        }

    # ------------------------------------------------------------------ #
    # State
    # ------------------------------------------------------------------ #
    def _fresh_state(self) -> dict:
        return {
            "enabled": False,
            "activated_at": None,
            "last_trade_cycle": None,
            "last_research": None,
            "research_cursor": 0,
            "promoted": [],       # [{id,strategy,tickers,params,holdout_score,...}]
            "managed": {},        # pos_key -> management record
            "last_opened": {},    # ticker -> iso ts (cooldown)
            "day_anchor": None,   # {"date": iso, "equity": float}
            "breaker": {"tripped": False, "reason": None, "at": None},
            "activity": [],
        }

    def _load(self) -> dict:
        try:
            if self._state_path.exists():
                data = json.loads(self._state_path.read_text())
                base = self._fresh_state()
                base.update({k: v for k, v in data.items() if k in base})
                return base
        except (json.JSONDecodeError, OSError):
            pass
        return self._fresh_state()

    def _save(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, indent=1, default=str))
        tmp.replace(self._state_path)

    def _log(self, kind: str, detail: str) -> None:
        ts = self.now_fn().isoformat()
        self._state["activity"].append({"ts": ts, "kind": kind, "detail": detail})
        self._state["activity"] = self._state["activity"][-ACTIVITY_CAP:]
        try:  # in-memory feed rolls at ACTIVITY_CAP; the ledger keeps it all
            from ..journal import get_ledger
            get_ledger(self._state_path.parent / "ledger.db").record_event(
                ts, kind, detail)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ #
    # Kill switch
    # ------------------------------------------------------------------ #
    def enable(self) -> dict:
        with self._lock:
            self._state["enabled"] = True
            self._state["activated_at"] = self.now_fn().isoformat()
            self._state["breaker"] = {"tripped": False, "reason": None, "at": None}
            self._state["day_anchor"] = None  # re-anchor on next cycle
            self._log("enable", "autopilot ENGAGED (kill switch armed)")
            self._save()
            return self.status()

    def disable(self, reason: str = "kill switch") -> dict:
        with self._lock:
            self._state["enabled"] = False
            self._log("disable", f"autopilot DISENGAGED — {reason}")
            self._save()
            return self.status()

    def status(self) -> dict:
        with self._lock:
            s = self._state
            return {
                "enabled": s["enabled"],
                "activated_at": s["activated_at"],
                "last_trade_cycle": s["last_trade_cycle"],
                "last_research": s["last_research"],
                "breaker": dict(s["breaker"]),
                "promoted": [dict(p) for p in s["promoted"]],
                "managed_positions": len(s["managed"]),
                "config": asdict(self.cfg),
            }

    def activity(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return list(reversed(self._state["activity"][-limit:]))

    # ------------------------------------------------------------------ #
    # Scheduler entry point
    # ------------------------------------------------------------------ #
    def tick(self, now: Optional[datetime] = None) -> None:
        """One scheduler heartbeat. Cheap when nothing is due. Never raises —
        errors are logged to the activity feed so the loop survives.

        Non-reentrant: a tick already in progress (e.g. a long research batch)
        makes concurrent ticks no-ops. The state lock is only taken for short
        reads/writes, so enable/disable/status NEVER wait on a running batch.
        """
        if not self._tick_gate.acquire(blocking=False):
            return
        try:
            now = now or self.now_fn()
            with self._lock:
                if not self._state["enabled"] or self._state["breaker"]["tripped"]:
                    return
                research_due = self._due(
                    self._state["last_research"],
                    timedelta(hours=self.cfg.research_interval_hr), now)
            if research_due:
                self.run_research_batch(now)
            with self._lock:
                if not self._state["enabled"]:  # killed mid-research
                    return
                trade_due = self._due(
                    self._state["last_trade_cycle"],
                    timedelta(minutes=self.cfg.trade_interval_min), now)
            if trade_due:
                self.run_trade_cycle(now)
        except Exception as exc:  # noqa: BLE001 - the loop must survive
            with self._lock:
                self._log("error", f"{type(exc).__name__}: {exc}")
                self._save()
            traceback.print_exc()
        finally:
            self._tick_gate.release()

    @staticmethod
    def _due(last_iso: Optional[str], interval: timedelta, now: datetime) -> bool:
        if last_iso is None:
            return True
        try:
            return now - datetime.fromisoformat(last_iso) >= interval
        except ValueError:
            return True

    # ------------------------------------------------------------------ #
    # Phase 1: research -> promotion
    # ------------------------------------------------------------------ #
    def run_research_batch(self, now: Optional[datetime] = None) -> Optional[dict]:
        """Run the learning loop on the next (strategy, ticker-batch) in the
        rotation; promote the config if its HOLDOUT clears the bar."""
        from ..strategies.library import STRATEGIES

        now = now or self.now_fn()
        universe = self.store.tickers()
        with self._lock:
            if not universe:
                self._state["last_research"] = now.isoformat()
                self._log("research", "no data in store; skipped")
                self._save()
                return None

            strategies = sorted(STRATEGIES)
            cursor = int(self._state["research_cursor"])
            strategy = strategies[cursor % len(strategies)]
            n = max(1, self.cfg.research_batch_tickers)
            t0 = (cursor // len(strategies)) * n % max(1, len(universe))
            batch = (universe + universe)[t0:t0 + n][: len(universe)]
            self._state["research_cursor"] = cursor + 1
            self._state["last_research"] = now.isoformat()

            # history window: last lookback_days ending at the latest date
            all_dates = sorted({d for tk in batch
                                for d in self.store.trading_dates(tk)})
            if len(all_dates) < 40:
                self._log("research", f"{strategy} on {batch}: not enough history")
                self._save()
                return None
            end = all_dates[-1]
            start = max(all_dates[0], end - timedelta(days=self.cfg.lookback_days))
            self._log("research", f"learning {strategy} on {','.join(batch)} "
                                  f"({start} -> {end})")
            started = self.now_fn()
            # arm live telemetry for the engine view
            self._research_live = {
                "active": True,
                "strategy": strategy,
                "tickers": batch,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "started_at": started.isoformat(),
                "n_iter": int(self.cfg.learn_iters),
                "iterations": [],
            }
            self._save()

        # the long part runs WITHOUT the state lock: kill switch stays live
        result: Optional[dict] = None
        try:
            result = self._learn(strategy, batch, start, end,
                                 on_iter=self._on_research_iter)
        finally:
            finished = self.now_fn()
            with self._lock:
                iters = list(self._research_live.get("iterations") or [])
                self._research_last = {
                    "strategy": strategy,
                    "tickers": batch,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "holdout_score": ((result or {}).get("holdout")
                                      or {}).get("score"),
                    "trials": (result or {}).get("trials"),
                    "iterations": len(iters),
                    "trades_simulated": int(
                        sum(r.get("n_trades") or 0 for r in iters)),
                    "duration_s": round(
                        (finished - started).total_seconds(), 1),
                    "finished_at": finished.isoformat(),
                    "verdict": None,
                }
                self._research_live = {"active": False}

        holdout = (result or {}).get("holdout") or {}
        score = holdout.get("score")
        summary = holdout.get("summary") or {}
        h_return = summary.get("total_return")
        h_trades = summary.get("n_trades")
        h_dd = summary.get("max_drawdown")

        reasons: list[str] = []
        if score is None or score < self.cfg.min_holdout_score:
            reasons.append(f"score={score}")
        if self.cfg.require_positive_holdout_return and not (
                h_return is not None and h_return > 0):
            reasons.append(f"return={h_return}")
        if h_trades is not None and h_trades < self.cfg.min_holdout_trades:
            reasons.append(f"trades={h_trades}<{self.cfg.min_holdout_trades}")
        if h_dd is not None and abs(h_dd) > self.cfg.max_holdout_drawdown:
            reasons.append(f"maxdd={h_dd}")
        if reasons:
            with self._lock:
                if self._research_last:
                    self._research_last["verdict"] = (
                        "rejected: " + ", ".join(reasons))
                self._log("research", f"{strategy}: NOT promoted "
                                      f"({', '.join(reasons)})")
                self._save()
            return None

        entry = {
            "id": f"{strategy}@{now.strftime('%Y%m%d%H%M%S')}",
            "strategy": strategy,
            "tickers": batch,
            "params": result.get("best_params") or {},
            "holdout_score": round(float(score), 4),
            "holdout_return": round(float(h_return), 4) if h_return is not None else None,
            "promoted_at": now.isoformat(),
            "realized_pnl": 0.0,
            "closed_trades": 0,
            "consecutive_losses": 0,
            "active": True,
        }
        with self._lock:
            promoted = [p for p in self._state["promoted"]
                        if not (p["strategy"] == strategy
                                and set(p["tickers"]) == set(batch))]
            promoted.append(entry)
            promoted.sort(key=lambda p: p["holdout_score"], reverse=True)
            self._state["promoted"] = promoted[: self.cfg.max_promoted]
            if self._research_last:
                self._research_last["verdict"] = "promoted"
            self._log("promote", f"{strategy} holdout={entry['holdout_score']} "
                                 f"ret={entry['holdout_return']} on {','.join(batch)}")
            try:
                from ..journal import get_ledger
                get_ledger(self._state_path.parent / "ledger.db").record_promotion(
                    ts=now.isoformat(), action="promoted", config=entry)
            except Exception:  # noqa: BLE001
                pass
            self._save()
        return entry

    # ------------------------------------------------------------------ #
    # Phase 2: trade cycle — mark, protect, manage exits, open
    # ------------------------------------------------------------------ #
    def run_trade_cycle(self, now: Optional[datetime] = None) -> None:
        now = now or self.now_fn()
        broker = self._broker_factory()

        # 1) mark the book (live when AV resolves, EOD otherwise) — network
        #    I/O stays OUTSIDE the state lock so the kill switch never waits.
        try:
            mark = broker.mark_live(self._av_factory(), self.store)
            live = bool(mark.get("live"))
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._log("error", f"mark failed: {exc}")
            live = False
        try:
            broker.snapshot(live=live)
        except Exception:  # noqa: BLE001
            pass

        equity = broker.equity()
        total = float(equity.get("total", 0.0))

        with self._lock:
            if not self._state["enabled"]:  # killed while marking
                return
            self._trade_cycle_locked(broker, now, total)

    def _trade_cycle_locked(self, broker, now: datetime, total: float) -> None:
        """Breaker check, exits, and opens — fast, under the state lock."""

        # 2) circuit breaker on the day's anchor
        today = now.date().isoformat()
        anchor = self._state.get("day_anchor")
        if not anchor or anchor.get("date") != today:
            anchor = {"date": today, "equity": total}
            self._state["day_anchor"] = anchor
        limit = float(anchor["equity"]) * (1.0 - self.cfg.daily_loss_limit_frac)
        if total < limit and float(anchor["equity"]) > 0:
            self._state["breaker"] = {
                "tripped": True,
                "reason": (f"day loss limit: equity {total:,.0f} < "
                           f"{limit:,.0f} ({self.cfg.daily_loss_limit_frac:.0%} "
                           f"below day anchor {float(anchor['equity']):,.0f})"),
                "at": now.isoformat(),
            }
            self._state["enabled"] = False
            self._log("breaker", self._state["breaker"]["reason"])
            self._state["last_trade_cycle"] = now.isoformat()
            self._save()
            return

        # 3) manage exits on autopilot-owned positions
        positions = broker.positions()
        for idx, pos in enumerate(positions):
            if pos.status != "OPEN":
                continue
            key = self._pos_key(pos)
            m = self._state["managed"].get(key)
            if not m:
                continue  # user-opened; never touch
            reason = self._exit_reason(pos, m, now)
            if reason is None:
                continue
            try:
                closed = broker.close(idx, reason=reason)
            except TypeError:  # broker without reason support (fakes)
                closed = broker.close(idx)
            except Exception as exc:  # noqa: BLE001
                self._log("error", f"close {pos.ticker} failed: {exc}")
                continue
            self._log("close", f"{pos.ticker} {pos.spec_name} -> {reason} "
                               f"pnl={closed.upnl:+.2f}")
            self._settle_config(m.get("config_id"), closed.upnl)
            self._state["managed"].pop(key, None)

        # 4) open new positions from promoted configs
        self._open_from_promoted(broker, now, total)

        self._state["last_trade_cycle"] = now.isoformat()
        self._save()

    # ------------------------------------------------------------------ #
    def _open_from_promoted(self, broker, now: datetime, equity_total: float) -> None:
        from ..strategies.library import STRATEGIES

        open_positions = [p for p in broker.positions() if p.status == "OPEN"]
        slots = self.cfg.max_open_positions - len(open_positions)
        opens_left = min(self.cfg.max_opens_per_cycle, max(0, slots))
        if opens_left <= 0:
            return

        gate = self._build_gate()
        rc = RiskConfig(max_concurrent=self.cfg.max_open_positions)
        sizer = PositionSizer(rc)
        budget = RiskBudget(rc, self._sector_map())
        held = {p.ticker.upper() for p in open_positions}
        shims = [_RiskShim(p, self._state["managed"].get(self._pos_key(p)))
                 for p in open_positions]

        for config in [p for p in self._state["promoted"] if p.get("active")]:
            if opens_left <= 0:
                break
            builder = STRATEGIES.get(config["strategy"])
            if builder is None:
                continue
            for tk in config["tickers"]:
                if opens_left <= 0:
                    break
                tku = tk.upper()
                if tku in held or self._on_cooldown(tku, now):
                    continue
                try:
                    dates = self.store.trading_dates(tku)
                    if not dates:
                        continue
                    asof = dates[-1]
                    chain = self.store.chain(tku, asof)
                    if not chain:
                        continue
                    if gate is not None and not gate.allow(tku, asof, config["strategy"]):
                        continue
                    if not self._vrp_ok(chain, tku, asof, config["strategy"]):
                        continue
                    underlying = next((q.underlying for q in chain if q.underlying > 0), 0.0)
                    spec = builder(chain, underlying, dict(config.get("params") or {}))
                    if spec is None:
                        continue
                    spec.meta["config_id"] = config["id"]  # ledger attribution
                    min_expiry = min(leg.expiry for leg in spec.legs)
                    if not self._earnings_ok(tku, min_expiry,
                                             config["strategy"], now):
                        self._log("skip", f"{tku} {config['strategy']}: earnings "
                                          f"report inside holding window")
                        continue
                    unit_risk = unit_risk_for(spec, equity_total, rc)
                    desired = sizer.desired_contracts(spec, equity_total, unit_risk)
                    qty = budget.fit(spec, desired, unit_risk, equity_total, shims)
                    if qty < 1:
                        continue
                    pos = broker.open(spec, chain, qty=qty)
                except Exception as exc:  # noqa: BLE001
                    self._log("error", f"open {tku} {config['strategy']} failed: {exc}")
                    continue

                m = self._management_record(spec, qty, unit_risk, config["id"])
                self._state["managed"][self._pos_key(pos)] = m
                self._state["last_opened"][tku] = now.isoformat()
                held.add(tku)
                shims.append(_RiskShim(pos, m))
                opens_left -= 1
                self._log("open", f"{tku} {spec.name} x{qty} "
                                  f"(risk ${unit_risk * qty:,.0f}, "
                                  f"config {config['strategy']} "
                                  f"holdout={config['holdout_score']})")

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _pos_key(pos) -> str:
        opened = pos.opened.isoformat() if hasattr(pos.opened, "isoformat") else str(pos.opened)
        return f"{pos.ticker.upper()}|{opened}"

    def _management_record(self, spec: StrategySpec, qty: int, unit_risk: float,
                           config_id: str) -> dict:
        total_risk = unit_risk * qty
        mp = spec.max_profit
        max_profit_total = (mp * qty) if (mp is not None and math.isfinite(mp) and mp > 0) \
            else total_risk
        min_expiry = min(leg.expiry for leg in spec.legs)
        return {
            "config_id": config_id,
            "target_upnl": round(self.cfg.profit_target * max_profit_total, 2),
            "stop_upnl": round(-self.cfg.stop_mult * total_risk, 2),
            "close_by": (min_expiry - timedelta(days=self.cfg.close_dte)).isoformat(),
            "expiry": min_expiry.isoformat(),
            "unit_risk": round(unit_risk, 2),
            "contracts": qty,
        }

    def _exit_reason(self, pos, m: dict, now: datetime) -> Optional[str]:
        today = now.date()
        try:
            if today >= date.fromisoformat(m["expiry"]):
                return "expiry"
            if today >= date.fromisoformat(m["close_by"]):
                return "close_dte"
        except (KeyError, ValueError):
            pass
        if pos.upnl >= m.get("target_upnl", float("inf")):
            return "target"
        if pos.upnl <= m.get("stop_upnl", float("-inf")):
            return "stop"
        return None

    def _settle_config(self, config_id: Optional[str], pnl: float) -> None:
        """Feed a realized close back into its config; demote persistent losers."""
        for cfgp in self._state["promoted"]:
            if cfgp["id"] != config_id:
                continue
            cfgp["realized_pnl"] = round(cfgp.get("realized_pnl", 0.0) + pnl, 2)
            cfgp["closed_trades"] = cfgp.get("closed_trades", 0) + 1
            if pnl < 0:
                cfgp["consecutive_losses"] = cfgp.get("consecutive_losses", 0) + 1
                if cfgp["consecutive_losses"] >= self.cfg.demote_after_losses:
                    cfgp["active"] = False
                    try:
                        from ..journal import get_ledger
                        get_ledger(self._state_path.parent / "ledger.db"
                                   ).record_promotion(
                            ts=self.now_fn().isoformat(), action="demoted",
                            config=cfgp)
                    except Exception:  # noqa: BLE001
                        pass
                    self._log("demote", f"{cfgp['strategy']} demoted after "
                                        f"{cfgp['consecutive_losses']} consecutive "
                                        f"losing closes (realized "
                                        f"{cfgp['realized_pnl']:+.2f})")
            else:
                cfgp["consecutive_losses"] = 0
            return

    def _on_cooldown(self, ticker: str, now: datetime) -> bool:
        last = self._state["last_opened"].get(ticker)
        if not last:
            return False
        try:
            return now - datetime.fromisoformat(last) < timedelta(
                hours=self.cfg.ticker_cooldown_hr)
        except ValueError:
            return False

    _SHORT_PREMIUM = frozenset({"bull_put_spread", "bear_call_spread",
                                "iron_condor", "covered_call", "short_straddle"})

    def _vrp_ok(self, chain, ticker: str, asof, strategy: str) -> bool:
        """Short premium requires a positive volatility risk premium (ATM IV >
        trailing realized vol). Pass-through when VRP can't be computed or the
        strategy isn't short premium."""
        if not self.cfg.require_vrp_for_short_premium:
            return True
        if strategy not in self._SHORT_PREMIUM:
            return True
        try:
            from ..signals.equity import vrp
            v = vrp(chain, ticker, asof)
        except ImportError:
            return True
        return True if v is None else v > 0.0

    def _earnings_map(self, now: datetime) -> Optional[dict]:
        """Upcoming report dates, fetched at most once per day; None on any
        failure (callers fail OPEN — an unknowable calendar blocks nothing)."""
        today = now.date()
        cached_day, cached = self._earnings_cache
        if cached_day == today:
            return cached
        result: Optional[dict] = None
        try:
            from ..live.alpha_vantage import fetch_earnings_calendar
            data = fetch_earnings_calendar(self._av_factory())
            if "earnings" in data:
                result = data["earnings"]
            else:
                self._log("research", f"earnings calendar unavailable "
                                      f"({data.get('error', 'unknown')[:80]}); "
                                      f"gate failing open")
        except Exception:  # noqa: BLE001 - never let the gate break a cycle
            result = None
        self._earnings_cache = (today, result)
        return result

    def _earnings_ok(self, ticker: str, expiry: date, strategy: str,
                     now: datetime) -> bool:
        """False when a short-premium entry would hold through an earnings
        report (today .. expiry + buffer). Long premium is unaffected —
        buying vol into earnings is a choice, not a blowup."""
        if not self.cfg.avoid_earnings_short_premium:
            return True
        if strategy not in self._SHORT_PREMIUM:
            return True
        cal = self._earnings_map(now)
        if not cal:
            return True  # fail open
        dates = cal.get(ticker.upper()) or []
        lo = now.date()
        hi = expiry + timedelta(days=self.cfg.earnings_buffer_days)
        for d in dates:
            try:
                rd = date.fromisoformat(d)
            except ValueError:
                continue
            if lo <= rd <= hi:
                return False
        return True

    def _build_gate(self):
        try:
            from ..signals.equity import build_default_gate
            return build_default_gate(self.store.tickers(), {})
        except ImportError:
            return None

    def _sector_map(self) -> dict:
        u = self.store.universe
        out: dict = {}
        try:
            if u is not None and not u.empty and "sector" in u and "ticker" in u:
                for _, row in u.iterrows():
                    if isinstance(row.get("ticker"), str):
                        out[row["ticker"].upper()] = str(row.get("sector") or "UNKNOWN")
        except Exception:  # noqa: BLE001
            pass
        return out


@dataclass(slots=True)
class _RiskShim:
    """Adapter so RiskBudget can read paper positions like engine positions."""
    _pos: object = field(repr=False)
    _managed: Optional[dict] = field(default=None, repr=False)

    @property
    def capital_at_risk(self) -> float:
        m = self._managed or {}
        if m.get("unit_risk") and m.get("contracts"):
            return float(m["unit_risk"]) * int(m["contracts"])
        return abs(float(getattr(self._pos, "cost_basis", 0.0)))

    @property
    def spec(self):
        pos = self._pos
        return type("S", (), {"ticker": pos.ticker})()


# --------------------------------------------------------------------------- #
# Process-wide singleton + scheduler thread
# --------------------------------------------------------------------------- #
_pilot: Optional[AutoPilot] = None
_thread: Optional[threading.Thread] = None
_singleton_lock = threading.Lock()


def get_pilot() -> AutoPilot:
    """Return the process singleton, starting the heartbeat thread once."""
    global _pilot, _thread
    with _singleton_lock:
        if _pilot is None:
            _pilot = AutoPilot()
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_heartbeat, name="autopilot",
                                       daemon=True)
            _thread.start()
    return _pilot


def _heartbeat() -> None:
    import time
    while True:
        time.sleep(30)
        p = _pilot
        if p is not None:
            p.tick()
