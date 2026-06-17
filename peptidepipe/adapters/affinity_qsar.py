"""QSAR affinity adapter — the calibration-VALIDATED CPU scorer.

Gate result: held-out Spearman +0.47 (p<0.001), scaffold-split +0.475 — the only
scorer that cleared the gate (AutoDock -0.03, Boltz +0.17).

Trainable: prepare() fits on the target's calibration labels; score() predicts
pIC50 from SMILES AND reports the applicability domain (max Tanimoto to the
training set + an in_domain flag), so candidate generation can be domain-guarded.
This is a data-driven INTERPOLATOR, trustworthy only within its training chemistry
— the AD signal is what enforces that. Model/features are exactly those validated
in the gate: GradientBoosting on Morgan FP(2048) + 10 physchem descriptors.

For production scoring it trains on ALL calibration rows (the 190/47 split was the
validation; deployment uses all labels). No target literals: everything comes from
the TargetSpec the config supplies.
"""
from __future__ import annotations
import numpy as np

from peptidepipe.core.candidate import Candidate
from peptidepipe.core.targetspec import TargetSpec
from peptidepipe.core.scoring.affinity_base import AffinityScorer, AffinityResult
from peptidepipe.core.scoring.registry import register


def _descriptors():
    from rdkit.Chem import Descriptors, rdMolDescriptors
    return [Descriptors.MolWt, Descriptors.MolLogP, Descriptors.TPSA,
            rdMolDescriptors.CalcNumHBD, rdMolDescriptors.CalcNumHBA,
            rdMolDescriptors.CalcNumRotatableBonds, rdMolDescriptors.CalcNumAromaticRings,
            rdMolDescriptors.CalcFractionCSP3, lambda m: m.GetNumHeavyAtoms(),
            rdMolDescriptors.CalcNumRings]


@register("qsar")
class QSARAffinity(AffinityScorer):
    def prepare(self, target: TargetSpec) -> None:
        import pandas as pd
        from rdkit import Chem, RDLogger
        from sklearn.ensemble import GradientBoostingRegressor
        RDLogger.DisableLog("rdApp.*")
        self._desc = _descriptors()
        seed = int(self.params.get("seed", 42))

        from rdkit.Chem.Scaffolds import MurckoScaffold
        df = pd.read_csv(target.resolve(target.calibration_csv))[
            [target.smiles_col, target.affinity_col]].dropna()
        X, y, self.train_fps, scaf = [], [], [], []
        for _, r in df.iterrows():
            m = Chem.MolFromSmiles(str(r[target.smiles_col]))
            if m is None:
                continue
            X.append(self._feat(m)); y.append(float(r[target.affinity_col]))
            self.train_fps.append(self._fp(m))
            try:
                scaf.append(MurckoScaffold.MurckoScaffoldSmiles(mol=m))
            except Exception:
                scaf.append("?")
        self.model = GradientBoostingRegressor(random_state=seed).fit(np.array(X), np.array(y))

        # applicability-domain threshold = low percentile of each active's max
        # Tanimoto to actives of a DIFFERENT Murcko scaffold. This is the
        # cross-scaffold similarity regime over which the model was actually
        # validated (scaffold-split CV ρ=0.475), so it is the honest floor for
        # trusting a prediction -- not the (much stricter) internal nearest
        # neighbour, which would reject any candidate that isn't a near-twin.
        from rdkit import DataStructs
        cross = []
        for i, fp in enumerate(self.train_fps):
            others = [self.train_fps[j] for j in range(len(self.train_fps)) if scaf[j] != scaf[i]]
            if others:                                   # C-level bulk Tanimoto (fast on big sets)
                cross.append(max(DataStructs.BulkTanimotoSimilarity(fp, others)))
        pct = float(self.params.get("ad_percentile", 10))
        self.ad_threshold = float(np.percentile(cross, pct)) if cross else 0.3

    # ---- features ----
    def _feat(self, mol):
        from rdkit.Chem import AllChem
        from rdkit import Chem, DataStructs
        fp = AllChem.GetMorganFingerprintAsBitVect(mol, 2, nBits=2048)
        arr = np.zeros(2048, dtype=np.int8); DataStructs.ConvertToNumpyArray(fp, arr)
        d = np.array([f(mol) for f in self._desc], dtype=float)
        return np.concatenate([arr, d])

    def _fp(self, mol):
        from rdkit.Chem import AllChem
        return AllChem.GetMorganFingerprintAsBitVect(mol, 2, nBits=2048)

    def _max_tanimoto(self, mol):
        from rdkit import DataStructs
        sims = DataStructs.BulkTanimotoSimilarity(self._fp(mol), self.train_fps)
        return float(max(sims)) if sims else 0.0

    # ---- scoring ----
    def score(self, candidate: Candidate) -> AffinityResult:
        from rdkit import Chem
        m = Chem.MolFromSmiles(candidate.smiles)
        if m is None:
            return AffinityResult(candidate.id, float("nan"), ok=False, note="bad SMILES")
        pred = float(self.model.predict(self._feat(m).reshape(1, -1))[0])
        ad = self._max_tanimoto(m)
        return AffinityResult(candidate.id, score=pred, raw={
            "pIC50": pred, "max_tanimoto": ad, "in_domain": ad >= self.ad_threshold,
            "ad_threshold": self.ad_threshold})
