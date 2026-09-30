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
    flagged = copy.deepcopy(comp)
    flagged["complexes"]["PBAF"]["slots"][0]["contested_notes"][0]["needs_review"] = True
    f = vc.Findings()
    vc.check_internal(flagged, f)
    assert any("PBAF" in r and "contested_notes" in r for r in f.review)


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


# ---- 2D cartoons (pipeline/cartoon2d.py) ---------------------------------------------

CARTOONS = CURATED.parent.parent / "site" / "src" / "lib" / "cartoons"


def test_cartoons_cover_every_modelled_subunit_and_parse():
    import json
    import re
    for name in ("cBAF", "PBAF", "ncBAF"):
        text = (CARTOONS / f"{name}.json").read_text()
        assert "Infinity" not in text and "NaN" not in text
        c = json.loads(text)
        m = json.loads((MODELS / f"{name}.json").read_text())
        modelled = {ch["symbol"] for ch in m["chains"] if ch["kind"] == "subunit"}
        shown = {p["sym"] for p in c["pieces"] if p["sym"]}
        assert shown | set(c["hidden"]) == modelled, name
        x0, y0, size = c["frame"]
        for p in c["pieces"]:
            assert re.fullmatch(r"(M-?[\d.]+ -?[\d.]+(L-?[\d.]+ -?[\d.]+)+Z)+", p["d"]), (name, p["sym"])
            assert x0 <= p["anchor"][0] <= x0 + size and y0 <= p["anchor"][1] <= y0 + size
        assert [p["depth"] for p in c["pieces"]] == sorted(p["depth"] for p in c["pieces"])     # back to front
        placed = [g for g in m["ghosts"] if g.get("anchor_subunits")]
        assert len(c["ghosts"]) == len(placed) and len(c["ghosts_flat"]) == len(m["ghosts"]) - len(placed)


def test_cartoon_framing_matches_the_3d_front_view():
    """Same centre and radius as Complex3D, so the stage can cross-fade."""
    import json
    import numpy as np
    for name in ("cBAF", "PBAF", "ncBAF"):
        c = json.loads((CARTOONS / f"{name}.json").read_text())
        b = np.array(json.loads((MODELS / f"{name}.json").read_text())["beads"]).reshape(-1, 4)[:, :3]
        center = b.mean(0)
        d = np.sort(np.linalg.norm(b - center, axis=1))
        R = d[int(np.floor(0.99 * (len(d) - 1)))]
        assert np.allclose(c["center"], center[:2], atol=0.1)
        assert abs(c["frame"][2] - 2 * R / (0.94 * 1.02)) < 0.2


def test_shared_cartoon_frame_is_common_and_contains_every_complex():
    """'Same scale' mode: one frame for all complexes, so scale and nucleosome
    position match across cBAF, PBAF and ncBAF."""
    import json
    cs = [json.loads((CARTOONS / f"{n}.json").read_text()) for n in ("cBAF", "PBAF", "ncBAF")]
    shared = cs[0]["shared_frame"]
    assert all(c["shared_frame"] == shared for c in cs)
    sx, sy, ss = shared
    for c in cs:
        x, y, s = c["frame"]
        assert sx - 0.1 <= x and sy - 0.1 <= y and x + s <= sx + ss + 0.1 and y + s <= sy + ss + 0.1, c["complex"]


def test_placed_chains_carry_provenance_and_fit_well():
    import json
    for name in ("cBAF", "PBAF"):
        m = json.loads((MODELS / f"{name}.json").read_text())
        placed = [c for c in m["chains"] if c["tier"] == "placed"]
        assert [c["symbol"] for c in placed] == ["BCL7A"], name
        src = placed[0]["source"]
        assert src["pdb"] == "9WBZ" and src["rmsd"] <= 3.0 and src["fit_calpha"] >= 12
        assert src["calpha_clashes"] <= 10


def test_atom_files_match_their_models():
    import json
    for name in ("cBAF", "PBAF", "ncBAF"):
        m = json.loads((MODELS / f"{name}.json").read_text())
        buf = (MODELS / f"{name}.atoms.bin").read_bytes()
        n = int(np.frombuffer(buf[:4], "<u4")[0])
        assert len(buf) == 4 + 8 * n
        xyz = np.frombuffer(buf[4:4 + 6 * n], "<i2").reshape(-1, 3) / 10
        chain = np.frombuffer(buf[4 + 6 * n:4 + 7 * n], np.uint8)
        elem = np.frombuffer(buf[4 + 7 * n:], np.uint8)
        assert chain.max() < len(m["chains"]) and set(np.unique(elem)) <= {0, 1, 2}
        beads = np.array(m["beads"]).reshape(-1, 4)
        for i, c in enumerate(m["chains"]):       # atoms sit on their chain's residues
            a, b = xyz[chain == i], beads[beads[:, 3] == i, :3]
            assert len(a) >= len(b), (name, c["chain"])
            assert np.allclose(a.mean(0), b.mean(0), atol=4.0), (name, c["chain"])
