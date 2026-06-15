"""Candidate — the unit passed through the whole pipeline. Category-agnostic:
a candidate is just an identity + a chemical representation + free metadata.
No notion of target, assay, or chemotype lives here."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Candidate:
    id: str
    smiles: str                      # canonical SMILES (the universal representation)
    sequence: str | None = None      # optional peptide sequence, if applicable
    meta: dict = field(default_factory=dict)
