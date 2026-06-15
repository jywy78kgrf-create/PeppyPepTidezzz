"""Boltz-2 affinity adapter — the DEFERRED PRIMARY scorer.

This is a real (un-mocked) implementation of the AffinityScorer interface that
drives Boltz-2. It is *deferred*, not cut: Boltz-2 is a GPU model and the
current sandbox is CPU-only, so prepare() will refuse to run unless the GPU
profile is installed and a CUDA device is available. It does NOT fabricate
scores. On a GPU instance (see README) it runs for real with no code change —
selecting it is a one-line edit (`scorer: boltz2`) in the target YAML.

Device, model, and protein target all come from config (scorer_params), never
hard-coded — so the same code runs against any target on any GPU machine.
"""
from __future__ import annotations
import json
import subprocess
import tempfile
from pathlib import Path

from peptidepipe.core.candidate import Candidate
from peptidepipe.core.targetspec import TargetSpec
from peptidepipe.core.scoring.affinity_base import AffinityScorer, AffinityResult
from peptidepipe.core.scoring.registry import register


@register("boltz2")
class Boltz2Affinity(AffinityScorer):
    def prepare(self, target: TargetSpec) -> None:
        p = self.params
        self.device = p.get("device", "cuda")          # from config; cpu allowed but impractical
        self.protein_seq = p["protein_sequence"]        # config supplies target sequence
        # Boltz REQUIRES an MSA for the protein. Either let it build one via the
        # public mmseqs2 server (needs internet) or point at a precomputed .a3m.
        self.use_msa_server = bool(p.get("use_msa_server", True))
        self.msa_path = p.get("msa_path")               # optional precomputed a3m (config-relative)
        if self.msa_path:
            self.msa_path = target.resolve(self.msa_path)
        self.diffusion_samples_affinity = int(p.get("diffusion_samples_affinity", 5))
        self.workdir = Path(p.get("workdir", tempfile.mkdtemp(prefix="boltz2_"))).resolve()
        self.workdir.mkdir(parents=True, exist_ok=True)

        # Hard, honest gate: require the real dependency + accelerator. No fallback.
        try:
            import boltz  # noqa: F401
        except Exception as e:  # pragma: no cover - exercised only off-GPU
            raise RuntimeError(
                "Boltz-2 is the deferred GPU scorer and is not installed in this "
                "environment. Install the GPU profile (./setup.sh --profile gpu) on a "
                "CUDA machine, then run with `scorer: boltz2`. Refusing to mock."
            ) from e
        if self.device == "cuda":
            try:
                import torch
                if not torch.cuda.is_available():
                    raise RuntimeError("device=cuda requested but torch.cuda.is_available() is False")
            except Exception as e:  # pragma: no cover
                raise RuntimeError(f"Boltz-2 requires a CUDA GPU: {e}") from e

    def score(self, candidate: Candidate) -> AffinityResult:
        # Build a Boltz-2 YAML job: protein + ligand(SMILES) + affinity property.
        msa_line = f"      msa: {self.msa_path}\n" if self.msa_path else ""
        job = self.workdir / f"{candidate.id}.yaml"
        job.write_text(
            "version: 1\n"
            "sequences:\n"
            "  - protein:\n"
            "      id: A\n"
            f"      sequence: {self.protein_seq}\n"
            f"{msa_line}"
            "  - ligand:\n"
            "      id: L\n"
            f"      smiles: '{candidate.smiles}'\n"
            "properties:\n"
            "  - affinity:\n"
            "      binder: L\n"
        )
        acc = "gpu" if self.device == "cuda" else "cpu"
        cmd = ["boltz", "predict", str(job), "--out_dir", str(self.workdir),
               "--accelerator", acc,
               "--diffusion_samples_affinity", str(self.diffusion_samples_affinity)]
        if self.use_msa_server and not self.msa_path:
            cmd.append("--use_msa_server")   # auto-build MSA (needs internet)
        subprocess.run(cmd, check=True, capture_output=True, text=True)

        # Boltz-2 writes affinity_<name>.json. affinity_pred_value is log10(IC50[uM])
        # -> LOWER = stronger binder. The AffinityScorer convention is higher = better,
        # so the score is NEGATED (constraint: every adapter returns higher=stronger),
        # which makes the calibration Spearman directly comparable to AutoDock4Zn.
        pred = list(self.workdir.glob(f"**/affinity_{candidate.id}.json"))
        if not pred:
            return AffinityResult(candidate.id, float("nan"), ok=False,
                                  note="boltz2: no affinity output")
        d = json.loads(pred[0].read_text())
        val = d.get("affinity_pred_value")
        if val is None:
            return AffinityResult(candidate.id, float("nan"), ok=False,
                                  note="boltz2: affinity_pred_value missing")
        return AffinityResult(candidate.id, score=-float(val), raw={
            "affinity_pred_value": val,                                  # log10(IC50 uM)
            "affinity_probability_binary": d.get("affinity_probability_binary"),
        })
