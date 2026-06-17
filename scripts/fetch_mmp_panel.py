"""Pull the MMP inhibitor panel from ChEMBL (drug-discovery scope).

Same curation as scripts/fetch_calibration.py (MMP-1), generalised to the related
MMPs so the model can cover more chemical space and support SELECTIVITY work
(MMP-1 inhibitor potency vs MMP-2/3/9/13 — the property whose neglect sank the
first generation of MMP-inhibitor drugs). Pure deterministic curation, no modeling.

Filters: standard_type=IC50, units=nM, relation '=', pchembl_value present,
canonical_smiles present. Dedup: median pIC50 (= pchembl) per molecule.
"""
import json, csv, time, statistics, datetime, urllib.request
from collections import defaultdict
from pathlib import Path

TARGETS = {"mmp2": "CHEMBL333", "mmp3": "CHEMBL283", "mmp9": "CHEMBL321", "mmp13": "CHEMBL280"}
BASE = "https://www.ebi.ac.uk/chembl/api/data/activity"
PAGE = 1000
OUT = Path("data/calibration"); OUT.mkdir(parents=True, exist_ok=True)


def fetch(cid):
    rows, offset = [], 0
    while True:
        url = (f"{BASE}?target_chembl_id={cid}&standard_type=IC50"
               f"&format=json&limit={PAGE}&offset={offset}")
        with urllib.request.urlopen(url, timeout=90) as r:
            d = json.load(r)
        acts = d.get("activities", [])
        rows.extend(acts)
        total = d["page_meta"]["total_count"]
        offset += PAGE
        print(f"    {len(rows)}/{total}", flush=True)
        if offset >= total or not acts:
            break
        time.sleep(0.3)
    return rows, total


def curate(rows):
    per, smi = defaultdict(list), {}
    kept = 0
    for a in rows:
        if a.get("standard_units") != "nM" or a.get("standard_relation") != "=":
            continue
        if a.get("pchembl_value") in (None, ""):
            continue
        s = a.get("canonical_smiles")
        if not s:
            continue
        mid = a["molecule_chembl_id"]
        per[mid].append(float(a["pchembl_value"])); smi[mid] = s; kept += 1
    out = [(mid, smi[mid], round(statistics.median(v), 2), len(v)) for mid, v in per.items()]
    return out, kept


def main():
    for name, cid in TARGETS.items():
        print(f"{name} ({cid}) ...", flush=True)
        rows, total = fetch(cid)
        out, kept = curate(rows)
        path = OUT / f"{name}_ic50.csv"
        with path.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["molecule_chembl_id", "canonical_smiles", "pIC50_median", "n_measurements"])
            w.writerows(sorted(out, key=lambda r: -r[2]))
        json.dump({
            "generated_utc": datetime.datetime.utcnow().isoformat() + "Z",
            "source": "ChEMBL REST API", "target_chembl_id": cid, "mmp": name,
            "raw_ic50_records": total, "records_passing_filters": kept,
            "unique_molecules": len(out),
            "filters": ["standard_type=IC50", "standard_units=nM", "standard_relation==",
                        "pchembl_value present", "canonical_smiles present"],
            "dedup": "median pIC50 per molecule",
        }, open(OUT / f"{name}_ic50.provenance.json", "w"), indent=2)
        print(f"  {name}: {total} raw IC50 -> {len(out)} unique molecules -> {path}")


if __name__ == "__main__":
    main()
