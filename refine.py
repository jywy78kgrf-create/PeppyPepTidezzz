"""Developability re-ranker: add synthesizability (SAScore), drug-likeness rule
filters, and model uncertainty to a profiled candidate set, then keep only the
"developable" ones and re-rank. Addresses the "these wouldn't survive a chemist"
critique — entirely on CPU.

  python refine.py --candidates candidates/hdac6_inhibitor/candidates_profiled.csv \
                   --target hdac6 --outdir candidates/hdac6_inhibitor
"""
import argparse, os, sys
import numpy as np, pandas as pd
from rdkit import Chem, RDLogger
from rdkit.Chem import Descriptors, Crippen, rdMolDescriptors, RDConfig
from sklearn.ensemble import RandomForestRegressor
from qsar_baseline import featurize, SEED
sys.path.append(os.path.join(RDConfig.RDContribDir, "SA_Score")); import sascorer
RDLogger.DisableLog("rdApp.*")

ap = argparse.ArgumentParser()
ap.add_argument("--candidates", required=True)
ap.add_argument("--target", required=True)
ap.add_argument("--outdir", required=True)
args = ap.parse_args()
pcol = f"pIC50_{args.target}"

df = pd.read_csv(args.candidates)
# selectivity column varies by pipeline; detect one if present
selcol = next((c for c in ["selectivity", "min_offtarget_sel", "min_MMP1_selectivity", "spare_MMP1"]
               if c in df.columns), None)

mols = [Chem.MolFromSmiles(s) for s in df["smiles"]]
df["sa_score"] = [round(sascorer.calculateScore(m), 2) if m else np.nan for m in mols]
df["MW"] = [round(Descriptors.MolWt(m), 1) for m in mols]
df["cLogP"] = [round(Crippen.MolLogP(m), 2) for m in mols]
df["HBD"] = [rdMolDescriptors.CalcNumHBD(m) for m in mols]
df["HBA"] = [rdMolDescriptors.CalcNumHBA(m) for m in mols]
df["TPSA"] = [round(Descriptors.TPSA(m), 1) for m in mols]
df["rotB"] = [rdMolDescriptors.CalcNumRotatableBonds(m) for m in mols]
lip_viol = ((df.MW > 500).astype(int) + (df.cLogP > 5).astype(int) +
            (df.HBD > 5).astype(int) + (df.HBA > 10).astype(int))
df["lipinski_ok"] = lip_viol <= 1
df["veber_ok"] = (df.rotB <= 10) & (df.TPSA <= 140)

# model uncertainty = std across RF trees (trees disagree -> less reliable)
cal = pd.read_csv(f"data/calibration/{args.target}_ic50.csv")[["canonical_smiles", "pIC50_median"]].dropna()
Xt, okt = featurize(cal["canonical_smiles"])
rf = RandomForestRegressor(n_estimators=400, random_state=SEED, n_jobs=-1).fit(Xt, cal["pIC50_median"].to_numpy()[okt])
Xc, okc = featurize(df["smiles"])
per_tree = np.stack([t.predict(Xc) for t in rf.estimators_])
unc = np.full(len(df), np.nan); unc[okc] = per_tree.std(axis=0)
df["pred_uncertainty"] = np.round(unc, 3)

# developable: synthesizable, drug-like, clean, single zinc-binder
df["developable"] = ((df.sa_score <= 4.5) & df.lipinski_ok & df.veber_ok &
                     (df.get("struct_alerts", 99) <= 1) & (df.get("n_chelators", 99) == 1))

df.to_csv(f"{args.outdir}/candidates_refined.csv", index=False)
dev = df[df.developable].copy()
sort_cols = [pcol] + ([selcol] if selcol else [])
dev = dev.sort_values(sort_cols, ascending=False)
print(f"{args.target}: {len(df)} candidates -> {int(df.developable.sum())} developable")
show = ["id", pcol] + ([selcol] if selcol else []) + ["sa_score", "MW", "cLogP", "druglikeness_qed",
        "struct_alerts", "n_chelators", "pred_uncertainty"]
show = [c for c in show if c in dev.columns]
print(dev[show].head(12).round(3).to_string(index=False))

# shortlist md
L = [f"# Developable shortlist — {args.target.upper()}\n",
     "Filtered for synthesizability + drug-likeness on top of potency/selectivity:",
     "**SAScore ≤ 4.5, ≤1 Lipinski violation, Veber OK, ≤1 structural alert, single zinc-binder.** "
     "Prediction uncertainty = std across RF trees (higher = less reliable).\n",
     f"- {len(df)} candidates → **{int(df.developable.sum())} developable**.\n"]
if len(dev):
    cols2 = ["id", pcol] + ([selcol] if selcol else []) + ["sa_score", "MW", "cLogP", "druglikeness_qed", "struct_alerts", "pred_uncertainty"]
    cols2 = [c for c in cols2 if c in dev.columns]
    L.append("| " + " | ".join(cols2) + " |")
    L.append("|" + "---|" * len(cols2))
    for r in dev.head(15).itertuples():
        L.append("| " + " | ".join(str(round(getattr(r, c), 3) if isinstance(getattr(r, c), float) else getattr(r, c)) for c in cols2) + " |")
    L.append("\n## SMILES")
    for r in dev.head(15).itertuples():
        L.append(f"- **{r.id}**  `{Chem.MolToSmiles(Chem.MolFromSmiles(r.smiles))}`")
else:
    L.append("**No candidate passed the developability gate** — the predicted-potent structures here "
             "are not synthesizable/drug-like enough. That is itself the finding: in this generated "
             "space, developability and potency don't co-occur.")
L.append("\nPredictions are QSAR triage, not measurements. Confirm in vitro.")
open(f"{args.outdir}/DEVELOPABLE.md", "w").write("\n".join(L))
print(f"wrote {args.outdir}/candidates_refined.csv + DEVELOPABLE.md")
