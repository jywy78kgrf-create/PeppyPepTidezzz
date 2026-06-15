"""Boltz-2 SMOKE TEST — run this on the GPU box BEFORE the full 237 run.

It docks just 5 calibration compounds (the 2 most potent, 2 weakest, 1 median by
measured pIC50) and checks three things:
  1. does the Boltz-2 adapter run end-to-end on this GPU at all,
  2. the SIGN is right (more potent compounds should get a HIGHER score, because
     the adapter negates Boltz's affinity_pred_value = log10(IC50 uM)),
  3. how long ONE compound takes -> multiply by 237 to estimate the full-run cost.

Usage (on the GPU box, from the repo root):
    /opt/miniconda3/bin/conda run -n peppy-gpu python smoke_boltz.py
"""
import time
import pandas as pd
from peptidepipe.core.targetspec import TargetSpec
from peptidepipe.core.candidate import Candidate
from peptidepipe.core.scoring import registry
import peptidepipe.adapters  # noqa: F401  registers scorers

CFG = "peptidepipe/configs/mmp1_cosmetic/target.yaml"


def main():
    t = TargetSpec.from_yaml(CFG)
    df = pd.read_csv(t.resolve(t.calibration_csv))[
        [t.id_col, t.smiles_col, t.affinity_col]].dropna().sort_values(t.affinity_col)
    pick = pd.concat([df.head(2), df.iloc[[len(df) // 2]], df.tail(2)])  # 2 weak, 1 mid, 2 strong

    print(f"building boltz2 scorer (device={t.scorer_params.get('device')}) ...", flush=True)
    s = registry.build("boltz2", t.scorer_params)
    s.prepare(t)   # raises a clear error if boltz/CUDA are missing

    rows = []
    for _, r in pick.iterrows():
        c = Candidate(id=str(r[t.id_col]), smiles=str(r[t.smiles_col]))
        t0 = time.time()
        res = s.score(c)
        dt = time.time() - t0
        rows.append((c.id, float(r[t.affinity_col]), res.score, res.ok, dt, res.raw, res.note))
        print(f"  {c.id:14s} pIC50={r[t.affinity_col]:.2f}  score={res.score if res.ok else 'FAIL'}"
              f"  ({dt:.0f}s)  raw={res.raw} {('' if res.ok else res.note)}", flush=True)

    ok = [x for x in rows if x[3]]
    if len(ok) < 4:
        print("\n[!] Too many failures — fix the adapter/env before the full run.")
        return
    strong = sorted(ok, key=lambda x: x[1])[-2:]   # highest pIC50
    weak = sorted(ok, key=lambda x: x[1])[:2]       # lowest pIC50
    ms, mw = sum(x[2] for x in strong) / 2, sum(x[2] for x in weak) / 2
    per = sum(x[4] for x in ok) / len(ok)
    print(f"\nmean score: strong(pIC50)={ms:+.3f}  weak(pIC50)={mw:+.3f}")
    if ms > mw:
        print("SIGN OK: potent compounds score higher (as expected).")
    else:
        print("[!] SIGN LOOKS INVERTED: potent compounds score LOWER. Stop and report this "
              "before the full run (the adapter's sign convention may need another look).")
    print(f"\n~{per:.0f}s per compound  ->  full 237-set ~= {per*237/3600:.1f} GPU-hours "
          f"(serial, --workers 1).")


if __name__ == "__main__":
    main()
