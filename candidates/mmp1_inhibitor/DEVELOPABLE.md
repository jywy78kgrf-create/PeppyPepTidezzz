# Developable shortlist — MMP1

Filtered for synthesizability + drug-likeness on top of potency/selectivity:
**SAScore ≤ 4.5, ≤1 Lipinski violation, Veber OK, ≤1 structural alert, single zinc-binder.** Prediction uncertainty = std across RF trees (higher = less reliable).

- 57 candidates → **5 developable**.

| id | pIC50_mmp1 | min_MMP1_selectivity | sa_score | MW | cLogP | druglikeness_qed | struct_alerts | pred_uncertainty |
|---|---|---|---|---|---|---|---|---|
| CAND-00006 | 5.86 | -2.09 | 2.93 | 345.5 | 4.1 | 0.802 | 1 | 0.867 |
| CAND-00008 | 5.82 | -2.18 | 2.93 | 359.5 | 4.49 | 0.741 | 1 | 0.831 |
| CAND-00010 | 5.61 | -2.68 | 3.26 | 357.5 | 4.24 | 0.836 | 1 | 0.778 |
| CAND-00055 | 5.43 | -0.84 | 2.57 | 370.4 | 2.89 | 0.743 | 1 | 0.842 |
| CAND-00056 | 5.13 | -0.6 | 2.95 | 371.4 | 2.06 | 0.763 | 0 | 0.815 |

## SMILES
- **CAND-00006**  `CCC(CCS)S(=O)(=O)c1ccc(-c2ccccc2C#N)cc1`
- **CAND-00008**  `CCCC(CCS)S(=O)(=O)c1ccc(-c2ccccc2C#N)cc1`
- **CAND-00010**  `N#Cc1ccccc1-c1ccc(S(=O)(=O)C2CCCC(S)C2)cc1`
- **CAND-00055**  `N#Cc1ccccc1NS(=O)(=O)N1CCc2c([nH]c3cc(F)ccc23)C1`
- **CAND-00056**  `N#Cc1ccccc1NS(=O)(=O)N1CCc2c(nn3cc(F)ccc23)C1`

Predictions are QSAR triage, not measurements. Confirm in vitro.