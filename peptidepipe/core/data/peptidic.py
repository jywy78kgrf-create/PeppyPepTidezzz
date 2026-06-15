"""Peptide / peptidomimetic classification (category-agnostic).

Counts backbone residues via the N-Calpha-C(=O) signature. The *thresholds*
that define "peptidomimetic" for a given run are NOT fixed here — they are
passed in by the config-driven caller, so a different target/chemotype policy
needs no edit to this module."""
from __future__ import annotations
from rdkit import Chem, RDLogger
RDLogger.DisableLog("rdApp.*")

_AMIDE = Chem.MolFromSmarts("C(=O)N")
_BACKBONE = Chem.MolFromSmarts("[NX3][CX4][CX3](=O)")   # one match ~ one residue linkage


def backbone_residues(smiles: str) -> int:
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        return -1
    return len(m.GetSubstructMatches(_BACKBONE))


def amide_bonds(smiles: str) -> int:
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        return -1
    return len(m.GetSubstructMatches(_AMIDE))


def in_residue_range(smiles: str, lo: int, hi: int) -> bool:
    """True if backbone-residue count is within [lo, hi] (inclusive). The caller
    supplies lo/hi from config (e.g. short ZBG peptidomimetic = 2..3)."""
    n = backbone_residues(smiles)
    return lo <= n <= hi
