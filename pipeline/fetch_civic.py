"""CIViC clinical evidence (CC0) -> tier-1 citations and gene-level evidence.

Nightly TSVs: VariantSummaries (variant -> gene, coordinates, ClinVar IDs) and
ClinicalEvidenceSummaries (molecular profile -> evidence items). Only
`accepted` evidence from PubMed sources is kept.

CIViC "variants" for BAF genes are mostly categories (Mutation, Loss,
Inactivating Mutation, Underexpression...). Those are gene-level evidence and
are never attached to an individual variant. A CIViC variant is attached to
one of ours only when it is a specific allele and matches exactly:
  1. by ClinVar VariationID, else
  2. by protein change whose reference residue matches UniProt (or MANE).
"""
from __future__ import annotations

import csv
import io
import re

from .common import fetch
from .fetch_litvar import to_three

BASE = "https://civicdb.org/downloads/nightly/"
PROTEIN = re.compile(r"^([ACDEFGHIKLMNPQRSTVWY])(\d+)([ACDEFGHIKLMNPQRSTVWY*])$")


def _tsv(name: str) -> list[dict]:
    txt = fetch(BASE + name, as_json=False, cache_dir="civic")
    return list(csv.DictReader(io.StringIO(txt), delimiter="\t"))


def fetch_genes(genes: set[str]) -> dict[str, dict]:
    """gene -> {"variants": [...], "evidence": {mp_id: [...]}} (accepted, PubMed only)."""
    variants = [r for r in _tsv("nightly-VariantSummaries.tsv") if r["feature_name"] in genes]
    mp = {r["single_variant_molecular_profile_id"]: r for r in variants if r["single_variant_molecular_profile_id"]}
    out = {g: {"variants": [], "evidence": {}} for g in genes}
    for r in variants:
        out[r["feature_name"]]["variants"].append({
            "variant_id": r["variant_id"], "name": r["variant"], "mp": r["single_variant_molecular_profile_id"],
            "clinvar_ids": [x for x in re.split(r"[,\s]+", r["clinvar_ids"] or "") if x.isdigit()],
            "url": r["variant_civic_url"],
        })
    for e in _tsv("nightly-ClinicalEvidenceSummaries.tsv"):
        v = mp.get(e["molecular_profile_id"])
        if not v or e["evidence_status"] != "accepted" or e["source_type"] != "PubMed":
            continue
        out[v["feature_name"]]["evidence"].setdefault(e["molecular_profile_id"], []).append({
            "eid": e["evidence_id"], "profile": e["molecular_profile"], "type": e["evidence_type"],
            "direction": e["evidence_direction"], "level": e["evidence_level"], "significance": e["significance"],
            "disease": e["disease"], "doid": e["doid"], "therapies": e["therapies"] or None,
            "origin": e["variant_origin"], "rating": int(e["rating"]) if e["rating"].isdigit() else None,
            "pmid": e["citation_id"], "statement": e["evidence_statement"], "url": e["evidence_civic_url"],
        })
    return out


def release() -> dict:
    return {"source": BASE, "files": ["nightly-VariantSummaries.tsv", "nightly-ClinicalEvidenceSummaries.tsv"]}


def split(civic: dict, variants: list[dict], stats) -> tuple[dict[str, list[dict]], list[dict]]:
    """-> (variant key -> [evidence], gene-level evidence)."""
    by_cv = {v["cv"]["id"]: v for v in variants if v.get("cv")}
    by_p = {}
    for v in variants:
        for name in {v.get("p"), v.get("mane")} - {None}:
            by_p.setdefault(name.removeprefix("p."), []).append(v)
    per_variant: dict[str, list[dict]] = {}
    gene_level: list[dict] = []
    for cvar in civic["variants"]:
        ev = civic["evidence"].get(cvar["mp"], [])
        if not ev:
            continue
        hit = next((by_cv[i] for i in cvar["clinvar_ids"] if i in by_cv), None)
        basis = "ClinVar ID" if hit else None
        m = PROTEIN.match(cvar["name"])
        if not hit and m:
            ref, pos, alt = m.group(1), int(m.group(2)), m.group(3).replace("*", "X")
            cands = by_p.get(to_three(ref, pos, alt).removeprefix("p."), [])
            # our p./MANE strings are built with a reference-residue assert, so a
            # string match is ref-checked; >1 candidate means the UniProt and MANE
            # numberings disagree -> ambiguous, not attached
            if len(cands) == 1:
                hit, basis = cands[0], "protein (ref-checked)"
        if hit:
            per_variant.setdefault(hit["k"], []).extend({**e, "basis": basis, "civic_variant": cvar["name"]} for e in ev)
            stats["civic:variant_level"] += len(ev)
        else:
            gene_level.extend({**e, "civic_variant": cvar["name"], "variant_url": cvar["url"]} for e in ev)
            stats["civic:gene_level"] += len(ev)
    return per_variant, gene_level
