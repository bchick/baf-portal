"""Project genomic variants onto UniProt canonical coordinates.

Rule: every variant is keyed by its GRCh38 genomic HGVS/SPDI. Protein
positions are never copied from a source's `proteinChange` string. Instead:

1. genomic GRCh38 -> Ensembl VEP REST -> MANE Select transcript consequence
   (protein position, reference/alternate residues, HGVSp)
2. MANE protein -> UniProt canonical via a global sequence alignment of the two
   protein sequences (exact for identical isoforms, handles indels such as the
   53-residue ARID1B difference)
3. ASSERT the reference residue(s) at the projected position equal the UniProt
   canonical sequence. A mismatch is a build failure (RefMismatch) and is
   written to reports/projection_<GENE>.tsv.
4. If Ensembl has a transcript whose translation is identical to UniProt
   canonical (VEP `uniprot_isoform` == <ACC>-1), its protein_start is used as
   an independent cross-check of step 2.

GRCh37 inputs (TCGA via cBioPortal) are first lifted to GRCh38 with the
Ensembl assembly-mapping endpoint and then take the same path.
"""
from __future__ import annotations

import difflib
import re

import requests

from .common import chunks, fetch

ENSEMBL = "https://rest.ensembl.org"
AA3 = {"A": "Ala", "R": "Arg", "N": "Asn", "D": "Asp", "C": "Cys", "Q": "Gln", "E": "Glu",
       "G": "Gly", "H": "His", "I": "Ile", "L": "Leu", "K": "Lys", "M": "Met", "F": "Phe",
       "P": "Pro", "S": "Ser", "T": "Thr", "W": "Trp", "Y": "Tyr", "V": "Val", "*": "Ter",
       "X": "Xaa", "U": "Sec"}

TRUNCATING = {"stop_gained", "frameshift_variant", "splice_acceptor_variant",
              "splice_donor_variant", "start_lost"}


class RefMismatch(AssertionError):
    pass


# ---------------------------------------------------------------- sequences

def gene_transcripts(symbol: str) -> dict:
    """MANE Select transcript/translation for a gene (Ensembl lookup)."""
    d = fetch(f"{ENSEMBL}/lookup/symbol/homo_sapiens/{symbol}", params={"expand": 1, "mane": 1},
              cache_dir="ensembl")
    out = {"gene_id": d["id"], "transcripts": {}}
    for t in d["Transcript"]:
        tr = t.get("Translation")
        if not tr:
            continue
        out["transcripts"][t["id"]] = {"protein_id": tr["id"], "length": tr["length"],
                                       "mane": [(m["type"], m["refseq_match"]) for m in t.get("MANE", [])]}
        for m in t.get("MANE", []):
            if m["type"] == "MANE_Select":
                out["mane_select"] = {"transcript": t["id"], "protein_id": tr["id"],
                                      "refseq": m["refseq_match"], "length": tr["length"]}
    return out


def protein_seq(ensp: str) -> str:
    d = fetch(f"{ENSEMBL}/sequence/id/{ensp}", params={"type": "protein"}, cache_dir="ensembl")
    return d["seq"]


def ensembl_release() -> dict:
    d = fetch(f"{ENSEMBL}/info/data", cache_dir="ensembl")
    s = fetch(f"{ENSEMBL}/info/software", cache_dir="ensembl")
    return {"data_release": d.get("releases"), "software": s.get("release")}


# ---------------------------------------------------------------- alignment

class Alignment:
    """Residue map from a transcript translation (1-based) to UniProt (1-based)."""

    def __init__(self, src: str, uniprot: str):
        self.src, self.uni = src, uniprot
        self.map: dict[int, int] = {}
        sm = difflib.SequenceMatcher(None, src, uniprot, autojunk=False)
        for a, b, n in sm.get_matching_blocks():
            for k in range(n):
                self.map[a + k + 1] = b + k + 1
        self.identical = src == uniprot
        self.blocks = [(a + 1, b + 1, n) for a, b, n in sm.get_matching_blocks() if n]

    def __call__(self, pos: int) -> int | None:
        if pos == len(self.src) + 1:          # stop codon position
            return len(self.uni) + 1
        return self.map.get(pos)

    def summary(self) -> dict:
        return {"src_len": len(self.src), "uniprot_len": len(self.uni), "identical": self.identical,
                "mapped_residues": len(self.map), "blocks": self.blocks}


def assert_ref(uniprot_seq: str, pos: int, ref: str) -> None:
    """Assert the reference residue(s) `ref` start at UniProt position `pos`."""
    if not ref or ref == "-":
        return
    for i, aa in enumerate(ref):
        p = pos + i
        if aa == "*":
            if p != len(uniprot_seq) + 1:
                raise RefMismatch(f"stop expected at {p}, sequence length {len(uniprot_seq)}")
            continue
        if p < 1 or p > len(uniprot_seq) or uniprot_seq[p - 1] != aa:
            got = uniprot_seq[p - 1] if 1 <= p <= len(uniprot_seq) else "out-of-range"
            raise RefMismatch(f"reference {aa}{p} expected, UniProt has {got}")


# ---------------------------------------------------------------- genomic inputs

def spdi_to_hgvs(spdi: str) -> str | None:
    """ClinVar canonical SPDI (0-based, full deletion/insertion) -> genomic HGVS."""
    try:
        acc, pos0, dele, ins = spdi.split(":")
    except ValueError:
        return None
    pos0 = int(pos0)
    if len(dele) == 1 and len(ins) == 1:
        return f"{acc}:g.{pos0 + 1}{dele}>{ins}"
    if not dele:
        return f"{acc}:g.{pos0}_{pos0 + 1}ins{ins}"
    s, e = pos0 + 1, pos0 + len(dele)
    rng = f"{s}" if s == e else f"{s}_{e}"
    if not ins:
        return f"{acc}:g.{rng}del"
    return f"{acc}:g.{rng}delins{ins}"


CHR38 = {"1": "NC_000001.11", "2": "NC_000002.12", "3": "NC_000003.12", "4": "NC_000004.12",
         "5": "NC_000005.10", "6": "NC_000006.12", "7": "NC_000007.14", "8": "NC_000008.11",
         "9": "NC_000009.12", "10": "NC_000010.11", "11": "NC_000011.10", "12": "NC_000012.12",
         "13": "NC_000013.11", "14": "NC_000014.9", "15": "NC_000015.10", "16": "NC_000016.10",
         "17": "NC_000017.11", "18": "NC_000018.10", "19": "NC_000019.10", "20": "NC_000020.11",
         "21": "NC_000021.9", "22": "NC_000022.11", "X": "NC_000023.11", "Y": "NC_000024.10"}


# GRCh37 gene spans (padded) used to fetch assembly-mapping blocks once per
# region instead of once per variant (the per-variant endpoint takes ~20 s).
_BLOCKS: dict[tuple[str, int, int], list] = {}


def _region_blocks(chrom: str, pos: int) -> list:
    win = 250_000
    lo = (pos // win) * win + 1
    key = (chrom, lo, lo + win - 1)
    if key not in _BLOCKS:
        d = fetch(f"{ENSEMBL}/map/human/GRCh37/{chrom}:{key[1]}..{key[2]}:1/GRCh38",
                  cache_dir="ensembl_map")
        _BLOCKS[key] = [(m["original"]["start"], m["original"]["end"], m["mapped"]["start"],
                         m["mapped"]["end"], m["mapped"]["strand"], m["mapped"]["seq_region_name"])
                        for m in d.get("mappings", [])]
    return _BLOCKS[key]


def _lift_pos(chrom: str, pos: int) -> int | None:
    for os_, oe, ms, me, strand, seq in _region_blocks(chrom, pos):
        if os_ <= pos <= oe and strand == 1 and seq == chrom and (oe - os_) == (me - ms):
            return ms + (pos - os_)
    return None


def liftover_37_38(chrom: str, start: int, end: int) -> tuple[int, int] | None:
    """Lift a GRCh37 interval; None unless both ends map colinearly."""
    s, e = _lift_pos(chrom, start), _lift_pos(chrom, end)
    if s is None or e is None or (e - s) != (end - start):
        return None
    return s, e


def maf_to_hgvs38(m: dict) -> str | None:
    """cBioPortal (MAF-style, GRCh37) mutation -> GRCh38 genomic HGVS."""
    chrom = str(m["chr"]).replace("chr", "")
    s, e = int(m["startPosition"]), int(m["endPosition"])
    ref, alt = m["referenceAllele"], m["variantAllele"]
    if m.get("ncbiBuild") not in ("GRCh37", "hg19", "37"):
        lifted = (s, e)
    else:
        lifted = liftover_37_38(chrom, s, e)
    if not lifted or chrom not in CHR38:
        return None
    s, e = lifted
    acc = CHR38[chrom]
    if ref == "-":
        return f"{acc}:g.{s}_{e}ins{alt}"
    if alt == "-":
        return f"{acc}:g.{s}del" if s == e else f"{acc}:g.{s}_{e}del"
    if len(ref) == 1 and len(alt) == 1:
        return f"{acc}:g.{s}{ref}>{alt}"
    return f"{acc}:g.{s}_{e}delins{alt}"


# ---------------------------------------------------------------- VEP

VEP_OPTS = {"uniprot": 1, "mane": 1, "canonical": 1, "hgvs": 1, "protein": 1,
            "shift_3prime": 1, "shift_genomic": 1}


def vep(hgvs: list[str]) -> dict[str, dict]:
    """Annotate genomic HGVS strings with VEP; returns input -> VEP record."""
    out: dict[str, dict] = {}

    def run(batch):
        try:
            res = fetch(f"{ENSEMBL}/vep/human/hgvs", method="POST",
                        json_body={"hgvs_notations": batch, **VEP_OPTS}, cache_dir="vep")
        except requests.HTTPError:
            if len(batch) == 1:
                out[batch[0]] = {"error": "VEP rejected input"}
                return
            mid = len(batch) // 2
            run(batch[:mid])
            run(batch[mid:])
            return
        for r in res:
            out[r["input"]] = r

    for b in chunks(sorted(set(hgvs)), 200):
        run(b)
    return out


# ---------------------------------------------------------------- projection

_POS = re.compile(r"(?<!fs)(?<!ext)(Ala|Arg|Asn|Asp|Cys|Gln|Glu|Gly|His|Ile|Leu|Lys|Met|Phe|Pro|Ser|Thr|Trp|Tyr|Val|Ter|Sec|Xaa)(\d+)")


def renumber_hgvsp(hgvsp: str, aln: Alignment) -> str | None:
    """Rewrite each residue position in a protein HGVS through the alignment."""
    ok = True

    def sub(m):
        nonlocal ok
        p = aln(int(m.group(2)))
        if p is None:
            ok = False
            return m.group(0)
        return f"{m.group(1)}{p}"

    body = hgvsp.split(":", 1)[-1]
    new = _POS.sub(sub, body)
    return new if ok else None


def classify(terms: list[str]) -> str:
    t = set(terms)
    if t & {"stop_gained", "frameshift_variant", "start_lost"}:
        return "truncating"
    if t & {"splice_acceptor_variant", "splice_donor_variant"}:
        return "splice"
    if "missense_variant" in t:
        return "missense"
    if t & {"inframe_deletion", "inframe_insertion", "protein_altering_variant"}:
        return "inframe"
    if "stop_lost" in t:
        return "stop_lost"
    if t & {"synonymous_variant", "stop_retained_variant"}:
        return "synonymous"
    return "other"


class GeneProjector:
    def __init__(self, symbol: str, uniprot_acc: str, uniprot_seq: str):
        self.symbol, self.acc, self.useq = symbol, uniprot_acc, uniprot_seq
        tx = gene_transcripts(symbol)
        self.gene_id = tx["gene_id"]
        self.mane = tx["mane_select"]
        self.mane_seq = protein_seq(self.mane["protein_id"])
        self.aln = Alignment(self.mane_seq, uniprot_seq)
        # Transcripts whose translation is identical to UniProt canonical.
        self.canonical_tx = [t for t, v in tx["transcripts"].items() if v["length"] == len(uniprot_seq)
                             and protein_seq(v["protein_id"]) == uniprot_seq]

    def info(self) -> dict:
        return {"uniprot": self.acc, "uniprot_length": len(self.useq), "mane_select": self.mane,
                "transcripts_identical_to_uniprot": self.canonical_tx, "alignment": self.aln.summary()}

    def project(self, v: dict) -> dict:
        """VEP record -> projection result (never raises; status tells)."""
        if "error" in v:
            return {"status": "vep_error", "detail": v["error"]}
        tcs = [t for t in v.get("transcript_consequences", []) if t.get("gene_id") == self.gene_id]
        mane = next((t for t in tcs if t["transcript_id"] == self.mane["transcript"]), None)
        if mane is None:
            return {"status": "no_mane_consequence"}
        terms = mane.get("consequence_terms", [])
        res = {"consequence": terms, "class": classify(terms),
               "mane_hgvsc": mane.get("hgvsc"), "mane_hgvsp": mane.get("hgvsp")}
        if "protein_start" not in mane:
            res["status"] = "noncoding"
            return res
        ps, pe = mane["protein_start"], mane.get("protein_end", mane["protein_start"])
        ref, _, alt = (mane.get("amino_acids") or "/").partition("/")
        alt = alt or ref  # synonymous: "R"
        res.update({"mane_pos": ps, "mane_end": pe, "ref": ref, "alt": alt})
        # sanity: VEP ref must agree with the MANE translation itself
        try:
            assert_ref(self.mane_seq, ps, ref)
        except RefMismatch as e:
            res.update(status="mane_ref_mismatch", detail=str(e))
            return res
        up, ue = self.aln(ps), self.aln(pe)
        if up is None or ue is None:
            res["status"] = "not_in_canonical"
            return res
        res.update(u_pos=up, u_end=ue)
        try:
            assert_ref(self.useq, up, ref)
        except RefMismatch as e:
            res.update(status="ref_mismatch", detail=str(e))
            return res
        # independent cross-check against a UniProt-identical transcript
        for t in tcs:
            if t["transcript_id"] in self.canonical_tx and "protein_start" in t:
                if t["protein_start"] != up:
                    res.update(status="crosscheck_mismatch",
                               detail=f"{t['transcript_id']} protein_start {t['protein_start']} != {up}")
                    return res
                res["crosscheck"] = t["transcript_id"]
                break
        if mane.get("hgvsp"):
            res["u_hgvsp"] = renumber_hgvsp(mane["hgvsp"], self.aln)
            res["mane_hgvsp"] = mane["hgvsp"].split(":", 1)[-1]
        res["status"] = "ok"
        return res


def vep_key(v: dict) -> str | None:
    """Normalised GRCh38 key from a VEP record (3'-shifted genomic coordinates)."""
    if "error" in v or "seq_region_name" not in v:
        return None
    return f"{v['seq_region_name']}:{v['start']}-{v['end']}:{v['allele_string']}"
