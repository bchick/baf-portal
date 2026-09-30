"""Data contract on the last `pixi run build-data` output (skips if absent).

Anchors from the plan's verification section, plus regressions found while
building Phase 0.
"""
import pytest

ANCHORS = ["SMARCA4", "SMARCB1", "ARID1B"]     # genes the plan's anchor tests name
BLOCKED = ("cosmic", "oncokb", "genie", "hgmd", "revel", "cadd")


def variant(g, p):
    return next(v for v in g["variants"] if v.get("p") == p)


def test_smarca4_r1192h_anchor(built):
    v = variant(built.gene("SMARCA4"), "p.Arg1192His")
    assert v["pos"] == 1192 and v["mane"] == "p.Arg1192His"
    assert v["g"] == "NC_000019.10:g.11033318G>A"


def test_smarcb1_r37h_is_curated_to_the_plan_pmids(built):
    v = variant(built.gene("SMARCB1"), "p.Arg37His")
    tier1 = {c["pmid"] for c in v["cit"] if c["t"] == 1 and c["src"] == "UniProt"}
    assert {"22726846", "29907796"} <= tier1


def test_arid1b_mane_and_uniprot_numbering_differ_after_1115(built):
    g = built.gene("ARID1B")
    assert g["projection"]["alignment"]["identical"] is False
    shifted = [v for v in g["variants"] if v.get("mane_pos") and v["mane_pos"] >= 1169]
    assert shifted and all(v["mane_pos"] - v["pos"] == 53 for v in shifted)
    assert all(v["mane_pos"] == v["pos"] for v in g["variants"] if v.get("mane_pos") and v["mane_pos"] <= 1115)


def test_every_reference_residue_matches_uniprot(built):
    for gene in built.genes():
        g = built.gene(gene)
        seq = g["uniprot"]["sequence"]
        for v in g["variants"]:
            if v.get("ref") and v["ref"] not in ("-", "*") and len(v["ref"]) == 1 and v.get("p"):
                assert seq[v["pos"] - 1] == v["ref"], v["k"]
        for v in built.tcga(gene)["variants"]:
            if v.get("ref") and len(v["ref"]) == 1 and v["ref"] not in ("-", "*"):
                assert seq[v["pos"] - 1] == v["ref"], v["k"]


def test_arid1b_exon1_variants_are_present(built):
    """Regression: ClinVar single_gene[prop] once dropped almost all of these."""
    n = sum(1 for v in built.gene("ARID1B")["variants"] if v["pos"] <= 200)
    assert n >= 100


def test_citations_are_well_formed(built):
    for gene in built.genes():
        allowed = {1: {"UniProt", "CIViC", "ClinVar expert panel", "ClinVar practice guideline"}, 2: {"ClinVar"},
                   3: {"LitVar2"}}
        for v in built.gene(gene)["variants"]:
            for c in v["cit"]:
                assert c["src"] in allowed[c["t"]], (v["k"], c)
                assert c["pmid"].isdigit()
                if c["t"] == 2:
                    assert c["s"] >= 1 and c.get("sub")
                if c["t"] == 3:
                    assert c["basis"] in {"rsID", "protein (ref-checked)"}
            higher = {c["pmid"] for c in v["cit"] if c["t"] < 3}
            assert not higher & {c["pmid"] for c in v["cit"] if c["t"] == 3}, v["k"]


def test_every_cited_pmid_is_resolved(built):
    for gene in built.genes():
        refs = built.refs(gene)
        cited = {c["pmid"] for v in built.gene(gene)["variants"] for c in v["cit"]}
        cited |= {e["pmid"] for e in built.gene(gene).get("civic", [])}
        missing = cited - set(refs)
        assert len(missing) <= 0.01 * len(cited), sorted(missing)[:10]


def test_no_licence_blocked_sources_in_output(built):
    for gene in built.genes():
        g = built.gene(gene)
        for v in g["variants"]:
            for c in v["cit"]:
                assert not any(b in c["src"].lower() for b in BLOCKED)
        for f in g["features"]:
            assert not any(b in str(f.get("ev", "")).lower() for b in BLOCKED)


def test_retracted_cohort_paper_is_flagged(built):
    assert built.refs()["32214244"]["retracted"] is True


def test_upfront_refs_stay_small(built):
    assert (built.path / "refs.json").stat().st_size < 100_000


def test_every_curated_subunit_was_built(built):
    import yaml
    from pipeline.common import CURATED
    if built.manifest().get("partial"):
        pytest.skip("partial build (BAF_GENES was set)")
    curated = {s["symbol"] for s in yaml.safe_load(open(CURATED / "composition.yaml"))["subunits"]}
    assert not curated - set(built.genes()), sorted(curated - set(built.genes()))


def test_tcga_counts_are_per_patient(built):
    for gene in built.genes():
        t = built.tcga(gene)
        assert t["counting"]["unit"] == "patient"
        assert 0 <= t["k"] < t["n"]
        assert t["k"] <= sum(s["k"] for s in t["per_study"].values())
        assert t["n"] >= max(s["n"] for s in t["per_study"].values())
