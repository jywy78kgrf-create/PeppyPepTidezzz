# Pareto front — MMP-1 candidates (potency × selectivity × drug-likeness)

Non-dominated candidates: each is best-in-class on *some* balance of the three objectives; none is beaten on all three. There is no single winner — pick the region of the frontier that matches your project's risk tolerance.

- pool: 57 unique candidates → **9 Pareto-optimal**

| id | pred pIC50 (MMP-1) | min selectivity (log) | QED | #ZBG | alerts | nearest-known Tanimoto |
|---|---|---|---|---|---|---|
| CAND-14209 | 7.53 | +0.22 | 0.40 | 2 | 2 | 0.53 |
| CAND-00037 | 6.65 | -0.54 | 0.63 | 1 | 2 | 0.67 |
| CAND-00013 | 6.39 | -0.82 | 0.64 | 1 | 2 | 0.54 |
| CAND-00044 | 6.38 | -0.35 | 0.47 | 1 | 3 | 0.67 |
| CAND-00011 | 5.94 | -1.17 | 0.66 | 1 | 2 | 0.63 |
| CAND-00006 | 5.86 | -2.09 | 0.80 | 1 | 1 | 0.52 |
| CAND-00010 | 5.61 | -2.68 | 0.84 | 1 | 1 | 0.56 |
| CAND-00055 | 5.43 | -0.84 | 0.74 | 1 | 1 | 0.53 |
| CAND-00056 | 5.13 | -0.60 | 0.76 | 1 | 0 | 0.53 |

## Reading the frontier
- **High-potency end**: best pIC50 but typically multi-chelator (high #ZBG, more alerts, lower QED) — the classic MMP liability.
- **Drug-like end**: high QED / single ZBG / few alerts but weaker and often not MMP-1-selective.
- **Middle**: the candidates worth a chemist's attention — they buy selectivity/cleanliness at modest potency cost.

All predictions are QSAR triage, not measurements (see BENCH_HANDOFF.md caveats). Confirm the chosen front region in vitro (MMP-1 IC50 + MMP-2/3/9/13 panel).