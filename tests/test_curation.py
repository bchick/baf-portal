"""Curated composition checks, reference formatting, and 3D superposition."""
import copy
from collections import Counter

import numpy as np
import pytest
import yaml

from pipeline import refs as refs_mod
from pipeline import verify_composition as vc
from pipeline.bead_model import kabsch
from pipeline.common import CURATED


@pytest.fixture(scope="module")
def comp():
    return yaml.safe_load(open(CURATED / "composition.yaml"))


def test_composition_is_internally_consistent(comp):
    f = vc.Findings()
    vc.check_internal(comp, f)
    assert f.errors == []


def test_every_complex_membership_claim_has_a_pmid(comp):
    for cid, c in comp["complexes"].items():
        for sl in c["slots"]:
            assert sl.get("pmids"), f"{cid} {sl['slot']}"


def test_verify_catches_undefined_pmid_and_member_absent_overlap(comp):
    bad = copy.deepcopy(comp)
    bad["complexes"]["cBAF"]["slots"][0]["pmids"].append("99999999")
    bad["complexes"]["cBAF"]["absent"].append("SMARCA4")
    f = vc.Findings()
    vc.check_internal(bad, f)
    msgs = " | ".join(e["msg"] for e in f.errors)
    assert "99999999" in msgs and "both a member and absent" in msgs


def test_verify_catches_contested_without_notes(comp):
    bad = copy.deepcopy(comp)
    bad["complexes"]["cBAF"]["slots"][0]["contested"] = True
    f = vc.Findings()
    vc.check_internal(bad, f)
    assert any("contested without" in e["msg"] for e in f.errors)


def test_needs_review_items_are_listed(comp):
    f = vc.Findings()
    vc.check_internal(comp, f)
    assert any("mouse_only" in r for r in f.review)


@pytest.mark.parametrize("text,want", [
    ("Wang 1996 EMBO J — purification", {"surname": "Wang", "year": "1996", "journal": "EMBO J"}),
    ("Kadoch & Crabtree 2013 Cell — SS18-SSX", {"surname": "Kadoch", "year": "2013", "journal": "Cell"}),
    ("no year here", {}),
])
def test_parse_reference(text, want):
    assert vc.parse_reference(text) == want


def test_format_ref_flags_retraction():
    s = {"uid": "32214244", "sortfirstauthor": "Poore GD", "pubdate": "2020 Mar", "source": "Nature",
         "title": "Microbiome analyses.", "authors": [{"name": "Poore GD", "authtype": "Author"}],
         "articleids": [{"idtype": "doi", "value": "10.1038/x"}], "pubtype": ["Journal Article", "Retracted Publication"]}
    r = refs_mod.format_ref(s)
    assert r["retracted"] and r["year"] == "2020" and r["doi"] == "10.1038/x" and r["title"] == "Microbiome analyses"


def test_kabsch_recovers_a_rigid_transform_without_reflection():
    rng = np.random.default_rng(0)
    P = rng.normal(size=(50, 3)) * 20
    th = 0.7
    R0 = np.array([[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1]])
    Q = P @ R0.T + np.array([5.0, -3.0, 12.0])
    R, t = kabsch(P, Q)
    assert np.allclose(P @ R.T + t, Q, atol=1e-8)
    assert np.isclose(np.linalg.det(R), 1.0)
    M = Q * np.array([1, 1, -1])                     # mirror image: must not be matched by a reflection
    R, _ = kabsch(P, M)
    assert np.isclose(np.linalg.det(R), 1.0)


# ---- bead models: UniProt residue numbering used by the stage -> domain-map morph --------

MODELS = CURATED.parent.parent / "site" / "src" / "lib" / "models"


def _chain_res(model, symbol):
    import json
    m = json.loads((MODELS / f"{model}.json").read_text())
    idx = {i for i, c in enumerate(m["chains"]) if c["symbol"] == symbol}
    return m, [m["res"][k] for k in range(len(m["res"])) if m["beads"][4 * k + 3] in idx]


def test_every_bead_has_a_residue_slot():
    import json
    for name in ("cBAF", "PBAF", "ncBAF"):
        m = json.loads((MODELS / f"{name}.json").read_text())
        assert len(m["res"]) == len(m["beads"]) // 4


def test_subunit_chains_align_to_uniprot():
    import json
    for name in ("cBAF", "PBAF", "ncBAF"):
        m = json.loads((MODELS / f"{name}.json").read_text())
        for c in m["chains"]:
            if c["kind"] == "subunit":
                assert c["uniprot_coverage"] >= 0.9, (name, c["chain"], c["symbol"], c["uniprot_coverage"])


def test_smarcb1_construct_gap_is_not_numbered_through():
    """6LTJ's SMARCB1 construct skips UniProt 114-171: no bead may land there."""
    _, res = _chain_res("cBAF", "SMARCB1")
    mapped = [r for r in res if r]
    assert min(mapped) >= 1 and max(mapped) <= 385
    assert not [r for r in mapped if 114 <= r <= 171]


def test_pbrm1_maps_where_sifts_did_not():
    """SIFTS numbering for 7VDV PBRM1 matched UniProt at ~5%; alignment places it at the C-terminus."""
    _, res = _chain_res("PBAF", "PBRM1")
    assert res and all(1590 <= r <= 1681 for r in res)
