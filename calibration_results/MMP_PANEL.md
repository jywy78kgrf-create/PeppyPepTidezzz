# Pan-MMP inhibitor QSAR — panel validation (drug-discovery scope)

Same QSAR recipe (Morgan FP + descriptors; model chosen by train-CV; held-out
scored once; scaffold-split GroupKFold for novel-chemotype generalisation) applied
across the MMP family. ChEMBL IC50 data, median pIC50 per molecule.

| target | ChEMBL | molecules | held-out Spearman ρ | scaffold-split ρ (# scaffolds) |
|---|---|---|---|---|
| MMP-1 (interstitial collagenase) | CHEMBL332 | 1,976 | **+0.85** | +0.73 (752) |
| MMP-2 (gelatinase A)             | CHEMBL333 | 3,127 | **+0.86** | +0.75 (1217) |
| MMP-3 (stromelysin-1)            | CHEMBL283 | 1,333 | **+0.83** | +0.76 (630) |
| MMP-9 (gelatinase B)             | CHEMBL321 | 2,086 | **+0.83** | +0.74 (900) |
| MMP-13 (collagenase-3)           | CHEMBL280 | 2,522 | **+0.81** | +0.76 (1043) |

GO bar (ρ ≥ 0.4, p < 0.01): cleared by a wide margin on every target, including the
scaffold-novelty test. This is a validated, generalisable **drug-discovery
MMP-inhibitor ranking model** across the family — not a single-target fluke.

Reference (MMP-1, same held-out fold): AutoDock4Zn −0.03, Boltz-2 +0.17, QSAR +0.85.

## What this enables
- Rank candidate MMP inhibitors by predicted potency for any of these 5 targets.
- **Selectivity** work: many compounds are tested against multiple MMPs, so
  per-target models support predicting MMP-1-vs-MMP-X selectivity — the property
  whose neglect (broad-spectrum chelators) sank the first generation of MMP drugs.
- Candidate generation can now explore a broad in-domain chemical space (thousands
  of scaffolds), unlike the narrow cosmetic peptidomimetic arm.

Per-target artifacts: calibration_results/qsar_mmp{1_full,2,3,9,13}/.
