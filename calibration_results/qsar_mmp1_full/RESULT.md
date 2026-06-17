# Calibration gate — MMP-1 inhibitor QSAR, FULL drug-discovery scope

## VERDICT: GO (strong) — validated drug-discovery MMP-1 inhibitor ranker

Trained on the FULL public ChEMBL MMP-1 IC50 set (1,976 molecules, all chemotypes
— not the 237-compound cosmetic peptidomimetic subset). This is the drug-discovery
asset: rank arbitrary small-molecule MMP-1 inhibitors by potency.

| metric | value |
|---|---|
| model (train-CV selected) | RandomForest on Morgan FP(2048) + 10 descriptors |
| held-out Spearman ρ | **+0.852** (p≈1e-112, n=395) |
| held-out Pearson r / R² / RMSE | +0.86 / 0.74 / 0.57 pIC50 |
| **scaffold-split CV Spearman** (GroupKFold, 752 Murcko scaffolds) | **+0.725** |
| GO bar | ρ ≥ 0.4, p < 0.01 ✓ (far exceeded) |

## Context
| scope | n | held-out ρ | scaffold-split ρ |
|---|---|---|---|
| cosmetic peptidomimetic subset | 237 | +0.47 | +0.475 |
| **full MMP-1 inhibitor set** | **1,976** | **+0.85** | **+0.73** |

More data + wider chemical/potency diversity make it both stronger and
broader-domain. The 752-scaffold cross-validation at ρ=0.73 means it ranks
genuinely novel chemotypes well — so its applicability domain spans real
medicinal-chemistry space, not just one congeneric series.

## What this changes
- This is a legitimate, honestly-validated **drug-discovery** MMP-1 inhibitor
  scoring model (not cosmetic — see LIMITATIONS.md for that distinction).
- Its broad domain means candidate GENERATION can now explore novel chemotypes
  in-domain (the cosmetic arm couldn't — its 237-compound domain was too tight).
- Reproduce: `python qsar_baseline.py --csv data/calibration/mmp1_ic50.csv --outdir calibration_results/qsar_mmp1_full`

## Honest notes
- Still a data-driven model: trustworthy within the (now broad) ChEMBL MMP-1
  chemical space; flag out-of-domain candidates.
- IC50 aggregated as median pIC50 per molecule across assays (some inter-assay
  noise). pIC50 spans the full ChEMBL MMP-1 range.
