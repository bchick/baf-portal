"""InterPro API: Pfam and InterPro domain entries on a UniProt accession (CC0)."""
from __future__ import annotations

from .common import fetch

API = "https://www.ebi.ac.uk/interpro/api"


def release() -> dict:
    d = fetch(f"{API}/", cache_dir="interpro")
    dbs = d.get("databases", {})
    return {k: {"version": dbs[k].get("version"), "date": dbs[k].get("releaseDate")}
            for k in ("interpro", "pfam") if k in dbs}


def fetch_domains(acc: str) -> list[dict]:
    out = []
    for db in ("pfam", "interpro"):
        d = fetch(f"{API}/entry/{db}/protein/uniprot/{acc}", params={"page_size": 200},
                  cache_dir="interpro")
        for r in d.get("results", []):
            md = r["metadata"]
            if db == "interpro" and md.get("type") not in ("domain", "repeat", "homologous_superfamily"):
                continue
            if db == "interpro" and md.get("type") == "homologous_superfamily":
                continue
            for p in r.get("proteins", []):
                for loc in p.get("entry_protein_locations", []):
                    for fr in loc.get("fragments", []):
                        out.append({"db": db, "acc": md["accession"], "name": md["name"],
                                    "type": md.get("type"), "start": fr["start"], "end": fr["end"]})
    return sorted(out, key=lambda x: (x["start"], x["db"]))
