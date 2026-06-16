"""Budget-safe, RESUMABLE Boltz-2 scoring of the held-out 47.

Writes each compound's result to results/mmp1_boltz2_heldout.csv the instant it
finishes (flush) and skips anything already there, so:
  - if GPU credit/pod dies mid-run, completed compounds are preserved;
  - re-running resumes from where it stopped (no recompute);
  - a running held-out Spearman is printed every 10 compounds, so even a partial
    run gives a usable number.

    /opt/miniconda3/bin/conda run --no-capture-output -n peppy-gpu python run_boltz_heldout.py
"""
import csv
from pathlib import Path
import pandas as pd
from scipy.stats import spearmanr
from peptidepipe.core.targetspec import TargetSpec
from peptidepipe.core.candidate import Candidate
from peptidepipe.core.scoring import registry
from peptidepipe.core.calibration import heldout_ids
import peptidepipe.adapters  # noqa: F401  registers scorers

t = TargetSpec.from_yaml("peptidepipe/configs/mmp1_cosmetic/target.yaml")
df = pd.read_csv(t.resolve(t.calibration_csv))[
    [t.id_col, t.smiles_col, t.affinity_col]].dropna().reset_index(drop=True)
test_ids = set(heldout_ids(df, t.id_col, 1234, 0.2))           # SAME split as AutoDock
test = df[df[t.id_col].astype(str).isin(test_ids)].reset_index(drop=True)

out = Path("results/mmp1_boltz2_heldout.csv")
out.parent.mkdir(parents=True, exist_ok=True)
done = set(pd.read_csv(out).id.astype(str)) if out.exists() else set()
print(f"held-out: {len(test)} compounds | {len(done)} already done | "
      f"{len(test)-len(done)} to go", flush=True)


def report():
    d = pd.read_csv(out)
    d = d[pd.to_numeric(d["predicted"], errors="coerce").notna()]
    if len(d) >= 3:
        r = spearmanr(pd.to_numeric(d["predicted"]), d["measured"])
        print(f"  [running] held-out Spearman  n={len(d)}  rho={r.statistic:+.4f}  "
              f"p={r.pvalue:.2e}", flush=True)


s = registry.build("boltz2", t.scorer_params)
s.prepare(t)
first = not out.exists()
with out.open("a", newline="") as fh:
    w = csv.writer(fh)
    if first:
        w.writerow(["id", "measured", "predicted", "prob_binary", "note"]); fh.flush()
    n = len(done)
    for _, r in test.iterrows():
        cid = str(r[t.id_col])
        if cid in done:
            continue
        res = s.score(Candidate(id=cid, smiles=str(r[t.smiles_col])))
        pb = (res.raw or {}).get("affinity_probability_binary", "")
        w.writerow([cid, r[t.affinity_col], res.score if res.ok else "", pb, res.note])
        fh.flush()
        n += 1
        tag = f"{res.score:+.4f}" if res.ok else f"FAIL: {res.note[:60]}"
        print(f"[{n}/{len(test)}] {cid}  measured={r[t.affinity_col]:.2f}  score={tag}", flush=True)
        if n % 10 == 0:
            report()

print("\n=== DONE (held-out 47) ===")
report()
