"""Phase 0 build: fetch -> project -> validate -> emit site/public/data/v<date>/.

    pixi run build-data            # uses data/cache/ where present
    BAF_REFRESH=1 pixi run build-data   # ignore the cache

Fails (exit 1) if any variant's reference residue disagrees with UniProt
canonical, unless BAF_ALLOW_MISMATCH=1. Mismatches and unmappable variants
are always written to reports/projection_<GENE>.tsv.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from collections import Counter, defaultdict

import yaml

from . import fetch_cbioportal as cbio
from . import fetch_clinvar as clinvar
from . import fetch_interpro as interpro
from . import fetch_uniprot as uniprot
from . import project_coords as pc
from . import refs as refs_mod
from .common import CURATED, GENES, ROOT, SITE_DATA, write_json
from .filters import drop_blocked, strip_omim

# cBioPortal mutation types counted as protein-affecting (gene-level k/n).
CBIO_COUNTED = {"Missense_Mutation", "Nonsense_Mutation", "Frame_Shift_Del", "Frame_Shift_Ins",
                "In_Frame_Del", "In_Frame_Ins", "Splice_Site", "Nonstop_Mutation",
                "Translation_Start_Site"}
SHOWN = {"missense", "truncating", "inframe", "splice", "stop_lost"}
MAX_INDEL = 100
FAIL_STATUSES = {"ref_mismatch", "mane_ref_mismatch", "crosscheck_mismatch"}


def one_letter(r) -> str | None:
    if r.get("class") == "missense" and len(r["ref"]) == 1 and len(r["alt"]) == 1:
        return f"{r['ref']}{r['u_pos']}{r['alt']}"
    return None


def small_spdi(spdi: str | None) -> bool:
    if not spdi:
        return False
    parts = spdi.split(":")
    return len(parts) == 4 and len(parts[2]) + len(parts[3]) <= MAX_INDEL


def build_gene(gene: str, acc: str, version: str, report_rows: list) -> tuple[dict, dict, set, dict]:
    print(f"[{gene}] UniProt {acc}", flush=True)
    entry = uniprot.fetch_entry(acc)
    entry["features"] = drop_blocked(entry["features"])
    domains = interpro.fetch_domains(acc)
    proj = pc.GeneProjector(gene, acc, entry["sequence"])

    print(f"[{gene}] ClinVar", flush=True)
    cv = clinvar.fetch_gene(gene)
    cv_small = [r for r in cv if small_spdi(r["spdi"])]
    cv_hgvs = {r["variation_id"]: pc.spdi_to_hgvs(r["spdi"]) for r in cv_small}

    print(f"[{gene}] cBioPortal TCGA PanCancer Atlas", flush=True)
    cb = cbio.fetch_gene(gene)
    muts = [m for m in cb["mutations"] if m["mutationType"] in CBIO_COUNTED]
    maf_hgvs = {}
    for m in muts:
        k = cbio.maf_key(m)
        if k not in maf_hgvs:
            maf_hgvs[k] = pc.maf_to_hgvs38(m)

    print(f"[{gene}] VEP ({len(set(cv_hgvs.values()) | set(maf_hgvs.values()))} inputs)", flush=True)
    ann = pc.vep([h for h in list(cv_hgvs.values()) + list(maf_hgvs.values()) if h])

    variants: dict[str, dict] = {}
    stats = Counter()

    def project(h, source, label):
        v = ann.get(h) if h else None
        if v is None:
            stats[f"{source}:unannotated"] += 1
            report_rows.append([gene, source, label, h or "", "unannotated", ""])
            return None, None
        res = proj.project(v)
        stats[f"{source}:{res['status']}"] += 1
        if res["status"] != "ok":
            if res["status"] not in ("noncoding",):
                report_rows.append([gene, source, label, h, res["status"],
                                    res.get("detail", "") or res.get("mane_hgvsp", "") or ""])
            return None, res
        return pc.vep_key(v), res

    def record(key, h, res):
        if key not in variants:
            variants[key] = {"k": key, "g": h, "pos": res["u_pos"], "end": res["u_end"],
                             "ref": res["ref"], "alt": res["alt"], "cls": res["class"],
                             "csq": res["consequence"], "p": res.get("u_hgvsp"),
                             "mane": res.get("mane_hgvsp"), "c": res.get("mane_hgvsc"),
                             "mane_pos": res["mane_pos"], "cit": []}
        return variants[key]

    # ClinVar
    for r in cv_small:
        h = cv_hgvs[r["variation_id"]]
        key, res = project(h, "clinvar", r["vcv"])
        if not key or res["class"] not in SHOWN:
            continue
        rec = record(key, h, res)
        rec["spdi"] = r["spdi"]
        if r["rs"]:
            rec["rs"] = r["rs"]
        g = r["germline"]
        rec["cv"] = {"id": r["variation_id"], "vcv": r["vcv"], "title": r["title"],
                     "pc": r["clinvar_protein_change"],
                     "germ": ({"c": g["class"], "s": g["stars"], "r": g["review"], "d": g["last_evaluated"],
                               "cond": strip_omim(g["conditions"])} if g else None),
                     "som": ({"c": r["somatic_impact"]["class"], "s": r["somatic_impact"]["stars"],
                              "cond": strip_omim(r["somatic_impact"]["conditions"])} if r["somatic_impact"] else None),
                     "onc": ({"c": r["oncogenicity"]["class"], "s": r["oncogenicity"]["stars"]}
                             if r["oncogenicity"] else None)}

    # TCGA (ODbL, kept in a separate file)
    tcga_by_key: dict[str, dict] = {}
    for m in muts:
        mk = cbio.maf_key(m)
        h = maf_hgvs[mk]
        key, res = project(h, "tcga", f"{m['sampleId']} {m['proteinChange']}")
        if not key:
            continue
        t = tcga_by_key.setdefault(key, {"k": key, "g": h, "pos": res["u_pos"], "end": res["u_end"],
                                         "ref": res["ref"], "alt": res["alt"], "cls": res["class"],
                                         "p": res.get("u_hgvsp"), "mane": res.get("mane_hgvsp"),
                                         "patients": set(), "studies": defaultdict(set),
                                         "cbio_pc": set(), "cbio_type": set()})
        t["patients"].add(m["patientId"])
        t["studies"][m["studyId"]].add(m["patientId"])
        t["cbio_pc"].add(m["proteinChange"])
        t["cbio_type"].add(m["mutationType"])

    # UniProt natural variants: tier-1 citations + standalone records
    pmids: set[str] = set()
    up_vars = [f for f in entry["features"] if f["type"] == "Natural variant"]
    for f in up_vars:
        cur = uniprot.curated_pmids(f)
        pmids.update(cur)
        if f["start"] != f["end"] or len(f.get("ref", "")) != 1 or len(f.get("alt", "")) != 1:
            stats["uniprot:complex_variant"] += 1
        try:
            pc.assert_ref(entry["sequence"], f["start"], f.get("ref", ""))
        except pc.RefMismatch as e:
            report_rows.append([gene, "uniprot", f.get("id", ""), "", "ref_mismatch", str(e)])
            stats["uniprot:ref_mismatch"] += 1
            continue
        matches = [v for v in variants.values() if v["pos"] == f["start"] and v["ref"] == f.get("ref")
                   and v["alt"] == f.get("alt")]
        if f.get("rs"):
            rs_match = [v for v in matches if v.get("rs") == f["rs"].replace("rs", "")]
            matches = rs_match or matches
        up = {"id": f.get("id"), "desc": f["desc"], "rs": f.get("rs")}
        cits = [{"t": 1, "pmid": p, "src": "UniProt", "eco": "ECO:0000269"} for p in cur]
        if matches:
            stats["uniprot:matched"] += 1
            for v in matches:
                v["up"] = up
                v["cit"].extend(cits)
        else:
            stats["uniprot:standalone"] += 1
            key = f"uniprot:{f.get('id')}"
            variants[key] = {"k": key, "pos": f["start"], "end": f["end"], "ref": f.get("ref"),
                             "alt": f.get("alt"), "cls": "missense" if len(f.get("alt", "")) == 1 else "other",
                             "p": None, "up": up, "cit": cits}
    # ClinVar submitter citations (tier 2: SCVs with >=1 star)
    cited = clinvar.var_citations({v["cv"]["id"] for v in variants.values() if "cv" in v})
    scv = clinvar.scv_citations([vid for vid in cited]) if cited else {}
    for v in variants.values():
        if "cv" not in v:
            continue
        for a in scv.get(v["cv"]["id"], []):
            if a["stars"] < 1:
                continue
            for p in a["pmids"]:
                pmids.add(p)
                v["cit"].append({"t": 2, "pmid": p, "src": "ClinVar", "sub": a["submitter"],
                                 "scv": a["scv"], "s": a["stars"], "cls": a["class"]})
    for v in variants.values():  # de-duplicate citations per (tier, pmid, submitter)
        seen, keep = set(), []
        for c in v["cit"]:
            k = (c["t"], c["pmid"], c.get("sub"))
            if k not in seen:
                seen.add(k)
                keep.append(c)
        v["cit"] = sorted(keep, key=lambda c: (c["t"], c["pmid"]))

    # gene-level TCGA k/n (per patient, deduplicated across studies)
    profiled, mutated, per_study = set(), set(), {}
    counted_patients = {m["patientId"] for m in muts}
    for sid, s in cb["studies"].items():
        prof = set(s["profiled"])
        mut = {p for p in s["mutated"] if p in counted_patients}
        profiled |= prof
        mutated |= mut
        per_study[sid] = {"name": s["name"], "cancer_type": s["cancer_type"], "k": len(mut), "n": len(prof),
                          "pmids": s["pmids"], "citation": s["citation"]}
        pmids.update(s["pmids"][:1])
    tcga_vars = []
    for t in sorted(tcga_by_key.values(), key=lambda x: (x["pos"], x["k"])):
        cbio_pc = sorted(t["cbio_pc"])
        ol = one_letter(t)
        tcga_vars.append({"k": t["k"], "g": t["g"], "pos": t["pos"], "end": t["end"], "ref": t["ref"],
                          "alt": t["alt"], "cls": t["cls"], "p": t["p"], "mane": t["mane"],
                          "n_pat": len(t["patients"]),
                          "studies": {s: len(p) for s, p in sorted(t["studies"].items())},
                          "cbio_pc": cbio_pc, "cbio_type": sorted(t["cbio_type"]),
                          "legacy_differs": bool(ol and any(x != ol for x in cbio_pc))})

    gene_json = {
        "gene": gene, "data_version": version,
        "uniprot": {k: entry[k] for k in ("accession", "entry_version", "sequence_version",
                                          "last_annotation_update", "protein_name", "length", "sequence")},
        "projection": proj.info(),
        "features": [f for f in entry["features"] if f["type"] != "Natural variant"],
        "domains": domains,
        "variants": sorted(variants.values(), key=lambda v: (v["pos"], v["k"])),
        "stats": dict(sorted(stats.items())),
    }
    odbl_json = {
        "gene": gene, "data_version": version, "license": "ODbL-1.0",
        "source": "cBioPortal public API, TCGA PanCancer Atlas 2018 (32 studies)",
        "counting": {"unit": "patient", "denominator": "patients with >=1 sample profiled for the gene",
                     "mutation_types": sorted(CBIO_COUNTED)},
        "k": len(mutated), "n": len(profiled), "per_study": per_study, "variants": tcga_vars,
    }
    cohort = {sid: {"name": s["name"], "citation": s["citation"], "pmids": s["pmids"]} for sid, s in cb["studies"].items()}
    return gene_json, odbl_json, pmids, cohort


def complexes_json(comp: dict) -> dict:
    # YAML parses an unquoted `version: 2026-09-29` as datetime.date.
    return {"version": str(comp["version"]),"complexes": comp["complexes"], "mouse_only": comp["mouse_only"],
            "subunits": {s["symbol"]: s for s in comp["subunits"]}, "references": comp["references"]}


def main() -> int:
    version = os.environ.get("BAF_DATA_VERSION", dt.date.today().isoformat())
    out = SITE_DATA / f"v{version}"
    odbl = SITE_DATA / "odbl" / f"v{version}"
    comp = yaml.safe_load(open(CURATED / "composition.yaml"))
    all_pmids = set(comp["references"])
    report = []
    genes_meta = {}
    cohort_all = {}
    for gene, acc in GENES.items():
        gj, oj, pm, cohort = build_gene(gene, acc, version, report)
        all_pmids |= pm
        cohort_all.update(cohort)
        write_json(out / f"{gene}.json", gj)
        write_json(odbl / f"{gene}.tcga.json", oj)
        genes_meta[gene] = {"uniprot": acc, "variants": len(gj["variants"]), "tcga_k": oj["k"],
                            "tcga_n": oj["n"], "stats": gj["stats"]}
        print(f"[{gene}] {len(gj['variants'])} variants; TCGA {oj['k']}/{oj['n']}; {gj['stats']}", flush=True)
    for s in cohort_all.values():
        all_pmids.update(s["pmids"])
    print(f"refs: resolving {len(all_pmids)} PMIDs", flush=True)
    refs = refs_mod.resolve(all_pmids)
    missing = sorted(all_pmids - set(refs), key=int)
    write_json(out / "refs.json", refs)
    write_json(out / "complexes.json", complexes_json(comp))
    write_json(odbl / "cohorts.json", cohort_all)
    manifest = {
        "data_version": version, "built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "genes": genes_meta,
        "sources": {
            "uniprot": {**uniprot.release(), "license": "CC BY 4.0"},
            "interpro": {**interpro.release(), "license": "CC0"},
            "clinvar": {**clinvar.release(), "license": "public domain (NCBI)"},
            "ensembl_vep": {**pc.ensembl_release(), "license": "Apache-2.0 / open"},
            "cbioportal": {**cbio.release(), "studies": "*_tcga_pan_can_atlas_2018", "license": "ODbL-1.0",
                           "path": f"odbl/v{version}/"},
            "pubmed": {"via": "NCBI ESummary", "resolved": len(refs), "unresolved": missing,
                       "retracted": sorted(p for p, r in refs.items() if r["retracted"])},
        },
    }
    write_json(out / "manifest.json", manifest, compact=False)
    write_json(SITE_DATA / "latest.json", {"version": version, "path": f"v{version}/", "odbl": f"odbl/v{version}/"},
               compact=False)
    rep = ROOT / "reports"
    rep.mkdir(exist_ok=True)
    by_gene = defaultdict(list)
    for r in report:
        by_gene[r[0]].append(r)
    for gene in GENES:
        with open(rep / f"projection_{gene}.tsv", "w") as fh:
            fh.write("gene\tsource\tlabel\thgvs_g_grch38\tstatus\tdetail\n")
            for r in sorted(by_gene[gene], key=lambda r: (r[4], r[1], r[2])):
                fh.write("\t".join(str(x) for x in r) + "\n")
    fails = [r for r in report if r[4] in FAIL_STATUSES]
    print(f"projection report: {len(report)} rows, {len(fails)} reference-residue failures")
    if fails and not os.environ.get("BAF_ALLOW_MISMATCH"):
        print("BUILD FAILED: reference residue mismatches (see reports/)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
