"""Candidate generator (category-agnostic).

Strategy: BRICS fragment recombination from a seed set of known actives. Breaking
the seeds at retrosynthetic (BRICS) bonds and recombining yields NOVEL molecules
built from the same medicinally-relevant fragments — so candidates stay near the
chemistry the scorer was validated on (its applicability domain), which is exactly
what we need for a data-driven scorer. No target/chemotype literals here; the
caller supplies the seeds and limits.
"""
from __future__ import annotations
import random

# Single-point "decoration" edits: small substituents that tune lipophilicity/
# permeability and H-bonding while leaving the core (and its zinc-binding group)
# intact -> products stay HIGH-similarity to the seed, i.e. inside a QSAR's
# applicability domain. Standard medicinal-chemistry moves, not target-specific.
_ANALOG_RXN = [
    "[cH:1]>>[c:1]F", "[cH:1]>>[c:1]Cl", "[cH:1]>>[c:1]C",
    "[cH:1]>>[c:1]OC", "[cH:1]>>[c:1][OH]", "[cH:1]>>[c:1]C(F)(F)F",
    "[cH:1]>>[c:1]C#N", "[CH3:1]>>[C:1]F",
]


def analog_candidates(seed_smiles, n_max=4000, seed=42):
    """Yield up to n_max unique, novel, sanitisable single-edit analogs of the
    seeds (one small substituent change each). High similarity to the seeds keeps
    them inside a data-driven scorer's validated domain. Deterministic given seed.
    """
    from rdkit import Chem, RDLogger
    from rdkit.Chem import AllChem
    RDLogger.DisableLog("rdApp.*")
    rxns = [AllChem.ReactionFromSmarts(s) for s in _ANALOG_RXN]

    seeds = [Chem.MolFromSmiles(s) for s in seed_smiles]
    seeds = [m for m in seeds if m is not None]
    seed_canon = {Chem.MolToSmiles(m) for m in seeds}

    random.seed(seed)
    order = list(range(len(seeds))); random.shuffle(order)
    out, seen = [], set()
    for idx in order:
        m = seeds[idx]
        for rxn in rxns:
            for prod in rxn.RunReactants((m,)):
                try:
                    p = prod[0]; Chem.SanitizeMol(p); smi = Chem.MolToSmiles(p)
                except Exception:
                    continue
                if smi in seen or smi in seed_canon:
                    continue
                seen.add(smi); out.append(smi)
                if len(out) >= n_max:
                    return out
    return out


def brics_candidates(seed_smiles, n_max=4000, max_depth=2, seed=42):
    """Yield up to n_max unique, sanitisable SMILES recombined from the seeds.

    Deterministic given `seed`. Excludes molecules identical to a seed (novelty is
    enforced downstream too)."""
    from rdkit import Chem, RDLogger
    from rdkit.Chem import BRICS
    RDLogger.DisableLog("rdApp.*")

    seeds = [Chem.MolFromSmiles(s) for s in seed_smiles]
    seeds = [m for m in seeds if m is not None]
    seed_canon = {Chem.MolToSmiles(m) for m in seeds}

    frags = set()
    for m in seeds:
        frags |= BRICS.BRICSDecompose(m)
    frag_mols = [Chem.MolFromSmiles(f) for f in frags]
    frag_mols = [f for f in frag_mols if f is not None]

    random.seed(seed)
    out, seen = [], set()
    builder = BRICS.BRICSBuild(frag_mols, scrambleReagents=True, maxDepth=max_depth)
    for prod in builder:
        try:
            Chem.SanitizeMol(prod)
            smi = Chem.MolToSmiles(prod)
        except Exception:
            continue
        if smi in seen or smi in seed_canon:
            continue
        seen.add(smi)
        out.append(smi)
        if len(out) >= n_max:
            break
    return out
