"""AffinityScorer — the binding/affinity term interface.

THIS is the seam that makes AutoDock4Zn <-> Boltz-2 a config-only swap.
Both engines are concrete AffinityScorer subclasses living in peptidepipe/adapters;
the core, the calibration harness, and the optimization loop depend ONLY on this
abstract class. To change which engine runs, change `scorer:` in the target YAML.

Sign convention (must be honoured by every adapter):
    AffinityResult.score is "higher = stronger predicted binder".
    (AutoDock returns an energy in kcal/mol where more-negative = better, so its
     adapter returns score = -energy. Boltz-2's affinity head returns a predicted
     pIC50/affinity directly. The harness only ever needs a monotone ranking.)
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from peptidepipe.core.candidate import Candidate
from peptidepipe.core.targetspec import TargetSpec


@dataclass
class AffinityResult:
    candidate_id: str
    score: float                 # higher = better predicted binder (see convention above)
    ok: bool = True              # False if this candidate could not be scored
    note: str = ""
    raw: dict = field(default_factory=dict)   # engine-specific detail (energy, paths, ...)


class AffinityScorer(ABC):
    """Abstract binding/affinity engine. Adapters implement prepare()+score()."""

    #: registry name; set by @register on the subclass
    name: str = "abstract"

    def __init__(self, params: dict | None = None):
        self.params = params or {}

    @abstractmethod
    def prepare(self, target: TargetSpec) -> None:
        """One-time setup for a target (e.g. receptor prep + grid maps, or model
        weight loading). Target-specific details arrive via `target`, never as
        hard-coded literals."""

    @abstractmethod
    def score(self, candidate: Candidate) -> AffinityResult:
        """Score a single candidate against the prepared target."""

    def score_many(self, candidates: list[Candidate]) -> list[AffinityResult]:
        return [self.score(c) for c in candidates]
