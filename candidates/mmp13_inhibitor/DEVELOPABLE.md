# Developable shortlist — MMP13

Filtered for synthesizability + drug-likeness on top of potency/selectivity:
**SAScore ≤ 4.5, ≤1 Lipinski violation, Veber OK, ≤1 structural alert, single zinc-binder.** Prediction uncertainty = std across RF trees (higher = less reliable).

- 5758 candidates → **525 developable**.

| id | pIC50_mmp13 | min_offtarget_sel | sa_score | MW | cLogP | druglikeness_qed | struct_alerts | pred_uncertainty |
|---|---|---|---|---|---|---|---|---|
| CAND-05580 | 9.09 | 2.14 | 2.98 | 561.5 | 4.47 | 0.269 | 1 | 0.502 |
| CAND-05581 | 9.07 | 2.24 | 2.96 | 561.5 | 4.47 | 0.269 | 1 | 0.511 |
| CAND-05582 | 9.06 | 2.23 | 2.96 | 561.5 | 4.47 | 0.269 | 1 | 0.561 |
| CAND-02231 | 8.82 | 1.78 | 3.27 | 516.6 | 2.05 | 0.512 | 1 | 0.425 |
| CAND-02207 | 8.72 | 1.66 | 3.15 | 509.5 | 2.31 | 0.528 | 1 | 0.49 |
| CAND-02219 | 8.7 | 1.79 | 3.16 | 521.6 | 2.18 | 0.485 | 1 | 0.407 |
| CAND-02211 | 8.69 | 1.62 | 3.15 | 526.0 | 2.83 | 0.512 | 1 | 0.528 |
| CAND-02215 | 8.66 | 2.03 | 3.15 | 505.6 | 2.48 | 0.533 | 1 | 0.49 |
| CAND-05648 | 8.64 | 1.73 | 2.48 | 464.5 | 2.81 | 0.332 | 0 | 1.171 |
| CAND-05649 | 8.61 | 1.73 | 2.52 | 464.5 | 2.81 | 0.332 | 1 | 1.203 |
| CAND-02223 | 8.61 | 1.4 | 3.23 | 507.5 | 1.88 | 0.465 | 1 | 0.796 |
| CAND-05646 | 8.58 | 1.66 | 2.42 | 478.5 | 3.11 | 0.358 | 0 | 1.143 |
| CAND-02229 | 8.58 | 0.64 | 3.27 | 516.6 | 2.05 | 0.512 | 1 | 0.699 |
| CAND-02227 | 8.56 | 1.54 | 3.29 | 559.5 | 3.19 | 0.38 | 1 | 0.795 |
| CAND-02230 | 8.56 | 1.43 | 3.29 | 516.6 | 2.05 | 0.512 | 1 | 0.688 |

## SMILES
- **CAND-05580**  `COCCC1(Oc2ccc(Oc3ccc(-c4nc(-c5ccc(F)cc5)co4)cc3)cc2OC)C(=O)NC(=O)NC1=O`
- **CAND-05581**  `COCCC1(Oc2ccc(Oc3ccc(-c4nc(-c5ccc(F)cc5)co4)cc3)c(OC)c2)C(=O)NC(=O)NC1=O`
- **CAND-05582**  `COCCC1(Oc2ccc(Oc3ccc(-c4nc(-c5ccc(F)cc5)co4)cc3OC)cc2)C(=O)NC(=O)NC1=O`
- **CAND-02231**  `C[C@]1(CS(=O)(=O)N2CCC(Oc3ccc(OCc4ccc(F)c(C#N)c4)cc3)CC2)NC(=O)NC1=O`
- **CAND-02207**  `C[C@]1(CS(=O)(=O)N2CCC(Oc3ccc(OCc4ccc(F)c(F)c4)cc3)CC2)NC(=O)NC1=O`
- **CAND-02219**  `COc1cc(COc2ccc(OC3CCN(S(=O)(=O)C[C@@]4(C)NC(=O)NC4=O)CC3)cc2)ccc1F`
- **CAND-02211**  `C[C@]1(CS(=O)(=O)N2CCC(Oc3ccc(OCc4ccc(F)c(Cl)c4)cc3)CC2)NC(=O)NC1=O`
- **CAND-02215**  `Cc1cc(COc2ccc(OC3CCN(S(=O)(=O)C[C@@]4(C)NC(=O)NC4=O)CC3)cc2)ccc1F`
- **CAND-05648**  `COc1cc(CNC(=O)c2nc3scc(CC(=O)Nc4ccccc4)c3c(=O)[nH]2)ccc1O`
- **CAND-05649**  `COc1cccc(CNC(=O)c2nc3scc(CC(=O)Nc4ccccc4)c3c(=O)[nH]2)c1O`
- **CAND-02223**  `C[C@]1(CS(=O)(=O)N2CCC(Oc3ccc(OCc4ccc(F)c(O)c4)cc3)CC2)NC(=O)NC1=O`
- **CAND-05646**  `COc1ccc(CNC(=O)c2nc3scc(CC(=O)Nc4ccccc4)c3c(=O)[nH]2)cc1OC`
- **CAND-02229**  `C[C@]1(CS(=O)(=O)N2CCC(Oc3ccc(OCc4ccc(F)cc4)c(C#N)c3)CC2)NC(=O)NC1=O`
- **CAND-02227**  `C[C@]1(CS(=O)(=O)N2CCC(Oc3ccc(OCc4ccc(F)c(C(F)(F)F)c4)cc3)CC2)NC(=O)NC1=O`
- **CAND-02230**  `C[C@]1(CS(=O)(=O)N2CCC(Oc3ccc(OCc4ccc(F)cc4C#N)cc3)CC2)NC(=O)NC1=O`

Predictions are QSAR triage, not measurements. Confirm in vitro.