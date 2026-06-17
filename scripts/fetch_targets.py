"""Generic ChEMBL IC50 puller (same curation as fetch_calibration / fetch_mmp_panel).
Pulls a panel for new target families so the platform can be aimed at them.
"""
import json, csv, time, statistics, datetime, urllib.request
from collections import defaultdict
from pathlib import Path

TARGETS = {
    # HDAC6-selectivity story: HDAC6 (target) vs class I (HDAC1/2/3)
    "hdac1": "CHEMBL325", "hdac2": "CHEMBL1937", "hdac3": "CHEMBL1829", "hdac6": "CHEMBL1865",
    # OA aggrecanase story: ADAMTS-5 (target) vs ADAMTS-4
    "adamts5": "CHEMBL2285", "adamts4": "CHEMBL2318",
}
BASE = "https://www.ebi.ac.uk/chembl/api/data/activity"
PAGE = 1000
OUT = Path("data/calibration"); OUT.mkdir(parents=True, exist_ok=True)


def fetch(cid):
    rows, offset = [], 0
    while True:
        url = f"{BASE}?target_chembl_id={cid}&standard_type=IC50&format=json&limit={PAGE}&offset={offset}"
        with urllib.request.urlopen(url, timeout=120) as r:
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
    per, smi, kept = defaultdict(list), {}, 0
    for a in rows:
        if a.get("standard_units") != "nM" or a.get("standard_relation") != "=":
            continue
        if a.get("pchembl_value") in (None, ""):
            continue
        s = a.get("canonical_smiles")
        if not s:
            continue
        mid = a["molecule_chembl_id"]; per[mid].append(float(a["pchembl_value"])); smi[mid] = s; kept += 1
    return [(mid, smi[mid], round(statistics.median(v), 2), len(v)) for mid, v in per.items()], kept


def main():
    for name, cid in TARGETS.items():
        print(f"{name} ({cid}) ...", flush=True)
        rows, total = fetch(cid); out, kept = curate(rows)
        with (OUT / f"{name}_ic50.csv").open("w", newline="") as fh:
            w = csv.writer(fh); w.writerow(["molecule_chembl_id", "canonical_smiles", "pIC50_median", "n_measurements"])
            w.writerows(sorted(out, key=lambda r: -r[2]))
        json.dump({"generated_utc": datetime.datetime.utcnow().isoformat() + "Z", "source": "ChEMBL REST API",
                   "target_chembl_id": cid, "name": name, "raw_ic50_records": total,
                   "records_passing_filters": kept, "unique_molecules": len(out)},
                  open(OUT / f"{name}_ic50.provenance.json", "w"), indent=2)
        print(f"  {name}: {total} raw -> {len(out)} unique molecules", flush=True)


if __name__ == "__main__":
    main()
