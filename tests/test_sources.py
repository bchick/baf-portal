"""Source-specific rules: licence filtering, patient counting, ClinVar query,
LitVar2 and CIViC matching."""
from pipeline import fetch_cbioportal as cbio
from pipeline import fetch_civic as civic
from pipeline import fetch_clinvar as clinvar
from pipeline import fetch_litvar as litvar
from pipeline.filters import drop_blocked, is_blocked, strip_omim

SEQ = "MRSTPDRRLGG"          # R2, R7, R8


# ---- licence filter (plan: EBI Proteins / myvariant.info mix COSMIC rows in) --------

def test_cosmic_and_other_licensed_rows_are_dropped():
    rows = [
        {"type": "Natural variant", "xrefs": [{"name": "ClinVar", "id": "RCV000001"}]},
        {"type": "Natural variant", "xrefs": [{"name": "cosmic curated", "id": "COSV123"}]},
        {"source": "OncoKB", "alteration": "R1192H"},
        {"db": "HGMD", "id": "CM000001"},
        {"score": {"REVEL": 0.9}},
    ]
    kept = drop_blocked(rows)
    assert kept == rows[:1]
    assert not is_blocked({"desc": "in CSS4", "ev": [{"eco": "ECO:0000269", "src": "PubMed"}]})


def test_strip_omim_keeps_open_identifiers_only():
    out = strip_omim([{"name": "Coffin-Siris syndrome", "mondo": "MONDO:0015452", "omim": "135900"}])
    assert out == [{"name": "Coffin-Siris syndrome", "mondo": "MONDO:0015452"}]


# ---- TCGA patient counting (plan: count per patient, dedupe across studies) --------

def _maf(patient, sample, study, pos=11033318):
    return {"patientId": patient, "sampleId": sample, "studyId": study, "ncbiBuild": "GRCh37", "chr": "19",
            "startPosition": pos, "endPosition": pos, "referenceAllele": "G", "variantAllele": "A"}


def test_patient_in_two_studies_and_two_samples_counts_once():
    muts = [_maf("TCGA-AB-0001", "TCGA-AB-0001-01", "luad_tcga_pan_can_atlas_2018"),
            _maf("TCGA-AB-0001", "TCGA-AB-0001-06", "luad_tcga_pan_can_atlas_2018"),
            _maf("TCGA-AB-0001", "TCGA-AB-0001-01", "lusc_tcga_pan_can_atlas_2018"),
            _maf("TCGA-CD-0002", "TCGA-CD-0002-01", "brca_tcga_pan_can_atlas_2018")]
    counts = cbio.count_patients(muts)
    assert len(counts) == 1
    assert counts[cbio.maf_key(muts[0])] == {"TCGA-AB-0001", "TCGA-CD-0002"}


def test_different_alleles_are_counted_separately():
    a, b = _maf("P1", "S1", "x"), _maf("P1", "S1", "x")
    b["variantAllele"] = "T"
    assert len(cbio.count_patients([a, b])) == 2


# ---- ClinVar: regression for the single_gene filter bug -------------------------------

def test_clinvar_keeps_variants_also_assigned_to_regulatory_loci(monkeypatch):
    """Exon-1 ARID1B variants list LOC... regulatory records as extra genes."""
    terms = []
    monkeypatch.setattr(clinvar, "fetch", lambda url, params=None, **k: terms.append(params["term"])
                        or {"esearchresult": {"idlist": ["1", "2", "3"]}})
    monkeypatch.setattr(clinvar, "summaries", lambda ids: [
        {"variation_id": "1", "genes": ["ARID1B"]},
        {"variation_id": "2", "genes": ["ARID1B", "LOC129997525"]},
        {"variation_id": "3", "genes": ["TMEM242"]},
    ])
    kept = clinvar.fetch_gene("ARID1B")
    assert [r["variation_id"] for r in kept] == ["1", "2"]
    assert terms == ["ARID1B[gene]"] and "single_gene" not in terms[0]


def test_clinvar_review_stars():
    assert clinvar.stars("reviewed by expert panel") == 3
    assert clinvar.stars("criteria provided, single submitter") == 1
    assert clinvar.stars("no assertion criteria provided") == 0


# ---- LitVar2 matching ------------------------------------------------------------------

def _v(k, pos, p, rs=None, mane=None):
    return {"k": k, "pos": pos, "p": p, "mane": mane or p, "rs": rs}


def _rec(_id, pmids, rsid=None, hgvs_prot=None):
    return {"_id": _id, "rsid": rsid, "hgvs_prot": hgvs_prot, "pmids": pmids}


def test_litvar_unique_rsid_matches(stats):
    vs = [_v("a", 2, "p.Arg2His", rs="111")]
    out = litvar.match([_rec("litvar@rs111##", [1, 2], rsid="rs111")], vs, SEQ, stats)
    assert [c["pmid"] for c in out["a"]] == ["1", "2"] and out["a"][0]["basis"] == "rsID"


def test_litvar_shared_rsid_needs_matching_protein_name(stats):
    vs = [_v("a", 2, "p.Arg2His", rs="111"), _v("b", 2, "p.Arg2Cys", rs="111")]
    out = litvar.match([_rec("x", [5], rsid="rs111", hgvs_prot="p.R2C")], vs, SEQ, stats)
    assert list(out) == ["b"]
    out = litvar.match([_rec("y", [6], rsid="rs111")], vs, SEQ, stats)        # no protein name
    assert out == {} and stats["litvar:rsid_ambiguous"] == 1


def test_litvar_protein_string_requires_reference_residue(stats):
    vs = [_v("a", 7, "p.Arg7Gln")]
    assert "a" in litvar.match([_rec("ok", [9], hgvs_prot="p.R7Q")], vs, SEQ, stats)
    # position 3 is S, not R: a text-mined 'R3Q' is from another isoform/gene
    assert litvar.match([_rec("bad", [9], hgvs_prot="p.R3Q")], [_v("c", 3, "p.Ser3Gln")], SEQ, stats) == {}


def test_litvar_protein_conflicting_numberings_are_rejected(stats):
    """UniProt p.Arg7Gln is one variant; MANE p.Arg7Gln is a different one."""
    vs = [_v("uni", 7, "p.Arg7Gln", mane="p.Arg60Gln"), _v("mane", 2, "p.Arg2Gln", mane="p.Arg7Gln")]
    assert litvar.match([_rec("z", [9], hgvs_prot="p.R7Q")], vs, SEQ, stats) == {}
    assert stats["litvar:protein_ambiguous"] == 1


def test_litvar_complex_protein_strings_are_not_guessed(stats):
    vs = [_v("a", 7, "p.Arg7fs")]
    assert litvar.match([_rec("fs", [9], hgvs_prot="p.R7fs")], vs, SEQ, stats) == {}
    assert stats["litvar:protein_unparsed"] == 1


# ---- CIViC ---------------------------------------------------------------------------

def _civic(variants, evidence):
    return {"variants": variants, "evidence": evidence}


EV = {"eid": "1", "pmid": "123", "type": "Diagnostic", "level": "B", "significance": "Positive",
      "disease": "Rhabdoid", "therapies": None, "url": "u"}


def test_civic_category_evidence_stays_gene_level(stats):
    c = _civic([{"name": "Loss", "mp": "10", "clinvar_ids": [], "url": "v"}], {"10": [EV]})
    per_variant, gene_level = civic.split(c, [_v("a", 7, "p.Arg7Gln")], stats)
    assert per_variant == {} and len(gene_level) == 1 and gene_level[0]["civic_variant"] == "Loss"


def test_civic_exact_variant_by_clinvar_id(stats):
    v = {**_v("a", 7, "p.Arg7Gln"), "cv": {"id": "555"}}
    c = _civic([{"name": "R7Q", "mp": "10", "clinvar_ids": ["555"], "url": "v"}], {"10": [EV]})
    per_variant, gene_level = civic.split(c, [v], stats)
    assert per_variant["a"][0]["basis"] == "ClinVar ID" and gene_level == []


def test_civic_protein_match_and_ambiguity(stats):
    c = _civic([{"name": "R7Q", "mp": "10", "clinvar_ids": [], "url": "v"}], {"10": [EV]})
    per_variant, _ = civic.split(c, [_v("a", 7, "p.Arg7Gln")], stats)
    assert per_variant["a"][0]["basis"] == "protein (ref-checked)"
    # UniProt and MANE numbering point at different variants -> not attached
    vs = [_v("a", 7, "p.Arg7Gln", mane="p.Arg60Gln"), _v("b", 2, "p.Arg2Gln", mane="p.Arg7Gln")]
    per_variant, gene_level = civic.split(c, vs, stats)
    assert per_variant == {} and len(gene_level) == 1


# ---- selective cache refresh (weekly CI keeps deterministic VEP results) ---------------

def test_refresh_is_per_cache_directory(monkeypatch):
    from pipeline.common import refreshing
    monkeypatch.delenv("BAF_REFRESH", raising=False)
    assert not refreshing("clinvar")
    monkeypatch.setenv("BAF_REFRESH", "clinvar, pubmed")
    assert refreshing("clinvar") and refreshing("pubmed") and not refreshing("vep")
    for everything in ("1", "all"):
        monkeypatch.setenv("BAF_REFRESH", everything)
        assert refreshing("vep")
    monkeypatch.setenv("BAF_REFRESH", "0")
    assert not refreshing("clinvar")
