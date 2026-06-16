# Calibration gate — MMP-1, QSAR baseline (control)

## VERDICT: GO (passes the gate) — and the set IS rankable

A QSAR model trained on the 237 measured pIC50s clears the pre-registered bar on
the SAME held-out fold AutoDock and Boltz were judged on.

| metric | value |
|---|---|
| model (selected by TRAIN-only 5-fold CV) | GradientBoosting on Morgan FP(2048) + 10 physchem descriptors |
| train 5-fold CV Spearman | +0.615 |
| **held-out Spearman ρ** | **+0.473  (p = 7.8e-4, n = 47)** |
| held-out Pearson r | +0.52 |
| held-out R² / RMSE | +0.26 / 0.76 pIC50 |
| **scaffold-split CV Spearman** (GroupKFold, 120 Murcko scaffolds) | **+0.475** |
| pre-registered GO bar | ρ ≥ 0.4, p < 0.01 ✓ |

### Head-to-head on the identical held-out fold
| scorer | held-out ρ |
|---|---|
| **QSAR (GradBoost)** | **+0.47** |
| Boltz-2 | +0.17 |
| AutoDock4Zn | −0.025 |

## Why this matters

1. **The benchmark is fine — it's rankable.** A label-trained model reaches ρ≈0.47.
   So the AutoDock (−0.03) and Boltz (+0.17) failures are about *those methods*, not
   noisy/unrankable data.
2. **It generalises to unseen chemotypes.** The scaffold-split CV (+0.475) ≈ the
   random held-out (+0.473), so the signal is real SAR, not memorising close analogs.

## Method / no-leakage discipline
- Same deterministic split as the other scorers (seed 1234, 190 train / 47 test).
- Model + hyperparameters chosen by 5-fold CV on the TRAIN fold ONLY; the held-out
  47 scored exactly once. Fixed seeds (split 1234, model 42) -> reproducible.

## Important caveat (what QSAR is and isn't)
QSAR is NOT a universal binding predictor like docking/Boltz aim to be — it is a
data-driven *interpolator* with an applicability domain. It is a valid, gate-passing
scorer for candidates that resemble the 237-compound training chemistry (the
scaffold-split shows it holds across the scaffolds present here). For genuinely
novel chemotypes far outside that space, its reliability drops and predictions
should be treated as out-of-domain. Candidate generation using QSAR must therefore
be applicability-domain-guarded (flag/penalise candidates dissimilar to the
training set), or QSAR used in consensus with other evidence.
