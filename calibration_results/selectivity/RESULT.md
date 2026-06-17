# MMP-1 selectivity QSAR — validation

Direct ΔpIC50 models (pIC50 MMP-1 − pIC50 MMP-X) on compounds tested against both.
Same discipline: model chosen by TRAIN-only CV, held-out scored once, scaffold-split
for novel-chemotype generalisation.

| selectivity axis | n | model | held-out ρ | scaffold-split ρ (# scaf) | mean ΔpIC50 |
|---|---|---|---|---|---|
| MMP-1 vs MMP-2  | 778 | RandomForest | **+0.90** | +0.71 (328) | −1.57 |
| MMP-1 vs MMP-3  | 745 | GradBoost    | **+0.85** | +0.68 (354) | −0.54 |
| MMP-1 vs MMP-9  | 938 | RandomForest | **+0.83** | +0.68 (419) | −1.25 |
| MMP-1 vs MMP-13 | 951 | RandomForest | **+0.86** | +0.72 (384) | −1.76 |

## Read
Selectivity is **learnable directly from structure** — held-out ρ 0.83–0.90, and
0.68–0.72 on novel scaffolds. So a molecule's MMP-1-vs-X selectivity can be
predicted, not just its raw potency. This addresses the failure mode of the first
MMP-inhibitor drugs (broad-spectrum chelators → musculoskeletal toxicity): you can
now triage candidates for selectivity, not only potency.

Reproduce: `python selectivity_baseline.py`
Artifacts: per-pair held-out CSVs + selectivity_metrics.json.
