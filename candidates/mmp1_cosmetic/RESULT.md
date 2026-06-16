# MMP-1 cosmetic candidates — ranked list (project deliverable)

Generated only AFTER the calibration gate passed (QSAR scorer: held-out
Spearman +0.47). These are COMPUTATIONAL PRIORITISATIONS for downstream lab
validation — predicted, not validated, actives.

## How they were made
1. **Scorer**: QSAR (GradientBoosting on Morgan FP + physchem descriptors),
   trained on all 237 measured MMP-1 pIC50s. The only gate-passing scorer.
2. **Generation**: single-point medicinal-chemistry edits (F, Cl, Me, OMe, OH,
   CF3, CN, ...) of the 237 known actives -> novel but high-similarity analogs
   that stay inside the QSAR's validated applicability domain.
3. **Filters**: novel (not a known active) -> correct chemotype (2-3 backbone
   residues) -> carries a zinc-binding group -> inside applicability domain
   (max Tanimoto to training >= 0.462, the cross-scaffold regime where the QSAR
   was validated). 5,615 of 6,000 generated passed.
4. **Ranking — COSMETIC fitness** (config weights): affinity 0.30 +
   skin-permeability 0.45 + safety 0.25.
   - affinity   = QSAR predicted pIC50.
   - permeability = Potts-Guy logKp QSPR (−2.7 + 0.71·logP − 0.0061·MW), the
     heaviest weight: a topical active must cross skin.
   - safety     = RDKit Brenk + PAINS structural-alert cleanliness.

## Result
- 5,615 ranked in-domain candidates; **4,684 predicted hits** (pIC50 ≥ 6.0).
- Top candidates: predicted pIC50 ≈ 7.0, near-maximal skin-permeability term,
  Tanimoto ≈ 0.67–0.82 to a known active. Files: candidates_top.csv (top 50),
  candidates_all.csv (all), candidates_landscape.png.
- The top series are CF3/halogen analogs of CHEMBL69323 (measured pIC50 7.46)
  with a thiol zinc-binding group — lipophilicity tuned up for skin penetration.

## Honest caveats (read before any lab work)
- **Predicted, not measured.** Affinity is a QSAR estimate (validated ρ≈0.47 —
  moderate ranking power, not exact); permeability is a logKp *proxy*, not a
  measured Kp; safety is structural-alerts only, not a tox/sensitisation assay.
- **In-domain analogs, not novel chemotypes.** By construction these resemble
  known inhibitors (that's what makes them scorable). The pipeline cannot reliably
  score genuinely novel chemotypes — no scorer we tested generalises that far
  (AutoDock and Boltz both failed the gate).
- **ZBG safety flag.** Hydroxamate/thiol zinc-binders trip a structural alert
  (safety_norm ≈ 0.8); these groups have known tox/stability concerns that matter
  for a leave-on cosmetic. The safety term down-weights but does not exclude them.
- **Next step = experiment.** Triers should go to a real MMP-1 inhibition assay,
  measured skin permeation, and a safety/sensitisation panel.

Reproduce: `python run_generate.py --config peptidepipe/configs/mmp1_cosmetic/target.yaml --outdir results/mmp1_candidates`
