"""AlphaFold Server input for BAF subunits no experimental structure resolves.

Each job pairs the unresolved subunits with an "anchor": pieces that ARE
resolved in a portal structure (SMARCA4 HSA region, ACTL6A, ACTB). After
prediction, the anchor's C-alphas are superposed onto the same residues in the
portal model, which carries the predicted subunits into place. They are then
drawn as "predicted" (paler, hatched) and never mixed with experimental chains.

    pixi run python -m pipeline.af_jobs   # writes data/predictions/alphafold_server_jobs[_round<N>].json

Submit that file at https://alphafoldserver.com (Upload JSON), download each
job's zip, and unpack it into data/predictions/<job name>/.

Round 1 (whole ncBAF base, SS18 on the ARP module) did not place the
ncBAF-specific subunits; see reports/af_assessment_2026-10-01.md. Round 2 asks
the narrower question of how BRD9's DUF3512 region meets BICRA's conserved
GLTSCR domain and SMARCD1 (the SMARCD1-BRD9-BICRA module, Schick 2019), with
two checks built in: the same jobs with paralog BICRAL, and BRD7 + SMARCD1, a
positive control whose interface is resolved in PBAF (7VDV).

Construct boundaries are approximate: disordered tails are trimmed to keep each
job under the server's 5,000-token limit.
"""
from __future__ import annotations

import json

import yaml

from . import fetch_uniprot
from .common import CURATED, ROOT

OUT_DIR = ROOT / "data" / "predictions"
TOKEN_LIMIT = 5000

# round -> job -> [(symbol, first residue, last residue, copies, role)]
ROUND1 = {
    "ncbaf_base": [
        ("SMARCC1", 1, 955, 2, "base scaffold dimer (disordered C-terminus 956-1105 trimmed)"),
        ("SMARCD1", 1, 515, 1, "base"),
        ("BRD9", 1, 597, 1, "ncBAF-specific"),
        ("BICRA", 1100, 1560, 1, "ncBAF-specific; C-terminal region incl. the conserved GiBAF domain"),
        ("SMARCA4", 350, 560, 1, "anchor: pre-HSA/HSA helix, resolved in 9WBZ and 6LTJ"),
        ("ACTL6A", 1, 429, 1, "anchor: ARP module"),
        ("ACTB", 1, 375, 1, "anchor: ARP module"),
    ],
    "ss18_arp": [
        ("SS18", 1, 186, 1, "cBAF/ncBAF; N-terminal half (QPGY-rich 188-418 trimmed)"),
        ("SMARCA4", 350, 760, 1, "anchor: HSA/post-HSA"),
        ("ACTL6A", 1, 429, 1, "anchor: ARP module"),
        ("ACTB", 1, 375, 1, "anchor: ARP module"),
        ("BCL7A", 1, 210, 1, "ARP-module partner (resolved in 9WBZ)"),
    ],
}

# Construct boundaries: Pfam/InterPro domains padded to the flanking UniProt
# "Disordered" regions. BRD9 241-535 is everything after the bromodomain up to
# the disordered C-terminus; it covers DUF3512 (287-464), which aligns to BRD7
# 278-467 (BLOSUM62 global alignment, 38% identity over the aligned length).
# SMARCD1 104-515 drops the disordered N-terminus (1-103) and keeps the region
# that binds BRD7 in 7VDV (contacts at SMARCD1 126-471).
BRD9 = ("BRD9", 241, 535, 1, "DUF3512 region (bromodomain and disordered C-terminus trimmed)")
SMARCD1 = ("SMARCD1", 104, 515, 1, "SWIFT + SWIB + C-terminal helices (disordered N-terminus trimmed)")
ROUND2 = {
    "brd9_bicra": [BRD9, ("BICRA", 1076, 1214, 1, "conserved GLTSCR domain 1092-1191, padded")],
    "brd9_bicra_smarcd1": [BRD9, ("BICRA", 1076, 1214, 1, "conserved GLTSCR domain 1092-1191, padded"), SMARCD1],
    "brd9_bicral_smarcd1": [BRD9, ("BICRAL", 692, 836, 1, "paralog check: GLTSCR domain 711-811, padded"), SMARCD1],
    "brd7_smarcd1_ctrl": [("BRD7", 290, 651, 1, "positive control: DUF3512 + C-terminus, resolved in 7VDV"), SMARCD1],
}
ROUNDS = {1: ("alphafold_server_jobs.json", ROUND1), 2: ("alphafold_server_jobs_round2.json", ROUND2)}


def write_round(fname: str, rjobs: dict, acc: dict) -> None:
    jobs = []
    for name, parts in rjobs.items():
        seqs, tokens = [], 0
        for sym, a, b, n, _ in parts:
            seq = fetch_uniprot.fetch_entry(acc[sym])["sequence"]
            assert 1 <= a < b <= len(seq), (name, sym, a, b, len(seq))
            seqs.append({"proteinChain": {"sequence": seq[a - 1:b], "count": n}})
            tokens += (b - a + 1) * n
        assert tokens <= TOKEN_LIMIT, f"{name}: {tokens} tokens > {TOKEN_LIMIT}"
        jobs.append({"name": name, "modelSeeds": [], "sequences": seqs, "dialect": "alphafoldserver", "version": 1})
        print(f"{name}: {tokens} tokens; " + ", ".join(f"{s}{f' x{n}' if n > 1 else ''} {a}-{b}"
                                                        for s, a, b, n, _ in parts))
    out = OUT_DIR / fname
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(jobs, indent=1) + "\n")
    print(f"-> {out.relative_to(ROOT)}")


def main() -> None:
    comp = yaml.safe_load(open(CURATED / "composition.yaml"))
    acc = {s["symbol"]: s["uniprot"] for s in comp["subunits"]}
    for fname, rjobs in ROUNDS.values():
        write_round(fname, rjobs, acc)


if __name__ == "__main__":
    main()
