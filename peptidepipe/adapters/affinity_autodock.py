"""AutoDock4(Zn) affinity adapter — the CPU, zinc-aware binding term used for
the calibration gate in this sandbox.

Real engine, no mocks. Pipeline per target (prepare, once):
  receptor PDB -> rigid PDBQT (Open Babel) -> add TZ tetrahedral-zinc pseudo
  atoms (zinc_pseudo.py) -> AutoGrid4 with the AD4Zn forcefield, precomputing
  affinity maps for a SUPERSET of ligand atom types so each ligand reuses them.
Per candidate (score):
  SMILES -> 3D (RDKit ETKDG, fixed seed) -> ligand PDBQT (Meeko) -> AutoDock4
  Lamarckian GA docking with a FIXED rng seed (constraint #1: reproducible) ->
  parse best estimated free energy of binding; score = -energy (higher=better).

Everything zinc/target-specific (AD4Zn file, catalytic-metal selection, grid
box) arrives via target.scorer_params from CONFIG. This module hard-codes no
MMP-1/zinc literals beyond honouring those config values.
"""
from __future__ import annotations
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from peptidepipe.core.candidate import Candidate
from peptidepipe.core.targetspec import TargetSpec
from peptidepipe.core.scoring.affinity_base import AffinityScorer, AffinityResult
from peptidepipe.core.scoring.registry import register

# Superset of common AutoDock4 ligand atom types -> maps precomputed once.
_LIGAND_TYPES = ["A", "C", "N", "NA", "OA", "SA", "S", "HD", "P",
                 "F", "Cl", "Br", "I"]


def _run(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


@register("autodock4zn")
class AutoDock4ZnAffinity(AffinityScorer):
    # ---- one-time target preparation -------------------------------------
    def prepare(self, target: TargetSpec) -> None:
        p = self.params
        # absolute: AutoDock4 runs per-candidate with cwd=candidate dir, so the
        # parameter_file path baked into each DPF must be absolute to resolve.
        self.workdir = Path(p.get("workdir", tempfile.mkdtemp(prefix="ad4zn_"))).resolve()
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.ad4zn_dat = target.resolve(p["ad4zn_dat"])          # config-supplied
        self.zinc_pseudo = target.resolve(p["zinc_pseudo_py"])   # config-supplied
        self.spacing = float(p.get("spacing", 0.375))
        self.npts = p.get("npts", [40, 40, 40])
        self.seed = int(p.get("seed", 42))
        self.ga_run = int(p.get("ga_run", 10))
        self.ga_evals = int(p.get("ga_num_evals", 250000))
        metal = p["catalytic_metal"]          # config: {element, resseq} -> grid centre

        struct = target.resolve(target.structure_path)
        rec_pdb = self._clean_receptor(struct, metal)
        center = self._metal_xyz(struct, metal)
        rec_pdbqt = self._receptor_pdbqt(rec_pdb, metal)
        rec_tz = self._add_tz(rec_pdbqt)
        self.fld = self._run_autogrid(rec_tz, center)

    def _clean_receptor(self, pdb, metal) -> Path:
        """Keep protein ATOMs + the catalytic metal HETATM; drop waters/others."""
        out = self.workdir / "receptor.pdb"
        keep = []
        for ln in Path(pdb).read_text().splitlines():
            if ln.startswith("ATOM"):
                keep.append(ln)
            elif ln.startswith("HETATM") and ln[12:16].strip() == metal["element"] \
                    and int(ln[22:26]) == int(metal["resseq"]):
                keep.append(ln)
        out.write_text("\n".join(keep) + "\nTER\nEND\n")
        return out

    def _metal_xyz(self, pdb, metal):
        for ln in Path(pdb).read_text().splitlines():
            if ln.startswith("HETATM") and ln[12:16].strip() == metal["element"] \
                    and int(ln[22:26]) == int(metal["resseq"]):
                return (float(ln[30:38]), float(ln[38:46]), float(ln[46:54]))
        raise ValueError(f"catalytic metal {metal} not found in {pdb}")

    def _receptor_pdbqt(self, rec_pdb, metal) -> Path:
        """Receptor -> rigid PDBQT with polar H + Gasteiger charges.

        Open Babel's Gasteiger model fails ("0 molecules converted") on the
        metal-containing receptor, so we charge the protein WITHOUT the catalytic
        metal, then re-attach the metal atom (correctly AutoDock-typed) afterwards.
        The metal's own charge is irrelevant here: zinc_pseudo.py zeroes it and the
        TZ pseudo-atoms carry the coordination term (the point of the AD4Zn force-
        field). Metal selection is config-driven (metal["element"]); no zinc literal.
        """
        el = metal["element"]
        # protein only (drop the catalytic metal so Gasteiger converges)
        prot_pdb = self.workdir / "protein.pdb"
        prot_pdb.write_text("\n".join(
            ln for ln in Path(rec_pdb).read_text().splitlines()
            if not (ln.startswith(("ATOM", "HETATM")) and ln[12:16].strip() == el)
        ) + "\nTER\nEND\n")
        prot_h = self.workdir / "protein_H.pdb"
        _run(["obabel", str(prot_pdb), "-O", str(prot_h), "-p", "7.4"])  # add polar H
        prot_pdbqt = self.workdir / "protein.pdbqt"
        _run(["obabel", str(prot_h), "-xr", "--partialcharge", "gasteiger",
              "-O", str(prot_pdbqt)])

        # metal atom line(s), AutoDock-typed (Open Babel keeps the metal here since
        # we do not request Gasteiger on this pass).
        full_pdbqt = self.workdir / "full.pdbqt"
        _run(["obabel", str(rec_pdb), "-xr", "-p", "7.4", "-O", str(full_pdbqt)])
        metal_lines = [ln for ln in Path(full_pdbqt).read_text().splitlines()
                       if ln.startswith(("ATOM", "HETATM")) and ln[12:16].strip() == el]
        if not metal_lines:
            raise ValueError(f"metal {el} not found after receptor PDBQT conversion")

        out = self.workdir / "receptor.pdbqt"
        body = [ln for ln in Path(prot_pdbqt).read_text().splitlines()
                if ln.startswith(("ATOM", "HETATM"))]
        body += metal_lines
        out.write_text("\n".join(body) + "\nTER\nEND\n")
        return out

    def _add_tz(self, rec_pdbqt) -> Path:
        out = self.workdir / "receptor_TZ.pdbqt"
        _run(["python", str(self.zinc_pseudo), "-r", str(rec_pdbqt), "-o", str(out)])
        return out

    def _receptor_types(self, rec_tz) -> list[str]:
        types = []
        for ln in Path(rec_tz).read_text().splitlines():
            if ln.startswith(("ATOM", "HETATM")):
                t = ln[77:79].strip()
                if t and t not in types:
                    types.append(t)
        return types

    def _run_autogrid(self, rec_tz, center) -> Path:
        shutil.copy(self.ad4zn_dat, self.workdir / "AD4Zn.dat")
        rtypes = self._receptor_types(rec_tz)
        stem = "receptor_TZ"
        gpf = self.workdir / "grid.gpf"
        lines = [
            "parameter_file AD4Zn.dat",
            f"npts {self.npts[0]} {self.npts[1]} {self.npts[2]}",
            f"gridfld {stem}.maps.fld",
            f"spacing {self.spacing}",
            f"receptor_types {' '.join(rtypes)}",
            f"ligand_types {' '.join(_LIGAND_TYPES)}",
            f"receptor {rec_tz.name}",
            f"gridcenter {center[0]:.3f} {center[1]:.3f} {center[2]:.3f}",
            "smooth 0.5",
        ]
        lines += [f"map {stem}.{t}.map" for t in _LIGAND_TYPES]
        lines += [f"elecmap {stem}.e.map", f"dsolvmap {stem}.d.map",
                  "dielectric -0.1465"]
        gpf.write_text("\n".join(lines) + "\n")
        _run(["autogrid4", "-p", "grid.gpf", "-l", "grid.glg"], cwd=self.workdir)
        return self.workdir / f"{stem}.maps.fld"

    # ---- per-candidate scoring -------------------------------------------
    def score(self, candidate: Candidate) -> AffinityResult:
        from rdkit import Chem, RDLogger
        from rdkit.Chem import AllChem
        RDLogger.DisableLog("rdApp.*")
        cdir = self.workdir / candidate.id
        cdir.mkdir(exist_ok=True)

        m = Chem.MolFromSmiles(candidate.smiles)
        if m is None:
            return AffinityResult(candidate.id, float("nan"), ok=False, note="bad SMILES")
        m = Chem.AddHs(m)
        ps = AllChem.ETKDGv3(); ps.randomSeed = self.seed     # deterministic 3D
        if AllChem.EmbedMolecule(m, ps) != 0:
            return AffinityResult(candidate.id, float("nan"), ok=False, note="embed failed")
        AllChem.MMFFOptimizeMolecule(m)
        sdf = cdir / "lig.sdf"
        Chem.SDWriter(str(sdf)).write(m)

        lig_pdbqt = cdir / "lig.pdbqt"
        try:
            _run(["mk_prepare_ligand.py", "-i", str(sdf), "-o", str(lig_pdbqt)])
        except Exception as e:
            return AffinityResult(candidate.id, float("nan"), ok=False,
                                  note=f"ligand prep failed: {e}")

        # symlink the prepared maps + grid field into the candidate dir, then run
        # AutoDock4 with a FIXED seed (reproducible). The glob already covers the
        # atom-type maps AND e.map/d.map, so dedupe via a set (+ the .fld) and link
        # each source once, idempotently.
        srcs = set(self.workdir.glob("receptor_TZ.*.map"))
        srcs.add(self.workdir / "receptor_TZ.maps.fld")
        for src in srcs:
            link = cdir / src.name
            if not link.exists():
                link.symlink_to(src)

        dpf = cdir / "dock.dpf"
        dpf.write_text(
            f"autodock_parameter_version 4.2\n"
            f"parameter_file {self.workdir/'AD4Zn.dat'}\n"
            f"seed {self.seed} {self.seed}\n"
            f"ligand_types {' '.join(self._lig_types(lig_pdbqt))}\n"
            f"fld receptor_TZ.maps.fld\n"
            + "".join(f"map receptor_TZ.{t}.map\n" for t in self._lig_types(lig_pdbqt))
            + "elecmap receptor_TZ.e.map\n"
            "desolvmap receptor_TZ.d.map\n"
            f"move {lig_pdbqt.name}\n"
            "ls_search_freq 0.06\n"          # AD4.2 keyword (was the invalid "search_freq")
            f"ga_num_evals {self.ga_evals}\n"
            "ga_pop_size 150\n"
            # method must be selected BEFORE ga_run: AutoDock4 executes ga_run on parse.
            "set_ga\nset_sw1\n"
            f"ga_run {self.ga_run}\n"
            "analysis\n"
        )
        try:
            _run(["autodock4", "-p", "dock.dpf", "-l", "dock.dlg"], cwd=cdir)
        except Exception as e:
            return AffinityResult(candidate.id, float("nan"), ok=False,
                                  note=f"docking failed: {e}")

        energy = self._best_energy(cdir / "dock.dlg")
        if energy is None:
            return AffinityResult(candidate.id, float("nan"), ok=False, note="no energy parsed")
        return AffinityResult(candidate.id, score=-energy, raw={"binding_energy": energy})

    @staticmethod
    def _lig_types(lig_pdbqt) -> list[str]:
        types = []
        for ln in Path(lig_pdbqt).read_text().splitlines():
            if ln.startswith(("ATOM", "HETATM")):
                t = ln[77:79].strip()
                if t and t not in types:
                    types.append(t)
        return types

    @staticmethod
    def _best_energy(dlg) -> float | None:
        best = None
        for ln in Path(dlg).read_text().splitlines():
            mo = re.search(r"Estimated Free Energy of Binding\s*=\s*([-\d.]+)", ln)
            if mo:
                v = float(mo.group(1))
                best = v if best is None else min(best, v)
        return best
