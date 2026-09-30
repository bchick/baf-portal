"""LitVar2 text-mined variant mentions (NCBI, public domain) -> tier-3 citations.

The bulk file litvar2_variants.json.gz (~2 GB, one JSON object per line) is
streamed once and filtered to curated BAF subunit genes; only the filtered
records are cached (data/cache/litvar/), keyed by the file's Last-Modified
date. The raw file is never written to disk.

Matching to our variants follows the plan's citation rules:
  * rsID entries: exact when exactly one of our variants carries that rsID;
    when several alleles share it, the entry's protein name must match ours.
  * protein-string entries (tmVar normalised, no rsID): accepted only for a
    simple substitution/nonsense whose reference residue matches UniProt at
    that position (or MANE numbering, where it differs), and only if the two
    numberings do not point at different variants.
"""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

import requests

from .common import BROWSER_UA, CACHE

URL = "https://ftp.ncbi.nlm.nih.gov/pub/lu/LitVar/litvar2_variants.json.gz"
KEEP = ("_id", "rsid", "gene", "hgvs_prot", "name", "pmids", "pmids_count", "flag_gene_variant")


def release() -> dict:
    r = requests.head(URL, timeout=60, headers={"User-Agent": BROWSER_UA})
    r.raise_for_status()
    return {"last_modified": r.headers.get("Last-Modified"), "bytes": int(r.headers.get("Content-Length", 0))}


def fetch_genes(genes: set[str]) -> dict[str, list[dict]]:
    """gene -> [LitVar2 records], variant-level only."""
    rel = release()
    stamp = re.sub(r"\W+", "_", rel["last_modified"] or "unknown")
    path = CACHE / "litvar" / f"litvar2_{stamp}.filtered.json.gz"
    if path.exists():
        with gzip.open(path, "rt") as fh:
            cached = json.load(fh)
        if set(cached["genes"]) >= genes:
            return {g: cached["records"].get(g, []) for g in genes}
    needles = [f'"{g}"' for g in genes]
    out: dict[str, list[dict]] = {g: [] for g in genes}
    print(f"  LitVar2: streaming {rel['bytes'] / 1e9:.1f} GB ({rel['last_modified']})", flush=True)
    with requests.get(URL, stream=True, timeout=1800, headers={"User-Agent": BROWSER_UA}) as r:
        r.raise_for_status()
        r.raw.decode_content = False
        with gzip.GzipFile(fileobj=r.raw) as gz:
            for raw in gz:
                line = raw.decode("utf-8", "replace")
                if not any(n in line for n in needles):     # cheap prefilter
                    continue
                rec = json.loads(line)
                if rec.get("flag_gene_variant"):
                    continue
                for g in set(rec.get("gene") or []) & genes:
                    out[g].append({k: rec.get(k) for k in KEEP})
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as fh:
        json.dump({"genes": sorted(genes), "release": rel, "records": out}, fh)
    return out


AA3 = {"A": "Ala", "R": "Arg", "N": "Asn", "D": "Asp", "C": "Cys", "Q": "Gln", "E": "Glu", "G": "Gly", "H": "His",
       "I": "Ile", "L": "Leu", "K": "Lys", "M": "Met", "F": "Phe", "P": "Pro", "S": "Ser", "T": "Thr", "W": "Trp",
       "Y": "Tyr", "V": "Val", "X": "Ter", "*": "Ter"}
SIMPLE = re.compile(r"^p\.([ACDEFGHIKLMNPQRSTVWY])(\d+)([ACDEFGHIKLMNPQRSTVWYX*])$")


def parse_simple(hgvs_prot: str | None):
    m = SIMPLE.match(hgvs_prot or "")
    if not m:
        return None
    return m.group(1), int(m.group(2)), m.group(3)


def to_three(ref: str, pos: int, alt: str) -> str:
    return f"p.{AA3[ref]}{pos}{AA3[alt]}"


def match(records: list[dict], variants: list[dict], sequence: str, stats) -> dict[str, list[dict]]:
    """variant key -> [{pmid, basis, id}] for tier-3 citations."""
    by_rs: dict[str, list[dict]] = {}
    by_p: dict[str, list[dict]] = {}
    by_mane: dict[str, list[dict]] = {}
    for v in variants:
        if v.get("rs"):
            by_rs.setdefault(str(v["rs"]), []).append(v)
        if v.get("p"):
            by_p.setdefault(v["p"], []).append(v)
        if v.get("mane"):
            by_mane.setdefault(v["mane"], []).append(v)
    out: dict[str, list[dict]] = {}

    def attach(vs, rec, basis):
        for v in vs:
            out.setdefault(v["k"], []).extend(
                {"pmid": str(p), "basis": basis, "id": rec["_id"]} for p in rec.get("pmids") or [])

    for rec in records:
        if not rec.get("pmids"):
            stats["litvar:no_pmids"] += 1
            continue
        simple = parse_simple(rec.get("hgvs_prot"))
        rs = (rec.get("rsid") or "").removeprefix("rs")
        if rs:
            cands = by_rs.get(rs, [])
            if len(cands) > 1 and simple:
                name = to_three(*simple)
                cands = [v for v in cands if name in (v.get("p"), v.get("mane"))]
            if len(cands) == 1:
                attach(cands, rec, "rsID")
                stats["litvar:rsid"] += 1
            elif cands:
                stats["litvar:rsid_ambiguous"] += 1
            else:
                stats["litvar:rsid_unmatched"] += 1
            continue
        if not simple:
            stats["litvar:protein_unparsed"] += 1
            continue
        ref, pos, alt = simple
        name = to_three(ref, pos, alt)
        on_uniprot = pos <= len(sequence) and sequence[pos - 1] == ref
        a = by_p.get(name, []) if on_uniprot else []
        b = [v for v in by_mane.get(name, []) if v.get("mane") != v.get("p")]   # MANE-only numbering
        if a and b and {v["k"] for v in a} != {v["k"] for v in b}:
            stats["litvar:protein_ambiguous"] += 1
        elif a or b:
            attach(a or b, rec, "protein (ref-checked)")
            stats["litvar:protein"] += 1
        else:
            stats["litvar:protein_unmatched"] += 1
    return out
