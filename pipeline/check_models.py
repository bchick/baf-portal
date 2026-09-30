"""Check the 3D models the site ships against their source structures and the
curated composition (independently of how pipeline/bead_model.py built them).

    pixi run python -m pipeline.check_models   # writes reports/model_check.json

Per complex:
  identity     every chain's UniProt accession matches the RCSB entity for that
               author chain; RCSB "unknown" entities are drawn as unassigned
  composition  every subunit chain is a curated member of the complex and none
               is listed absent; every slot is resolved, placed or a ghost, and
               the ghosts shipped to the site match the current composition
  geometry     residue and heavy-atom counts per chain equal a fresh read of the
               mmCIF, and one rigid transform maps the source onto the shipped
               beads and atoms (RMSD at the 0.1 A storage rounding)
  numbering    every UniProt-numbered bead's residue is the UniProt amino acid
  placed       borrowed chains are a rigid copy of their source chain, with
               provenance and a bounded clash count
"""
from __future__ import annotations

import json

import gemmi
import numpy as np
import yaml

from . import fetch_uniprot
from .bead_model import MODELS, OUT, kabsch
from .cartoon_layout import load_structure
from .common import CURATED, ROOT, fetch, write_json

REPORT = ROOT / "reports" / "model_check.json"
MAX_RMSD = 0.1          # A: storage rounds beads and atoms to 0.1 A
MAX_CLASH = 10


def read_atoms(name: str):
    buf = (OUT / f"{name}.atoms.bin").read_bytes()
    n = int(np.frombuffer(buf[:4], "<u4")[0])
    xyz = np.frombuffer(buf[4:4 + 6 * n], "<i2").reshape(-1, 3) / 10
    return xyz, np.frombuffer(buf[4 + 6 * n:4 + 7 * n], np.uint8)


def source_chains(pdb: str) -> dict[str, dict]:
    """Fresh read: per author chain, bead atoms (CA, or P/C4' for nucleic acids),
    their residue one-letter codes, and heavy atoms (first altloc)."""
    st = load_structure(pdb)
    out = {}
    for ch in st[0]:
        beads, aa, heavy = [], [], []
        for res in ch:
            info = gemmi.find_tabulated_residue(res.name)
            nuc = bool(info and info.is_nucleic_acid())
            a = (res.find_atom("P", "*") or res.find_atom("C4'", "*")) if nuc else res.find_atom("CA", "*")
            if not a:
                continue
            beads.append(a.pos.tolist())
            aa.append(info.one_letter_code.upper() if info and info.is_amino_acid() else "X")
            heavy += [at.pos.tolist() for at in res if not at.element.is_hydrogen and at.altloc in ("\0", "A")]
        if beads:
            out[ch.name] = {"beads": np.array(beads), "aa": aa, "atoms": np.array(heavy)}
    return out


def rcsb_chain_accessions(pdb: str) -> dict[str, str | None]:
    entry = fetch(f"https://data.rcsb.org/rest/v1/core/entry/{pdb}", cache_dir="verify")
    out = {}
    for eid in entry["rcsb_entry_container_identifiers"]["polymer_entity_ids"]:
        e = fetch(f"https://data.rcsb.org/rest/v1/core/polymer_entity/{pdb}/{eid}", cache_dir="verify")
        ids = e["rcsb_polymer_entity_container_identifiers"]
        accs = [r["database_accession"] for r in ids.get("reference_sequence_identifiers") or []
                if r.get("database_name") == "UniProt"]
        for cid in ids.get("auth_asym_ids") or []:
            out[cid] = accs[0] if accs else None
    return out


def check(name: str, comp: dict, seqs: dict) -> dict:
    pdb = MODELS[name][0]
    m = json.loads((OUT / f"{name}.json").read_text())
    index = json.loads((OUT / "index.json").read_text())[name]
    beads = np.array(m["beads"]).reshape(-1, 4)
    res = np.array(m["res"])
    axyz, achain = read_atoms(name)
    src = source_chains(pdb)
    rcsb = rcsb_chain_accessions(pdb)
    cx = comp["complexes"][name]
    members = {s for sl in cx["slots"] for s in sl["members"]}
    errors, warnings, info = [], [], []

    # identity
    for i, c in enumerate(m["chains"]):
        if c["tier"] != "experimental":
            continue
        want = rcsb.get(c["chain"], "missing")
        if want == "missing":
            errors.append(f"chain {c['chain']} ({c['symbol']}) is not a polymer chain of {pdb}")
        elif c["kind"] == "dna":
            if want is not None:
                errors.append(f"chain {c['chain']} drawn as DNA but RCSB maps it to {want}")
        elif want is None:
            if c["kind"] != "unassigned":
                errors.append(f"chain {c['chain']} is an RCSB 'unknown' entity but drawn as {c['symbol']}")
            else:
                info.append(f"chain {c['chain']}: RCSB 'unknown' entity, {c['n']} residues, drawn unassigned")
        elif c["uniprot"] != want:
            errors.append(f"chain {c['chain']} ({c['symbol']}) has UniProt {c['uniprot']}, RCSB says {want}")

    # composition
    subunit_syms = {c["symbol"] for c in m["chains"] if c["kind"] == "subunit"}
    for s in sorted(subunit_syms - members):
        errors.append(f"{s} is drawn but is not a curated member of {name}")
    for s in sorted(subunit_syms & set(cx.get("absent", []))):
        errors.append(f"{s} is drawn but listed absent from {name}")
    slots = {}
    for sl in cx["slots"]:
        tiers = {c["tier"] for c in m["chains"] if c["symbol"] in sl["members"]}
        slots[sl["slot"]] = "resolved" if "experimental" in tiers else next(iter(tiers)) if tiers else "ghost"
    ghost_slots = {g["slot"]: g["members"] for g in index["ghosts"]}
    for sl in cx["slots"]:
        if slots[sl["slot"]] == "ghost":
            if sl["slot"] not in ghost_slots:
                errors.append(f"slot {sl['slot']} has no chain and no ghost")
            elif ghost_slots[sl["slot"]] != sl["members"]:
                errors.append(f"ghost {sl['slot']} lists {ghost_slots[sl['slot']]}, composition has {sl['members']}")
        elif sl["slot"] in ghost_slots:
            errors.append(f"slot {sl['slot']} is drawn but also shipped as a ghost")
    for g in ghost_slots:
        if g not in slots:
            errors.append(f"ghost {g} is not a slot of {name}")

    # geometry: one rigid transform, source -> shipped
    P, Q, PA, QA = [], [], [], []
    for i, c in enumerate(m["chains"]):
        if c["tier"] != "experimental":
            continue
        s = src.get(c["chain"])
        if s is None:
            continue
        mb = beads[beads[:, 3] == i, :3]
        ma = axyz[achain == i]
        if len(mb) != len(s["beads"]):
            errors.append(f"chain {c['chain']}: {len(mb)} beads shipped, {len(s['beads'])} residues in {pdb}")
            continue
        if len(ma) != len(s["atoms"]):
            errors.append(f"chain {c['chain']}: {len(ma)} atoms shipped, {len(s['atoms'])} heavy atoms in {pdb}")
            continue
        P.append(s["beads"]); Q.append(mb); PA.append(s["atoms"]); QA.append(ma)
    P, Q, PA, QA = map(np.vstack, (P, Q, PA, QA))
    R, t = kabsch(P, Q)
    rmsd_b = float(np.sqrt((((P @ R.T + t) - Q) ** 2).sum(1).mean()))
    rmsd_a = float(np.sqrt((((PA @ R.T + t) - QA) ** 2).sum(1).mean()))
    if rmsd_b > MAX_RMSD or rmsd_a > MAX_RMSD:
        errors.append(f"shipped model is not a rigid copy of {pdb}: bead RMSD {rmsd_b:.3f}, atom {rmsd_a:.3f} A")

    # numbering: mapped residues are the UniProt amino acid
    mism = 0; mapped = 0
    for i, c in enumerate(m["chains"]):
        if c["kind"] != "subunit" or c["tier"] != "experimental":
            continue
        seq = seqs[c["uniprot"]]
        aa = src[c["chain"]]["aa"]
        r = res[beads[:, 3] == i]
        for a, u in zip(aa, r):
            if u:
                mapped += 1
                mism += a != seq[u - 1]
    if mism:
        errors.append(f"{mism} of {mapped} UniProt-numbered residues differ from the UniProt sequence")

    # placed chains
    placed = []
    for i, c in enumerate(m["chains"]):
        if c["tier"] == "experimental":
            continue
        s = c.get("source")
        if not s:
            errors.append(f"{c['symbol']} is {c['tier']} but has no provenance")
            continue
        sb = source_chains(s["pdb"])[s["chain"]]["beads"]
        mb = beads[beads[:, 3] == i, :3]
        R2, t2 = kabsch(sb, mb)
        r2 = float(np.sqrt((((sb @ R2.T + t2) - mb) ** 2).sum(1).mean()))
        if len(sb) != len(mb) or r2 > MAX_RMSD:
            errors.append(f"placed {c['symbol']} is not a rigid copy of {s['pdb']} chain {s['chain']}")
        if s["calpha_clashes"] > MAX_CLASH:
            warnings.append(f"placed {c['symbol']}: {s['calpha_clashes']} C-alphas clash")
        placed.append({"symbol": c["symbol"], **s})

    return {"pdb": pdb, "errors": errors, "warnings": warnings, "info": info,
            "slots": slots, "placed": placed,
            "chains": len(m["chains"]), "beads": int(len(beads)), "atoms": int(len(axyz)),
            "rigid_rmsd": {"beads": round(rmsd_b, 3), "atoms": round(rmsd_a, 3)},
            "uniprot_numbered": mapped, "superposed_on": m.get("superposed_on")}


def main() -> None:
    comp = yaml.safe_load(open(CURATED / "composition.yaml"))
    accs = {s["uniprot"] for s in comp["subunits"]}
    seqs = {a: fetch_uniprot.fetch_entry(a)["sequence"] for a in sorted(accs)}
    report = {name: check(name, comp, seqs) for name in MODELS}
    write_json(REPORT, report, compact=False)
    for name, r in report.items():
        sup = r["superposed_on"]
        print(f"{name} {r['pdb']}: {r['chains']} chains, {r['beads']} beads, {r['atoms']} atoms; "
              f"rigid RMSD {r['rigid_rmsd']['beads']}/{r['rigid_rmsd']['atoms']} A; "
              f"{r['uniprot_numbered']} residues UniProt-checked"
              + (f"; histone fit {sup['rmsd']} A on {sup['pdb']}" if sup else ""))
        print("   slots: " + ", ".join(f"{k}={v}" for k, v in r["slots"].items()))
        for kind in ("errors", "warnings", "info"):
            for x in r[kind]:
                print(f"   {kind[:-1]}: {x}")
    n_err = sum(len(r["errors"]) for r in report.values())
    print(f"{n_err} errors -> {REPORT.relative_to(ROOT)}")
    raise SystemExit(1 if n_err else 0)


if __name__ == "__main__":
    main()
