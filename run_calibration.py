#!/usr/bin/env python
"""Run the calibration gate for a target config with the configured scorer.

Engine selection is entirely config-driven (target.yaml `scorer:`). `--scorer`
is only an optional override for A/B comparison on the IDENTICAL held-out split.

  python run_calibration.py --config peptidepipe/configs/mmp1_cosmetic/target.yaml \
                            --outdir results/mmp1_autodock
"""
import argparse
from peptidepipe.core.targetspec import TargetSpec
from peptidepipe.core.calibration import run_calibration
from peptidepipe.core.scoring import registry
import peptidepipe.adapters  # noqa: F401  -> registers all scorers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--test-frac", type=float, default=0.2)
    ap.add_argument("--scorer", default=None,
                    help="override config scorer (same held-out split, for A/B)")
    args = ap.parse_args()

    target = TargetSpec.from_yaml(args.config)
    name = args.scorer or target.scorer
    print(f"target={target.name}  scorer={name}  available={registry.available()}")
    scorer = registry.build(name, target.scorer_params)

    res = run_calibration(target, scorer, args.outdir,
                          seed=args.seed, test_frac=args.test_frac)
    print("\n=== CALIBRATION RESULT ===")
    print(f"held-out molecules scored : {res.n_scored}/{res.n_test}")
    print(f"Spearman rho              : {res.spearman:.4f}  (p={res.pvalue:.2e})")
    print(f"predicted-vs-actual csv   : {res.csv_path}")
    print(f"plot                      : {res.plot_path}")


if __name__ == "__main__":
    main()
