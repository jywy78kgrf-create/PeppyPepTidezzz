#!/usr/bin/env python
"""Candidate generation stage — produces the ranked candidate list (the project
deliverable). Runs ONLY after the calibration gate has passed (QSAR: held-out
Spearman +0.47).

Pipeline (all config-driven):
  1. build + train the configured scorer on the target's calibration set;
  2. BRICS-recombine the known actives into novel candidates;
  3. filter: valid -> novel -> correct chemotype (config backbone-residue window)
     -> carries a zinc-binding group (config ZBG SMARTS) -> inside the scorer's
     applicability domain (max Tanimoto to training >= learned threshold);
  4. score the multi-term COSMETIC fitness (affinity + skin-permeability + safety,
     config weights);
  5. rank, write the top-N ranked candidates + a full table.

  python run_generate.py --config peptidepipe/configs/mmp1_cosmetic/target.yaml \
                         --outdir results/mmp1_candidates --n-generate 4000 --top 50
"""
import argparse
from pathlib import Path
import pandas as pd

from peptidepipe.core.targetspec import TargetSpec
from peptidepipe.core.candidate import Candidate
from peptidepipe.core.scoring import registry
from peptidepipe.core.generate import brics_candidates, analog_candidates
from peptidepipe.core.data.peptidic import in_residue_range
from peptidepipe.core import fitness as fit
import peptidepipe.adapters  # noqa: F401  registers scorers


def load_zbg(target):
    from rdkit import Chem
    path = target.resolve(target.extra["zbg_smarts"])
    pats = []
    for ln in Path(path).read_text().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "\t" not in ln:
            continue
        name, smarts = ln.split("\t", 1)
        p = Chem.MolFromSmarts(smarts.strip())
        if p is not None:
            pats.append((name, p))
    return pats


def has_zbg(smiles, zbg):
    from rdkit import Chem
    m = Chem.MolFromSmiles(smiles)
    return m is not None and any(m.HasSubstructMatch(p) for _, p in zbg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--n-generate", type=int, default=4000)
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--method", choices=["analog", "brics"], default="analog",
                    help="analog = in-domain single edits (default); brics = explorative recombination")
    args = ap.parse_args()

    target = TargetSpec.from_yaml(args.config)
    print(f"target={target.name}  scorer={target.scorer}")
    scorer = registry.build(target.scorer, target.scorer_params)
    scorer.prepare(target)
    print(f"scorer trained; applicability-domain Tanimoto threshold = {getattr(scorer,'ad_threshold',float('nan')):.3f}")

    # seeds + novelty reference = the known actives
    cal = pd.read_csv(target.resolve(target.calibration_csv))
    from rdkit import Chem, RDLogger
    RDLogger.DisableLog("rdApp.*")
    seeds = [str(s) for s in cal[target.smiles_col].dropna()]
    known = {Chem.MolToSmiles(m) for m in (Chem.MolFromSmiles(s) for s in seeds) if m}

    lo, hi = target.domain.get("chemotype_backbone_residues", [1, 99])
    zbg = load_zbg(target)
    gen = analog_candidates if args.method == "analog" else brics_candidates
    print(f"generating up to {args.n_generate} {args.method} candidates from {len(seeds)} actives ...")
    raw = gen(seeds, n_max=args.n_generate, seed=args.seed)
    print(f"  generated {len(raw)} unique sanitisable molecules")

    # cheap structural filters first
    rows = []
    n_novel = n_chemo = n_zbg = 0
    for smi in raw:
        if smi in known:
            continue
        n_novel += 1
        if not in_residue_range(smi, lo, hi):
            continue
        n_chemo += 1
        if not has_zbg(smi, zbg):
            continue
        n_zbg += 1
        rows.append(smi)
    print(f"  novel={n_novel}  chemotype[{lo}-{hi} residues]={n_chemo}  with ZBG={n_zbg}")

    # score (gives pIC50 + applicability domain), keep in-domain
    cands = [Candidate(id=f"CAND-{i:05d}", smiles=s) for i, s in enumerate(rows)]
    results = scorer.score_many(cands)
    keep = []
    for c, r in zip(cands, results):
        if r.ok and r.raw.get("in_domain"):
            keep.append((c, r))
    print(f"  in applicability domain = {len(keep)}")
    if not keep:
        print("No in-domain candidates — widen generation or lower ad_percentile.")
        return

    # multi-term cosmetic fitness over the in-domain pool
    mols = [Chem.MolFromSmiles(c.smiles) for c, _ in keep]
    pIC50 = [r.raw["pIC50"] for _, r in keep]
    logkp = [fit.potts_guy_logkp(m) for m in mols]
    alerts = [fit.structural_alerts(m) for m in mols]
    score, comp = fit.combine(pIC50, logkp, alerts, target.weights)

    out = pd.DataFrame({
        "id": [c.id for c, _ in keep],
        "smiles": [c.smiles for c, _ in keep],
        "fitness": score,
        "pred_pIC50": pIC50,
        "affinity_norm": comp["affinity_norm"],
        "permeability_norm": comp["permeability_norm"],
        "safety_norm": comp["safety_norm"],
        "logKp_cm_h": logkp,
        "struct_alerts": alerts,
        "applicability_tanimoto": [r.raw["max_tanimoto"] for _, r in keep],
        "is_hit": [p >= (target.hit_threshold or 0) for p in pIC50],
    }).sort_values("fitness", ascending=False).reset_index(drop=True)
    out.insert(0, "rank", out.index + 1)

    Path(args.outdir).mkdir(parents=True, exist_ok=True)
    out.to_csv(Path(args.outdir) / "candidates_all.csv", index=False)
    out.head(args.top).to_csv(Path(args.outdir) / "candidates_top.csv", index=False)

    print(f"\n=== RANKED CANDIDATES (top {min(args.top,len(out))} of {len(out)}) ===")
    cols = ["rank", "id", "fitness", "pred_pIC50", "permeability_norm", "safety_norm",
            "struct_alerts", "applicability_tanimoto", "is_hit"]
    pd.set_option("display.width", 160)
    print(out.head(min(args.top, 15))[cols].round(3).to_string(index=False))
    print(f"\nhits (pred_pIC50 >= {target.hit_threshold}): {int(out.is_hit.sum())}/{len(out)}")
    print(f"written: {args.outdir}/candidates_top.csv  (+ candidates_all.csv)")


if __name__ == "__main__":
    main()
