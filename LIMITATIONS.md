# Limitations & what's needed next

A clear-eyed read of what this project produced — written to travel with the
deliverable so no one over-reads the candidate list.

## TL;DR
The pipeline is sound and runs end-to-end (calibration gate → in-domain
generation → ranked list). But the candidate list is best read as a **validation
of the machinery, not a discovery.** The candidates are minor analogs of known
*drug-like* MMP-1 inhibitors — probably bioactive, but unlikely to be useful *new
cosmetic* ingredients. The root cause is a **data/goal mismatch**: we calibrated on
drug inhibitors, but the goal was cosmetic peptides.

## What the deliverable IS — and ISN'T
**IS:** ~5,615 in-domain, novel-but-close analogs of validated MMP-1 inhibitors,
ranked by a cosmetic fitness — a reasonable in-vitro triage start for a *defensive
MMP-1 inhibitor* screen.
**IS NOT:** novel cosmetic-peptide actives; non-obvious/patentable chemistry;
experimentally validated; the peptide space the brief actually targeted.

## Honest probability read
- **P(a top candidate inhibits MMP-1 in vitro): moderate–high.** They're
  single-atom edits of validated inhibitors with the zinc-binder intact; close
  analogs of potent compounds usually keep activity. So this is not "nothing"
  biochemically.
- **P(a top candidate is a valuable, novel cosmetic ingredient): low.** Because:
  1. **Low novelty** — "add a CF3/halogen to a known inhibitor" is the most obvious
     medchem move; many were likely already made in the original drug campaigns.
  2. **Wrong/risky chemotype** — hydroxamate/thiol chelators were largely abandoned
     therapeutically over tox/selectivity and trip the safety alert; poor fit for a
     leave-on cosmetic.
  3. **Not the peptide space** the project was about (GHK-Cu / palmitoyl-peptide
     territory).
  4. **Soft predictions** — affinity ρ≈0.47, permeability a proxy, safety
     alerts-only.

## Root cause: data/goal mismatch
- Calibration set = 237 drug-like peptidomimetic MMP-1 *inhibitors* (ChEMBL).
- Only the QSAR scorer passed the gate, and a QSAR is valid only near its training
  chemistry.
- So generation was (correctly) confined to the neighborhood of those drug
  inhibitors — not cosmetic-peptide space.
- The pipeline answered *"what are good analogs of known MMP-1 drug inhibitors?"*,
  not *"what are good novel cosmetic peptide actives?"*

## Scorer scorecard (for the record)
| scorer | held-out Spearman ρ | verdict |
|---|---|---|
| AutoDock4Zn | −0.025 | NO-GO |
| Boltz-2 | +0.17 (n.s.) | NO-GO |
| QSAR | +0.47 | GO, but applicability-domain-limited |

No scorer generalizes beyond the drug-inhibitor chemotype, so the pipeline cannot
currently reach novel cosmetic-peptide space reliably.

## What would actually move the needle
1. **Recalibrate on cosmetic-relevant data** — measured MMP-1 (or
   procollagen/collagenase) effects of *peptide* actives. This is the unlock;
   without it the search is stuck near drug chemistry. Even a modest peptide
   dataset changes what the scorer can validly rank.
2. **Reframe the target/readout** to one that has peptide data.
3. If a *defensive MMP-1 inhibitor* screen is genuinely wanted, the current list is
   a fine triage start — but prioritize by experimental, not predicted, evidence.

## What NOT to do
- Don't pour more compute into docking/Boltz on this set — both failed the gate;
  the limit is the data, not the search.
- Don't treat the predicted pIC50 / permeability / safety numbers as
  decision-grade — they're a triage prior, not measurements.

## Bottom line
The valuable output of this project is the validated, honest **machinery** plus a
clear, evidence-based **"redirect"** signal: to find novel cosmetic peptide actives,
get cosmetic-peptide data and recalibrate. The candidate list is a by-product —
useful only as a modest in-vitro triage for the drug-inhibitor chemotype.
