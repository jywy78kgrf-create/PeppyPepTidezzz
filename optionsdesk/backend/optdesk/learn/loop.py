"""
Recursive walk-forward learning loop.

The loop searches a strategy's parameter space using a small evolutionary /
bandit hybrid: it exploits the best-known parameters (mutating them with a
shrinking step) and explores neighbours, scoring every candidate on an
in-sample (IS) fold and *validating* on an out-of-sample (OOS) fold.  A
candidate is accepted only when it improves the OOS objective, which is what
makes the loop a genuine self-improvement process rather than a random sweep.

The search space is derived from the strategy's library defaults; we perturb
numeric defaults within sensible bounds.  Everything is seeded for
determinism.
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta
from typing import Any, Callable, Optional

from ..backtest.engine import Backtester
from ..config import SETTINGS, Settings
from ..contracts import BacktestResult, LearnIteration
from ..data.loader import ChainStore, EquityStore
from ..strategies.library import STRATEGIES

_TRADING_DAYS_PER_YEAR = 252

# Objective key -> field on BacktestMetrics (higher is better for all of these).
# Note: the engine reports max_drawdown as a NEGATIVE number (peak-to-trough
# fraction), so calmar must divide by its magnitude — dividing by the signed
# value (or gating on ``> 0``) silently degrades calmar to plain CAGR.
_OBJECTIVES: dict[str, Callable[[Any], float]] = {
    "sortino": lambda m: m.sortino,
    "sharpe": lambda m: m.sharpe,
    "cagr": lambda m: m.cagr,
    "total_return": lambda m: m.total_return,
    "profit_factor": lambda m: m.profit_factor,
    "calmar": lambda m: (m.cagr / abs(m.max_drawdown)) if abs(m.max_drawdown) > 1e-12 else m.cagr,
}

# Fraction of the full date range reserved as a final, untouched holdout.
# The evolutionary loop accepts candidates on repeated peeks at the same OOS
# window, so ``best_params`` are themselves selected on OOS — reporting that
# OOS score as "out of sample" overstates it.  The holdout is never evaluated
# during the search; ``best_params`` are scored on it exactly once at the end.
_HOLDOUT_FRAC = 0.15

# Default search space: (low, high, is_int) per known parameter name.  Unknown
# numeric params are perturbed multiplicatively around their default.
_PARAM_BOUNDS: dict[str, tuple[float, float, bool]] = {
    "dte_target": (7.0, 120.0, True),
    "dte_min": (3.0, 90.0, True),
    "dte_max": (14.0, 180.0, True),
    "close_dte": (0.0, 30.0, True),
    "delta_target": (0.05, 0.45, False),
    "short_delta": (0.05, 0.45, False),
    "long_delta": (0.02, 0.40, False),
    "width": (1.0, 50.0, False),
    "wing_width": (1.0, 50.0, False),
    "profit_target": (0.2, 0.9, False),
    "stop_mult": (1.0, 4.0, False),
    "stop_loss": (1.0, 4.0, False),
    "min_pop": (0.3, 0.9, False),
    "min_edge": (0.0, 1.0, False),
    "min_oi": (0.0, 5000.0, True),
    "min_volume": (0.0, 2000.0, True),
}


class LearningLoop:
    """Walk-forward evolutionary parameter search over a single strategy."""

    def __init__(self, store: ChainStore, settings: Settings = SETTINGS,
                 equity_store: Optional[EquityStore] = None) -> None:
        self.store = store
        self.settings = settings
        self._bt = Backtester(store, settings=settings)
        # Injectable for tests; None -> the shared data/equity Parquet store
        # (resolved lazily so a missing equity dir just disables regimes).
        self._equity = equity_store

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def run(
        self,
        strategy_name: str,
        tickers: list[str],
        start: date,
        end: date,
        n_iter: int = 12,
        objective: str = "sortino",
        seed: int = 7,
        on_iter: Optional[Callable[[LearnIteration], None]] = None,
    ) -> dict:
        """Run the walk-forward search and return best params + history.

        Returns ``{"best_params", "history": [LearnIteration...], "best":
        BacktestResult.to_summary()}`` plus (additive) ``"holdout"``: the final
        ~15% of ``[start, end]`` is reserved before the search begins, never
        evaluated during it, and ``best_params`` are scored on it exactly once
        at the end — a defensible out-of-sample estimate, unlike the search's
        own OOS window which is peeked at every iteration.

        Also (additive) ``"regimes"``: the best-params run's equity-curve days
        classified into low/mid/high realized-vol terciles (average rv20
        across the run's tickers; terciles over the run's own range) with
        per-regime ``{days, total_return, sharpe, max_drawdown}`` — or None
        when no equity data covers the run.
        """
        if strategy_name not in STRATEGIES:
            raise ValueError(f"unknown strategy {strategy_name!r}")
        score_of = _OBJECTIVES.get(objective)
        if score_of is None:
            raise ValueError(f"unknown objective {objective!r}")

        rng = random.Random(seed)
        search_start, search_end, holdout_start, holdout_end = self._holdout_split(start, end)
        is_start, is_end, oos_start, oos_end = self._fold(search_start, search_end)

        base_params = self._default_params(strategy_name)
        bounds = self._space(base_params)

        history: list[LearnIteration] = []

        # --- iteration 0: evaluate the library defaults (the incumbent) ----
        best_params = dict(base_params)
        best_is = self._backtest(strategy_name, best_params, tickers, is_start, is_end)
        best_oos = self._backtest(strategy_name, best_params, tickers, oos_start, oos_end)
        best_oos_score = score_of(best_oos.metrics)
        best_oos_result = best_oos

        it0 = LearnIteration(
            iteration=0,
            strategy=strategy_name,
            params=dict(best_params),
            oos_score=round(best_oos_score, 4),
            is_score=round(score_of(best_is.metrics), 4),
            metrics=best_oos.to_summary(),
            accepted=True,
            note="baseline (library defaults)",
        )
        history.append(it0)
        if on_iter is not None:
            on_iter(it0)

        # --- evolutionary search ------------------------------------------
        for i in range(1, max(1, n_iter)):
            frac = i / max(1, n_iter - 1)          # 0 -> 1 over the run
            temperature = max(0.08, 1.0 - 0.85 * frac)   # shrink step over time
            explore = rng.random() < (0.35 + 0.25 * (1.0 - frac))  # explore early

            if explore:
                cand = self._explore(bounds, rng)
                note = "explore"
            else:
                cand = self._mutate(best_params, bounds, temperature, rng)
                note = "exploit"

            is_res = self._backtest(strategy_name, cand, tickers, is_start, is_end)
            oos_res = self._backtest(strategy_name, cand, tickers, oos_start, oos_end)
            is_score = score_of(is_res.metrics)
            oos_score = score_of(oos_res.metrics)

            # Accept only on genuine OOS improvement (with a tiny epsilon so we
            # do not churn on numerical noise).
            accepted = oos_score > best_oos_score + 1e-9 and math.isfinite(oos_score)
            if accepted:
                best_params = dict(cand)
                best_oos_score = oos_score
                best_oos_result = oos_res
                note += " | accepted (OOS improved)"
            else:
                note += " | rejected"

            it = LearnIteration(
                iteration=i,
                strategy=strategy_name,
                params=dict(cand),
                oos_score=round(oos_score, 4),
                is_score=round(is_score, 4),
                metrics=oos_res.to_summary(),
                accepted=accepted,
                note=note,
            )
            history.append(it)
            if on_iter is not None:
                on_iter(it)

        # --- final holdout evaluation (search is over; peek exactly once) ---
        if holdout_start is not None and holdout_end is not None:
            h_res = self._backtest(strategy_name, best_params, tickers,
                                   holdout_start, holdout_end)
            h_score = score_of(h_res.metrics)
            holdout = {
                "start": holdout_start.isoformat(),
                "end": holdout_end.isoformat(),
                "score": round(h_score, 4) if math.isfinite(h_score) else None,
                "summary": h_res.to_summary(),
                "note": ("final ~15% of the range, reserved before the search "
                         "and evaluated exactly once on best_params"),
            }
        else:
            holdout = {
                "start": None, "end": None, "score": None, "summary": None,
                "note": "range too short to reserve a holdout",
            }

        # --- regime analytics on the best-params run (purely additive) -----
        try:
            regimes = self._regimes(best_oos_result, tickers)
        except Exception:  # noqa: BLE001 - analytics must never break the loop
            regimes = None

        return {
            "best_params": best_params,
            "history": history,
            "best": best_oos_result.to_summary(),
            "objective": objective,
            "folds": {
                "in_sample": [is_start.isoformat(), is_end.isoformat()],
                "out_of_sample": [oos_start.isoformat(), oos_end.isoformat()],
                "holdout": ([holdout["start"], holdout["end"]]
                            if holdout_start is not None else None),
            },
            "holdout": holdout,
            "regimes": regimes,
            # multiple-testing transparency: how many parameter candidates were
            # evaluated to arrive at best_params. The holdout is evaluated
            # exactly once and is immune; treat OOS scores as optimistic in
            # proportion to this count.
            "trials": len(history),
        }

    # ------------------------------------------------------------------ #
    # Regime analytics
    # ------------------------------------------------------------------ #
    def _regimes(self, result: BacktestResult, tickers: list[str]) -> Optional[dict]:
        """Vol-regime decomposition of the best-params run's equity curve.

        Every equity-curve day with a defined daily return (i.e. from the
        second curve point on) is classified into low/mid/high terciles of
        the average 20d realized vol (rv20) across the run's tickers, with
        the tercile cut-offs computed over the run's own range.  Returns
        ``{"low"/"mid"/"high": {days, total_return, sharpe, max_drawdown}}``
        or None when no equity data covers the run.  Days whose rv20 is not
        yet defined (indicator warm-up) are left unclassified.
        """
        curve = result.equity_curve
        if len(curve) < 2:
            return None

        import pandas as pd

        from ..signals.equity import indicator_frame

        store = self._equity if self._equity is not None else EquityStore()
        rv_series = []
        for tk in dict.fromkeys(t.upper() for t in tickers):
            try:
                frame = indicator_frame(tk, store)
            except Exception:  # noqa: BLE001 - ticker without equity data
                continue
            rv_series.append(pd.Series(frame["rv20"].to_numpy(),
                                       index=list(frame["date"])))
        if not rv_series:
            return None  # no equity data for any of the run's tickers

        # Average rv20 across tickers (NaN-skipping), sampled on curve days.
        avg_rv = pd.concat(rv_series, axis=1).mean(axis=1)
        rv_on_day = avg_rv.reindex([p.asof for p in curve])

        # Daily simple returns: day i's return (and regime) belongs to day i.
        classified: list[tuple[float, float]] = []   # (rv, daily return)
        for i in range(1, len(curve)):
            rv = rv_on_day.iloc[i]
            if pd.isna(rv):
                continue
            prev = curve[i - 1].equity
            ret = (curve[i].equity - prev) / prev if prev else 0.0
            classified.append((float(rv), ret))
        if not classified:
            return None  # equity data never overlaps the run range

        cuts = pd.Series([rv for rv, _ in classified]).quantile([1 / 3, 2 / 3])
        q1, q2 = float(cuts.iloc[0]), float(cuts.iloc[1])
        buckets: dict[str, list[float]] = {"low": [], "mid": [], "high": []}
        for rv, ret in classified:
            key = "low" if rv <= q1 else ("mid" if rv <= q2 else "high")
            buckets[key].append(ret)
        return {name: _regime_stats(rets) for name, rets in buckets.items()}

    # ------------------------------------------------------------------ #
    # Search internals
    # ------------------------------------------------------------------ #
    @staticmethod
    def _holdout_split(start: date, end: date) -> tuple[date, date, Optional[date], Optional[date]]:
        """Carve the final ``_HOLDOUT_FRAC`` of ``[start, end]`` off the search range.

        Returns ``(search_start, search_end, holdout_start, holdout_end)``.
        The holdout begins strictly after the search range ends, so neither the
        IS nor the (repeatedly peeked) OOS fold can touch it.  Windows too short
        to split sensibly get no holdout (``None, None``).
        """
        span = (end - start).days
        holdout_days = int(round(span * _HOLDOUT_FRAC))
        if span < 20 or holdout_days < 2:
            return start, end, None, None
        search_end = end - timedelta(days=holdout_days)
        return start, search_end, search_end + timedelta(days=1), end

    @staticmethod
    def _fold(start: date, end: date) -> tuple[date, date, date, date]:
        """Split the window 70/30 into in-sample / out-of-sample folds."""
        span = (end - start).days
        if span < 4:
            # Degenerate window: reuse the same span for both folds.
            return start, end, start, end
        cut = start + timedelta(days=int(span * 0.7))
        oos_start = cut + timedelta(days=1)
        if oos_start >= end:
            oos_start = cut
        return start, cut, oos_start, end

    def _default_params(self, strategy_name: str) -> dict:
        """Pull library defaults if the builder exposes them, else a sane set."""
        builder = STRATEGIES[strategy_name]
        defaults = getattr(builder, "default_params", None)
        if isinstance(defaults, dict) and defaults:
            return dict(defaults)
        # Generic, strategy-agnostic defaults the engine/builders understand.
        return {
            "dte_target": 30,
            "close_dte": 7,
            "short_delta": 0.25,
            "width": 5.0,
            "profit_target": 0.5,
            "stop_mult": 2.0,
        }

    @staticmethod
    def _space(params: dict) -> dict[str, tuple[float, float, bool]]:
        """Build per-parameter bounds for every numeric default."""
        space: dict[str, tuple[float, float, bool]] = {}
        for key, val in params.items():
            if key in _PARAM_BOUNDS:
                space[key] = _PARAM_BOUNDS[key]
            elif isinstance(val, bool):
                continue  # leave booleans fixed
            elif isinstance(val, int):
                lo = max(0.0, val * 0.25)
                space[key] = (lo, max(lo + 1.0, val * 3.0), True)
            elif isinstance(val, float):
                lo = val * 0.25
                space[key] = (lo, max(lo + 1e-6, val * 3.0), False)
        return space

    @staticmethod
    def _clamp(name: str, value: float, bounds: dict) -> float:
        lo, hi, is_int = bounds[name]
        value = min(hi, max(lo, value))
        return float(round(value)) if is_int else round(value, 4)

    def _mutate(
        self, params: dict, bounds: dict, temperature: float, rng: random.Random
    ) -> dict:
        """Gaussian-perturb a subset of the best params (exploit + local search)."""
        out = dict(params)
        keys = [k for k in out if k in bounds]
        if not keys:
            return out
        # Mutate ~half the parameters each step (at least one).
        k = max(1, len(keys) // 2)
        for name in rng.sample(keys, k):
            lo, hi, is_int = bounds[name]
            scale = (hi - lo) * temperature
            new = float(out[name]) + rng.gauss(0.0, scale)
            out[name] = self._clamp(name, new, bounds)
        return self._repair(out)

    def _explore(self, bounds: dict, rng: random.Random) -> dict:
        """Sample a fresh point uniformly from the search space."""
        out: dict[str, Any] = {}
        for name, (lo, hi, is_int) in bounds.items():
            v = rng.uniform(lo, hi)
            out[name] = float(round(v)) if is_int else round(v, 4)
        return self._repair(out)

    @staticmethod
    def _repair(params: dict) -> dict:
        """Enforce simple ordering invariants between related parameters."""
        out = dict(params)
        if "dte_min" in out and "dte_max" in out and out["dte_min"] > out["dte_max"]:
            out["dte_min"], out["dte_max"] = out["dte_max"], out["dte_min"]
        if "long_delta" in out and "short_delta" in out and out["long_delta"] > out["short_delta"]:
            out["long_delta"] = round(out["short_delta"] * 0.6, 4)
        return out

    # ------------------------------------------------------------------ #
    def _backtest(
        self, strategy_name: str, params: dict, tickers: list[str], start: date, end: date
    ) -> BacktestResult:
        """Run one backtest; never let an exception abort the whole search."""
        try:
            return self._bt.run(strategy_name, params, tickers, start, end)
        except Exception as exc:  # noqa: BLE001 - search must be robust
            from ..contracts import BacktestMetrics

            metrics = BacktestMetrics(
                start=start, end=end,
                survivorship_note=f"backtest failed: {exc!r}",
            )
            return BacktestResult(
                config_name=strategy_name, metrics=metrics, params=dict(params)
            )


def _regime_stats(rets: list[float]) -> dict:
    """{days, total_return, sharpe, max_drawdown} for one regime's daily returns.

    total_return compounds the regime's days; sharpe is annualised mean/std of
    those days; max_drawdown is measured on the compounded sub-curve of the
    regime's days treated as a contiguous series (same conventions as
    ``compute_metrics``: std is population std, dd is <= 0).
    """
    if not rets:
        return {"days": 0, "total_return": 0.0, "sharpe": 0.0, "max_drawdown": 0.0}
    eq, peak, max_dd = 1.0, 1.0, 0.0
    for r in rets:
        eq *= (1.0 + r)
        peak = max(peak, eq)
        if peak > 0:
            max_dd = min(max_dd, (eq - peak) / peak)
    mean = sum(rets) / len(rets)
    var = sum((x - mean) ** 2 for x in rets) / len(rets)
    std = math.sqrt(var)
    sharpe = (mean / std) * math.sqrt(_TRADING_DAYS_PER_YEAR) if std > 1e-12 else 0.0
    return {
        "days": len(rets),
        "total_return": round(eq - 1.0, 4),
        "sharpe": round(sharpe, 3),
        "max_drawdown": round(max_dd, 4),
    }
