# Calibration gate — MMP-1 (cosmetic arm), scorer = AutoDock4Zn

## VERDICT: **NO-GO** (confirmed at thorough GA convergence)

AutoDock4Zn docking score does **not** track measured MMP-1 potency on the
237-compound peptidomimetic calibration set. Raising GA sampling 10× did not
change this. Per the gate protocol, the pipeline is **not** validated end-to-end
and candidate generation must **not** proceed; reconsider the binding scorer.

## Results — two attempts on the identical set & held-out split

| attempt | ga_num_evals | n scored | Spearman ρ (FULL) | p | Spearman ρ (held-out 47) | p |
|---|---|---|---|---|---|---|
| #1 "short" | 250,000 | 236/237 | **+0.007** | 0.92 | −0.025 | 0.87 |
| #2 "thorough" | 2,500,000 | 236/237 | **+0.054** | 0.41 | +0.021 | 0.89 |

Both are statistically indistinguishable from zero and far below the pre-stated
GO bar (ρ ≥ ~0.4, p < 0.01 on the held-out fold). Pearson r at 2.5M = +0.12.

Artifacts: `ga250k_*` (attempt 1) and `ga2p5M_*` (attempt 2) — each a
`predicted_vs_actual.{csv,png}`.

## Why this is the scorer, not the search (the key diagnostic)

The 10× sampling increase **did** make the GA search more thorough — docking
scores improved broadly (mean Δ +1.46; 229/236 compounds scored better; 123 moved
by >1 unit). **Yet the correlation stayed flat.** More thorough search found
lower-energy poses that ranked potency no better. A convergence spot-check
(2.5M → 5M on a torsion-spanning, IC50-blind sample) showed scores have largely
stopped moving (|Δ| = 0.00–0.09 for 3 of 4; 1.24 for one mid-torsion case). So the
limiter is the **scoring function / pose ranking**, not GA convergence.

Qualitative confirmation (2.5M): the 8 most potent (sub-nM) inhibitors dock at
percentiles scattered from 14% to 96% — no consistent rank-up. Best-docked decile
mean pIC50 = 6.55 vs worst-docked 5.92 (noise-level 0.63 gap).

## Method (as configured; only ga_num_evals changed, a priori)

- MMP-1, PDB **1HFC**, catalytic zinc (resseq 275) = grid centre; AD4Zn forcefield
  + TZ tetrahedral-zinc pseudo-atom. Box 40³ @ 0.375 Å.
- AutoDock **4.2.6** / AutoGrid **4.2.7.x**, Lamarckian GA, ga_run=10, fixed seed 42.
- Ligands: RDKit ETKDGv3 (seed 42) → MMFF → Meeko PDBQT (rigid macrocycles).
- Calibration: ChEMBL **CHEMBL332** IC50 → pIC50_median, 237 peptidomimetics.
- Held-out split: seed 1234, 190 train / 47 test (`calibration/heldout_split.json`),
  reused unchanged for the Boltz-2 run.

## Reproducibility (constraint #1) — verified

The two 250k runs gave byte-identical predicted scores on all 207 shared compounds
(max |Δ| = 0.000000).

## Coverage

236 / 237 scored both times. CHEMBL4584813 exceeds AutoDock4's hard 32-torsion limit.

## Required next step

Pause; do **not** generate candidates. The failure is not search depth, so simply
docking harder will not help. Options (each must clear this same gate on this same
held-out fold before candidate generation):
- the deferred **Boltz-2** GPU primary (see repo README + runbook) — but watch for
  pretraining leakage on ChEMBL MMP-1;
- a plain **QSAR/ML baseline** trained on these 237 labels (cheap; strong for a
  congeneric series) — also a useful "is this set even rankable?" control;
- better physics (multi-conformer/flexible receptor, alternative engine, MM-GBSA
  rescoring).

Scoring/search parameters were not tuned to the gate metric; `ga_num_evals` was
raised once, a priori, per AutoDock's per-torsion guidance, and committed before
the result was known.
