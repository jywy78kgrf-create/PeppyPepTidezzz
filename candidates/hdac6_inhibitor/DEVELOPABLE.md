# Developable shortlist — HDAC6

Filtered for synthesizability + drug-likeness on top of potency/selectivity:
**SAScore ≤ 4.5, ≤1 Lipinski violation, Veber OK, ≤1 structural alert, single zinc-binder.** Prediction uncertainty = std across RF trees (higher = less reliable).

- 6236 candidates → **331 developable**.

| id | pIC50_hdac6 | selectivity | sa_score | MW | cLogP | druglikeness_qed | struct_alerts | pred_uncertainty |
|---|---|---|---|---|---|---|---|---|
| CAND-03763 | 8.01 | 0.9 | 3.4 | 535.0 | 3.24 | 0.408 | 0 | 0.437 |
| CAND-00277 | 7.95 | 1.05 | 3.33 | 463.9 | 4.32 | 0.465 | 0 | 0.676 |
| CAND-01808 | 7.74 | 0.77 | 3.54 | 445.4 | 3.67 | 0.521 | 0 | 0.324 |
| CAND-00282 | 7.7 | 0.81 | 3.32 | 443.5 | 3.97 | 0.493 | 0 | 0.608 |
| CAND-03768 | 7.66 | 0.54 | 3.39 | 514.6 | 2.89 | 0.425 | 0 | 0.309 |
| CAND-00305 | 7.63 | 0.9 | 3.36 | 447.5 | 3.61 | 0.438 | 1 | 0.589 |
| CAND-03901 | 7.61 | 0.5 | 3.66 | 456.4 | 3.04 | 0.531 | 0 | 0.449 |
| CAND-00272 | 7.6 | 0.72 | 3.34 | 447.5 | 3.8 | 0.492 | 0 | 0.586 |
| CAND-03881 | 7.58 | 0.48 | 3.55 | 465.9 | 3.82 | 0.489 | 1 | 0.42 |
| CAND-03885 | 7.56 | 0.49 | 3.53 | 445.4 | 3.47 | 0.549 | 0 | 0.35 |
| CAND-00287 | 7.55 | 0.72 | 3.29 | 459.5 | 3.67 | 0.451 | 0 | 0.575 |
| CAND-03889 | 7.53 | 0.5 | 3.51 | 461.4 | 3.17 | 0.503 | 0 | 0.359 |
| CAND-03902 | 7.53 | 0.41 | 3.63 | 456.4 | 3.04 | 0.531 | 0 | 0.424 |
| CAND-00359 | 7.52 | 0.57 | 3.64 | 513.5 | 4.26 | 0.292 | 1 | 0.69 |
| CAND-03878 | 7.51 | 0.41 | 3.59 | 449.4 | 3.3 | 0.51 | 0 | 0.39 |

## SMILES
- **CAND-03763**  `O=S(=O)(CCN1CCCOCC1)N(Cc1ncc(-c2nnc(C(F)F)o2)s1)c1cncc(Cl)c1`
- **CAND-00277**  `CCCCS(=O)(=O)N(Cc1ncc(-c2nnc(C(F)F)o2)s1)c1cncc(Cl)c1`
- **CAND-01808**  `O=S(=O)(CF)N(Cc1ncc(-c2nnc(C(F)F)o2)s1)c1cncc(C2CC2)c1`
- **CAND-00282**  `CCCCS(=O)(=O)N(Cc1ncc(-c2nnc(C(F)F)o2)s1)c1cncc(C)c1`
- **CAND-03768**  `Cc1cncc(N(Cc2ncc(-c3nnc(C(F)F)o3)s2)S(=O)(=O)CCN2CCCOCC2)c1`
- **CAND-00305**  `O=S(=O)(CCCCF)N(Cc1ncc(-c2nnc(C(F)F)o2)s1)c1cccnc1`
- **CAND-03901**  `N#Cc1ncc(N(Cc2ncc(-c3nnc(C(F)F)o3)s2)S(=O)(=O)C2CC2)cc1F`
- **CAND-00272**  `CCCCS(=O)(=O)N(Cc1ncc(-c2nnc(C(F)F)o2)s1)c1cncc(F)c1`
- **CAND-03881**  `O=S(=O)(C1CC1)N(Cc1ncc(-c2nnc(C(F)F)o2)s1)c1cnc(Cl)c(F)c1`
- **CAND-03885**  `Cc1ncc(N(Cc2ncc(-c3nnc(C(F)F)o3)s2)S(=O)(=O)C2CC2)cc1F`
- **CAND-00287**  `CCCCS(=O)(=O)N(Cc1ncc(-c2nnc(C(F)F)o2)s1)c1cncc(OC)c1`
- **CAND-03889**  `COc1ncc(N(Cc2ncc(-c3nnc(C(F)F)o3)s2)S(=O)(=O)C2CC2)cc1F`
- **CAND-03902**  `N#Cc1c(F)cncc1N(Cc1ncc(-c2nnc(C(F)F)o2)s1)S(=O)(=O)C1CC1`
- **CAND-00359**  `CC(C)CS(=O)(=O)N(Cc1ncc(-c2nnc(C(F)F)o2)s1)c1cnc(F)c(OC(F)F)c1`
- **CAND-03878**  `O=S(=O)(C1CC1)N(Cc1ncc(-c2nnc(C(F)F)o2)s1)c1cncc(F)c1F`

Predictions are QSAR triage, not measurements. Confirm in vitro.