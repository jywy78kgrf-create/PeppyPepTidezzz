"""Pareto (multi-objective) selection over the generated MMP-1 candidates.

Objectives, all MAXIMISED:
  1. potency       = predicted MMP-1 pIC50
  2. selectivity   = min_MMP1_selectivity (worst-case log margin vs MMP-2/3/9/13)
  3. drug-likeness = QED
A candidate is Pareto-optimal (non-dominated) if no other candidate is >= on all
three and strictly > on at least one. The front IS the trade-off frontier: there is
no single "best" -- only the set where improving one objective costs another.
Writes the front (CSV), a plot, and PARETO.md.
"""
import numpy as np, pandas as pd
from rdkit import Chem, RDLogger
RDLogger.DisableLog("rdApp.*")

SRC = "results/mmp1_inhibitor_candidates/candidates_profiled.csv"
OUTDIR = "candidates/mmp1_inhibitor"
OBJ = ["pIC50_mmp1", "min_MMP1_selectivity", "druglikeness_qed"]

df = pd.read_csv(SRC)
df["canon"] = df["smiles"].map(lambda s: Chem.MolToSmiles(Chem.MolFromSmiles(s)) if Chem.MolFromSmiles(s) else None)
df = df.dropna(subset=["canon"]).drop_duplicates("canon").reset_index(drop=True)

O = df[OBJ].to_numpy(dtype=float)
def pareto_mask(O):
    n = len(O); nd = np.ones(n, bool)
    for i in range(n):
        d = O - O[i]
        dominated = ((d >= -1e-9).all(axis=1) & (d > 1e-9).any(axis=1))
        if dominated.any():
            nd[i] = False
    return nd
df["pareto"] = pareto_mask(O)
front = df[df["pareto"]].sort_values(["pIC50_mmp1", "min_MMP1_selectivity"], ascending=False).reset_index(drop=True)
front.to_csv(f"{OUTDIR}/pareto_front.csv", index=False)
print(f"pool {len(df)} unique  ->  Pareto front {len(front)}")

cols = ["id", "pIC50_mmp1", "min_MMP1_selectivity", "druglikeness_qed", "n_chelators", "struct_alerts", "applicability_tanimoto"]
print(front[cols].round(3).to_string(index=False))

# --- plot: potency vs selectivity, colour = QED, front ringed ---
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(6.5, 5))
sc = ax.scatter(df.pIC50_mmp1, df.min_MMP1_selectivity, c=df.druglikeness_qed,
                cmap="viridis", s=22, alpha=0.6)
ax.scatter(front.pIC50_mmp1, front.min_MMP1_selectivity, facecolors="none",
           edgecolors="red", s=90, linewidths=1.4, label=f"Pareto front (n={len(front)})")
ax.axhline(0, color="gray", ls="--", lw=0.7)
ax.set_xlabel("predicted MMP-1 pIC50  (potency →)")
ax.set_ylabel("min selectivity vs MMP-2/3/9/13 (log)  (MMP-1-selective ↑)")
ax.set_title("MMP-1 candidates: potency–selectivity–druglikeness trade-off\n"
             "colour = QED (drug-likeness); red = non-dominated")
plt.colorbar(sc, label="QED"); ax.legend(loc="best", fontsize=8); fig.tight_layout()
fig.savefig(f"{OUTDIR}/pareto_front.png", dpi=120)
print(f"\nwrote {OUTDIR}/pareto_front.csv + pareto_front.png")

# --- PARETO.md ---
L = ["# Pareto front — MMP-1 candidates (potency × selectivity × drug-likeness)\n",
     "Non-dominated candidates: each is best-in-class on *some* balance of the three "
     "objectives; none is beaten on all three. There is no single winner — pick the "
     "region of the frontier that matches your project's risk tolerance.\n",
     f"- pool: {len(df)} unique candidates → **{len(front)} Pareto-optimal**\n",
     "| id | pred pIC50 (MMP-1) | min selectivity (log) | QED | #ZBG | alerts | nearest-known Tanimoto |",
     "|" + "---|" * 7]
for r in front.itertuples():
    L.append(f"| {r.id} | {r.pIC50_mmp1:.2f} | {r.min_MMP1_selectivity:+.2f} | "
             f"{r.druglikeness_qed:.2f} | {int(r.n_chelators)} | {int(r.struct_alerts)} | {r.applicability_tanimoto:.2f} |")
L.append("\n## Reading the frontier")
L.append("- **High-potency end**: best pIC50 but typically multi-chelator (high #ZBG, more alerts, lower QED) — the classic MMP liability.")
L.append("- **Drug-like end**: high QED / single ZBG / few alerts but weaker and often not MMP-1-selective.")
L.append("- **Middle**: the candidates worth a chemist's attention — they buy selectivity/cleanliness at modest potency cost.")
L.append("\nAll predictions are QSAR triage, not measurements (see BENCH_HANDOFF.md caveats). "
         "Confirm the chosen front region in vitro (MMP-1 IC50 + MMP-2/3/9/13 panel).")
open(f"{OUTDIR}/PARETO.md", "w").write("\n".join(L))
print("wrote PARETO.md")
