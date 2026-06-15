# peptidepipe

A **category-agnostic** computational pipeline for discovering candidate
peptide / small-molecule binders, with deterministic scoring and a hard
calibration gate. MMP-1 (cosmetic anti-collagenase arm) is the **first config**;
re-aiming at a new target is a new config dir, **no core edits**.

## Architecture: CORE vs CONFIG

```
peptidepipe/
  core/        category-agnostic engine — NO target/zinc/cosmetic literals
    scoring/   AffinityScorer interface + registry  <-- engine swap seam
    calibration.py  held-out Spearman gate (same for every scorer)
  adapters/    concrete engines, registered by name:
    autodock4zn  (CPU, zinc-aware; runs now)   boltz2 (GPU primary; deferred)
  configs/<target>/target.yaml   everything target-specific lives here
```

**Swapping the binding engine is one line** in `target.yaml`:
`scorer: autodock4zn` ↔ `scorer: boltz2`. The core never imports an engine; it
builds whatever name the config selects via the registry.

## Quick start (CPU, AutoDock4Zn — runs anywhere)

```bash
git clone <repo> && cd PeppyPepTidezzz
./setup.sh --profile cpu
/opt/miniconda3/bin/conda run -n peppy-cpu python run_calibration.py \
    --config peptidepipe/configs/mmp1_cosmetic/target.yaml \
    --outdir results/mmp1_autodock
```

## Boltz-2 calibration on a fresh GPU instance (RunPod / Lambda)

Boltz-2 is the deferred **primary** scorer (GPU-only). On a CUDA box:

```bash
git clone <repo> && cd PeppyPepTidezzz
PROFILE=gpu ./setup.sh --profile gpu          # installs boltz 2.2.1 + torch
# ensure a CUDA torch build if needed:
/opt/miniconda3/bin/conda run -n peppy-gpu \
    pip install --index-url https://download.pytorch.org/whl/cu124 torch
# flip the engine (one line) then run the SAME command/gate:
sed -i 's/^scorer: .*/scorer: boltz2/' peptidepipe/configs/mmp1_cosmetic/target.yaml
/opt/miniconda3/bin/conda run -n peppy-gpu python run_calibration.py \
    --config peptidepipe/configs/mmp1_cosmetic/target.yaml \
    --outdir results/mmp1_boltz2
```

Both engines score the **identical held-out split** (fixed seed), so their
Spearman correlations are directly comparable.

## Determinism

Scoring is reproducible (constraint #1): fixed RDKit embedding seed + fixed
AutoDock GA seed; AD4Zn forcefield supplies the explicit zinc term (constraint
#3). Boltz-2 affinity is likewise run with fixed settings.
