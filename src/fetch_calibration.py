"""Stage 1: curate the MMP-1 IC50 calibration benchmark from ChEMBL.

This is REFERENCE TRUTH for the Stage-4 calibration hard gate: the fitness
function will later be correlated against these measured affinities. No LLM,
no modeling here -- pure deterministic data curation (constraint #1).

Source : ChEMBL REST API, target CHEMBL332 (Interstitial collagenase / human MMP-1)
Filters (quality control, all explicit + logged):
  - standard_type == IC50
  - standard_units == nM, standard_relation == '=' (drop censored >/<)
  - pchembl_value present (ChEMBL's -log10(IC50[M]))
  - canonical_smiles present
Dedup  : one row per molecule = median pIC50 across its measurements.
Output : data/calibration/mmp1_ic50.csv  (+ provenance .json)
"""
import json, csv, sys, time, urllib.request, datetime, statistics
from collections import defaultdict

TARGET = "CHEMBL332"
BASE = "https://www.ebi.ac.uk/chembl/api/data/activity"
PAGE = 1000


def fetch_all():
    rows, offset = [], 0
    while True:
        url = (f"{BASE}?target_chembl_id={TARGET}&standard_type=IC50"
               f"&format=json&limit={PAGE}&offset={offset}")
        with urllib.request.urlopen(url, timeout=60) as r:
            d = json.load(r)
        acts = d.get("activities", [])
        rows.extend(acts)
        total = d["page_meta"]["total_count"]
        offset += PAGE
        print(f"  fetched {len(rows)}/{total}", flush=True)
        if offset >= total or not acts:
            break
        time.sleep(0.3)
    return rows


def curate(acts):
    by_mol = defaultdict(list)
    smiles = {}
    kept = 0
    for a in acts:
        if a.get("standard_units") != "nM":      continue
        if a.get("standard_relation") != "=":     continue
        p = a.get("pchembl_value")
        smi = a.get("canonical_smiles")
        mol = a.get("molecule_chembl_id")
        if not (p and smi and mol):               continue
        by_mol[mol].append(float(p))
        smiles[mol] = smi
        kept += 1
    out = []
    for mol, ps in by_mol.items():
        out.append((mol, smiles[mol], round(statistics.median(ps), 3), len(ps)))
    out.sort(key=lambda r: -r[2])  # strongest binders first (deterministic order)
    return out, kept


def main():
    print(f"Fetching IC50 activities for {TARGET} (human MMP-1)...")
    acts = fetch_all()
    rows, kept = curate(acts)
    import os
    os.makedirs("data/calibration", exist_ok=True)
    with open("data/calibration/mmp1_ic50.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["molecule_chembl_id", "canonical_smiles", "pIC50_median", "n_measurements"])
        w.writerows(rows)
    prov = {
        "generated_utc": datetime.datetime.utcnow().isoformat() + "Z",
        "source": "ChEMBL REST API",
        "target_chembl_id": TARGET,
        "target_name": "Interstitial collagenase (human MMP-1)",
        "raw_ic50_records": len(acts),
        "records_passing_filters": kept,
        "unique_molecules": len(rows),
        "filters": ["standard_type=IC50", "standard_units=nM",
                    "standard_relation==", "pchembl_value present",
                    "canonical_smiles present"],
        "dedup": "median pIC50 per molecule",
    }
    with open("data/calibration/mmp1_ic50.provenance.json", "w") as fh:
        json.dump(prov, fh, indent=2)
    print(json.dumps(prov, indent=2))
    print(f"\nWrote data/calibration/mmp1_ic50.csv with {len(rows)} unique molecules.")


if __name__ == "__main__":
    main()
