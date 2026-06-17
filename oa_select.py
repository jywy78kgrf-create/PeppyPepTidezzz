"""OA-profile selection: profile MMP-13 candidates across the MMP family and find
the Pareto front for the osteoarthritis objective set —
  1. potency      = predicted MMP-13 pIC50            (max)
  2. MMP-1 sparing = pIC50(MMP-13) − pIC50(MMP-1)      (max; >0 = spares MMP-1)
  3. drug-likeness = QED                               (max)
This is the OPPOSITE selectivity to the mmp1_inhibitor run: we now WANT MMP-1 spared.
"""
import numpy as np, pandas as pd
from rdkit import Chem, RDLogger
from sklearn.ensemble import RandomForestRegressor
from qsar_baseline import featurize, SEED
RDLogger.DisableLog("rdApp.*")

MMPS = ["mmp1", "mmp2", "mmp3", "mmp9", "mmp13"]
CAND = "results/mmp13_inhibitor_candidates/candidates_all.csv"
OUTDIR = "candidates/mmp13_inhibitor"
import os; os.makedirs(OUTDIR, exist_ok=True)

print("training per-MMP potency models ...")
models = {}
for m in MMPS:
    df = pd.read_csv(f"data/calibration/{m}_ic50.csv")[["canonical_smiles", "pIC50_median"]].dropna()
    X, ok = featurize(df["canonical_smiles"])
    models[m] = RandomForestRegressor(n_estimators=400, random_state=SEED, n_jobs=-1).fit(
        X, df["pIC50_median"].to_numpy()[ok])

cand = pd.read_csv(CAND)
cand["canon"] = cand["smiles"].map(lambda s: Chem.MolToSmiles(Chem.MolFromSmiles(s)) if Chem.MolFromSmiles(s) else None)
cand = cand.dropna(subset=["canon"]).drop_duplicates("canon").reset_index(drop=True)
Xc, okc = featurize(cand["smiles"]); cand = cand[okc].reset_index(drop=True)
for m in MMPS:
    cand[f"pIC50_{m}"] = np.round(models[m].predict(Xc), 2)
cand["spare_MMP1"] = np.round(cand["pIC50_mmp13"] - cand["pIC50_mmp1"], 2)       # >0 spares MMP-1
cand["min_offtarget_sel"] = np.round(cand["pIC50_mmp13"] - cand[["pIC50_mmp1","pIC50_mmp2","pIC50_mmp3","pIC50_mmp9"]].max(axis=1), 2)

OBJ = ["pIC50_mmp13", "spare_MMP1", "druglikeness_qed"]
O = cand[OBJ].to_numpy(dtype=float)
nd = np.ones(len(O), bool)
for i in range(len(O)):
    d = O - O[i]
    if ((d >= -1e-9).all(axis=1) & (d > 1e-9).any(axis=1)).any():
        nd[i] = False
cand["pareto"] = nd
front = cand[nd].sort_values(["pIC50_mmp13", "spare_MMP1"], ascending=False).reset_index(drop=True)
cand.to_csv(f"{OUTDIR}/candidates_profiled.csv", index=False)
front.to_csv(f"{OUTDIR}/pareto_front.csv", index=False)
print(f"pool {len(cand)} -> Pareto front {len(front)}")
cols = ["id", "pIC50_mmp13", "pIC50_mmp1", "spare_MMP1", "druglikeness_qed", "n_chelators", "struct_alerts"]
print(front[cols].round(3).to_string(index=False))

import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(6.5, 5))
sc = ax.scatter(cand.pIC50_mmp13, cand.spare_MMP1, c=cand.druglikeness_qed, cmap="viridis", s=22, alpha=0.6)
ax.scatter(front.pIC50_mmp13, front.spare_MMP1, facecolors="none", edgecolors="red", s=90, linewidths=1.4,
           label=f"Pareto front (n={len(front)})")
ax.axhline(0, color="gray", ls="--", lw=0.7)
ax.set_xlabel("predicted MMP-13 pIC50  (potency →)")
ax.set_ylabel("MMP-1 sparing = pIC50(MMP-13) − pIC50(MMP-1)  (spares MMP-1 ↑)")
ax.set_title("OA-profile MMP-13 candidates: potency vs MMP-1 sparing\ncolour = QED; red = non-dominated")
plt.colorbar(sc, label="QED"); ax.legend(fontsize=8); fig.tight_layout()
fig.savefig(f"{OUTDIR}/pareto_front.png", dpi=120)
print(f"wrote {OUTDIR}/pareto_front.{{csv,png}} + candidates_profiled.csv")

n_good = int(((cand.pIC50_mmp13 >= 7) & (cand.spare_MMP1 > 0)).sum())
L = ["# OA-profile candidates — potent MMP-13, MMP-1-sparing\n",
     "Re-aimed objective (opposite of the mmp1_inhibitor run): inhibit **MMP-13** "
     "(cartilage collagenase, the osteoarthritis target) while **sparing MMP-1** "
     "(systemic MMP-1 inhibition caused the musculoskeletal toxicity that sank "
     "first-gen MMP drugs).\n",
     f"- pool {len(cand)} in-domain candidates; **{n_good}** predicted potent MMP-13 (pIC50≥7) AND MMP-1-sparing (>0); **{len(front)}** Pareto-optimal.\n",
     "| id | pIC50 MMP-13 | pIC50 MMP-1 | MMP-1 sparing | QED | #ZBG | alerts |",
     "|" + "---|" * 7]
for r in front.itertuples():
    L.append(f"| {r.id} | {r.pIC50_mmp13:.2f} | {r.pIC50_mmp1:.2f} | {r.spare_MMP1:+.2f} | "
             f"{r.druglikeness_qed:.2f} | {int(r.n_chelators)} | {int(r.struct_alerts)} |")
L.append("\nPredictions are QSAR triage, not measurements. Confirm in vitro (MMP-13 IC50 + MMP-1 counter-screen).")
open(f"{OUTDIR}/PARETO.md", "w").write("\n".join(L))
print("wrote PARETO.md")
