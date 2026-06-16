# MMP-1 calibration gate — overall conclusion

Both binding scorers were run on the SAME 237-compound peptidomimetic calibration
set and the SAME deterministic held-out fold (seed 1234, 190/47).

| scorer | scope | Spearman ρ vs measured pIC50 | verdict |
|---|---|---|---|
| AutoDock4Zn (CPU, zinc-aware) | full 237 | +0.007 | NO-GO |
| AutoDock4Zn | held-out 47 | −0.025 | NO-GO |
| Boltz-2 (GPU, trained) | held-out 46 | +0.17 (p≈0.25, n.s.) | NO-GO |

**Neither scorer passes the gate.** Structure-based docking (even at thorough GA
convergence) and a state-of-the-art co-folding affinity model both fail to rank
these MMP-1 peptidomimetics by potency on held-out data. Per protocol, the
pipeline is NOT validated end-to-end and candidate generation must NOT proceed.

That both methods fail — and that more GA sampling (AutoDock) and the full range
(Boltz) didn't help — suggests the bottleneck is the target/benchmark, not a single
tool. Options before any candidate generation:
- a QSAR/ML baseline trained on these 237 labels (is the set rankable at all?);
- better receptor/pose modelling (multi-conformer, flexible active site);
- re-examine the calibration set (assay heterogeneity, congeneric subsets);
- a different, better-behaved target/benchmark.

The scoring interface, calibration harness, held-out split, and GPU path are all
built and validated as plumbing; swapping in a new scorer remains a one-line config
change. What's missing is a scorer that actually clears this gate.
