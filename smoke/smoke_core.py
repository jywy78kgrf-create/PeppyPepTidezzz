"""Stage 0-B smoke test: prove the deterministic core stack works.
NOTE: This stack is the DETERMINISTIC fitness spine (constraint #1).
No LLM, no network, no randomness here."""
import platform
import numpy as np, scipy, pandas as pd, sklearn
from rdkit import Chem, RDLogger
from rdkit.Chem import Descriptors, rdMolDescriptors
RDLogger.DisableLog("rdApp.*")

print("python      :", platform.python_version())
print("numpy       :", np.__version__)
print("scipy       :", scipy.__version__)
print("pandas      :", pd.__version__)
print("scikit-learn:", sklearn.__version__)
import rdkit; print("rdkit       :", rdkit.__version__)

# Real operation: build a dipeptide from a SMILES, confirm RDKit parses
# peptides and can compute the descriptors the fitness fn will need.
gly_gly = Chem.MolFromSequence("GG")          # peptide-aware parser
assert gly_gly is not None, "RDKit failed to build peptide from sequence"
print("GG canonical SMILES:", Chem.MolToSmiles(gly_gly))
print("GG MolWt           :", round(Descriptors.MolWt(gly_gly), 3))
print("GG HBD/HBA         :", rdMolDescriptors.CalcNumHBD(gly_gly),
      rdMolDescriptors.CalcNumHBA(gly_gly))

# Determinism check: same input -> identical canonical SMILES twice.
a = Chem.MolToSmiles(Chem.MolFromSequence("GHK"))
b = Chem.MolToSmiles(Chem.MolFromSequence("GHK"))
assert a == b, "RDKit canonicalization not deterministic!"
print("determinism check  : PASS (GHK ->", a + ")")
print("\nSTAGE 0-B SMOKE: PASS")
