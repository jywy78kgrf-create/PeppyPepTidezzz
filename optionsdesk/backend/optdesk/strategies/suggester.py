"""
Strategy suggester — ranks the library's structures for one underlying/date.

Builds every strategy in :data:`STRATEGIES` over the supplied chain, then scores
each candidate with a transparent, deterministic blend of:
  * expected edge (model mispricing captured, normalised by risk),
  * probability of profit (POP),
  * reward/risk (max_profit / max_loss), and
  * liquidity (open interest, volume, and relative bid/ask spread of its legs).

No randomness: identical inputs always yield identical, identically-ordered
output. Weights live in :data:`SCORE_WEIGHTS` and are exposed via ``meta`` for
auditability.
"""
from __future__ import annotations

import math
from datetime import date

from ..config import SETTINGS
from ..contracts import OptionQuote, StrategySpec
from ..quant.pricing import find_quote
from .library import STRATEGIES

SCORE_WEIGHTS: dict[str, float] = {
    "edge": 0.35,
    "pop": 0.25,
    "reward_risk": 0.20,
    "liquidity": 0.20,
}


class StrategySuggester:
    """Rank library strategies by a blended, deterministic score."""

    def __init__(self, settings=SETTINGS):
        """Hold settings (risk-free rate etc.) used for any model recomputation."""
        self.settings = settings
        self.weights = dict(SCORE_WEIGHTS)

    # ------------------------------------------------------------------ #
    def suggest(self, chain: list[OptionQuote], asof: date, top_k: int = 5,
                params: dict | None = None) -> list[StrategySpec]:
        """Return the ``top_k`` highest-scoring specs buildable from ``chain``.

        Builders that cannot find suitable strikes are skipped. Ties break on
        strategy name for determinism.
        """
        if not chain:
            return []
        underlying = self._underlying(chain)
        specs: list[StrategySpec] = []
        for name in sorted(STRATEGIES):  # sorted -> deterministic build order
            builder = STRATEGIES[name]
            try:
                spec = builder(chain, underlying, params or {})
            except Exception:
                spec = None
            if spec is None:
                continue
            spec.score = round(self._score(spec, chain), 6)
            specs.append(spec)
        specs.sort(key=lambda s: (-s.score, s.name))
        return specs[:max(0, top_k)]

    # ------------------------------------------------------------------ #
    def _underlying(self, chain: list[OptionQuote]) -> float:
        """Underlying price from the chain (all quotes share it on a date)."""
        for q in chain:
            if q.underlying > 0:
                return q.underlying
        return 0.0

    def _liquidity(self, spec: StrategySpec, chain: list[OptionQuote]) -> float:
        """0..1 liquidity score from leg OI, volume, and relative spread."""
        scores: list[float] = []
        for leg in spec.legs:
            q = find_quote(chain, leg.kind, leg.strike, leg.expiry)
            if q is None:
                scores.append(0.0)
                continue
            oi = math.log1p(max(0, q.open_interest)) / math.log1p(5000)
            vol = math.log1p(max(0, q.volume)) / math.log1p(1000)
            mid = q.mid if q.mid > 0 else q.last
            rel_spread = (q.spread / mid) if mid > 0 else 1.0
            tightness = 1.0 / (1.0 + 5.0 * rel_spread)
            scores.append(_clip01(0.4 * oi + 0.3 * vol + 0.3 * tightness))
        return sum(scores) / len(scores) if scores else 0.0

    def _score(self, spec: StrategySpec, chain: list[OptionQuote]) -> float:
        """Blend edge, POP, reward/risk, and liquidity into a 0..1-ish score."""
        # Edge normalised by capital at risk (fallback to a nominal $100).
        risk = spec.max_loss if spec.max_loss > 0 else 100.0
        edge_norm = _clip01(0.5 + spec.expected_edge / (2.0 * risk))

        pop = _clip01(spec.pop)

        if spec.max_profit == float("inf"):
            rr = 0.6  # convex/unbounded upside: credit it moderately
        elif risk > 0:
            rr = _clip01(spec.max_profit / risk / 3.0)  # 3:1 reward/risk -> ~1.0
        else:
            rr = 0.0

        liq = self._liquidity(spec, chain)

        w = self.weights
        blended = (w["edge"] * edge_norm + w["pop"] * pop +
                   w["reward_risk"] * rr + w["liquidity"] * liq)
        spec.meta["score_breakdown"] = {
            "edge": round(edge_norm, 4),
            "pop": round(pop, 4),
            "reward_risk": round(rr, 4),
            "liquidity": round(liq, 4),
        }
        return blended


def _clip01(x: float) -> float:
    """Clamp to [0, 1]."""
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)
