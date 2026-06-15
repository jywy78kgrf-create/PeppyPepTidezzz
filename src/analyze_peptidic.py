"""Pre-Stage-2 check: how many of the assembled MMP-1 IC50 datapoints are
genuinely PEPTIDIC? Drives the decision on where the first real gate lives.

Operational definitions (transparent, deterministic):
  amide bonds      : C(=O)N matches
  backbone residues: [NX3][CX4][CX3](=O)  (N-Calpha-C=O signature per residue)
  classification by backbone-residue count:
     >=4 residues -> peptide (clearly)
     2-3 residues -> peptidomimetic / short peptide
     <2           -> small molecule
"""
import pandas as pd
from rdkit import Chem, RDLogger
from rdkit.Chem import rdMolDescriptors
RDLogger.DisableLog("rdApp.*")

df = pd.read_csv("data/calibration/mmp1_ic50.csv")
amide = Chem.MolFromSmarts("C(=O)N")
backbone = Chem.MolFromSmarts("[NX3][CX4][CX3](=O)")

rows = []
for _, r in df.iterrows():
    m = Chem.MolFromSmiles(r.canonical_smiles)
    if m is None:
        rows.append((0, 0)); continue
    na = len(m.GetSubstructMatches(amide))
    nb = len(m.GetSubstructMatches(backbone))
    rows.append((na, nb))
df["n_amide"], df["n_backbone"] = zip(*rows)

def klass(nb):
    if nb >= 4: return "peptide(>=4 res)"
    if nb >= 2: return "short-peptide/mimetic(2-3 res)"
    return "small-molecule(<2 res)"
df["class"] = df.n_backbone.apply(klass)

print(f"total molecules: {len(df)}\n")
print("=== backbone-residue count distribution ===")
print(df.n_backbone.value_counts().sort_index().to_string())
print("\n=== class breakdown ===")
print(df["class"].value_counts().to_string())

pep4  = (df.n_backbone >= 4).sum()
pep2  = (df.n_backbone >= 2).sum()
print(f"\nclearly peptidic (>=4 backbone residues): {pep4}")
print(f"peptidic incl. short/mimetic (>=2 residues): {pep2}")
print("\n=== strongest peptidic (>=4 res) examples ===")
sub = df[df.n_backbone >= 4].sort_values("pIC50_median", ascending=False).head(5)
for _, r in sub.iterrows():
    print(f"  {r.molecule_chembl_id}  pIC50={r.pIC50_median}  residues~{r.n_backbone}")

print(f"\nGATE-VIABILITY: peptide-specific gate needs ~30+ points -> "
      f"{'OK' if pep4 >= 30 else 'TOO FEW (rethink first gate)'} (>=4-res count={pep4})")
