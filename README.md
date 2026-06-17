# peppypeptidezzz — a calibration-gated inhibitor triage platform

A **target-agnostic** computational pipeline that, for any target with enough public
bioactivity data, runs: **calibration gate → potency QSAR → selectivity models →
in-domain candidate generation → multi-objective (Pareto) ranking → developability
filter → bench hand-off.** Re-aiming at a new target is a new `config/` dir — **no
core edits.**

## Honest TL;DR (read this first)
- This is **decision-support, not drug discovery.** Every output is a *ranked
  hypothesis*; **no molecule has been made or tested.**
- The methods are **standard, off-the-shelf cheminformatics** (ECFP + RF/GBM QSAR,
  scaffold-split validation, Tanimoto applicability domain, BRICS, QED, SAScore,
  Pareto). Nothing here is algorithmically novel.
- Its real virtue is **rigor and honesty**: a hard gate, scaffold-split (not
  flattering random-split) validation, applicability-domain gating, uncertainty,
  and documented **negative** results — it says *"stop"* when warranted.
- The one thing it **cannot** do (and the only thing that turns this into discovery)
  is the **experimental feedback loop** — make the molecules, test them, retrain.
  That needs a wet lab. See `LIMITATIONS.md`.

## The pipeline
```
pull ChEMBL data ─► CALIBRATION GATE ─► POTENCY QSAR ─► SELECTIVITY QSAR
(scripts/fetch_*)   (does ANY scorer    (per target,    (target vs off-targets)
                     rank potency?)      held-out+scaffold)
        │                                                      │
        └──────────────► CANDIDATE GENERATION ◄────────────────┘
                         (in-domain analogs / BRICS, ZBG + AD gated)
                                    │
                         MULTI-OBJECTIVE PARETO  (potency × selectivity × QED)
                                    │
                         DEVELOPABILITY FILTER  (SAScore + Lipinski/Veber +
                                    │            alerts + single ZBG + uncertainty)
                         BENCH HAND-OFF  (candidates/<target>/)
```

## Architecture: CORE vs CONFIG
```
peptidepipe/
  core/        category-agnostic engine — NO target/chemotype literals
    scoring/   AffinityScorer interface + registry  <- engine swap seam
    calibration.py  held-out + scaffold Spearman gate
    generate.py  analog + BRICS candidate generators
    fitness.py   affinity + permeability/druglikeness + safety + chelator penalty
  adapters/    scorers registered by name: qsar (validated), autodock4zn, boltz2
  configs/<target>/target.yaml   everything target-specific lives here
```
Swapping the scorer is one line in `target.yaml` (`scorer: qsar|autodock4zn|boltz2`).

## Results

### Scorer scorecard — the calibration gate (MMP-1, identical held-out fold)
| scorer | held-out Spearman ρ | verdict |
|---|---|---|
| AutoDock4Zn (CPU, zinc-aware docking) | −0.03 | **NO-GO** |
| Boltz-2 (GPU co-folding affinity model) | +0.17 (n.s.) | **NO-GO** |
| **QSAR** (ECFP + RF/GBM, trained on the labels) | **+0.85** | **GO** |

Docking and a SOTA foundation model both *failed* to rank potency on these
congeneric sets; a standard ligand-based QSAR succeeded. (See
`calibration_results/CONCLUSION.md`.)

### Target panel — 11 targets validated (held-out ρ / novel-scaffold ρ)
| family | targets | held-out ρ | scaffold-split ρ |
|---|---|---|---|
| MMPs | MMP-1/2/3/9/13 | 0.81–0.86 | 0.73–0.76 |
| HDACs | HDAC1/2/3/6 | 0.73–0.85 | 0.67–0.77 |
| ADAMTS | ADAMTS-4/5 | 0.81–0.86 | 0.77 |

Selectivity is also learnable directly (MMP-1-vs-X ΔpIC50: held-out ρ 0.83–0.90).
(`calibration_results/MMP_PANEL.md`, `EXPANDED_PANEL.md`, `selectivity/`.)

### Candidate frontiers + developable shortlists
Four indication profiles taken end-to-end (`candidates/<target>/`):
| profile | developable | standout pick |
|---|---|---|
| **MMP-13 (OA collagenase)** | 525 | CAND-05580: pIC50 9.1, ~140× selective, SAScore 3.0 |
| **HDAC6-selective** | 331 | CAND-03763: pIC50 8.0, ~8× selective, 0 alerts |
| **ADAMTS-5 (OA aggrecanase)** | 260 | CAND-00727: pIC50 7.6, drug-like (ADAMTS-4 selectivity modest) |
| **MMP-1** | 5 | all weak — confirms MMP-1's potency/developability tension |

Each `candidates/<target>/` has: `candidates_profiled.csv`, `pareto_front.{csv,png}`,
`DEVELOPABLE.md` (shortlist with SAScore + rules + uncertainty), `PARETO.md`.

## The journey (honest findings)
- **Cosmetic → drug-discovery pivot.** The brief was cosmetic *peptide* MMP-1
  actives, but the only public data (ChEMBL) is drug-like *inhibitors* — and no
  cosmetic-peptide MMP data exists in pullable form. The platform can only operate
  where there's data, so it became a drug-discovery MMP/metalloenzyme tool. The
  cosmetic-peptide goal needs generated/supplier data (`LIMITATIONS.md`).
- **What failed, and why it's documented:** AutoDock & Boltz (gate); BRICS on tight
  domains (0 in-domain → switched to analog generation); the cosmetic-peptide data
  gap. Negative results are first-class here.
- **The core trade-off:** potency/selectivity vs drug-likeness are in tension — the
  most potent generated structures were un-makeable multi-chelators; the
  developability filter (SAScore + single-ZBG + alerts) is what surfaces usable
  shortlists. MMP-13 (OA) is the most promising profile; ADAMTS-5/ADAMTS-4 are too
  similar to separate.

## Limitations & what's needed next
See `LIMITATIONS.md`. In short: predicted, not measured; in-domain only; the genuine
next step everywhere is **wet-lab confirmation** (target IC50 + off-target
counter-screen) on the developable shortlists, then retrain on the results.

## Reproduce / aim at a new target (3 steps)
```bash
./setup.sh --profile cpu                                   # env (rdkit, sklearn, ...)
# 1. pull data: add target to scripts/fetch_targets.py (name -> ChEMBL id), run it
# 2. gate it:
conda run -n peppy-cpu python qsar_baseline.py --csv data/calibration/<t>_ic50.csv \
    --outdir calibration_results/qsar_<t>
# 3. if it passes, add configs/<t>_inhibitor/target.yaml then:
conda run -n peppy-cpu python run_generate.py --config peptidepipe/configs/<t>_inhibitor/target.yaml \
    --outdir results/<t>_candidates --method analog
conda run -n peppy-cpu python frontier.py --candidates results/<t>_candidates/candidates_all.csv \
    --target <t> --offtargets <a,b,c> --outdir candidates/<t>_inhibitor --label "<t>-selective"
conda run -n peppy-cpu python refine.py --candidates candidates/<t>_inhibitor/candidates_profiled.csv \
    --target <t> --outdir candidates/<t>_inhibitor
```

## Repo map
```
peptidepipe/        core engine + adapters + per-target configs
data/calibration/   curated ChEMBL IC50 sets (+ provenance) for 11 targets
scripts/            fetch_calibration.py, fetch_mmp_panel.py, fetch_targets.py
run_calibration.py  the gate (any scorer)
qsar_baseline.py    potency QSAR + validation (gate for trainable scorers)
selectivity_baseline.py  direct ΔpIC50 selectivity models
run_generate.py     candidate generation (analog/BRICS, ZBG + AD gated, fitness)
integrate_candidates.py / oa_select.py / frontier.py   profile + Pareto
refine.py           developability (SAScore + rules + uncertainty) re-ranker
pareto.py / write_handoff.py   frontier + bench hand-off artifacts
calibration_results/  all gate results + CONCLUSION.md, MMP_PANEL.md, EXPANDED_PANEL.md
candidates/         per-target deliverables (frontier, developable shortlist, hand-off)
LIMITATIONS.md      the honest read: what this is, isn't, and needs
```

## Determinism
Fixed seeds throughout (split 1234, model 42, RDKit/GA seeds); scaffold-split and
applicability-domain gating make the validation honest rather than optimistic.
