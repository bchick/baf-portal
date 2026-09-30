"""PMID -> formatted reference via NCBI ESummary; retraction flags.

A reference is flagged retracted when PubMed lists the publication type
"Retracted Publication". (Crossref `update-to` checks are Phase 1.)
"""
from __future__ import annotations

from .common import chunks, fetch
from .fetch_clinvar import E, TOOL


def _authors(auth: list[dict]) -> str:
    names = [a["name"] for a in auth if a.get("authtype") == "Author"]
    if not names:
        return ""
    if len(names) > 3:
        return ", ".join(names[:3]) + ", et al."
    return ", ".join(names) + "."


def format_ref(s: dict) -> dict:
    year = (s.get("pubdate") or "")[:4]
    doi = next((a["value"] for a in s.get("articleids", []) if a.get("idtype") == "doi"), None)
    vol = s.get("volume") or ""
    iss = f"({s['issue']})" if s.get("issue") else ""
    pages = f":{s['pages']}" if s.get("pages") else ""
    title = (s.get("title") or "").rstrip(".")
    text = f"{_authors(s.get('authors', []))} {title}. {s.get('source', '')}. {year}"
    if vol:
        text += f";{vol}{iss}{pages}"
    text += "."
    pubtypes = s.get("pubtype", []) or []
    return {
        "pmid": s["uid"], "text": " ".join(text.split()),
        "first_author": s.get("sortfirstauthor"), "year": year, "journal": s.get("source"),
        "title": title, "doi": doi,
        "retracted": "Retracted Publication" in pubtypes,
        "has_retraction_notice": any(r.get("reftype") == "Retraction in" for r in s.get("references", []) or []),
        "pubtypes": pubtypes,
    }


def resolve(pmids: set[str]) -> dict[str, dict]:
    out = {}
    for batch in chunks(sorted({p for p in pmids if p and p.isdigit()}, key=int), 200):
        d = fetch(E + "esummary.fcgi", method="POST",
                  data={"db": "pubmed", "id": ",".join(batch), "retmode": "json", **TOOL},
                  cache_dir="pubmed")
        res = d["result"]
        for uid in res.get("uids", []):
            if "error" in res[uid]:
                continue
            out[uid] = format_ref(res[uid])
    return out
