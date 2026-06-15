"""Calibration harness (category-agnostic).

Given any TargetSpec (which names a structure, a known-actives CSV with measured
affinities, and a scorer), this:
  1. loads the known actives,
  2. makes a FIXED, reproducible held-out split (so every scorer is judged on
     the identical molecules -> AutoDock4Zn and Boltz-2 are directly comparable),
     and LABELS every molecule train/test,
  3. scores the calibration set with the configured scorer. For a physics scorer
     (AutoDock4Zn, no training) we score the FULL set: that full-set Spearman is
     the meaningful gate number. For a trainable scorer (Boltz-2) the held-out
     Spearman is the honest number. We report BOTH every time, on the same split,
  4. writes predicted-vs-actual CSV (with the split label) + PNG, and persists the
     held-out split manifest so a later engine evaluates on the identical molecules.

No target/engine specifics live here. The split depends only on (rows, seed,
test_frac), so it is identical across engines, which is what makes the held-out
correlations comparable.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import json
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from peptidepipe.core.candidate import Candidate
from peptidepipe.core.targetspec import TargetSpec
from peptidepipe.core.scoring.affinity_base import AffinityScorer


@dataclass
class CalibrationResult:
    n_total: int           # molecules in the calibration set (after dropna)
    n_test: int            # size of the held-out fold
    n_scored: int          # molecules actually scored ok (full set if score_full)
    n_scored_test: int     # held-out molecules scored ok
    spearman_full: float   # Spearman over ALL scored molecules (AD4Zn gate number)
    pvalue_full: float
    spearman: float        # Spearman over the held-out fold (engine-comparable number)
    pvalue: float
    csv_path: str
    plot_path: str
    split_path: str


def heldout_ids(df: pd.DataFrame, id_col: str, seed: int, test_frac: float) -> list[str]:
    """IDs of the deterministic held-out fold (same seed -> same molecules, always).

    Positional shuffle over the (already-ordered) rows, identical for any engine.
    """
    rng = np.random.default_rng(seed)
    idx = np.arange(len(df))
    rng.shuffle(idx)
    n_test = max(1, int(round(len(df) * test_frac)))
    test_pos = sorted(idx[:n_test])
    return [str(df.iloc[i][id_col]) for i in test_pos]


def _score_all(scorer: AffinityScorer, cands: list[Candidate], workers: int):
    """Score candidates, optionally in parallel. Each candidate is independent
    (own work dir; shared read-only maps), so threads give real parallelism while
    AutoDock4 runs in subprocesses. workers=1 -> the scorer's own score_many."""
    if workers <= 1:
        return scorer.score_many(cands)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(scorer.score, cands))


def run_calibration(target: TargetSpec, scorer: AffinityScorer, outdir: str,
                    seed: int = 1234, test_frac: float = 0.2,
                    workers: int = 1, score_full: bool = True) -> CalibrationResult:
    df = pd.read_csv(target.resolve(target.calibration_csv))
    df = df[[target.id_col, target.smiles_col, target.affinity_col]].dropna().reset_index(drop=True)

    # deterministic held-out fold -> label every molecule train/test
    test_ids = set(heldout_ids(df, target.id_col, seed, test_frac))
    df["split"] = [("test" if str(r[target.id_col]) in test_ids else "train")
                   for _, r in df.iterrows()]

    score_df = df if score_full else df[df["split"] == "test"]
    cands = [Candidate(id=str(r[target.id_col]), smiles=str(r[target.smiles_col]))
             for _, r in score_df.iterrows()]
    measured = {str(r[target.id_col]): float(r[target.affinity_col]) for _, r in df.iterrows()}
    split_of = {str(r[target.id_col]): r["split"] for _, r in df.iterrows()}

    scorer.prepare(target)
    results = _score_all(scorer, cands, workers)

    rows = [(r.candidate_id, split_of[r.candidate_id], measured[r.candidate_id],
             r.score, r.note)
            for r in results if r.ok and r.candidate_id in measured]
    out = pd.DataFrame(rows, columns=["id", "split", "measured", "predicted", "note"])

    Path(outdir).mkdir(parents=True, exist_ok=True)
    csv_path = str(Path(outdir) / "predicted_vs_actual.csv")
    out.to_csv(csv_path, index=False)

    def _rho(frame):
        if len(frame) >= 3:
            r, p = spearmanr(frame.predicted, frame.measured)
            return float(r), float(p)
        return float("nan"), float("nan")

    rho_full, p_full = _rho(out)
    test_out = out[out["split"] == "test"]
    rho_test, p_test = _rho(test_out)

    # persist the held-out split manifest (engine-independent; for the Boltz-2 run)
    split_path = str(Path(outdir) / "heldout_split.json")
    Path(split_path).write_text(json.dumps({
        "seed": seed, "test_frac": test_frac,
        "n_total": int(len(df)), "n_test": int(df["split"].eq("test").sum()),
        "test_ids": sorted(test_ids),
        "train_ids": sorted(set(map(str, df[target.id_col])) - test_ids),
    }, indent=2))

    plot_path = str(Path(outdir) / "predicted_vs_actual.png")
    _plot(out, rho_full, rho_test, target, scorer, plot_path)

    return CalibrationResult(
        n_total=len(df), n_test=int(df["split"].eq("test").sum()),
        n_scored=len(out), n_scored_test=len(test_out),
        spearman_full=rho_full, pvalue_full=p_full,
        spearman=rho_test, pvalue=p_test,
        csv_path=csv_path, plot_path=plot_path, split_path=split_path,
    )


def _plot(out: pd.DataFrame, rho_full: float, rho_test: float, target: TargetSpec,
          scorer: AffinityScorer, path: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(5.2, 5.2))
    tr = out[out["split"] == "train"]
    te = out[out["split"] == "test"]
    if len(tr):
        ax.scatter(tr.predicted, tr.measured, s=18, alpha=0.55, label=f"train (n={len(tr)})")
    if len(te):
        ax.scatter(te.predicted, te.measured, s=30, alpha=0.85,
                   edgecolor="k", linewidth=0.4, label=f"held-out (n={len(te)})")
    ax.set_xlabel(f"predicted score ({scorer.name}, higher = better binder)")
    ax.set_ylabel(f"measured {target.affinity_col}")
    ax.set_title(f"{target.name}: calibration\n"
                 f"Spearman rho = {rho_full:.3f} (full n={len(out)})  |  "
                 f"{rho_test:.3f} (held-out n={len(te)})")
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
