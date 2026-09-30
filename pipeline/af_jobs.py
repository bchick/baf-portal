"""AlphaFold Server input for BAF subunits no experimental structure resolves.

Each job pairs the unresolved subunits with an "anchor": pieces that ARE
resolved in a portal structure (SMARCA4 HSA region, ACTL6A, ACTB). After
prediction, the anchor's C-alphas are superposed onto the same residues in the
portal model, which carries the predicted subunits into place. They are then
drawn as "predicted" (paler, hatched) and never mixed with experimental chains.

    pixi run python -m pipeline.af_jobs   # writes data/predictions/alphafold_server_jobs.json

Submit that file at https://alphafoldserver.com (Upload JSON), download each
job's zip, and unpack it into data/predictions/<job name>/.

Construct boundaries are approximate: disordered tails are trimmed to keep each
job under the server's 5,000-token limit.
"""
from __future__ import annotations

import json

import yaml

from . import fetch_uniprot
from .common import CURATED, ROOT

OUT = ROOT / "data" / "predictions" / "alphafold_server_jobs.json"
TOKEN_LIMIT = 5000

# job -> [(symbol, first residue, last residue, copies, role)]
JOBS = {
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


def main() -> None:
    comp = yaml.safe_load(open(CURATED / "composition.yaml"))
    acc = {s["symbol"]: s["uniprot"] for s in comp["subunits"]}
    jobs = []
    for name, parts in JOBS.items():
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
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(jobs, indent=1) + "\n")
    print(f"-> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
