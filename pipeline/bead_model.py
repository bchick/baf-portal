"""Coarse-grained 3D bead models of the BAF complexes for the spinning renderer.

One bead per modelled residue (C-alpha; phosphorus for DNA). cBAF (6LTJ) is
centred and rotated into the 2D cartoon layout's front view. PBAF and ncBAF
are superposed onto it on the nucleosome (Kabsch on histone H3/H4
C-alphas; the two histone copies are paired whichever way fits best), so every
complex shares one frame with the nucleosome as a fixed pedestal: switching
complexes in the browser keeps the nucleosome still while the remodeller
changes. Coordinates in Angstrom, 0.1 A.

Each bead also carries its UniProt residue number (`res`, 0 = unmapped) from
aligning the chain's modelled residues to the UniProt sequence (see
uniprot_numbers; author numbering and SIFTS both proved unreliable). The
browser uses `res` to morph a subunit's beads onto its domain map.

    pixi run beads        # writes site/src/lib/models/{cBAF,PBAF,ncBAF}.json
"""
from __future__ import annotations

import difflib
import json

import numpy as np
import yaml

from . import fetch_uniprot
from .cartoon_layout import ca_coords, chain_map, load_structure
from .common import CURATED, ROOT, fetch, write_json

LAYOUT = ROOT / "site" / "src" / "lib" / "layouts" / "cBAF.json"
OUT = ROOT / "site" / "src" / "lib" / "models"
MODELS = {"cBAF": ("6LTJ", "32001526"), "PBAF": ("7VDV", "35477757"), "ncBAF": ("9WBZ", "41402274")}
REFERENCE = "cBAF"
ANCHORS = ("H3", "H4")   # histone families used for superposition
MIN_RUN = 6             # residues per exact sequence match used for numbering
MIN_COVERAGE = 0.05     # a subunit chain with less aligned is almost certainly misassigned
TIE = 1.5                # A: histone fits this close to the best count as equivalent


def classify(c: dict) -> str:
    if c["kind"] in ("subunit", "histone", "dna"):
        return c["kind"]
    if str(c["symbol"]).endswith("_XENLA"):      # H2A variants etc. not named H*
        return "histone"
    return "unassigned"


def kabsch(P: np.ndarray, Q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """R, t minimising |(P @ R.T + t) - Q|."""
    pc, qc = P.mean(0), Q.mean(0)
    U, _, Vt = np.linalg.svd((P - pc).T @ (Q - qc))
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1, 1, d]) @ U.T
    return R, qc - pc @ R.T


def anchor_atoms(chains: dict, swap: dict[str, bool] | None = None) -> dict[tuple, np.ndarray]:
    """Histone H3/H4 C-alphas keyed by (family, copy, residue). `swap` flips
    the copy order for a family, to try both pairings against the reference."""
    fams: dict[str, list] = {}
    for cid in sorted(chains):
        c = chains[cid]
        if classify(c) == "histone":
            fam = str(c["symbol"])[:2]
            if fam in ANCHORS:
                fams.setdefault(fam, []).append(c)
    out = {}
    for fam, cs in fams.items():
        if swap and swap.get(fam):
            cs = cs[::-1]
        for k, c in enumerate(cs):
            for r, p in zip(c["res"], c["xyz"]):
                out[(fam, k, int(r))] = p
    return out


def uniprot_numbers(pdb: str, chains: dict, seqs: dict[str, str]) -> dict[str, dict]:
    """chain -> {"res": [UniProt residue or 0 per bead], "coverage", "sifts_agreement"}.

    Numbering comes from aligning the chain's observed residues to the UniProt
    sequence and keeping only beads inside exact matching runs of >= MIN_RUN
    residues, so every mapped bead is identical to UniProt by construction.
    SIFTS (label_seq_id segments) is only a diagnostic: in 7VDV/9WBZ it is
    misregistered for parts of SMARCA4, ARID2 and PBRM1.
    """
    sifts = fetch(f"https://www.ebi.ac.uk/pdbe/api/mappings/uniprot/{pdb.lower()}", cache_dir="pdbe")
    segs: dict[tuple[str, str], list] = {}
    for acc, v in sifts[pdb.lower()]["UniProt"].items():
        for m in v["mappings"]:
            segs.setdefault((m["chain_id"], acc), []).append(
                (m["start"]["residue_number"], m["end"]["residue_number"], m["unp_start"]))
    out = {}
    for cid, c in chains.items():
        seq = seqs.get(c["uniprot"]) if classify(c) == "subunit" else None
        res = [0] * len(c["aa"])
        if seq:
            obs = "".join(c["aa"])
            sm = difflib.SequenceMatcher(None, obs, seq, autojunk=False)
            for a, b, n in sm.get_matching_blocks():
                if n >= MIN_RUN:
                    for k in range(n):
                        res[a + k] = b + k + 1
            seg = segs.get((cid, c["uniprot"]), [])
            sifts_res = [next((us + (int(lab) - ls) for ls, le, us in seg if ls <= lab <= le), 0)
                         for lab in c["label_seq"]]
            both = [(r, s_) for r, s_ in zip(res, sifts_res) if r and s_]
            cov = sum(1 for r in res if r) / len(res)
            if cov < MIN_COVERAGE:
                raise AssertionError(f"{pdb} chain {cid} ({c['symbol']}): only {cov:.0%} of beads align to "
                                     f"UniProt {c['uniprot']}")
            out[cid] = {"res": res, "coverage": cov,
                        "sifts_agreement": sum(r == s_ for r, s_ in both) / len(both) if both else None}
        else:
            out[cid] = {"res": res, "coverage": None, "sifts_agreement": None}
    return out


def export(name: str, pdb: str, pmid: str, chains: dict, ghosts: list, rmsd: float | None,
           numbering: dict[str, dict]) -> None:
    out_chains, beads, res = [], [], []
    for i, (cid, c) in enumerate(sorted(chains.items())):
        cov = numbering[cid]["coverage"]
        out_chains.append({"chain": cid, "symbol": c["symbol"], "kind": classify(c), "uniprot": c["uniprot"],
                           "n": len(c["xyz"]), "centroid": np.round(c["xyz"].mean(0), 1).tolist(),
                           "uniprot_coverage": None if cov is None else round(cov, 3)})
        res.extend(numbering[cid]["res"])
        for p in c["xyz"]:
            beads.extend([round(float(p[0]), 1), round(float(p[1]), 1), round(float(p[2]), 1), i])
    allxyz = np.array(beads).reshape(-1, 4)[:, :3]
    write_json(OUT / f"{name}.json", {
        "complex": name, "pdb": pdb, "pmid": pmid,
        "superposed_on": None if rmsd is None else {"pdb": MODELS[REFERENCE][0], "on": "histone H3/H4 C-alpha",
                                                    "rmsd": round(rmsd, 2)},
        "radius": float(np.round(np.linalg.norm(allxyz, axis=1).max(), 1)),
        "chains": out_chains,
        "ghosts": ghosts,
        "beads": beads,   # flat [x, y, z, chainIndex, ...]
        "res": res,       # UniProt residue number per bead (0 = unmapped)
    })
    for cid in sorted(numbering):
        n = numbering[cid]
        if n["coverage"] is not None and (n["coverage"] < 0.9 or (n["sifts_agreement"] or 1) < 0.99):
            sa = "n/a" if n["sifts_agreement"] is None else f"{n['sifts_agreement']:.0%}"
            print(f"  {pdb} {cid} {chains[cid]['symbol']}: {n['coverage']:.0%} of beads aligned; SIFTS agrees on {sa}")
    print(f"{name} {pdb}: {len(out_chains)} chains, {len(beads) // 4} beads, "
          f"{sum(1 for r in res if r)} mapped to UniProt"
          + ("" if rmsd is None else f", superposed RMSD {rmsd:.2f} A"))


def main() -> None:
    comp = yaml.safe_load(open(CURATED / "composition.yaml"))
    layout = json.load(open(LAYOUT))

    loaded = {n: ca_coords(load_structure(pdb), chain_map(pdb, comp)) for n, (pdb, _) in MODELS.items()}
    accs = {c["uniprot"] for ch in loaded.values() for c in ch.values() if classify(c) == "subunit"}
    seqs = {a: fetch_uniprot.fetch_entry(a)["sequence"] for a in sorted(accs)}
    numbering = {n: uniprot_numbers(MODELS[n][0], ch, seqs) for n, ch in loaded.items()}

    ref = loaded[REFERENCE]
    center = np.vstack([c["xyz"] for c in ref.values()]).mean(0)
    Rv = np.array(layout["view"]["rotation"])
    for c in ref.values():
        c["xyz"] = (c["xyz"] - center) @ Rv.T
    ref_anchor = anchor_atoms(ref)

    for name, (pdb, pmid) in MODELS.items():
        chains, rmsd = loaded[name], None
        if name != REFERENCE:
            # The nucleosome is pseudo-two-fold symmetric about its dyad, so the
            # histone copy pairings fit about equally well but put the remodeller
            # on opposite faces. Among fits within TIE of the best RMSD, keep the
            # one that places SMARCA4 closest to its cBAF position (same pose).
            ref_atp = np.vstack([c["xyz"] for c in ref.values() if c["symbol"] == "SMARCA4"]).mean(0)
            atp = np.vstack([c["xyz"] for c in chains.values() if c["symbol"] == "SMARCA4"]).mean(0)
            fits = []
            for swap in ({"H3": a, "H4": b} for a in (False, True) for b in (False, True)):
                mob = anchor_atoms(chains, swap)
                keys = sorted(set(mob) & set(ref_anchor))
                P = np.array([mob[k] for k in keys]); Q = np.array([ref_anchor[k] for k in keys])
                R, t = kabsch(P, Q)
                e = float(np.sqrt((((P @ R.T + t) - Q) ** 2).sum(1).mean()))
                d = float(np.linalg.norm(atp @ R.T + t - ref_atp))
                fits.append((e, d, R, t, len(keys), swap))
            best_e = min(f[0] for f in fits)
            rmsd, d, R, t, n_anchor, swap = min((f for f in fits if f[0] <= best_e + TIE), key=lambda f: f[1])
            print(f"  {name}: {n_anchor} histone C-alphas; fits (rmsd, SMARCA4 offset) "
                  + ", ".join(f"({f[0]:.2f}, {f[1]:.0f})" for f in fits) + f"; chose {swap}")
            for c in chains.values():
                c["xyz"] = c["xyz"] @ R.T + t
        # Complex members with no chain in the model become 3D ghosts anchored
        # between the subunits they bind (cBAF anchors curated in cartoon_layout).
        present = {c["symbol"] for c in chains.values()}
        cx = comp["complexes"][name]
        ghosts = []
        for sl in cx["slots"]:
            if not present & set(sl["members"]):
                g = next((g for g in layout["ghosts"] if g["slot"] == sl["slot"]), None) if name == REFERENCE else None
                ghosts.append({"slot": sl["slot"], "members": sl["members"], "reason": f"not modelled in {pdb}",
                               "anchor_subunits": g["anchor_subunits"] if g else []})
        export(name, pdb, pmid, chains, ghosts, rmsd, numbering[name])


if __name__ == "__main__":
    main()
