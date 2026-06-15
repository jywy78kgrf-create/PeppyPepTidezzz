"""TargetSpec — the CONTRACT that CONFIG fills and CORE consumes.

This is the entire surface through which target-specific information enters the
category-agnostic core. Swapping targets (MMP-1 -> some therapeutic) or scorers
(autodock4zn -> boltz2) is done by editing a config YAML that populates this
object — never by editing core code.

Fields are deliberately generic. Anything that is MMP-1/zinc/cosmetic-specific
is carried opaquely inside `scorer_params` / `weights` / `extra` and is only
interpreted by the *adapter* the config selects, not by the core.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import yaml


@dataclass
class TargetSpec:
    name: str
    root: Path                       # config directory (for resolving relative paths)

    # --- structure / binding context (opaque to core) ---
    structure_path: str

    # --- scorer selection: THE config-only swap point ---
    scorer: str                      # registry key, e.g. "autodock4zn" | "boltz2"
    scorer_params: dict = field(default_factory=dict)

    # --- calibration data for THIS target ---
    calibration_csv: str = ""
    id_col: str = "molecule_chembl_id"
    smiles_col: str = "canonical_smiles"
    affinity_col: str = "pIC50_median"   # measured value the gate correlates against

    # --- fitness term weights (target-class policy: cosmetic vs therapeutic) ---
    weights: dict = field(default_factory=dict)
    hit_threshold: float | None = None

    # --- applicability domain + any target-class-specific extras (ZBG, etc.) ---
    domain: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)

    def resolve(self, rel: str) -> str:
        """Resolve a config-relative path to absolute (portability: no abs paths in YAML)."""
        p = Path(rel)
        return str(p if p.is_absolute() else (self.root / p))

    @classmethod
    def from_yaml(cls, path: str | Path) -> "TargetSpec":
        path = Path(path)
        d = yaml.safe_load(path.read_text())
        d["root"] = path.parent
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})
