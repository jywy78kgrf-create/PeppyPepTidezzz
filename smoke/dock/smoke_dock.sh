#!/usr/bin/env bash
# Stage 0-A smoke test: prove a ZINC-AWARE docking grid (AutoDock4Zn / AD4Zn
# forcefield) installs and runs DETERMINISTICALLY in this environment.
#
# Constraint #3: MMP-1 is a zinc metalloprotease; vanilla docking mishandles
# the catalytic zinc. AD4Zn adds a TZ tetrahedral-zinc pseudo-atom (placed by
# zinc_pseudo.py) plus an explicit zinc atom_par, so the grid carries the
# zinc-binding term. Constraint #1: same input -> identical map every run.
#
# Requires: conda env "dock" (autodock4, autogrid4) + deps/ad4zn/{AD4Zn.dat,zinc_pseudo.py}
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
cp ../../deps/ad4zn/AD4Zn.dat .

echo "== versions =="
autogrid4 --version 2>&1 | head -1
autodock4 --version 2>&1 | head -1

echo "== build minimal tetrahedral zinc site =="
python3 gen_receptor.py

echo "== place TZ zinc pseudo-atom (zinc_pseudo.py) =="
python ../../deps/ad4zn/zinc_pseudo.py -r receptor.pdbqt -o receptor_TZ.pdbqt | tail -1
grep -q " TZ$" receptor_TZ.pdbqt || { echo "FAIL: no TZ pseudo-atom placed"; exit 1; }

echo "== AutoGrid4 with AD4Zn forcefield (run 1) =="
autogrid4 -p grid.gpf -l gridA.glg >/dev/null 2>&1
grep -q "Successful Completion" gridA.glg || { echo "FAIL: autogrid did not complete"; exit 1; }
N=$(tail -n +7 receptor_TZ.C.map | wc -l | tr -d ' ')
[ "$N" = "9261" ] || { echo "FAIL: expected 9261 grid values, got $N"; exit 1; }

echo "== determinism: run 2, compare =="
md5a=$(md5sum receptor_TZ.C.map | awk '{print $1}')
autogrid4 -p grid.gpf -l gridB.glg >/dev/null 2>&1
md5b=$(md5sum receptor_TZ.C.map | awk '{print $1}')
[ "$md5a" = "$md5b" ] || { echo "FAIL: map not deterministic ($md5a != $md5b)"; exit 1; }

echo "grid values : $N"
echo "map md5     : $md5b (identical across runs)"
echo
echo "STAGE 0-A SMOKE: PASS"
