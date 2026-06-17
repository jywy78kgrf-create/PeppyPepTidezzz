# Developable shortlist — ADAMTS5

Filtered for synthesizability + drug-likeness on top of potency/selectivity:
**SAScore ≤ 4.5, ≤1 Lipinski violation, Veber OK, ≤1 structural alert, single zinc-binder.** Prediction uncertainty = std across RF trees (higher = less reliable).

- 2081 candidates → **260 developable**.

| id | pIC50_adamts5 | selectivity | sa_score | MW | cLogP | druglikeness_qed | struct_alerts | pred_uncertainty |
|---|---|---|---|---|---|---|---|---|
| CAND-00727 | 7.61 | 0.36 | 3.88 | 489.5 | 1.48 | 0.525 | 1 | 0.303 |
| CAND-00726 | 7.6 | 0.2 | 3.82 | 503.5 | 1.79 | 0.554 | 1 | 0.338 |
| CAND-01025 | 7.6 | 0.01 | 3.67 | 434.5 | 1.2 | 0.581 | 1 | 0.323 |
| CAND-01024 | 7.58 | 0.06 | 3.64 | 434.5 | 1.2 | 0.581 | 1 | 0.424 |
| CAND-00590 | 7.49 | 0.22 | 3.85 | 440.4 | 1.34 | 0.576 | 1 | 0.276 |
| CAND-01023 | 7.49 | -0.08 | 3.61 | 448.5 | 1.51 | 0.614 | 1 | 0.352 |
| CAND-00589 | 7.42 | 0.16 | 3.77 | 454.5 | 1.64 | 0.608 | 1 | 0.337 |
| CAND-01708 | 7.42 | 0.05 | 3.86 | 470.5 | 0.88 | 0.543 | 1 | 0.37 |
| CAND-01709 | 7.4 | 0.1 | 3.94 | 456.4 | 0.58 | 0.514 | 1 | 0.413 |
| CAND-00643 | 7.39 | -0.14 | 4.21 | 466.5 | 1.73 | 0.551 | 1 | 0.301 |
| CAND-00642 | 7.38 | -0.17 | 4.13 | 480.5 | 2.03 | 0.58 | 1 | 0.327 |
| CAND-01063 | 7.34 | -0.02 | 3.86 | 441.9 | 2.52 | 0.608 | 1 | 0.337 |
| CAND-01429 | 7.33 | 0.02 | 4.15 | 440.4 | 1.34 | 0.596 | 1 | 0.332 |
| CAND-01062 | 7.31 | -0.07 | 3.77 | 455.9 | 2.83 | 0.643 | 1 | 0.286 |
| CAND-01128 | 7.3 | -0.02 | 3.85 | 442.4 | -0.08 | 0.454 | 1 | 0.388 |

## SMILES
- **CAND-00727**  `COc1c(O)c(N2CCN(C(=O)[C@@H](C)C[C@@]3(c4ccccn4)NC(=O)NC3=O)CC2)cc(F)c1F`
- **CAND-00726**  `COc1c(N2CCN(C(=O)[C@@H](C)C[C@@]3(c4ccccn4)NC(=O)NC3=O)CC2)cc(F)c(F)c1OC`
- **CAND-01025**  `COc1cc(F)cc(N2CCN(C(=O)[C@@H](C)C[C@@]3(C4CC4)NC(=O)NC3=O)CC2)c1O`
- **CAND-01024**  `COc1cc(N2CCN(C(=O)[C@@H](C)C[C@@]3(C4CC4)NC(=O)NC3=O)CC2)cc(F)c1O`
- **CAND-00590**  `CC[C@]1(C[C@H](C)C(=O)N2CCN(c3cc(F)c(F)c(OC)c3O)CC2)NC(=O)NC1=O`
- **CAND-01023**  `COc1cc(F)cc(N2CCN(C(=O)[C@@H](C)C[C@@]3(C4CC4)NC(=O)NC3=O)CC2)c1OC`
- **CAND-00589**  `CC[C@]1(C[C@H](C)C(=O)N2CCN(c3cc(F)c(F)c(OC)c3OC)CC2)NC(=O)NC1=O`
- **CAND-01708**  `COC[C@]1(C[C@H](C)C(=O)N2CCN(c3cc(F)c(F)c(OC)c3OC)CC2)NC(=O)NC1=O`
- **CAND-01709**  `COC[C@]1(C[C@H](C)C(=O)N2CCN(c3cc(F)c(F)c(OC)c3O)CC2)NC(=O)NC1=O`
- **CAND-00643**  `COc1c(O)c(N2CCN(C(=O)[C@@H](C)C[C@@]3(C4CC4)NC(=O)NC3=O)C[C@@H]2C)cc(F)c1F`
- **CAND-00642**  `COc1c(N2CCN(C(=O)[C@@H](C)C[C@@]3(C4CC4)NC(=O)NC3=O)C[C@@H]2C)cc(F)c(F)c1OC`
- **CAND-01063**  `COc1c(C2CCN(C(=O)[C@@H](C)C[C@@]3(C)NC(=O)NC3=O)CC2)cc(Cl)c(F)c1O`
- **CAND-01429**  `COc1c(O)c(N2CCN(C(=O)[C@@H](C)C[C@@]3(C)NC(=O)NC3=O)C[C@@H]2C)cc(F)c1F`
- **CAND-01062**  `COc1c(C2CCN(C(=O)[C@@H](C)C[C@@]3(C)NC(=O)NC3=O)CC2)cc(Cl)c(F)c1OC`
- **CAND-01128**  `COc1c(O)c(N2CCN(C(=O)[C@@H](CO)C[C@@]3(C)NC(=O)NC3=O)CC2)cc(F)c1F`

Predictions are QSAR triage, not measurements. Confirm in vitro.