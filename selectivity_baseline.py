"""Selectivity QSAR — predict MMP-1-vs-X selectivity directly (drug-discovery).

For each MMP-1 / MMP-X pair, target = ΔpIC50 = pIC50(MMP-1) − pIC50(MMP-X) on the
compounds tested against BOTH (positive = MMP-1-selective). Modelling the
difference directly is the honest test of whether selectivity is learnable (vs
subtracting two noisy single-target predictions). Same discipline as the potency
QSAR: model chosen by TRAIN-only CV, held-out scored once, scaffold-split for
novel-chemotype generalisation. Fixed seeds.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.model_selection import cross_val_score, KFold, GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.svm import SVR
from sklearn.neighbors import KNeighborsRegressor

from qsar_baseline import featurize, heldout_ids, murcko, spearman, SEED

PAIRS = [("mmp1", "mmp2"), ("mmp1", "mmp3"), ("mmp1", "mmp9"), ("mmp1", "mmp13")]
OUT = Path("calibration_results/selectivity"); OUT.mkdir(parents=True, exist_ok=True)


def load_pair(a, b):
    da = pd.read_csv(f"data/calibration/{a}_ic50.csv").set_index("molecule_chembl_id")
    db = pd.read_csv(f"data/calibration/{b}_ic50.csv").set_index("molecule_chembl_id")
    common = da.index.intersection(db.index)
    return pd.DataFrame({
        "molecule_chembl_id": list(common),
        "smiles": da.loc[common, "canonical_smiles"].values,
        "delta": (da.loc[common, "pIC50_median"] - db.loc[common, "pIC50_median"]).values,
    })


def models():
    return {
        "Ridge": make_pipeline(StandardScaler(), Ridge(alpha=10.0, random_state=SEED)),
        "RandomForest": RandomForestRegressor(n_estimators=400, random_state=SEED, n_jobs=-1),
        "GradBoost": GradientBoostingRegressor(random_state=SEED),
        "SVR": make_pipeline(StandardScaler(), SVR(C=5.0, gamma="scale")),
        "kNN": make_pipeline(StandardScaler(), KNeighborsRegressor(n_neighbors=5)),
    }


def run_pair(a, b):
    df = load_pair(a, b)
    X, ok = featurize(df["smiles"]); df = df[ok].reset_index(drop=True); y = df["delta"].to_numpy()
    test_ids = heldout_ids(df, "molecule_chembl_id")
    is_test = df["molecule_chembl_id"].astype(str).isin(test_ids).to_numpy()
    Xtr, ytr, Xte, yte = X[~is_test], y[~is_test], X[is_test], y[is_test]

    cv = KFold(5, shuffle=True, random_state=SEED)
    scorer = lambda est, Xv, yv: spearman(yv, est.predict(Xv))
    cvs = {n: float(np.mean(cross_val_score(m, Xtr, ytr, cv=cv, scoring=scorer)))
           for n, m in models().items()}
    best = max(cvs, key=cvs.get)
    mdl = models()[best]; mdl.fit(Xtr, ytr); pred = mdl.predict(Xte)
    rho, p = spearmanr(pred, yte)

    groups = df["smiles"].map(murcko).to_numpy()
    scaf_rho = float(np.mean(cross_val_score(models()[best], X, y,
                     cv=GroupKFold(5), groups=groups, scoring=scorer)))
    res = {"pair": f"{a.upper()}-{b.upper()}", "n": int(len(df)), "model": best,
           "heldout_spearman": float(rho), "heldout_p": float(p),
           "scaffold_cv_spearman": scaf_rho, "n_scaffolds": int(len(set(groups))),
           "delta_mean": float(np.mean(y)), "delta_sd": float(np.std(y))}
    pd.DataFrame({"id": df.loc[is_test, "molecule_chembl_id"].values,
                  "measured_delta": yte, "predicted_delta": pred}
                 ).to_csv(OUT / f"{a}_vs_{b}_heldout.csv", index=False)
    return res


def main():
    rows = []
    for a, b in PAIRS:
        r = run_pair(a, b); rows.append(r)
        print(f"{r['pair']:11s} n={r['n']:4d} model={r['model']:12s} "
              f"held-out ρ={r['heldout_spearman']:+.3f} (p={r['heldout_p']:.1e}) "
              f"scaffold ρ={r['scaffold_cv_spearman']:+.3f} ({r['n_scaffolds']} scaf)", flush=True)
    json.dump(rows, open(OUT / "selectivity_metrics.json", "w"), indent=2)
    print(f"\nwrote {OUT}/selectivity_metrics.json + per-pair held-out CSVs")


if __name__ == "__main__":
    main()
