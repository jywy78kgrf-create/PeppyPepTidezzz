"""peptidepipe — a category-agnostic peptide/small-molecule discovery pipeline.

Layers:
  core/      category-agnostic engine (generator, scoring interface, calibration,
             ranking, optimization, handoff). NO target/chemotype literals.
  adapters/  concrete scorer engines (autodock4zn now, boltz2 deferred) that
             register under a name; selected by CONFIG.
  configs/   per-target configuration (structure, calibration set, weights,
             scorer choice, target-class specifics like zinc-binding groups).

Re-aiming at a new target = a new config dir, no core edits.
"""
