"""Calibration harness (category-agnostic).

Given any TargetSpec (which names a structure, a known-actives CSV with measured
affinities, and a scorer), this:
  1. loads the known actives,
  2. makes a FIXED, reproducible held-out split (so every scorer is judged on
     the identical molecules -> AutoDock4Zn and Boltz-2 are directly comparable),
  3. scores the held-out fold with the configured scorer,
  4. reports Spearman( predicted_score , measured_affinity ) on the held-out
     fold  -- THIS number is the gate,
  5. writes predicted-vs-actual CSV + PNG.

No target/engine specifics live here. Trainable scorers (future) may use the
train fold; physics scorers (AutoDock) simply ignore it. The split is the same
either way, which is what makes the correlations comparable.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from peptidepipe.core.candidate import Candidate
from peptidepipe.core.targetspec import TargetSpec
from peptidepipe.core.scoring.affinity_base import AffinityScorer


@dataclass
class CalibrationResult:
    n_total: int
    n_test: int
    n_scored: int
    spearman: float
    pvalue: float
    csv_path: str
    plot_path: str


def _split(df: pd.DataFrame, seed: int, test_frac: float) -> pd.DataFrame:
    """Deterministic held-out split (same seed -> same test molecules, always)."""
    rng = np.random.default_rng(seed)
    idx = np.arange(len(df))
    rng.shuffle(idx)
    n_test = max(1, int(round(len(df) * test_frac)))
    test_idx = sorted(idx[:n_test])
    return df.iloc[test_idx].reset_index(drop=True)


def run_calibration(target: TargetSpec, scorer: AffinityScorer, outdir: str,
                    seed: int = 1234, test_frac: float = 0.2) -> CalibrationResult:
    df = pd.read_csv(target.resolve(target.calibration_csv))
    df = df[[target.id_col, target.smiles_col, target.affinity_col]].dropna()
    test = _split(df, seed, test_frac)

    cands = [Candidate(id=str(r[target.id_col]), smiles=str(r[target.smiles_col]))
             for _, r in test.iterrows()]
    measured = {str(r[target.id_col]): float(r[target.affinity_col])
                for _, r in test.iterrows()}

    scorer.prepare(target)
    results = scorer.score_many(cands)

    rows = [(r.candidate_id, measured[r.candidate_id], r.score, r.note)
            for r in results if r.ok and r.candidate_id in measured]
    out = pd.DataFrame(rows, columns=["id", "measured", "predicted", "note"])

    Path(outdir).mkdir(parents=True, exist_ok=True)
    csv_path = str(Path(outdir) / "predicted_vs_actual.csv")
    out.to_csv(csv_path, index=False)

    if len(out) >= 3:
        rho, p = spearmanr(out.predicted, out.measured)
    else:
        rho, p = float("nan"), float("nan")

    plot_path = str(Path(outdir) / "predicted_vs_actual.png")
    _plot(out, rho, target, scorer, plot_path)

    return CalibrationResult(
        n_total=len(df), n_test=len(test), n_scored=len(out),
        spearman=float(rho), pvalue=float(p), csv_path=csv_path, plot_path=plot_path,
    )


def _plot(out: pd.DataFrame, rho: float, target: TargetSpec,
          scorer: AffinityScorer, path: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(5, 5))
    if len(out):
        ax.scatter(out.predicted, out.measured, s=18, alpha=0.7)
    ax.set_xlabel(f"predicted score ({scorer.name}, higher=better binder)")
    ax.set_ylabel(f"measured {target.affinity_col}")
    ax.set_title(f"{target.name}: held-out calibration\nSpearman rho = {rho:.3f} (n={len(out)})")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
