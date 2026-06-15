"""Leakage / generalization probe for a TRAINED scorer (Boltz-2).

Boltz-2's affinity head was trained on public data that likely includes ChEMBL
MMP-1, so a good calibration correlation may be partial memorisation rather than
generalisation. The downstream job is ranking NOVEL candidates, so what we really
need to know is: does the scorer still rank compounds whose CHEMOTYPE is new?

This splits the held-out fold by Bemis-Murcko scaffold novelty (relative to the
rest of the calibration set) and reports Spearman on each subset:
  - "seen scaffold"  : scaffold also appears elsewhere in the set
  - "novel scaffold" : scaffold unique to this held-out molecule
If the correlation holds only on seen scaffolds and collapses on novel ones, the
model is leaning on memorised chemotypes -> treat a calibration "pass" with
suspicion. (Necessary, not sufficient: Boltz may have seen a scaffold from some
other source. It's a first-line check, not proof.)

Usage:
    python leakage_probe.py [predicted_vs_actual.csv]
    (default: results/mmp1_boltz2/predicted_vs_actual.csv)
"""
import sys
import pandas as pd
from scipy.stats import spearmanr
from rdkit import Chem, RDLogger
from rdkit.Chem.Scaffolds import MurckoScaffold
RDLogger.DisableLog("rdApp.*")

from peptidepipe.core.targetspec import TargetSpec

CSV = sys.argv[1] if len(sys.argv) > 1 else "results/mmp1_boltz2/predicted_vs_actual.csv"
CFG = "peptidepipe/configs/mmp1_cosmetic/target.yaml"


def scaffold(smi):
    m = Chem.MolFromSmiles(smi)
    if m is None:
        return None
    try:
        return MurckoScaffold.MurckoScaffoldSmiles(mol=m)
    except Exception:
        return None


def rho(frame):
    if len(frame) >= 3:
        r = spearmanr(frame.predicted, frame.measured)
        return f"rho={r.statistic:+.3f} (p={r.pvalue:.3f}, n={len(frame)})"
    return f"n={len(frame)} (too few for rho)"


def main():
    res = pd.read_csv(CSV)
    t = TargetSpec.from_yaml(CFG)
    smi = pd.read_csv(t.resolve(t.calibration_csv))[[t.id_col, t.smiles_col]]
    smi.columns = ["id", "smiles"]
    df = res.merge(smi, on="id", how="left")
    df["scaffold"] = df.smiles.map(scaffold)

    counts = df.scaffold.value_counts()
    df["novel"] = df.scaffold.map(lambda s: counts.get(s, 0) <= 1)

    print(f"file: {CSV}   (n={len(df)})")
    print(f"\noverall            : {rho(df)}")
    if "split" in df.columns:
        te = df[df.split == "test"]
        print(f"held-out (all)     : {rho(te)}")
        print(f"held-out, seen scaf: {rho(te[~te.novel])}")
        print(f"held-out, novel scf: {rho(te[te.novel])}")
    print(f"\nfull set, seen scaf: {rho(df[~df.novel])}")
    print(f"full set, novel scf: {rho(df[df.novel])}")
    print("\nInterpretation: if 'novel scaffold' rho is much weaker than 'seen scaffold',")
    print("the scorer is likely leaning on memorised chemotypes -> a calibration pass")
    print("does NOT guarantee it will rank genuinely new candidates.")


if __name__ == "__main__":
    main()
