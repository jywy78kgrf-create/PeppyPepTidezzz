#!/usr/bin/env bash
# Bootstrap the FULL pipeline environment on a fresh (ephemeral) container.
# Reproducibility (constraint #5): every dependency pinned + re-fetched here.
# Idempotent: safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"

echo "### 1. Python core stack (deterministic fitness spine) ###"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
. .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements-core.txt
python -c "import rdkit,numpy,pandas,sklearn; print('core stack OK:', rdkit.__version__)"

echo "### 2. Miniconda + zinc-aware docking engines (AutoDock4Zn) ###"
if [ ! -x /opt/miniconda3/bin/conda ]; then
  curl -sSL -o /tmp/miniconda.sh https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
  bash /tmp/miniconda.sh -b -p /opt/miniconda3
fi
if ! /opt/miniconda3/bin/conda env list | grep -q '^dock '; then
  /opt/miniconda3/bin/conda create -n dock -y --override-channels \
    -c conda-forge -c bioconda "autodock=4.2.6" "autogrid=4.2.9" "autodock-vina=1.1.2"
fi
/opt/miniconda3/envs/dock/bin/autogrid4 --version | head -1

echo "### 3. AutoDock4Zn forcefield + zinc pseudo-atom script (constraint #3) ###"
mkdir -p deps/ad4zn
AD="https://raw.githubusercontent.com/ccsb-scripps/AutoDock-Vina/develop"
[ -s deps/ad4zn/AD4Zn.dat ]      || curl -sSL -o deps/ad4zn/AD4Zn.dat      "$AD/data/AD4Zn.dat"
[ -s deps/ad4zn/zinc_pseudo.py ] || curl -sSL -o deps/ad4zn/zinc_pseudo.py "$AD/example/autodock_scripts/zinc_pseudo.py"
grep -q "TZ" deps/ad4zn/AD4Zn.dat && echo "AD4Zn forcefield OK"

echo "### 4. MMP-1 catalytic-domain structure (1HFC, catalytic Zn) ###"
mkdir -p data/structures
[ -s data/structures/1HFC.pdb ] || curl -sSL -o data/structures/1HFC.pdb "https://files.rcsb.org/download/1HFC.pdb"
grep -qE "^HETATM.* ZN " data/structures/1HFC.pdb && echo "1HFC + catalytic zinc OK"

echo "### bootstrap complete ###"
