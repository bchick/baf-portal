"""cBioPortal public API: TCGA PanCancer Atlas 2018 mutations (ODbL 1.0).

Counting rules
* one TCGA version only: the 32 `*_tcga_pan_can_atlas_2018` studies
* counts are per PATIENT (TCGA barcode), never per sample
* denominator = patients with >=1 sample profiled for the gene
  (`gene-panel-data`, `profiled: true`, and the gene on the panel if any)
"""
from __future__ import annotations

from .common import fetch

API = "https://www.cbioportal.org/api"
SUFFIX = "_tcga_pan_can_atlas_2018"


def entrez_id(gene: str) -> int:
    """Entrez Gene ID from cBioPortal (the source of the mutation calls),
    cross-checked against HGNC so a symbol clash can never pull another gene."""
    g = fetch(f"{API}/genes/{gene}", cache_dir="cbioportal")
    if g.get("hugoGeneSymbol") != gene:
        raise ValueError(f"cBioPortal resolves {gene} to {g.get('hugoGeneSymbol')}")
    h = fetch(f"https://rest.genenames.org/fetch/symbol/{gene}", cache_dir="hgnc")["response"]["docs"]
    if not h or str(h[0].get("entrez_id")) != str(g["entrezGeneId"]):
        raise ValueError(f"{gene}: cBioPortal Entrez {g['entrezGeneId']} != HGNC {h[0].get('entrez_id') if h else None}")
    return int(g["entrezGeneId"])


def release() -> dict:
    i = fetch(f"{API}/info", cache_dir="cbioportal")
    return {"portal_version": i.get("portalVersion"), "db_version": i.get("dbVersion")}


def studies() -> list[dict]:
    st = fetch(f"{API}/studies", params={"projection": "SUMMARY"}, cache_dir="cbioportal")
    out = [s for s in st if s["studyId"].endswith(SUFFIX)]
    return sorted(out, key=lambda s: s["studyId"])


def _panel_genes(panel_id: str) -> set[int]:
    p = fetch(f"{API}/gene-panels/{panel_id}", cache_dir="cbioportal")
    return {g["entrezGeneId"] for g in p.get("genes", [])}


def profiled_patients(study_id: str, entrez: int) -> set[str]:
    rows = fetch(f"{API}/molecular-profiles/{study_id}_mutations/gene-panel-data/fetch",
                 method="POST", json_body={"sampleListId": f"{study_id}_all"}, cache_dir="cbioportal")
    pats = set()
    for r in rows:
        if not r.get("profiled"):
            continue
        pid = r.get("genePanelId")
        if pid and entrez not in _panel_genes(pid):
            continue
        pats.add(r["patientId"])
    return pats


def mutations(study_id: str, entrez: int) -> list[dict]:
    return fetch(f"{API}/molecular-profiles/{study_id}_mutations/mutations/fetch", method="POST",
                 params={"projection": "DETAILED"},
                 json_body={"entrezGeneIds": [entrez], "sampleListId": f"{study_id}_all"},
                 cache_dir="cbioportal")


def count_patients(muts: list[dict]) -> dict[str, set[str]]:
    """Variant key -> set of patient IDs. A patient seen in several samples
    (or several studies) is counted once."""
    out: dict[str, set[str]] = {}
    for m in muts:
        out.setdefault(maf_key(m), set()).add(m["patientId"])
    return out


def maf_key(m: dict) -> str:
    return f"{m['ncbiBuild']}:{m['chr']}:{m['startPosition']}-{m['endPosition']}:{m['referenceAllele']}>{m['variantAllele']}"


def fetch_gene(gene: str) -> dict:
    entrez = entrez_id(gene)
    per_study = {}
    all_muts = []
    for s in studies():
        sid = s["studyId"]
        prof = profiled_patients(sid, entrez)
        muts = [m for m in mutations(sid, entrez) if m["patientId"] in prof or not prof]
        per_study[sid] = {
            "name": s["name"], "cancer_type": s.get("cancerTypeId"),
            "pmids": [p.strip() for p in (s.get("pmid") or "").split(",") if p.strip()],
            "citation": s.get("citation"), "import_date": s.get("importDate"),
            "profiled": sorted(prof),
            "mutated": sorted({m["patientId"] for m in muts}),
        }
        all_muts.extend(muts)
    return {"gene": gene, "entrez": entrez, "studies": per_study, "mutations": all_muts}
