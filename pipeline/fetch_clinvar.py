"""ClinVar via NCBI E-utilities (public domain).

* esearch  `<GENE>[gene]`                        -> VariationIDs
  (not `single_gene[prop]`: ClinVar counts overlapping NCBI regulatory-element
  records (LOC...) as genes, which silently dropped e.g. ~450 ARID1B exon-1
  variants. Multi-gene CNVs are excluded downstream instead: build.py keeps
  only SPDI alleles <= MAX_INDEL that project onto the canonical protein.)
* esummary (batched POST)                        -> classification, stars, conditions, SPDI
* var_citations.txt, stream-filtered to our VariationIDs (the raw 250 MB file
  is never written to disk)                     -> which variants carry citations
* efetch rettype=vcv for cited variants          -> per-SCV submitter, review status, PMIDs
"""
from __future__ import annotations

import gzip
import json
import xml.etree.ElementTree as ET

import requests

from .common import BROWSER_UA, CACHE, chunks, fetch

E = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
TOOL = {"tool": "baf-portal", "email": "bchick@salk.edu"}
VAR_CITATIONS = "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/var_citations.txt"

STARS = {
    "practice guideline": 4,
    "reviewed by expert panel": 3,
    "criteria provided, multiple submitters, no conflicts": 2,
    "criteria provided, conflicting classifications": 1,
    "criteria provided, conflicting interpretations": 1,
    "criteria provided, single submitter": 1,
}


def stars(review_status: str) -> int:
    return STARS.get((review_status or "").strip().lower(), 0)


def release() -> dict:
    d = fetch(E + "einfo.fcgi", params={"db": "clinvar", "retmode": "json", **TOOL}, cache_dir="clinvar")
    info = d["einforesult"]["dbinfo"][0]
    return {"last_update": info.get("lastupdate"), "records": info.get("count")}


def search_ids(gene: str) -> list[str]:
    term = f"{gene}[gene]"
    d = fetch(E + "esearch.fcgi", params={"db": "clinvar", "term": term, "retmax": 100000,
                                          "retmode": "json", **TOOL}, cache_dir="clinvar")
    return d["esearchresult"]["idlist"]


def _traits(block):
    out = []
    for t in (block or {}).get("trait_set", []) or []:
        x = {r["db_source"]: r["db_id"] for r in t.get("trait_xrefs", [])}
        rec = {"name": t.get("trait_name")}
        if "MONDO" in x:
            rec["mondo"] = x["MONDO"]
        if "MedGen" in x:
            rec["medgen"] = x["MedGen"]
        if "Orphanet" in x:
            rec["orphanet"] = x["Orphanet"]
        out.append(rec)
    return out


def _cls(block):
    if not block or not block.get("description"):
        return None
    return {"class": block["description"], "review": block.get("review_status", ""),
            "stars": stars(block.get("review_status")),
            "last_evaluated": (block.get("last_evaluated") or "")[:10].replace("/", "-"),
            "conditions": _traits(block)}


def summaries(ids: list[str]) -> list[dict]:
    out = []
    for batch in chunks(ids, 200):
        d = fetch(E + "esummary.fcgi", method="POST",
                  data={"db": "clinvar", "id": ",".join(batch), "retmode": "json", **TOOL},
                  cache_dir="clinvar")
        res = d["result"]
        for uid in res.get("uids", []):
            s = res[uid]
            vs = (s.get("variation_set") or [{}])[0]
            xr = {x["db_source"]: x["db_id"] for x in vs.get("variation_xrefs", [])}
            loc38 = next((l for l in vs.get("variation_loc", []) if l.get("assembly_name") == "GRCh38"), {})
            out.append({
                "variation_id": uid,
                "vcv": s.get("accession"),
                "title": s.get("title"),
                "type": s.get("obj_type"),
                "spdi": vs.get("canonical_spdi") or None,
                "chr": loc38.get("chr"),
                "start38": loc38.get("start"),
                "stop38": loc38.get("stop"),
                "rs": xr.get("dbSNP"),
                "uniprot_xref": xr.get("UniProtKB"),
                "clinvar_protein_change": s.get("protein_change") or None,
                "consequences": s.get("molecular_consequence_list", []),
                "germline": _cls(s.get("germline_classification")),
                "somatic_impact": _cls(s.get("clinical_impact_classification")),
                "oncogenicity": _cls(s.get("oncogenicity_classification")),
                "genes": [g["symbol"] for g in s.get("genes", [])],
            })
    return out


def var_citations(variation_ids: set[str]) -> dict[str, list[tuple[str, str]]]:
    """Stream var_citations.txt and keep rows for our VariationIDs.

    Cached as a small filtered gzip under data/cache/clinvar/; the raw file is
    never stored.
    """
    path = CACHE / "clinvar" / "var_citations.filtered.json.gz"
    if path.exists():
        with gzip.open(path, "rt") as fh:
            cached = json.load(fh)
        if set(cached["ids"]) >= variation_ids:
            return {k: [tuple(x) for x in v] for k, v in cached["rows"].items() if k in variation_ids}
    rows: dict[str, list[tuple[str, str]]] = {}
    with requests.get(VAR_CITATIONS, stream=True, timeout=600,
                      headers={"User-Agent": BROWSER_UA}) as r:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line or line.startswith("#"):
                continue
            f = line.split("\t")
            if len(f) > 5 and f[1] in variation_ids:
                rows.setdefault(f[1], []).append((f[4], f[5]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as fh:
        json.dump({"ids": sorted(variation_ids), "rows": rows}, fh)
    return rows


def _scv_citations(xml_text: str) -> dict[str, list[dict]]:
    """VariationID -> [{scv, submitter, review, stars, class, pmids}]"""
    out: dict[str, list[dict]] = {}
    root = ET.fromstring(xml_text)
    for va in root.iter("VariationArchive"):
        vid = va.get("VariationID")
        for ca in va.iter("ClinicalAssertion"):
            acc = ca.find("ClinVarAccession")
            cls = ca.find("Classification")
            review = (cls.findtext("ReviewStatus") if cls is not None else "") or ""
            label = ""
            if cls is not None:
                for tag in ("GermlineClassification", "SomaticClinicalImpact", "OncogenicityClassification"):
                    if cls.findtext(tag):
                        label = cls.findtext(tag)
                        break
            # Citations anywhere in the assertion except inside trait definitions
            # (those are generic GeneReviews/OMIM disease references).
            trait_ids = {id(c) for ts in ca.iter("TraitSet") for c in ts.iter("Citation")}
            pmids = []
            for c in ca.iter("Citation"):
                if id(c) in trait_ids:
                    continue
                for i in c.findall("ID"):
                    if i.get("Source") == "PubMed" and i.text and i.text.strip() not in pmids:
                        pmids.append(i.text.strip())
            if not pmids:
                continue
            out.setdefault(vid, []).append({
                "scv": acc.get("Accession") if acc is not None else None,
                "submitter": acc.get("SubmitterName") if acc is not None else None,
                "review": review, "stars": stars(review), "class": label, "pmids": pmids,
            })
    return out


def scv_citations(variation_ids: list[str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for batch in chunks(sorted(variation_ids, key=int), 25):
        txt = fetch(E + "efetch.fcgi", method="POST",
                    data={"db": "clinvar", "rettype": "vcv", "is_variationid": "true",
                          "id": ",".join(batch), **TOOL},
                    as_json=False, cache_dir="clinvar_vcv")
        out.update(_scv_citations(txt))
    return out


def fetch_gene(gene: str) -> list[dict]:
    ids = search_ids(gene)
    recs = [r for r in summaries(ids) if gene in r["genes"]]
    return recs
