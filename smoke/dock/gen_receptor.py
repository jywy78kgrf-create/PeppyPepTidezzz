"""Emit a minimal tetrahedral zinc site in STRICT PDBQT columns so AutoGrid4
parses the atom type at columns 78-79 correctly. Zn at origin, 3 coordinating
N atoms on tetrahedral directions (~2.1 A); 4th direction left open for the
TZ pseudo-atom that zinc_pseudo.py will add. Non-H-bonding 'N' avoids AutoGrid's
hydrogen/closestH requirement. Deterministic: fixed coords (constraint #1)."""

R = 2.100
k = R / (3 ** 0.5)

# name, resName, chain, resSeq, x, y, z, charge, ad4_type
ATOMS = [
    ("ZN", "ZN",  "A", 1,  0.0,  0.0,  0.0,  2.000, "Zn"),
    ("N1", "HIS", "A", 2,  k,    k,    k,   -0.300, "N"),
    ("N2", "HIS", "A", 3,  k,   -k,   -k,   -0.300, "N"),
    ("N3", "HIS", "A", 4, -k,    k,   -k,   -0.300, "N"),
    # One polar hydrogen bonded to N1 (~1.0 A, pointing away from Zn).
    # AutoGrid's H-bond preprocessing needs >=1 HD to assign "closest H";
    # real receptors get these from prepare_receptor. Non-directional C
    # map is unaffected by it.
    ("H1", "HIS", "A", 2,  k + 0.577, k + 0.577, k + 0.577, 0.200, "HD"),
]


def put(buf, s, start):  # start is 1-indexed column
    for i, ch in enumerate(str(s)):
        buf[start - 1 + i] = ch


def pdbqt_line(serial, name, res, chain, resseq, x, y, z, charge, atype):
    b = [" "] * 80
    put(b, "ATOM", 1)
    put(b, f"{serial:>5}", 7)
    put(b, f"{name:<4}", 13)
    put(b, f"{res:>3}", 18)
    put(b, chain, 22)
    put(b, f"{resseq:>4}", 23)
    put(b, f"{x:8.3f}", 31)
    put(b, f"{y:8.3f}", 39)
    put(b, f"{z:8.3f}", 47)
    put(b, f"{1.00:6.2f}", 55)
    put(b, f"{0.00:6.2f}", 61)
    put(b, f"{charge:6.3f}", 71)
    put(b, f"{atype:<2}", 78)
    return "".join(b).rstrip()


lines = ["REMARK minimal tetrahedral zinc site for AD4Zn smoke test (strict columns)"]
for i, (name, res, ch, rs, x, y, z, q, t) in enumerate(ATOMS, 1):
    lines.append(pdbqt_line(i, name, res, ch, rs, x, y, z, q, t))
lines.append("TER")
with open("receptor.pdbqt", "w") as fh:
    fh.write("\n".join(lines) + "\n")
print("wrote receptor.pdbqt: Zn +", len(ATOMS) - 1, "coordinating N atoms (strict PDBQT)")
