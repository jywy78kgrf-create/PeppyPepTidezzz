"""QSAR baseline / "is this set even rankable?" control.

NOT a production scorer: a QSAR model needs measured labels FOR THIS TARGET to
train, so it can't score genuinely novel chemotypes the way docking/Boltz aim to.
Its job here is a control: if a model trained on the 237 measured pIC50s can rank
a held-out fold, the calibration set IS rankable and the docking/Boltz failures
are about those methods; if even this fails, the benchmark itself is the problem.

Discipline (no leakage):
  - SAME deterministic held-out split as AutoDock/Boltz (seed 1234, 20%).
  - Model + hyperparameters chosen by cross-validation on the TRAIN fold ONLY.
  - The held-out 47 is scored EXACTLY ONCE, at the end.
  - Plus a scaffold-split CV (Bemis-Murcko GroupKFold) = the honest test of
    generalisation to unseen chemotypes (what matters for ranking novel candidates).
Deterministic: fixed seeds throughout.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import spearmanr, pearsonr
from rdkit import Chem, RDLogger
from rdkit.Chem import AllChem, Descriptors, rdMolDescriptors
from rdkit.Chem.Scaffolds import MurckoScaffold
from sklearn.model_selection import cross_val_score, KFold, GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.svm import SVR
from sklearn.neighbors import KNeighborsRegressor
from sklearn.metrics import r2_score, mean_squared_error

RDLogger.DisableLog("rdApp.*")
SEED = 42
CFG_CSV = "peptidepipe/configs/mmp1_cosmetic/calibration/peptidomimetic.csv"
OUT = Path("calibration_results/qsar"); OUT.mkdir(parents=True, exist_ok=True)

DESC = [("MolWt", Descriptors.MolWt), ("LogP", Descriptors.MolLogP),
        ("TPSA", Descriptors.TPSA), ("HBD", rdMolDescriptors.CalcNumHBD),
        ("HBA", rdMolDescriptors.CalcNumHBA), ("RotB", rdMolDescriptors.CalcNumRotatableBonds),
        ("ArRings", rdMolDescriptors.CalcNumAromaticRings), ("FracCsp3", rdMolDescriptors.CalcFractionCSP3),
        ("HeavyAtoms", lambda m: m.GetNumHeavyAtoms()), ("Rings", rdMolDescriptors.CalcNumRings)]


def featurize(smiles):
    """Morgan fingerprint (2048b, r=2) + 10 physchem descriptors."""
    X, ok = [], []
    for s in smiles:
        m = Chem.MolFromSmiles(s)
        if m is None:
            ok.append(False); continue
        fp = AllChem.GetMorganFingerprintAsBitVect(m, 2, nBits=2048)
        arr = np.zeros(2048, dtype=np.int8); Chem.DataStructs.ConvertToNumpyArray(fp, arr)
        d = np.array([f(m) for _, f in DESC], dtype=float)
        X.append(np.concatenate([arr, d])); ok.append(True)
    return np.array(X), np.array(ok)


def heldout_ids(df, id_col, seed=1234, frac=0.2):
    rng = np.random.default_rng(seed); idx = np.arange(len(df)); rng.shuffle(idx)
    n = max(1, int(round(len(df) * frac)))
    return {str(df.iloc[i][id_col]) for i in sorted(idx[:n])}


def murcko(s):
    m = Chem.MolFromSmiles(s)
    try:
        return MurckoScaffold.MurckoScaffoldSmiles(mol=m) if m else "?"
    except Exception:
        return "?"


def spearman(a, b):
    return spearmanr(a, b).correlation


def main():
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=CFG_CSV, help="calibration CSV (id, SMILES, pIC50)")
    ap.add_argument("--outdir", default=str(OUT))
    args = ap.parse_args()
    OUT = Path(args.outdir); OUT.mkdir(parents=True, exist_ok=True)
    print(f"calibration set: {args.csv}")
    df = pd.read_csv(args.csv)[["molecule_chembl_id", "canonical_smiles", "pIC50_median"]].dropna().reset_index(drop=True)
    X, ok = featurize(df["canonical_smiles"])
    df = df[ok].reset_index(drop=True)
    y = df["pIC50_median"].to_numpy()
    test_ids = heldout_ids(df, "molecule_chembl_id")
    is_test = df["molecule_chembl_id"].astype(str).isin(test_ids).to_numpy()
    Xtr, ytr = X[~is_test], y[~is_test]
    Xte, yte = X[is_test], y[is_test]
    print(f"featurized {len(df)} molecules | train {len(Xtr)} | held-out {len(Xte)}")

    # --- model selection: 5-fold CV on TRAIN ONLY, scored by Spearman ---
    models = {
        "Ridge": make_pipeline(StandardScaler(), Ridge(alpha=10.0, random_state=SEED)),
        "RandomForest": RandomForestRegressor(n_estimators=400, random_state=SEED, n_jobs=-1),
        "GradBoost": GradientBoostingRegressor(random_state=SEED),
        "SVR": make_pipeline(StandardScaler(), SVR(C=5.0, gamma="scale")),
        "kNN": make_pipeline(StandardScaler(), KNeighborsRegressor(n_neighbors=5)),
    }
    cv = KFold(n_splits=5, shuffle=True, random_state=SEED)
    scorer = lambda est, Xv, yv: spearman(yv, est.predict(Xv))
    cv_scores = {name: float(np.mean(cross_val_score(m, Xtr, ytr, cv=cv, scoring=scorer)))
                 for name, m in models.items()}
    print("\n--- 5-fold CV Spearman on TRAIN (model selection) ---")
    for name, s in sorted(cv_scores.items(), key=lambda x: -x[1]):
        print(f"  {name:14s} {s:+.3f}")
    best = max(cv_scores, key=cv_scores.get)
    print(f"selected by train-CV: {best}")

    # --- refit chosen model on full train, score held-out ONCE ---
    model = models[best]; model.fit(Xtr, ytr)
    pred = model.predict(Xte)
    rho, p = spearmanr(pred, yte)
    pear = pearsonr(pred, yte)[0]
    rmse = mean_squared_error(yte, pred) ** 0.5

    # --- honest generalisation: scaffold-split CV on ALL data (GroupKFold) ---
    groups = df["canonical_smiles"].map(murcko).to_numpy()
    n_scaf = len(set(groups))
    gkf = GroupKFold(n_splits=5)
    scaf_scores = cross_val_score(models[best], X, y, cv=gkf, groups=groups, scoring=scorer)
    scaf_rho = float(np.mean(scaf_scores))

    print("\n=== QSAR BASELINE RESULT ===")
    print(f"model                         : {best}")
    print(f"held-out Spearman rho         : {rho:+.4f}  (p={p:.2e}, n={len(yte)})  <- compare to AD4Zn/Boltz")
    print(f"held-out Pearson r            : {pear:+.4f}")
    print(f"held-out R^2 / RMSE           : {r2_score(yte,pred):+.3f} / {rmse:.3f} pIC50")
    print(f"scaffold-split CV Spearman    : {scaf_rho:+.4f}  ({n_scaf} Murcko scaffolds, GroupKFold)  <- novel-chemotype test")
    print(f"(reference: AutoDock4Zn held-out -0.025 ; Boltz-2 held-out +0.17)")

    out = pd.DataFrame({"id": df.loc[is_test, "molecule_chembl_id"].values,
                        "measured": yte, "predicted": pred})
    out.to_csv(OUT / "predicted_vs_actual.csv", index=False)
    json.dump({"model": best, "cv_spearman_train": cv_scores,
               "heldout_spearman": float(rho), "heldout_pvalue": float(p),
               "heldout_pearson": float(pear), "heldout_r2": float(r2_score(yte, pred)),
               "heldout_rmse": float(rmse), "scaffold_cv_spearman": scaf_rho,
               "n_train": int(len(Xtr)), "n_test": int(len(Xte)), "n_scaffolds": n_scaf,
               "seed_split": 1234, "seed_model": SEED},
              open(OUT / "metrics.json", "w"), indent=2)
    _plot(yte, pred, best, rho, OUT / "predicted_vs_actual.png")
    print(f"\nwrote {OUT}/predicted_vs_actual.csv, metrics.json, predicted_vs_actual.png")


def _plot(yte, pred, model, rho, path):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.scatter(pred, yte, s=28, alpha=0.8, edgecolor="k", linewidth=0.4)
    lo = min(pred.min(), yte.min()); hi = max(pred.max(), yte.max())
    ax.plot([lo, hi], [lo, hi], "--", color="gray", linewidth=0.8)
    ax.set_xlabel(f"QSAR predicted pIC50 ({model})"); ax.set_ylabel("measured pIC50")
    ax.set_title(f"QSAR baseline: held-out\nSpearman rho = {rho:.3f} (n={len(yte)})")
    fig.tight_layout(); fig.savefig(path, dpi=120); plt.close(fig)


if __name__ == "__main__":
    main()
