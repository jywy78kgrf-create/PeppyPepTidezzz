"""Run ONE Boltz-2 prediction with FULL output visible (no capture), to surface
why the adapter's boltz call fails. Uses the first calibration compound.

    /opt/miniconda3/bin/conda run --no-capture-output -n peppy-gpu python debug_boltz.py
"""
import subprocess, tempfile
from pathlib import Path
import pandas as pd
from peptidepipe.core.targetspec import TargetSpec

t = TargetSpec.from_yaml("peptidepipe/configs/mmp1_cosmetic/target.yaml")
seq = t.scorer_params["protein_sequence"]
row = pd.read_csv(t.resolve(t.calibration_csv)).iloc[0]
smiles = str(row[t.smiles_col])
wd = Path(tempfile.mkdtemp(prefix="boltzdbg_"))
job = wd / "dbg.yaml"
job.write_text(
    "version: 1\nsequences:\n  - protein:\n      id: A\n"
    f"      sequence: {seq}\n  - ligand:\n      id: L\n"
    f"      smiles: '{smiles}'\nproperties:\n  - affinity:\n      binder: L\n")
print("=== job YAML ===\n" + job.read_text())
cmd = ["boltz", "predict", str(job), "--out_dir", str(wd),
       "--accelerator", "gpu", "--diffusion_samples_affinity", "1", "--use_msa_server"]
print("=== running (output is LIVE, not captured) ===\n" + " ".join(cmd), flush=True)
r = subprocess.run(cmd)   # no capture -> real error streams to terminal
print(f"\n=== boltz exit code: {r.returncode} ===")
if r.returncode == 0:
    for f in wd.glob("**/affinity_*.json"):
        print("affinity output:", f, "\n", f.read_text())
