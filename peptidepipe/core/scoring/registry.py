"""Scorer registry — the indirection that keeps engine choice in CONFIG.

Adapters decorate their class with @register("name"). The core builds a scorer
purely from the string in target.yaml (`scorer:`), so it never imports a
specific engine. AutoDock4Zn -> Boltz-2 is therefore a one-line config change.
"""
from __future__ import annotations
from peptidepipe.core.scoring.affinity_base import AffinityScorer

_REGISTRY: dict[str, type[AffinityScorer]] = {}


def register(name: str):
    def deco(cls: type[AffinityScorer]):
        cls.name = name
        _REGISTRY[name] = cls
        return cls
    return deco


def available() -> list[str]:
    return sorted(_REGISTRY)


def build(name: str, params: dict | None = None) -> AffinityScorer:
    if name not in _REGISTRY:
        raise KeyError(
            f"scorer '{name}' not registered; available={available()}. "
            f"(Did the adapters package get imported?)"
        )
    return _REGISTRY[name](params or {})
