"""2D cartoon template from the cBAF cryo-EM structure (PDB 6LTJ, He et al. 2020).

* chains -> subunits via PDBe SIFTS (UniProt accession -> HGNC symbol from
  data/curated/composition.yaml); histone and DNA chains form the nucleosome
* viewing direction: sample orientations on a sphere and keep the one with the
  least overlap between subunit footprints, then rotate in-plane so the
  nucleosome sits at the bottom
* per subunit (chains of the same subunit, e.g. the SMARCC2 dimer, are kept as
  separate shapes): projected C-alpha centroid, a 2D hull (concave-ish: union of
  convex hulls of sequence-contiguous segments, simplified), and depth
  (mean z toward the viewer) for back-to-front drawing
* cBAF members with no chain in the model (SS18, BCL7) are listed as ghosts

    pixi run layout        # writes site/src/lib/layouts/cBAF.json
"""
from __future__ import annotations

import gzip
import json

import gemmi
import numpy as np
import yaml
from scipy.spatial import ConvexHull

from .common import CACHE, CURATED, ROOT, fetch, write_json

PDB = "6LTJ"
OUT = ROOT / "site" / "src" / "lib" / "layouts" / "cBAF.json"
SEGMENT = 60          # residues per hull segment
SCALE = 1.0           # Å -> SVG units before normalisation
CANVAS = 1000


def load_structure(pdb: str) -> gemmi.Structure:
    path = CACHE / "pdb" / f"{pdb.lower()}.cif.gz"
    if not path.exists():
        import requests
        path.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(f"https://files.rcsb.org/download/{pdb}.cif.gz", timeout=300)
        r.raise_for_status()
        path.write_bytes(r.content)
    st = gemmi.read_structure(str(path))
    st.setup_entities()
    return st


def chain_map(pdb: str, comp: dict) -> dict[str, dict]:
    sifts = fetch(f"https://www.ebi.ac.uk/pdbe/api/mappings/uniprot/{pdb.lower()}", cache_dir="pdbe")
    acc2sym = {s["uniprot"]: s["symbol"] for s in comp["subunits"]}
    out = {}
    for acc, v in sifts[pdb.lower()]["UniProt"].items():
        for m in v["mappings"]:
            sym = acc2sym.get(acc)
            kind = "subunit" if sym else ("histone" if v["identifier"].startswith("H") else "other")
            out[m["chain_id"]] = {"uniprot": acc, "symbol": sym or v["identifier"], "kind": kind,
                                  "entity": m["entity_id"]}
    return out


def ca_coords(st: gemmi.Structure, cmap: dict) -> dict[str, dict]:
    """One bead (C-alpha, or P / C4' for DNA) per residue, plus the residue's
    heavy atoms for the atom-level renderer: `atoms` (xyz), `elem` (0 carbon,
    1 other, 2 sulfur) and `atom_bead` (index of the atom's residue bead)."""
    model = st[0]
    chains = {}
    for ch in model:
        pts, resnums, labels, aas = [], [], [], []
        atoms, elem, atom_bead = [], [], []
        is_dna = False
        for res in ch:
            info = gemmi.find_tabulated_residue(res.name)
            if info and info.is_nucleic_acid():
                is_dna = True
                a = res.find_atom("P", "*") or res.find_atom("C4'", "*")
            else:
                a = res.find_atom("CA", "*")
            if a:
                for at in res:
                    if at.element.is_hydrogen or (at.altloc not in ("\0", "A")):
                        continue
                    atoms.append([at.pos.x, at.pos.y, at.pos.z])
                    elem.append(0 if at.element.name == "C" else 2 if at.element.name == "S" else 1)
                    atom_bead.append(len(pts))
                pts.append([a.pos.x, a.pos.y, a.pos.z])
                resnums.append(res.seqid.num)
                labels.append(res.label_seq if res.label_seq is not None else -1)
                aas.append((info.one_letter_code.upper() if info and info.is_amino_acid() else "X"))
        if not pts:
            continue
        meta = cmap.get(ch.name) or {"symbol": "DNA" if is_dna else ch.name,
                                     "kind": "dna" if is_dna else "other", "uniprot": None}
        chains[ch.name] = {**meta, "xyz": np.array(pts), "res": np.array(resnums),
                           "label_seq": np.array(labels), "aa": aas,
                           "atoms": np.array(atoms).reshape(-1, 3), "elem": np.array(elem, dtype=np.uint8),
                           "atom_bead": np.array(atom_bead, dtype=np.int32)}
    return chains


def rotation_to(v: np.ndarray) -> np.ndarray:
    """Rotation matrix whose third row is the unit view vector v."""
    z = v / np.linalg.norm(v)
    tmp = np.array([1.0, 0, 0]) if abs(z[0]) < 0.9 else np.array([0, 1.0, 0])
    x = np.cross(tmp, z); x /= np.linalg.norm(x)
    y = np.cross(z, x)
    return np.vstack([x, y, z])


def fibonacci_sphere(n: int) -> np.ndarray:
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * i / n)
    th = np.pi * (1 + 5 ** 0.5) * i
    return np.stack([np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)], 1)


def overlap_score(groups: list[np.ndarray], R: np.ndarray, grid=6.0) -> float:
    """Fraction of occupied pixels covered by more than one subunit."""
    counts = {}
    for gi, xyz in enumerate(groups):
        p = xyz @ R[:2].T
        cells = set(map(tuple, np.floor(p / grid).astype(int)))
        for c in cells:
            counts[c] = counts.get(c, 0) + 1
    occ = len(counts)
    multi = sum(1 for v in counts.values() if v > 1)
    return multi / max(occ, 1)


def segment_hull(p2: np.ndarray, resnums: np.ndarray) -> list[list[float]]:
    """Outline for one chain: convex hull of the union of per-segment hulls'
    vertices, shrunk toward per-segment points (a cheap concave hull)."""
    order = np.argsort(resnums)
    p2 = p2[order]
    segs = [p2[i:i + SEGMENT] for i in range(0, len(p2), SEGMENT)]
    pts = []
    for s in segs:
        if len(s) >= 3:
            try:
                h = ConvexHull(s)
                pts.extend(s[h.vertices])
                continue
            except Exception:
                pass
        pts.extend(s)
    pts = np.array(pts)
    if len(pts) < 3:
        return pts.tolist()
    return concave_outline(pts)


def concave_outline(pts: np.ndarray, k_angle=48) -> list[list[float]]:
    """Radial concave outline: for each angular bin around the centroid keep the
    farthest point; then drop spikes. Good enough as a tracing template."""
    c = pts.mean(0)
    d = pts - c
    ang = np.arctan2(d[:, 1], d[:, 0])
    r = np.hypot(d[:, 0], d[:, 1])
    bins = np.floor((ang + np.pi) / (2 * np.pi) * k_angle).astype(int) % k_angle
    out = []
    for b in range(k_angle):
        m = bins == b
        if m.any():
            i = np.argmax(np.where(m, r, -1))
            out.append((ang[i], pts[i]))
    out.sort(key=lambda t: t[0])
    ring = np.array([p for _, p in out])
    # smooth radii to avoid needle spikes from lone residues
    rr = np.hypot(*(ring - c).T)
    sm = np.convolve(np.r_[rr[-2:], rr, rr[:2]], np.ones(5) / 5, mode="valid")
    lim = np.minimum(rr, sm * 1.25)
    ring = c + (ring - c) * (lim / np.maximum(rr, 1e-6))[:, None]
    return ring.tolist()


def main() -> None:
    comp = yaml.safe_load(open(CURATED / "composition.yaml"))
    st = load_structure(PDB)
    cmap = chain_map(PDB, comp)
    chains = ca_coords(st, cmap)
    allxyz = np.vstack([c["xyz"] for c in chains.values()])
    center = allxyz.mean(0)
    for c in chains.values():
        c["xyz"] = c["xyz"] - center

    # group by subunit for the overlap score (nucleosome as one group)
    groups = {}
    for cid, c in chains.items():
        g = "nucleosome" if c["kind"] in ("histone", "dna") else c["symbol"]
        groups.setdefault(g, []).append(c["xyz"])
    garr = [np.vstack(v) for v in groups.values()]
    best = None
    for v in fibonacci_sphere(600):
        R = rotation_to(v)
        s = overlap_score(garr, R)
        if best is None or s < best[0]:
            best = (s, R, v)
    score, R, view = best
    # in-plane rotation: nucleosome centroid straight down (+y in SVG)
    nuc = np.vstack(groups["nucleosome"]) @ R.T
    rest = np.vstack([np.vstack(v) for k, v in groups.items() if k != "nucleosome"]) @ R.T
    d = nuc[:, :2].mean(0) - rest[:, :2].mean(0)
    theta = np.arctan2(d[0], d[1])  # rotate so d points along +y
    cz, sz = np.cos(theta), np.sin(theta)
    Rin = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    R = Rin @ R

    proj = {cid: c["xyz"] @ R.T for cid, c in chains.items()}
    allp = np.vstack(list(proj.values()))
    lo, hi = allp[:, :2].min(0), allp[:, :2].max(0)
    pad = 0.08 * (hi - lo).max()
    span = (hi - lo).max() + 2 * pad
    s = CANVAS / span

    def to_svg(p2):
        q = (p2 - lo + pad) * s
        return q

    width = float((hi[0] - lo[0] + 2 * pad) * s)
    height = float((hi[1] - lo[1] + 2 * pad) * s)
    shapes = []
    zmin, zmax = allp[:, 2].min(), allp[:, 2].max()
    for cid, c in chains.items():
        p = proj[cid]
        p2 = to_svg(p[:, :2])
        shapes.append({
            "chain": cid, "symbol": c["symbol"], "kind": c["kind"], "uniprot": c.get("uniprot"),
            "n_residues": int(len(p)), "residue_range": [int(c["res"].min()), int(c["res"].max())],
            "centroid": [round(float(x), 1) for x in p2.mean(0)],
            "depth": round(float((p[:, 2].mean() - zmin) / (zmax - zmin)), 3),
            "hull": [[round(x, 1), round(y, 1)] for x, y in segment_hull(p2, c["res"])],
        })
    # merge nucleosome parts into one context object (histone octamer + DNA)
    nuc_shapes = [x for x in shapes if x["kind"] in ("histone", "dna")]
    sub_shapes = [x for x in shapes if x["kind"] == "subunit"]
    nuc_pts = np.vstack([to_svg(proj[x["chain"]][:, :2]) for x in nuc_shapes if x["kind"] == "histone"])
    dna_pts = np.vstack([to_svg(proj[x["chain"]][:, :2]) for x in nuc_shapes if x["kind"] == "dna"])
    dna_chains = [x for x in nuc_shapes if x["kind"] == "dna"]

    members = sorted({m for sl in comp["complexes"]["cBAF"]["slots"] for m in sl["members"]})
    modelled = sorted({x["symbol"] for x in sub_shapes})
    slot_of = {m: sl["slot"] for sl in comp["complexes"]["cBAF"]["slots"] for m in sl["members"]}
    modelled_slots = {slot_of[m] for m in modelled if m in slot_of}
    ghosts = []
    for sl in comp["complexes"]["cBAF"]["slots"]:
        if sl["slot"] not in modelled_slots:
            ghosts.append({"slot": sl["slot"], "members": sl["members"],
                           "reason": f"not modelled in {PDB}"})
    # ghost anchors: SS18 binds the SMARCA4 N-terminal region / ARP module side;
    # BCL7 binds the ATPase module near ACTL6A/ACTB. Placed next to those shapes.
    def cen(sym):
        pts = [x["centroid"] for x in sub_shapes if x["symbol"] == sym]
        return np.mean(pts, 0) if pts else np.array([width / 2, height / 2])
    anchors = {"SS18": ("ACTL6A", "SMARCA4"), "BCL7": ("ACTB", "ACTL6A")}
    for g in ghosts:
        a, b = anchors.get(g["slot"], ("SMARCA4", "SMARCA4"))
        ca, cb = cen(a), cen(b)
        g["anchor_subunits"] = [a, b]
        g["anchor"] = [round(float(x), 1) for x in (ca + (ca - cb) * 0.35)]
    layout = {
        "complex": "cBAF", "pdb": PDB, "pmid": "32001526",
        "view": {"direction": [round(float(x), 4) for x in view], "overlap_fraction": round(float(score), 3),
                 "rotation": np.round(R, 5).tolist()},
        "width": round(width, 1), "height": round(height, 1),
        "subunits": sorted(sub_shapes, key=lambda x: x["depth"]),
        "nucleosome": {
            "histone_chains": [x["chain"] for x in nuc_shapes if x["kind"] == "histone"],
            "dna_chains": [x["chain"] for x in dna_chains],
            "hull": [[round(x, 1), round(y, 1)] for x, y in concave_outline(nuc_pts, 64)],
            "dna_path": [[[round(float(x), 1), round(float(y), 1)] for x, y in to_svg(proj[c["chain"]][:, :2])[::2]]
                         for c in dna_chains],
            "centroid": [round(float(x), 1) for x in nuc_pts.mean(0)],
            "depth": round(float(np.mean([x["depth"] for x in nuc_shapes])), 3),
        },
        "members": members, "modelled": modelled,
        "not_modelled": sorted({m for g in ghosts for m in g["members"]}),
        "paralogs_sharing_shape": {m: slot_of[m] for m in sorted(set(members) - set(modelled))
                                   if slot_of[m] in modelled_slots},
        "ghosts": ghosts,
        "note": ("Paralogs share one shape: the model contains SMARCA4, ARID1A, SMARCC2 (x2), SMARCD1, "
                 "DPF2, ACTL6A; their paralogs occupy the same slot."),
    }
    write_json(OUT, layout, compact=False)
    print(f"view {view.round(3)} overlap {score:.3f}; modelled {modelled}; ghosts {[g['slot'] for g in ghosts]}")


if __name__ == "__main__":
    main()
