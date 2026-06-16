# MMP-1 calibration gate — overall conclusion

All scorers judged on the SAME 237-compound set and the SAME held-out fold
(seed 1234, 190 train / 47 test).

| scorer | held-out Spearman ρ | passes gate? |
|---|---|---|
| AutoDock4Zn (CPU, zinc-aware docking) | −0.025 | NO |
| Boltz-2 (GPU, co-folding affinity model) | +0.17 (p≈0.25) | NO |
| **QSAR (GradBoost on FP+descriptors, trained on the labels)** | **+0.47 (p<0.001)** | **YES** |

GO bar (pre-registered): ρ ≥ 0.4, p < 0.01.

## Findings
1. **The calibration set is rankable.** QSAR clears the gate AND holds on a
   scaffold-novelty split (ρ≈0.475), so it's real SAR, not analog memorisation.
2. **Structure-based / co-folding scorers fail here.** AutoDock (even at thorough
   GA convergence) ≈ 0; Boltz-2 weakly positive but not significant. The problem
   was the methods, not the benchmark.
3. **A data-driven scorer passes** — so the pipeline CAN proceed, with QSAR as the
   affinity term, provided candidate generation is constrained to QSAR's
   applicability domain (flag out-of-domain candidates).

## Recommended path forward
- Adopt QSAR as the calibration-validated affinity scorer (config-swappable, same
  interface), with an applicability-domain filter on generated candidates.
- Optionally: consensus (QSAR + Boltz) for candidates near the domain edge.
- Keep AutoDock/Boltz as documented negatives; revisit Boltz only with a
  leakage-clean, in-domain protocol if structure-based scoring is needed for novel
  chemotypes beyond QSAR's reach.

The engine interface, calibration harness, held-out split, and CPU/GPU paths are
all built and validated; QSAR is the first scorer to actually clear the gate.
