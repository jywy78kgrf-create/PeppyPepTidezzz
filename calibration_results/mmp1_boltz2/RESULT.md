# Calibration gate — MMP-1 (cosmetic arm), scorer = Boltz-2 (GPU)

## STATUS: INCONCLUSIVE (partial run) — promising, not validated

Run on a rented GPU (RunPod, A100 then A4500). GPU credit ran out partway, so
**26 of the 47 held-out compounds** were scored. The runner processes in
potency-descending order, so the 26 completed are the **most potent half**
(pIC50 ≈ 6.5–9); the ~21 weakest held-out compounds were never scored.

## Result (held-out, partial)

| metric | value | n |
|---|---|---|
| Spearman ρ, Boltz `affinity_pred_value` (negated) vs pIC50 | **+0.1145** | 26 |
| Spearman ρ, Boltz `affinity_probability_binary` vs pIC50 | +0.0318 | 26 |

### Head-to-head on the IDENTICAL 26 compounds
| scorer | Spearman ρ |
|---|---|
| **Boltz-2** | **+0.1145** |
| AutoDock4Zn (from the 2.5M run) | −0.1221 |

Boltz is the **better** scorer (positive vs negative), but neither is strong, and
+0.11 is not significant at n=26.

## Why this is inconclusive (and likely understates Boltz)

- **Incomplete:** only 26/47 (budget). A clean verdict needs all 47.
- **Range-restricted:** the 26 are the potent half. Correlation within a narrow
  potency band is mechanically suppressed. The missing weak compounds are exactly
  the ones Boltz separated cleanly in the 5-compound preflight (potent +1.6/+1.8
  vs weak −0.36), so finishing the run would most likely RAISE Boltz's ρ.
- **Pre-flight (5 extremes) was clean:** mean score strong +1.72 vs weak −0.09,
  SIGN OK, binder-probability monotonic (0.26 → 0.94 → 0.997). Extremes are easy;
  the mid-range (where the partial run sits) is the hard part.

## Leakage caveat (unresolved)

Boltz-2's affinity head was trained on public data that likely includes ChEMBL
MMP-1, so even a strong held-out ρ could be partial memorisation. Not a concern at
the current weak ρ, but it must be probed (scaffold-novelty split, `leakage_probe.py`)
before trusting any future "pass".

## Engineering notes (what it took to run Boltz at all)

GPU env required fixes beyond the committed scaffold, all pushed:
- env build (`setup.sh --profile gpu`): pip-in-env + standalone Boltz install
  (Boltz pins scikit-learn==1.6.1, conflicting with core's 1.5.1);
- CUDA-12.8 torch build (`+cu128`) to match the host driver;
- `cuequivariance-torch` + `cuequivariance-ops-torch-cu12` for Boltz's triangle
  kernels (otherwise it crashes with ModuleNotFoundError; `use_kernels: false`
  is the dependency-free fallback);
- adapter fixes: pass an MSA (`--use_msa_server`), NEGATE `affinity_pred_value`
  (log10(IC50 uM), lower=stronger) to honour higher=better, surface boltz errors.

## Verdict and next step

Neither engine currently justifies proceeding to candidate generation:
- AutoDock4Zn: **NO-GO** (full 47, ρ ≈ 0, definitive).
- Boltz-2: **INCONCLUSIVE** — better than AutoDock, but unproven on this partial,
  range-restricted run.

To resolve Boltz cleanly: finish the held-out 47 (resumable runner; ~$1–2 on a
cheap GPU, picks up from compound 26), then judge against the pre-registered bar
(ρ ≥ ~0.4, p < 0.01) AND the leakage probe. Even then, a borderline ρ would make
Boltz a "lead to develop", not a validated scorer.

Raw per-compound data: results/mmp1_boltz2_heldout.csv on the GPU volume
(26 rows: id, measured pIC50, predicted score, binder probability).
