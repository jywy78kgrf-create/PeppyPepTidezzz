"""Integrate Option 1 (selectivity) + Option 2 (generation): give each generated
candidate a full predicted potency profile across MMP-1/2/3/9/13 and the resulting
MMP-1 selectivity. Uses the per-target potency models (each trained on its full
ChEMBL set, broad domain) and takes differences -> a candidate's MMP-1-vs-X
selectivity. The deliverable: novel candidates triaged by potency AND selectivity.
"""
import pandas as pd, numpy as np
from sklearn.ensemble import RandomForestRegressor
from qsar_baseline import featurize, SEED

MMPS = ["mmp1", "mmp2", "mmp3", "mmp9", "mmp13"]
CAND = "results/mmp1_inhibitor_candidates/candidates_all.csv"
OUT = "results/mmp1_inhibitor_candidates/candidates_profiled.csv"

print("training per-MMP potency models (full sets) ...")
models = {}
for m in MMPS:
    df = pd.read_csv(f"data/calibration/{m}_ic50.csv")[["canonical_smiles", "pIC50_median"]].dropna()
    X, ok = featurize(df["canonical_smiles"])
    models[m] = RandomForestRegressor(n_estimators=400, random_state=SEED, n_jobs=-1).fit(
        X, df["pIC50_median"].to_numpy()[ok])
    print(f"  {m}: trained on {ok.sum()} molecules")

cand = pd.read_csv(CAND)
Xc, okc = featurize(cand["smiles"])
cand = cand[okc].reset_index(drop=True)
for m in MMPS:
    cand[f"pIC50_{m}"] = np.round(models[m].predict(Xc), 2)
for m in ["mmp2", "mmp3", "mmp9", "mmp13"]:
    cand[f"sel_vs_{m}"] = np.round(cand["pIC50_mmp1"] - cand[f"pIC50_{m}"], 2)
sel_cols = [f"sel_vs_{m}" for m in ["mmp2", "mmp3", "mmp9", "mmp13"]]
cand["min_MMP1_selectivity"] = cand[sel_cols].min(axis=1)        # worst-case MMP-1 preference
cand["potent_and_MMP1_selective"] = (cand["pIC50_mmp1"] >= 7.0) & (cand["min_MMP1_selectivity"] > 0)

cand = cand.sort_values(["potent_and_MMP1_selective", "pIC50_mmp1", "min_MMP1_selectivity"],
                        ascending=False).reset_index(drop=True)
cand.to_csv(OUT, index=False)

print(f"\ncandidates profiled: {len(cand)}")
print(f"predicted potent (MMP-1 pIC50>=7): {(cand.pIC50_mmp1>=7).sum()}")
print(f"potent AND MMP-1-selective over ALL of MMP-2/3/9/13: {cand.potent_and_MMP1_selective.sum()}")
cols = ["id", "pIC50_mmp1", "pIC50_mmp2", "pIC50_mmp3", "pIC50_mmp9", "pIC50_mmp13",
        "min_MMP1_selectivity", "struct_alerts", "applicability_tanimoto"]
pd.set_option("display.width", 170)
print("\n=== top candidates by MMP-1 potency + selectivity ===")
print(cand.head(12)[cols].to_string(index=False))
print(f"\nwrote {OUT}")
