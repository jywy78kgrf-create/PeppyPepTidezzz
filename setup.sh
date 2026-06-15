#!/usr/bin/env bash
# ============================================================================
# Reproducible bootstrap. Clone -> setup -> run, on a fresh machine, from the
# repo alone. Two profiles selected by flag/env:
#   ./setup.sh --profile cpu    (default; AutoDock4Zn, runs anywhere)
#   ./setup.sh --profile gpu    (Boltz-2; run on a CUDA instance)
# Profile may also be set via PROFILE=gpu ./setup.sh
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

PROFILE="${PROFILE:-cpu}"
while [ $# -gt 0 ]; do case "$1" in
  --profile) PROFILE="$2"; shift 2;;
  *) echo "unknown arg: $1"; exit 2;;
esac; done
echo "### bootstrap profile: $PROFILE ###"

# --- Miniconda (env manager for both profiles) ---
if [ ! -x /opt/miniconda3/bin/conda ]; then
  curl -sSL -o /tmp/miniconda.sh https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
  bash /tmp/miniconda.sh -b -p /opt/miniconda3
fi
CONDA=/opt/miniconda3/bin/conda

# --- AutoDock4Zn forcefield assets (needed by the zinc-aware CPU scorer) ---
mkdir -p deps/ad4zn
AD="https://raw.githubusercontent.com/ccsb-scripps/AutoDock-Vina/develop"
[ -s deps/ad4zn/AD4Zn.dat ]      || curl -sSL -o deps/ad4zn/AD4Zn.dat      "$AD/data/AD4Zn.dat"
[ -s deps/ad4zn/zinc_pseudo.py ] || curl -sSL -o deps/ad4zn/zinc_pseudo.py "$AD/example/autodock_scripts/zinc_pseudo.py"

if [ "$PROFILE" = "cpu" ]; then
  ENV=peppy-cpu
  if ! $CONDA env list | grep -q "^$ENV "; then
    $CONDA create -n $ENV -y --override-channels -c conda-forge -c bioconda \
      python=3.11 "autodock=4.2.6" "autogrid=4.2.9" "autodock-vina=1.1.2" openbabel
  fi
  $CONDA run -n $ENV pip install --quiet -r requirements-core.txt -r requirements-cpu.txt
  $CONDA run -n $ENV python -c "import rdkit,meeko; print('cpu env OK rdkit',rdkit.__version__)"
  $CONDA run -n $ENV autogrid4 --version | head -1
  echo "### CPU ready. Run: $CONDA run -n $ENV python run_calibration.py \\"
  echo "      --config peptidepipe/configs/mmp1_cosmetic/target.yaml --outdir results/mmp1_autodock"

elif [ "$PROFILE" = "gpu" ]; then
  ENV=peppy-gpu
  if ! $CONDA env list | grep -q "^$ENV "; then
    $CONDA create -n $ENV -y --override-channels -c conda-forge python=3.11
  fi
  $CONDA run -n $ENV pip install --quiet -r requirements-core.txt -r requirements-gpu.txt
  # On a CUDA box, ensure a CUDA torch build (boltz pulls torch; override if needed):
  #   $CONDA run -n $ENV pip install --index-url https://download.pytorch.org/whl/cu124 torch
  $CONDA run -n $ENV python -c "import boltz, torch; print('gpu env OK; cuda=', torch.cuda.is_available())"
  echo "### GPU ready. Set scorer: boltz2 in target.yaml, then run run_calibration.py"

else
  echo "unknown profile: $PROFILE (use cpu|gpu)"; exit 2
fi
echo "### bootstrap complete ($PROFILE) ###"
