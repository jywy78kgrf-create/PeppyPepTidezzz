"""Multi-term fitness (category-agnostic engine; policy lives in CONFIG).

Three terms, combined with config-supplied weights:
  - affinity     : predicted potency (pIC50) from the validated scorer.
  - permeability : skin-permeability proxy via the Potts-Guy logKp QSPR
                   logKp = -2.7 + 0.71*logP - 0.0061*MW  (cm/h, octanol-water logP,
                   MW in g/mol). Higher = penetrates skin better — central for a
                   TOPICAL cosmetic active.
  - safety       : structural-alert cleanliness (RDKit Brenk + PAINS catalogues);
                   fewer alerts = safer.

The terms are generic; the *weighting* (cosmetic: heavy permeability + safety) is
the config's `weights`. The engine just normalises each term across the candidate
pool and takes the weighted sum, so the same code serves any target-class policy.
"""
from __future__ import annotations
import numpy as np


def potts_guy_logkp(mol) -> float:
    from rdkit.Chem import Descriptors, Crippen
    return -2.7 + 0.71 * Crippen.MolLogP(mol) - 0.0061 * Descriptors.MolWt(mol)


_CATALOG = None


def _catalog():
    global _CATALOG
    if _CATALOG is None:
        from rdkit.Chem import FilterCatalog
        from rdkit.Chem.FilterCatalog import FilterCatalogParams
        p = FilterCatalogParams()
        p.AddCatalog(FilterCatalogParams.FilterCatalogs.BRENK)
        p.AddCatalog(FilterCatalogParams.FilterCatalogs.PAINS)
        _CATALOG = FilterCatalog.FilterCatalog(p)
    return _CATALOG


def structural_alerts(mol) -> int:
    return len(_catalog().GetMatches(mol))


def _minmax(v):
    v = np.asarray(v, dtype=float)
    lo, hi = np.nanmin(v), np.nanmax(v)
    return np.zeros_like(v) if hi - lo < 1e-12 else (v - lo) / (hi - lo)


def combine(pIC50, logkp, alerts, weights):
    """Per-candidate weighted fitness in [0,1], normalised across the pool.

    pIC50, logkp, alerts are arrays over the candidate pool. Returns (fitness,
    components dict) where components are the normalised [0,1] terms."""
    aff = _minmax(pIC50)
    perm = _minmax(logkp)
    safe = 1.0 - _minmax(alerts)                 # fewer alerts -> safer (higher)
    wa = float(weights.get("affinity", 0.0))
    wp = float(weights.get("permeability", 0.0))
    ws = float(weights.get("safety", 0.0))
    tot = wa + wp + ws or 1.0
    fit = (wa * aff + wp * perm + ws * safe) / tot
    return fit, {"affinity_norm": aff, "permeability_norm": perm, "safety_norm": safe}
