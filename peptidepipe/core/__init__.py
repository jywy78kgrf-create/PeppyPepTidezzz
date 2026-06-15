"""peptidepipe.core — the CATEGORY-AGNOSTIC pipeline.

Nothing in this subpackage may contain MMP-1, cosmetic, or zinc-specific
assumptions. Everything target-specific is supplied at runtime via a
TargetSpec loaded from a CONFIG (see peptidepipe/configs/<target>/target.yaml).
If you need an MMP-1/zinc/permeability literal here, it belongs in CONFIG.
"""
