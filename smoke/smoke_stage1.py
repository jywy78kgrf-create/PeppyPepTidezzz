"""Stage 1 smoke test: confirm the ground-truth inputs are usable.
(1) MMP-1 structure 1HFC parses and the catalytic zinc + its His coordination
    are present (constraint #3 -- we must know where the zinc is).
(2) The ChEMBL calibration set loads and the pIC50 values are sane.
Deterministic, no network, no modeling."""
import pandas as pd
from rdkit import Chem, RDLogger
RDLogger.DisableLog("rdApp.*")

PDB = "data/structures/1HFC.pdb"
CSV = "data/calibration/mmp1_ic50.csv"

print("=== (1) MMP-1 structure 1HFC ===")
zns, his_ne_nd = [], []
with open(PDB) as fh:
    for ln in fh:
        if ln.startswith("HETATM") and ln[12:16].strip() == "ZN":
            zns.append((int(ln[22:26]), float(ln[30:38]), float(ln[38:46]), float(ln[46:54])))
        if ln.startswith("ATOM") and ln[17:20] == "HIS" and ln[12:16].strip() in ("NE2", "ND1"):
            his_ne_nd.append((float(ln[30:38]), float(ln[38:46]), float(ln[46:54])))
print(f"zinc ions found: {len(zns)}  -> {[z[0] for z in zns]}")
assert len(zns) >= 1, "no zinc in MMP-1 structure!"

# Catalytic zinc = the one coordinated by >=3 His imidazole nitrogens (~2.0-2.3 A).
def coord_his(zn):
    zx, zy, zz = zn[1], zn[2], zn[3]
    return sum(1 for (x, y, z) in his_ne_nd
               if ((x-zx)**2 + (y-zy)**2 + (z-zz)**2) ** 0.5 < 2.6)
for zn in zns:
    n = coord_his(zn)
    tag = "  <- catalytic (3-His)" if n >= 3 else ""
    print(f"  ZN {zn[0]} coordinated by {n} His N atoms{tag}")
assert any(coord_his(z) >= 3 for z in zns), "no 3-His catalytic zinc found!"

print("\n=== (2) ChEMBL calibration set ===")
df = pd.read_csv(CSV)
assert {"molecule_chembl_id", "canonical_smiles", "pIC50_median"} <= set(df.columns)
print(f"molecules           : {len(df)}")
print(f"pIC50 range         : {df.pIC50_median.min():.2f} .. {df.pIC50_median.max():.2f}")
print(f"pIC50 median        : {df.pIC50_median.median():.2f}")
# Spot-check a SMILES parses in RDKit (it'll feed the fitness function).
top = df.iloc[0]
m = Chem.MolFromSmiles(top.canonical_smiles)
assert m is not None, "strongest binder SMILES failed to parse"
print(f"strongest binder    : {top.molecule_chembl_id}  pIC50={top.pIC50_median} "
      f"(RDKit atoms={m.GetNumAtoms()})")

print("\nSTAGE 1 SMOKE: PASS")
