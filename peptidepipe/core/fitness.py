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


def qed(mol) -> float:
    """Quantitative Estimate of Drug-likeness (0..1, higher = more drug-like)."""
    from rdkit.Chem import QED
    try:
        return float(QED.qed(mol))
    except Exception:
        return 0.0


def chelator_types(mol, zbg_patterns) -> int:
    """Number of DISTINCT zinc-binding-group motif types present. A clean MMP
    inhibitor chelates the catalytic zinc with ONE group; >=2 metal-binders is the
    over-chelation liability that plagued first-gen MMP inhibitors. zbg_patterns is
    the config's (name, RDKit-SMARTS) list, so no target literals live here."""
    return sum(1 for _, p in zbg_patterns if mol.HasSubstructMatch(p))


def _minmax(v):
    v = np.asarray(v, dtype=float)
    lo, hi = np.nanmin(v), np.nanmax(v)
    return np.zeros_like(v) if hi - lo < 1e-12 else (v - lo) / (hi - lo)


def combine(pIC50, logkp, alerts, weights, qed_vals=None, n_chelators=None):
    """Per-candidate weighted fitness in [0,1], normalised across the pool.

    Core terms (always): affinity, permeability, safety. Optional terms:
      qed_vals   -> a `druglikeness` term (QED is already 0..1; not re-normalised).
      n_chelators-> a MULTIPLICATIVE penalty demoting over-chelators: 1 ZBG ->x1,
                    2 ->x0.5, 3 ->x0.33 ... so the optimiser stops favouring the
                    multi-metal-binder liability chemotype.
    Weights come from CONFIG (target-class policy); terms are generic."""
    aff = _minmax(pIC50)
    perm = _minmax(logkp)
    safe = 1.0 - _minmax(alerts)                 # fewer alerts -> safer (higher)
    parts = [(float(weights.get("affinity", 0.0)), aff),
             (float(weights.get("permeability", 0.0)), perm),
             (float(weights.get("safety", 0.0)), safe)]
    comp = {"affinity_norm": aff, "permeability_norm": perm, "safety_norm": safe}
    if qed_vals is not None:
        dl = np.asarray(qed_vals, dtype=float)
        parts.append((float(weights.get("druglikeness", 0.0)), dl))
        comp["druglikeness"] = dl
    tot = sum(w for w, _ in parts) or 1.0
    fit = sum(w * v for w, v in parts) / tot
    if n_chelators is not None:
        nc = np.asarray(n_chelators, dtype=float)
        pen = np.where(nc <= 1, 1.0, 1.0 / (1.0 + (nc - 1.0)))
        fit = fit * pen
        comp["chelator_penalty"] = pen
        comp["n_chelators"] = nc
    return fit, comp
