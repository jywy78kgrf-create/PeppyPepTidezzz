# Expanded target panel — gate validation (HDAC, ADAMTS)

Aiming the platform at two more target families. Same QSAR gate (train-CV model
selection, held-out scored once, scaffold-split for novel-chemotype generalisation).

| family | target | ChEMBL | molecules | held-out ρ | scaffold-split ρ (#scaf) |
|---|---|---|---|---|---|
| **HDAC6 selectivity** | HDAC6 (target) | CHEMBL1865 | 6,394 | **+0.81** | +0.75 (2,706) |
| | HDAC1 (class I) | CHEMBL325 | 8,176 | +0.85 | +0.77 (3,611) |
| | HDAC2 (class I) | CHEMBL1937 | 2,688 | +0.73 | +0.67 (1,406) |
| | HDAC3 (class I) | CHEMBL1829 | 2,547 | +0.83 | +0.72 (1,242) |
| **OA aggrecanase** | ADAMTS-5 (target) | CHEMBL2285 | 960 | **+0.86** | +0.76 (265) |
| | ADAMTS-4 (off-target) | CHEMBL2318 | 335 | +0.81 | +0.77 (149) |

All clear the GO bar (ρ ≥ 0.4, p < 0.01) by a wide margin, including on novel
scaffolds. Both families are tractable for the gate→generate→selectivity→Pareto flow.

## Ready-to-run selectivity stories
- **HDAC6-selective** (potent HDAC6, sparing class I HDAC1/2/3): all four models
  validated → direct ΔpIC50 selectivity + Pareto, exactly like the MMP work. HDAC6
  is zinc/hydroxamate chemistry like MMPs, so the chemistry is squarely in domain.
- **ADAMTS-5 (OA)**: potent ADAMTS-5, sparing ADAMTS-4 (and the MMPs) → an OA
  aggrecanase profile complementary to the MMP-13 collagenase work.

Per-target artifacts: calibration_results/qsar_{hdac1,hdac2,hdac3,hdac6,adamts4,adamts5}/.
