"""Generic selectivity + Pareto frontier for generated candidates.

Profiles candidates with per-target QSAR potency models, computes selectivity of
the primary target over its off-targets, and finds the non-dominated front over
  [ target potency, min selectivity over off-targets, QED ]   (all maximised).
Usage:
  python frontier.py --candidates results/X/candidates_all.csv \
                     --target hdac6 --offtargets hdac1,hdac2,hdac3 \
                     --outdir candidates/hdac6_inhibitor --label "HDAC6-selective"
"""
import argparse, numpy as np, pandas as pd, os
from rdkit import Chem, RDLogger
from sklearn.ensemble import RandomForestRegressor
from qsar_baseline import featurize, SEED
RDLogger.DisableLog("rdApp.*")

ap = argparse.ArgumentParser()
ap.add_argument("--candidates", required=True)
ap.add_argument("--target", required=True)
ap.add_argument("--offtargets", required=True)   # comma-separated
ap.add_argument("--outdir", required=True)
ap.add_argument("--label", default="")
args = ap.parse_args()
offs = args.offtargets.split(",")
names = [args.target] + offs
os.makedirs(args.outdir, exist_ok=True)

print(f"training potency models: {names}")
models = {}
for m in names:
    df = pd.read_csv(f"data/calibration/{m}_ic50.csv")[["canonical_smiles", "pIC50_median"]].dropna()
    X, ok = featurize(df["canonical_smiles"])
    models[m] = RandomForestRegressor(n_estimators=400, random_state=SEED, n_jobs=-1).fit(
        X, df["pIC50_median"].to_numpy()[ok])

cand = pd.read_csv(args.candidates)
cand["canon"] = cand["smiles"].map(lambda s: Chem.MolToSmiles(Chem.MolFromSmiles(s)) if Chem.MolFromSmiles(s) else None)
cand = cand.dropna(subset=["canon"]).drop_duplicates("canon").reset_index(drop=True)
Xc, okc = featurize(cand["smiles"]); cand = cand[okc].reset_index(drop=True)
for m in names:
    cand[f"pIC50_{m}"] = np.round(models[m].predict(Xc), 2)
cand["selectivity"] = np.round(cand[f"pIC50_{args.target}"] - cand[[f"pIC50_{o}" for o in offs]].max(axis=1), 2)

OBJ = [f"pIC50_{args.target}", "selectivity", "druglikeness_qed"]
O = cand[OBJ].to_numpy(dtype=float)
nd = np.ones(len(O), bool)
for i in range(len(O)):
    d = O - O[i]
    if ((d >= -1e-9).all(axis=1) & (d > 1e-9).any(axis=1)).any():
        nd[i] = False
cand["pareto"] = nd
front = cand[nd].sort_values([f"pIC50_{args.target}", "selectivity"], ascending=False).reset_index(drop=True)
cand.to_csv(f"{args.outdir}/candidates_profiled.csv", index=False)
front.to_csv(f"{args.outdir}/pareto_front.csv", index=False)
print(f"pool {len(cand)} -> Pareto front {len(front)}")
cols = ["id", f"pIC50_{args.target}"] + [f"pIC50_{o}" for o in offs] + ["selectivity", "druglikeness_qed", "n_chelators", "struct_alerts"]
print(front[cols].round(3).head(15).to_string(index=False))

import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(6.5, 5))
sc = ax.scatter(cand[f"pIC50_{args.target}"], cand.selectivity, c=cand.druglikeness_qed, cmap="viridis", s=20, alpha=0.6)
ax.scatter(front[f"pIC50_{args.target}"], front.selectivity, facecolors="none", edgecolors="red", s=85, linewidths=1.3,
           label=f"Pareto front (n={len(front)})")
ax.axhline(0, color="gray", ls="--", lw=0.7)
ax.set_xlabel(f"predicted {args.target.upper()} pIC50  (potency →)")
ax.set_ylabel(f"selectivity vs {','.join(o.upper() for o in offs)}  (↑ = {args.target.upper()}-selective)")
ax.set_title(f"{args.label or args.target.upper()} candidates: potency vs selectivity\ncolour = QED; red = non-dominated")
plt.colorbar(sc, label="QED"); ax.legend(fontsize=8); fig.tight_layout()
fig.savefig(f"{args.outdir}/pareto_front.png", dpi=120)

n_good = int(((cand[f"pIC50_{args.target}"] >= 7) & (cand.selectivity > 0)).sum())
L = [f"# {args.label or args.target.upper()} candidates — Pareto frontier\n",
     f"Objective: potent **{args.target.upper()}**, selective over **{', '.join(o.upper() for o in offs)}**, drug-like (QED).\n",
     f"- pool {len(cand)} in-domain; **{n_good}** predicted potent ({args.target.upper()} pIC50≥7) AND selective (>0); **{len(front)}** Pareto-optimal.\n",
     "| id | pIC50 " + args.target.upper() + " | selectivity | QED | #ZBG | alerts |",
     "|" + "---|" * 6]
for r in front.head(20).itertuples():
    L.append(f"| {r.id} | {getattr(r, f'pIC50_{args.target}'):.2f} | {r.selectivity:+.2f} | "
             f"{r.druglikeness_qed:.2f} | {int(r.n_chelators)} | {int(r.struct_alerts)} |")
L.append("\nPredictions are QSAR triage, not measurements. Confirm in vitro (target IC50 + off-target counter-screen).")
open(f"{args.outdir}/PARETO.md", "w").write("\n".join(L))
print(f"wrote {args.outdir}/pareto_front.{{csv,png}}, candidates_profiled.csv, PARETO.md")
