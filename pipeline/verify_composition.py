"""Re-check every claim in data/curated/composition.yaml.

Internal (always):
  * every PMID used anywhere is defined in `references` (and flags unused ones)
  * every slot member / absent symbol is a curated subunit; no symbol is both
    a member and absent in one complex; symbols and accessions are unique
  * lists every `needs_review` item (the Phase 0 curator review gate)
Live (unless --offline), against the source APIs:
  * PubMed ESummary: PMID exists, first-author surname and year match the
    reference text, journal roughly matches, not retracted
  * UniProt: accession is reviewed, human, primary gene = symbol, length
  * HGNC: ID approved, symbol matches, cross-references the UniProt accession
  * RCSB: structure exists and its primary-citation PMID is the one we cite
  * Affinage: every subunit has a gene entry (the site links to it)

    pixi run verify                 # live
    pixi run verify --cached        # reuse data/cache/verify/ responses
    pixi run verify --offline       # internal checks only

Writes reports/verify_composition.json; exits 1 if any error.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import unicodedata
from collections import defaultdict

import yaml

from .common import CURATED, ROOT, chunks, fetch
from .fetch_clinvar import E, TOOL

REPORT = ROOT / "reports" / "verify_composition.json"
JOURNAL_ALIAS = {"pnas": "proc natl acad sci"}


class Findings:
    def __init__(self):
        self.errors, self.warnings, self.review, self.ok = [], [], [], []
        self.pubmed: dict[str, dict] = {}      # PMID -> ESummary record, for later checks

    def error(self, where, msg): self.errors.append({"where": where, "msg": msg})
    def warn(self, where, msg): self.warnings.append({"where": where, "msg": msg})


def walk(node, path=""):
    """Yield (path, key, value) for every mapping entry in the YAML tree."""
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}" if path else str(k)
            yield p, k, v
            yield from walk(v, p)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            label = v.get("slot") or v.get("pdb") or v.get("symbol") or i if isinstance(v, dict) else i
            yield from walk(v, f"{path}[{label}]")


def used_pmids(comp: dict) -> dict[str, list[str]]:
    """PMID -> paths that cite it (outside the `references` block)."""
    out = defaultdict(list)
    for path, key, val in walk({k: v for k, v in comp.items() if k != "references"}):
        if key == "pmid":
            out[str(val)].append(path)
        elif key in ("pmids", "defining_pmids"):
            for p in val:
                out[str(p)].append(path)
    return out


def parse_reference(text: str) -> dict:
    """'Wang 1996 EMBO J — ...' -> {surname, year, journal}."""
    head = text.split("—")[0].strip()
    m = re.match(r"^(\S+(?: & \S+)?)\s+(\d{4})\s+(.*)$", head)
    if not m:
        return {}
    return {"surname": m.group(1).split(" & ")[0], "year": m.group(2), "journal": m.group(3).strip()}


def fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


# ------------------------------------------------------------------ internal

def check_internal(comp: dict, f: Findings) -> None:
    refs = {str(k): v for k, v in comp["references"].items()}
    used = used_pmids(comp)
    for p, paths in sorted(used.items()):
        if p not in refs:
            f.error(paths[0], f"PMID {p} is cited but not defined in `references`")
    for p in sorted(set(refs) - set(used)):
        f.warn(f"references.{p}", "defined but never cited")
    for p, text in refs.items():
        if not parse_reference(text):
            f.warn(f"references.{p}", f"cannot parse 'Author Year Journal' from {text!r}")

    subs = comp["subunits"]
    symbols = [s["symbol"] for s in subs]
    for dup in {s for s in symbols if symbols.count(s) > 1}:
        f.error("subunits", f"duplicate symbol {dup}")
    accs = [s["uniprot"] for s in subs]
    for dup in {a for a in accs if accs.count(a) > 1}:
        f.error("subunits", f"duplicate UniProt accession {dup}")
    known = set(symbols)
    for cid, c in comp["complexes"].items():
        members = {m for sl in c["slots"] for m in sl["members"]}
        for m in sorted(members - known):
            f.error(f"complexes.{cid}", f"slot member {m} is not a curated subunit")
        for m in sorted(set(c.get("absent", [])) - known):
            f.error(f"complexes.{cid}.absent", f"{m} is not a curated subunit")
        for m in sorted(members & set(c.get("absent", []))):
            f.error(f"complexes.{cid}", f"{m} is both a member and absent")
        for sl in c["slots"]:
            if sl.get("contested") and not sl.get("contested_notes"):
                f.error(f"complexes.{cid}.slots[{sl['slot']}]", "contested without contested_notes")
            if not sl.get("pmids"):
                f.error(f"complexes.{cid}.slots[{sl['slot']}]", "membership claim without a PMID")

    for path, key, val in walk(comp):
        if key == "needs_review" and val:
            f.review.append(path.removesuffix(".needs_review"))
        elif isinstance(val, str) and "needs_review" in val and key != "needs_review":
            f.review.append(f"{path} (in text)")


# ------------------------------------------------------------------ live

def check_pubmed(comp: dict, f: Findings, refresh: bool) -> None:
    refs = {str(k): v for k, v in comp["references"].items()}
    for batch in chunks(sorted(refs, key=int), 200):
        d = fetch(E + "esummary.fcgi", method="POST", refresh=refresh, cache_dir="verify",
                  data={"db": "pubmed", "id": ",".join(batch), "retmode": "json", **TOOL})
        res = d["result"]
        for p in batch:
            s = res.get(p)
            where = f"references.{p}"
            if s and "error" not in s:
                f.pubmed[p] = s
            if not s or "error" in s:
                f.error(where, "PMID not found in PubMed")
                continue
            want = parse_reference(refs[p])
            got_author = fold(s.get("sortfirstauthor") or "").split(" ")[0]
            got_year = (s.get("pubdate") or "")[:4]
            if want and fold(want["surname"]) != got_author:
                f.error(where, f"first author {want['surname']!r} in reference, PubMed has {s.get('sortfirstauthor')!r}")
            if want and want["year"] != got_year:
                f.error(where, f"year {want['year']} in reference, PubMed has {got_year}")
            j = fold(want.get("journal", "")).replace(".", "")
            j = JOURNAL_ALIAS.get(j, j)
            src = fold(s.get("source", "")).replace(".", "")
            if want and j and not (src.startswith(j) or j.startswith(src)):
                f.warn(where, f"journal {want['journal']!r} in reference, PubMed has {s.get('source')!r}")
            if "Retracted Publication" in (s.get("pubtype") or []):
                f.error(where, "publication is retracted")


def check_uniprot(comp: dict, f: Findings, refresh: bool) -> None:
    for s in comp["subunits"]:
        where = f"subunits[{s['symbol']}]"
        try:
            d = fetch(f"https://rest.uniprot.org/uniprotkb/{s['uniprot']}", refresh=refresh, cache_dir="verify",
                      params={"format": "json", "fields": "accession,gene_primary,organism_id,length,reviewed"})
        except Exception as e:  # noqa: BLE001 - report, keep checking the rest
            f.error(where, f"UniProt {s['uniprot']}: {e}")
            continue
        if d.get("entryType", "").startswith("Inactive"):
            f.error(where, f"UniProt {s['uniprot']} is inactive/obsolete")
            continue
        if "Swiss-Prot" not in d.get("entryType", ""):
            f.error(where, f"UniProt {s['uniprot']} is not reviewed (Swiss-Prot)")
        if d.get("organism", {}).get("taxonId") != 9606:
            f.error(where, f"UniProt {s['uniprot']} is not human")
        genes = [g.get("geneName", {}).get("value") for g in d.get("genes", [])]
        if s["symbol"] not in genes:
            f.error(where, f"UniProt {s['uniprot']} primary gene is {genes}, not {s['symbol']}")
        length = d.get("sequence", {}).get("length")
        if s.get("uniprot_length") and length != s["uniprot_length"]:
            f.error(where, f"length {s['uniprot_length']} in YAML, UniProt has {length}")


def check_hgnc(comp: dict, f: Findings, refresh: bool) -> None:
    for s in comp["subunits"]:
        where = f"subunits[{s['symbol']}]"
        d = fetch(f"https://rest.genenames.org/fetch/hgnc_id/{s['hgnc_id']}", refresh=refresh, cache_dir="verify",
                  headers={"Accept": "application/json"})
        docs = d.get("response", {}).get("docs", [])
        if not docs:
            f.error(where, f"{s['hgnc_id']} not found in HGNC")
            continue
        h = docs[0]
        if h.get("status") != "Approved":
            f.error(where, f"{s['hgnc_id']} status is {h.get('status')}")
        if h.get("symbol") != s["symbol"]:
            f.error(where, f"{s['hgnc_id']} approved symbol is {h.get('symbol')}, not {s['symbol']}")
        if s["uniprot"] not in (h.get("uniprot_ids") or []):
            f.error(where, f"HGNC does not cross-reference {s['uniprot']} (has {h.get('uniprot_ids')})")
        prev = set(h.get("prev_symbol") or [])
        if set(s.get("previous_symbols") or []) - prev:
            f.warn(where, f"previous_symbols {sorted(set(s['previous_symbols']) - prev)} not in HGNC {sorted(prev)}")


def check_structures(comp: dict, f: Findings, refresh: bool) -> None:
    for cid, c in comp["complexes"].items():
        for st in c.get("structures", []):
            where = f"complexes.{cid}.structures[{st['pdb']}]"
            try:
                d = fetch(f"https://data.rcsb.org/rest/v1/core/entry/{st['pdb']}", refresh=refresh, cache_dir="verify")
            except Exception as e:  # noqa: BLE001
                f.error(where, f"RCSB entry not found: {e}")
                continue
            cit = d.get("rcsb_primary_citation") or {}
            pm = str(cit.get("pdbx_database_id_pub_med") or "")
            cited = f.pubmed.get(str(st.get("pmid")), {})
            cited_doi = next((a["value"] for a in cited.get("articleids", []) if a.get("idtype") == "doi"), "")
            rdoi = cit.get("pdbx_database_id_doi") or ""
            desc = f"{(cit.get('rcsb_authors') or ['?'])[0]} {cit.get('year')}: {cit.get('title', '')[:70]!r}"
            if pm:
                if pm == str(st.get("pmid")):
                    f.ok.append(f"{where}: PMID matches RCSB primary citation")
                else:
                    f.error(where, f"cited PMID {st.get('pmid')}, RCSB primary citation is PMID {pm} ({desc})")
            elif rdoi and cited_doi:
                if rdoi.lower() == cited_doi.lower():
                    f.ok.append(f"{where}: DOI {rdoi} matches cited PMID {st.get('pmid')}")
                else:
                    f.error(where, f"cited PMID {st.get('pmid')} has DOI {cited_doi}; RCSB primary citation DOI "
                                   f"is {rdoi} ({desc})")
            else:
                # no shared identifier: fall back to title similarity
                r = difflib.SequenceMatcher(None, fold(cit.get("title", "")), fold(cited.get("title", ""))).ratio()
                if r >= 0.9:
                    f.ok.append(f"{where}: title matches cited PMID {st.get('pmid')} (similarity {r:.2f})")
                else:
                    f.warn(where, f"cannot confirm pairing: RCSB citation {desc} (no PMID/DOI); "
                                  f"cited PMID {st.get('pmid')} title {cited.get('title', '')[:70]!r} (similarity {r:.2f})")


def check_affinage(comp: dict, f: Findings, refresh: bool) -> None:
    import requests
    from .common import BROWSER_UA
    for s in comp["subunits"]:
        url = f"https://affinage.wi.mit.edu/api/gene/{s['symbol']}"
        try:
            r = requests.get(url, timeout=60, headers={"User-Agent": BROWSER_UA})
            ok = r.status_code == 200 and r.json().get("gene") == s["symbol"]
        except Exception as e:  # noqa: BLE001
            f.warn(f"subunits[{s['symbol']}]", f"Affinage check failed: {e}")
            continue
        if not ok:
            f.warn(f"subunits[{s['symbol']}]", f"no Affinage entry (HTTP {r.status_code}); the site's link would 404")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--offline", action="store_true", help="internal consistency checks only")
    g.add_argument("--cached", action="store_true", help="reuse cached API responses")
    args = ap.parse_args(argv)

    comp = yaml.safe_load(open(CURATED / "composition.yaml"))
    f = Findings()
    check_internal(comp, f)
    if not args.offline:
        refresh = not args.cached
        for name, check in [("PubMed", check_pubmed), ("UniProt", check_uniprot), ("HGNC", check_hgnc),
                            ("RCSB", check_structures), ("Affinage", check_affinage)]:
            print(f"checking {name}…", flush=True)
            check(comp, f, refresh)

    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps({"version": str(comp["version"]), "live": not args.offline,
                                  "errors": f.errors, "warnings": f.warnings, "needs_review": f.review}, indent=1))
    for msg in f.ok:
        print(f"ok      {msg}")
    for label, items in (("ERROR", f.errors), ("warning", f.warnings)):
        for it in items:
            print(f"{label:7} {it['where']}: {it['msg']}")
    print(f"needs_review ({len(f.review)}):")
    for r in f.review:
        print(f"        {r}")
    print(f"{len(f.errors)} errors, {len(f.warnings)} warnings, {len(f.review)} awaiting curator review "
          f"-> {REPORT.relative_to(ROOT)}")
    return 1 if f.errors else 0


if __name__ == "__main__":
    sys.exit(main())
