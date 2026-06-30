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
from ..data.loader import ChainStore
from ..strategies.library import STRATEGIES

# Objective key -> field on BacktestMetrics (higher is better for all of these,
# drawdown is negated so "less drawdown" scores higher).
_OBJECTIVES: dict[str, Callable[[Any], float]] = {
    "sortino": lambda m: m.sortino,
    "sharpe": lambda m: m.sharpe,
    "cagr": lambda m: m.cagr,
    "total_return": lambda m: m.total_return,
    "profit_factor": lambda m: m.profit_factor,
    "calmar": lambda m: (m.cagr / m.max_drawdown) if m.max_drawdown > 0 else m.cagr,
}

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

    def __init__(self, store: ChainStore, settings: Settings = SETTINGS) -> None:
        self.store = store
        self.settings = settings
        self._bt = Backtester(store, settings=settings)

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
        BacktestResult.to_summary()}``.
        """
        if strategy_name not in STRATEGIES:
            raise ValueError(f"unknown strategy {strategy_name!r}")
        score_of = _OBJECTIVES.get(objective)
        if score_of is None:
            raise ValueError(f"unknown objective {objective!r}")

        rng = random.Random(seed)
        is_start, is_end, oos_start, oos_end = self._fold(start, end)

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

        return {
            "best_params": best_params,
            "history": history,
            "best": best_oos_result.to_summary(),
            "objective": objective,
            "folds": {
                "in_sample": [is_start.isoformat(), is_end.isoformat()],
                "out_of_sample": [oos_start.isoformat(), oos_end.isoformat()],
            },
        }

    # ------------------------------------------------------------------ #
    # Search internals
    # ------------------------------------------------------------------ #
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
