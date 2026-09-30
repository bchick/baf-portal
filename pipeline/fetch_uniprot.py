"""UniProt REST: canonical sequence and sequence features (CC BY 4.0)."""
from __future__ import annotations

import requests

from .common import BROWSER_UA, fetch

KEEP = {
    "Domain", "Region", "Motif", "Zinc finger", "DNA binding", "Coiled coil",
    "Compositional bias", "Repeat", "Modified residue", "Cross-link",
    "Natural variant", "Mutagenesis", "Binding site",
}
LAYER = {  # how the site groups features
    "Domain": "domain", "Zinc finger": "domain", "DNA binding": "domain", "Repeat": "domain",
    "Region": "region", "Coiled coil": "region", "Compositional bias": "region",
    "Motif": "motif", "Binding site": "motif",
    "Modified residue": "ptm", "Cross-link": "ptm",
    "Natural variant": "variant", "Mutagenesis": "mutagenesis",
}


def release() -> dict:
    r = requests.head("https://rest.uniprot.org/uniprotkb/P51532.json",
                      headers={"User-Agent": BROWSER_UA}, timeout=60)
    return {"release": r.headers.get("X-UniProt-Release"),
            "date": r.headers.get("X-UniProt-Release-Date")}


def _evidence(ev_list):
    out = []
    for e in ev_list or []:
        out.append({k: v for k, v in {"eco": e.get("evidenceCode"), "src": e.get("source"),
                                       "id": e.get("id")}.items() if v})
    return out


def fetch_entry(acc: str) -> dict:
    d = fetch(f"https://rest.uniprot.org/uniprotkb/{acc}.json", cache_dir="uniprot")
    feats = []
    for f in d.get("features", []):
        if f["type"] not in KEEP:
            continue
        s, e = f["location"]["start"].get("value"), f["location"]["end"].get("value")
        if s is None or e is None:
            continue
        rec = {"type": f["type"], "layer": LAYER[f["type"]], "start": s, "end": e,
               "desc": f.get("description", ""), "ev": _evidence(f.get("evidences"))}
        if f.get("featureId"):
            rec["id"] = f["featureId"]
        alt = f.get("alternativeSequence")
        if alt:
            rec["ref"] = alt.get("originalSequence", "")
            rec["alt"] = (alt.get("alternativeSequences") or [""])[0]
        xr = [x["id"] for x in f.get("featureCrossReferences", []) if x.get("database") == "dbSNP"]
        if xr:
            rec["rs"] = xr[0]
        feats.append(rec)
    return {
        "accession": d["primaryAccession"],
        "entry_version": d["entryAudit"]["entryVersion"],
        "sequence_version": d["entryAudit"]["sequenceVersion"],
        "last_annotation_update": d["entryAudit"]["lastAnnotationUpdateDate"],
        "gene": d["genes"][0]["geneName"]["value"],
        "protein_name": d["proteinDescription"]["recommendedName"]["fullName"]["value"],
        "sequence": d["sequence"]["value"],
        "length": d["sequence"]["length"],
        "features": feats,
    }


def curated_pmids(feature: dict) -> list[str]:
    """PMIDs supporting a feature with experimental evidence (ECO:0000269)."""
    return [e["id"] for e in feature.get("ev", [])
            if e.get("eco") == "ECO:0000269" and e.get("src") == "PubMed"]
