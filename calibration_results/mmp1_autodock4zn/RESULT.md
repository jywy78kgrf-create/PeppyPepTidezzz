# Calibration gate — MMP-1 (cosmetic arm), scorer = AutoDock4Zn

## VERDICT: **NO-GO**

AutoDock4Zn docking score does **not** track measured MMP-1 potency on the
237-compound peptidomimetic calibration set. Per the gate protocol, the pipeline
is **not** validated end-to-end and candidate generation must **not** proceed
until the binding scorer is reconsidered.

## Result (the gate number)

| metric | value | n | p |
|---|---|---|---|
| **Spearman ρ, FULL set** (AutoDock4Zn gate) | **+0.007** | 236 | 0.92 |
| Spearman ρ, held-out fold | −0.025 | 47 | 0.87 |
| Pearson r, FULL set | +0.100 | 236 | — |

Both correlations are statistically indistinguishable from zero. A meaningfully
positive correlation (the GO condition) is absent.

Supporting evidence that the signal is genuinely absent (not a degenerate run):
- Predicted scores span a real range (−21.6 … +8.6; σ≈1.5 over the bulk), so the
  engine is discriminating poses, not returning a constant.
- The most potent measured binders (pIC50 ≈ 8.9, sub-nM hydroxamates) receive
  only mediocre docking scores (≈ 2.8–4.3); the single best-docked compound
  (CHEMBL71120, score 8.6) is among the *weakest* measured (pIC50 4.85).
- Best-docked decile mean pIC50 = 6.57 vs worst-docked decile = 6.21 — a
  noise-level 0.36 gap (a working scorer would show a large positive gap).

See `predicted_vs_actual.png` (structureless vertical cloud) and
`predicted_vs_actual.csv` (per-compound id, split, measured, predicted).

## Method (as configured, not tuned)

- Target/structure: MMP-1, PDB **1HFC**, catalytic zinc (resseq 275) = grid centre.
- Engine: **AutoDock 4.2.6 / AutoGrid 4.2.7.x**, AD4Zn zinc forcefield + TZ
  tetrahedral-zinc pseudo-atom. Box 40×40×40 @ 0.375 Å.
- Search (from config, unchanged): Lamarckian GA, ga_run=10, ga_num_evals=250000,
  ga_pop_size=150, fixed seed 42. Ligands: RDKit ETKDGv3 (seed 42) → MMFF →
  Meeko PDBQT (rigid macrocycles).
- Calibration data: ChEMBL **CHEMBL332** (human MMP-1) IC50 → pIC50_median,
  237 peptidomimetics (`calibration/peptidomimetic.csv`).
- Held-out split: seed 1234, test_frac 0.2 → 190 train / 47 test
  (`calibration/heldout_split.json`; reused unchanged by the future Boltz-2 run).

## Reproducibility (constraint #1) — verified

Two independent full runs produced **byte-identical** predicted scores for all
207 shared compounds (max |Δ| = 0.000000).

## Coverage

236 / 237 scored. One compound (CHEMBL4584813) exceeds AutoDock4's hard 32-torsion
limit and cannot be docked by this engine.

## Interpretation / why this likely failed

Not investigated beyond the gate (the gate is decisive on its own), but the
qualitative pattern — flexible, potent inhibitors scoring poorly — is consistent
with **GA under-convergence**: 250 000 evaluations is well below AutoDock4's own
guidance for ligands with ~10–13 rotatable bonds (these peptidomimetics have up
to 12+), so the search often fails to find each ligand's favourable, zinc-chelated
pose. Other candidates: rigid-receptor docking ignoring induced fit, and the
coarse single-conformer receptor prep.

## Required next step (do NOT skip)

Pause. Do **not** generate candidates. Reconsider the binding scorer before
re-running this gate. Options (each must re-pass this same gate, on this same
held-out split, before candidate generation):
- increase GA sampling (ga_num_evals) and/or replicas for the flexible ligands;
- improve receptor/pose preparation;
- bring forward the deferred **Boltz-2** primary scorer (GPU) — the held-out
  fold is already preserved for a like-for-like comparison.

Scoring/search parameters were **not** adjusted after seeing results; the only
code changes made were correctness fixes required to make the pipeline run at all
(receptor charging, DPF keywords, signed-energy parsing, macrocycle prep).
