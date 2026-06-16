# Calibration gate — MMP-1 (cosmetic arm), scorer = Boltz-2 (GPU)

## VERDICT: NO-GO (weak positive, not significant)

Held-out fold, near-complete run (**46 / 47** scored; 1 dropped). GPU: RunPod
A100 then A5000 (cuEquivariance kernels, cu128 torch).

| metric | value |
|---|---|
| **Spearman ρ, Boltz score vs pIC50 (held-out)** | **+0.17** |
| n | 46 |
| p (two-tailed) | ≈ 0.25 (not significant) |
| 95% CI (Fisher) | ≈ [−0.12, +0.44] (includes 0) |
| pre-registered GO bar | ρ ≥ 0.4, p < 0.01 |

Below the GO bar and not statistically distinguishable from zero.

### Same held-out fold, head-to-head
| scorer | held-out ρ |
|---|---|
| **Boltz-2** | **+0.17** (n=46) |
| AutoDock4Zn | −0.025 (n=47) |

Boltz is the better scorer (positive vs ~zero), but neither tracks measured
potency well enough to pass. Extending from the potent-only partial (ρ=0.11, n=26)
to the full range (ρ=0.17, n=46) barely moved it — the signal is genuinely weak,
not just range-restricted.

### Leakage note
Boltz-2 was likely trained on public ChEMBL MMP-1 data, so its true generalisation
to novel chemotypes is ≤ the observed 0.17 (memorisation can only inflate). At this
weak level the distinction is academic — there is no strong signal to attribute.
(`leakage_probe.py` can split the held-out by Murcko-scaffold novelty if a finer
read is wanted.)

## Pre-flight vs held-out — why the smoke test misled
The 5-compound pre-flight looked great (potent +1.6/+1.8 vs weak −0.4, SIGN OK,
binder-prob monotonic) because it used only the extremes, which are easy to
separate. Across the full held-out range the mid-potency compounds dominate and
Boltz does not rank them — hence ρ ≈ 0.17. A reminder that a clean extremes-only
sanity check is necessary but not sufficient.

## Engineering record (what it took to run Boltz on GPU)
- env: standalone Boltz install (scikit-learn 1.6.1 vs core 1.5.1 conflict);
- CUDA-12.8 torch build (`+cu128`) to match the host driver;
- cuEquivariance kernels (`cuequivariance-torch` + `-ops-torch-cu12`), else Boltz
  crashes (ModuleNotFoundError); `use_kernels: false` is the pure-torch fallback;
- adapter: pass an MSA (`--use_msa_server`), NEGATE `affinity_pred_value`
  (log10(IC50 µM), lower=stronger), surface boltz errors, resumable runner.

Raw per-compound data: results/mmp1_boltz2_heldout.csv (on the GPU volume).
