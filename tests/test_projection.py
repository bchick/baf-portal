"""Coordinate projection: the biggest accuracy risk in the plan."""
import random

import pytest

from pipeline import project_coords as pc
from pipeline.common import GENES

from .conftest import cached_or_skip

SEQ = "MSTPDPPLGG"
# non-periodic, so the alignment has exactly one correct answer
_rng = random.Random(7)
UNI = "".join(_rng.choice("ACDEFGHIKLMNPQRSTVY") for _ in range(60))
assert len(set(UNI)) > 10 and "W" not in UNI     # really non-periodic; W marks inserted residues


# ---- reference-residue assert ------------------------------------------------

def test_assert_ref_accepts_matching_residues():
    pc.assert_ref(SEQ, 1, "M")
    pc.assert_ref(SEQ, 3, "TPD")
    pc.assert_ref(SEQ, 11, "*")          # stop right after the last residue
    pc.assert_ref(SEQ, 5, "-")           # insertion: nothing to check


@pytest.mark.parametrize("pos,ref", [(2, "M"), (9, "GA"), (0, "M"), (11, "G"), (5, "*")])
def test_assert_ref_rejects_mismatch(pos, ref):
    with pytest.raises(pc.RefMismatch):
        pc.assert_ref(SEQ, pos, ref)


# ---- isoform alignment ---------------------------------------------------------

def test_alignment_identical_isoform_is_identity():
    aln = pc.Alignment(SEQ, SEQ)
    assert aln.identical and all(aln(i) == i for i in range(1, len(SEQ) + 1))
    assert aln(len(SEQ) + 1) == len(SEQ) + 1                    # stop codon


def test_alignment_maps_across_an_insertion_like_arid1b():
    """MANE has an extra exon (ARID1B: 53 residues) absent from UniProt."""
    uni = UNI
    src = uni[:30] + "W" * 10 + uni[30:]
    aln = pc.Alignment(src, uni)
    assert not aln.identical
    assert aln(30) == 30
    assert aln(31) is None                                      # inside the extra exon
    assert aln(41) == 31                                        # first residue after it
    assert aln(len(src)) == len(uni)


def test_renumber_hgvsp_through_alignment():
    uni = UNI
    src = uni[:30] + "W" * 10 + uni[30:]
    aln = pc.Alignment(src, uni)
    assert pc.renumber_hgvsp("ENSP1:p.Arg45His", aln) == "p.Arg35His"
    assert pc.renumber_hgvsp("p.Arg35_Lys36del", aln) is None   # 35/36 fall in the insertion


# ---- genomic inputs ------------------------------------------------------------------

@pytest.mark.parametrize("spdi,hgvs", [
    ("NC_000019.10:11033317:G:A", "NC_000019.10:g.11033318G>A"),
    ("NC_000019.10:100:AC:", "NC_000019.10:g.101_102del"),
    ("NC_000019.10:100:A:", "NC_000019.10:g.101del"),
    ("NC_000019.10:100::T", "NC_000019.10:g.100_101insT"),
    ("NC_000019.10:100:AC:GT", "NC_000019.10:g.101_102delinsGT"),
])
def test_spdi_to_hgvs(spdi, hgvs):
    assert pc.spdi_to_hgvs(spdi) == hgvs


def test_spdi_to_hgvs_rejects_malformed():
    assert pc.spdi_to_hgvs("not-an-spdi") is None


@pytest.mark.parametrize("terms,cls", [
    (["stop_gained"], "truncating"), (["frameshift_variant", "splice_region_variant"], "truncating"),
    (["splice_donor_variant"], "splice"), (["missense_variant"], "missense"),
    (["inframe_deletion"], "inframe"), (["stop_lost"], "stop_lost"),
    (["synonymous_variant"], "synonymous"), (["intron_variant"], "other"),
])
def test_classify(terms, cls):
    assert pc.classify(terms) == cls


# ---- GeneProjector on real (cached) transcripts ------------------------------------------

def _projector(gene, seq=None):
    from pipeline import fetch_uniprot
    entry = cached_or_skip(fetch_uniprot.fetch_entry, GENES[gene])
    return cached_or_skip(pc.GeneProjector, gene, GENES[gene], seq or entry["sequence"]), entry


def _vep(proj, pos, aa):
    """Minimal VEP record with one MANE consequence."""
    return {"transcript_consequences": [{
        "gene_id": proj.gene_id, "transcript_id": proj.mane["transcript"],
        "consequence_terms": ["missense_variant"], "protein_start": pos, "protein_end": pos,
        "amino_acids": aa}]}


def test_smarca4_mane_is_identical_to_uniprot(offline):
    proj, _ = _projector("SMARCA4")
    assert proj.aln.identical
    res = proj.project(_vep(proj, 1192, "R/H"))
    assert res["status"] == "ok" and res["u_pos"] == 1192


def test_arid1b_mane_position_maps_onto_uniprot(offline):
    """ARID1B MANE (2372 aa) carries 53 residues UniProt canonical (2319) lacks:
    MANE 1169 is UniProt 1116."""
    proj, entry = _projector("ARID1B")
    assert not proj.aln.identical
    assert len(proj.mane_seq) - len(entry["sequence"]) == 53
    ref = proj.mane_seq[1169 - 1]
    res = proj.project(_vep(proj, 1169, f"{ref}/A" if ref != "A" else "A/G"))
    assert res["status"] == "ok" and res["u_pos"] == 1116


def test_arid1b_residue_only_in_mane_is_not_forced_onto_uniprot(offline):
    proj, _ = _projector("ARID1B")
    ref = proj.mane_seq[1140 - 1]                       # inside the MANE-only exon
    res = proj.project(_vep(proj, 1140, f"{ref}/A" if ref != "A" else "A/G"))
    assert res["status"] == "not_in_canonical"


def test_ref_assert_fails_on_deliberately_wrong_isoform(offline):
    """Positions taken on the wrong isoform without realignment must fail.

    Simulated by projecting onto an isoform shifted by one residue while
    (wrongly) treating the numbering as identical."""
    proj, entry = _projector("SMARCA4")
    proj.useq = "M" + entry["sequence"]
    proj.aln = pc.Alignment(proj.mane_seq, proj.mane_seq)       # identity: no realignment
    proj.canonical_tx = []
    res = proj.project(_vep(proj, 1192, "R/H"))
    assert res["status"] == "ref_mismatch"


def test_copying_mane_numbering_onto_arid1b_uniprot_is_caught(offline):
    """Copying MANE positions past the 53-residue insertion onto UniProt
    canonical fails the reference check for almost every residue."""
    proj, entry = _projector("ARID1B")
    uni, fails, n = entry["sequence"], 0, 0
    for mane_pos in range(1169, len(proj.mane_seq) + 1, 7):
        n += 1
        try:
            pc.assert_ref(uni, mane_pos, proj.mane_seq[mane_pos - 1])
        except pc.RefMismatch:
            fails += 1
    assert fails / n > 0.85


def test_vep_ref_disagreeing_with_mane_translation_is_caught(offline):
    proj, _ = _projector("SMARCA4")
    res = proj.project(_vep(proj, 1192, "W/H"))          # residue 1192 is R, not W
    assert res["status"] == "mane_ref_mismatch"


# ---- UniProt variants numbered on a non-canonical isoform (e.g. DPF3 VAR_082912) --------

def _remap(monkeypatch, canonical, isoforms, f):
    from pipeline import build, fetch_uniprot
    monkeypatch.setattr(fetch_uniprot, "isoform_sequences", lambda acc: isoforms)
    return build.uniprot_isoform_remap("P0", canonical, f)


def test_isoform_numbered_variant_is_remapped_onto_canonical(monkeypatch):
    canonical = UNI
    iso = UNI[:20] + UNI[35:]                      # isoform lacking canonical 21-35
    # isoform position p == canonical p + 15; pick one where the stated residue
    # really disagrees with canonical at p (so the plain check fails)
    pos = next(p for p in range(21, 41) if canonical[p - 1] != iso[p - 1])
    f = {"start": pos, "end": pos, "ref": iso[pos - 1], "alt": "W"}
    status, g = _remap(monkeypatch, canonical, {"P0-2": iso}, f)
    assert status == "uniprot_isoform_remapped" and g["start"] == pos + 15
    assert g["remapped_from"] == f"P0-2:{pos}" and canonical[g["start"] - 1] == f["ref"]


def test_isoform_only_residue_is_excluded_not_forced(monkeypatch):
    iso = UNI[:40] + "WWWWWWWWWW"                  # isoform-specific C-terminus
    f = {"start": 45, "end": 45, "ref": "W", "alt": "A"}
    assert _remap(monkeypatch, UNI, {"P0-2": iso}, f) == ("uniprot_isoform_only", None)


def test_ambiguous_or_unexplained_mismatch(monkeypatch):
    f = {"start": 45, "end": 45, "ref": "W", "alt": "A"}
    two = {"P0-2": UNI[:44] + "W" + UNI[45:], "P0-3": UNI[:44] + "W" + UNI[45:50]}
    assert _remap(monkeypatch, UNI, two, f)[0] == "uniprot_isoform_ambiguous"
    assert _remap(monkeypatch, UNI, {"P0-2": UNI}, f) == ("ref_mismatch", None)   # still a build failure
