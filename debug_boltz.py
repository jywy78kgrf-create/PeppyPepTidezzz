"""Run ONE Boltz-2 prediction and print the REAL error cleanly.

Captures boltz's full stdout+stderr, strips tqdm progress-bar lines, and prints
the last ~40 meaningful lines (= the actual traceback). Uses the strongest (small,
~36 heavy-atom) calibration compound so ligand size is not a factor.

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
cmd = ["boltz", "predict", str(job), "--out_dir", str(wd),
       "--accelerator", "gpu", "--diffusion_samples_affinity", "1", "--use_msa_server"]
print("running:", " ".join(cmd), "\n(this takes ~3-4 min; please wait)", flush=True)
r = subprocess.run(cmd, capture_output=True, text=True)
out = (r.stdout or "") + "\n" + (r.stderr or "")
clean = []
for chunk in out.replace("\r", "\n").split("\n"):
    c = chunk.rstrip()
    if c and "it/s]" not in c and "%|" not in c:   # drop tqdm progress lines
        clean.append(c)
log = Path("/tmp/boltz_debug.log"); log.write_text(out)
print(f"\n=== boltz exit code: {r.returncode} (full raw log: {log}) ===")
print("=== last 40 meaningful lines (the real error is here) ===")
print("\n".join(clean[-40:]))
