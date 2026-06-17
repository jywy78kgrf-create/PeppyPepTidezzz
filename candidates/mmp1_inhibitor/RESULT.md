# MMP-1 inhibitor candidates (drug-discovery scope) — potency + selectivity

Generated against the FULL-MMP-1 model (held-out ρ 0.85, broad domain) and profiled
across the whole MMP family. Combines Option 1 (selectivity) + Option 2 (generation).

## Pipeline
1. **Generate**: BRICS recombination of the 1,976 ChEMBL MMP-1 inhibitors → novel
   chemotypes (not just analogs — the broad domain admits them; the tight cosmetic
   domain admitted 0).
2. **Filter**: novel → carries a zinc-binding group → inside the QSAR applicability
   domain. 77 passed.
3. **Score**: predict pIC50 at MMP-1/2/3/9/13 (per-target RandomForest models, each
   held-out ρ 0.81–0.86); selectivity = pIC50(MMP-1) − pIC50(MMP-X).
4. **Triage**: by MMP-1 potency AND selectivity over all off-targets.

## Result
- 77 novel in-domain candidates; **8 predicted potent** (MMP-1 pIC50 ≥ 7);
  **5 predicted potent AND MMP-1-selective** over all of MMP-2/3/9/13.
- Top: CAND-04389 — MMP-1 pIC50 ≈ 8.15, ≥0.57 log (≈4×) selective vs every other MMP.
- Full table: `candidates_profiled.csv` (per-MMP pIC50, selectivity, alerts, AD).

## Honest caveats
- **Predicted, not measured** (QSAR; strong but not exact). Selectivity = difference
  of two model predictions → errors compound; treat as triage, not truth.
- **BRICS structures**: novel but synthesizability not assessed; most carry 3–4
  structural alerts (recombined fragments + the reactive zinc-binding group). A
  medicinal chemist should sanity-check before synthesis.
- **Near the domain edge**: applicability Tanimoto ≈ 0.54–0.62 (in-domain but not
  close analogs) → more extrapolation than the cosmetic analogs.
- **Duplicates**: BRICS yields equivalent isomers (e.g., CAND-04389/04425) — dedupe
  before ordering.
- **Next step = wet lab**: synthesize top picks → MMP-1 inhibition assay + an
  MMP-2/3/9/13 selectivity panel (the predictions to confirm).

Reproduce: `python run_generate.py --config peptidepipe/configs/mmp1_inhibitor/target.yaml --method brics --outdir results/mmp1_inhibitor_candidates` then `python integrate_candidates.py`.
