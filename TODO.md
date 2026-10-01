# TODO — BAF portal

Working notes for picking this back up. The authoritative checklist is the
symbiosis workspace in `research/` (`sym -w research ready`); this file is the
human-readable summary of where things stand and what is next.

Last updated 2026-10-01. Position fix (`5cbf772`) and About page (`29c2532`)
are pushed to `main`.

## Blocked on you

1. **AlphaFold jobs for the ncBAF base.** `data/predictions/alphafold_server_jobs.json`
   holds two jobs, already validated against the 5,000-token limit:
   - `ncbaf_base` (4,498 tokens) — SMARCC1 x2, SMARCD1, BRD9, BICRA 1100–1560,
     plus SMARCA4 350–560 / ACTL6A / ACTB as anchors
   - `ss18_arp` (1,611 tokens) — SS18 1–186 on the same ARP anchors, with BCL7A

   Upload at alphafoldserver.com, unpack each result into
   `data/predictions/<job name>/`, then say so. Import will superpose on the
   anchor chains and add the subunits as `predicted` (paler, hatched, distinct
   from the `placed` tier), then re-run `pixi run check-models`.

   Until then ncBAF's BICRA, BRD9, SMARCC, SMARCD and SS18 stay as chips —
   there is no better experimental ncBAF structure; all 8 PDB entries resolve
   only the ATPase and ARP modules.

2. **Launch decisions.** Confirmed current state: GitHub Pages is *not* enabled
   (API 404) and *no* repository variables are set.
   - [ ] Make `bchick/baf-portal` public (private + free plan cannot use Pages;
         Suggest-edit also needs a public repo to accept outside issues).
         **Check the git history for anything that should not go public first.**
         The `lit/` PDFs were never committed.
   - [ ] Settings → Pages → Source = **GitHub Actions**
   - [ ] Set repo variable `DEPLOY_PAGES=true`
   - [ ] Decide the **NCBI contact email** (repo secret; the weekly build calls
         NCBI APIs and they ask for a contact)
   - [ ] Run the data workflow once manually with "deploy" checked
   - Site lands at https://bchick.github.io/baf-portal/, then rebuilds Mondays.

3. **Test on a real low-end phone.** `SMARCA4.json` is 3.0 MB raw / 306 KB
   gzipped, almost all variant records. Bandwidth is fine (Pages compresses),
   but that is 3 MB to *parse*. This is the main untested mobile risk. If it
   drags, split per-variant detail into a second lazily-loaded file rather than
   trimming data.

## Next up (in rough priority order)

- [x] ~~Fix the MNV off-by-one and decide the position-vs-label convention~~
      — decided: **the dot follows the label**. MNVs are trimmed to the
      changed residue; 3'-shifted indels/frameshifts plot at the first residue
      the HGVS protein label names (639 records), checked against UniProt
      (`label_mismatch` fails the build); `vpos` keeps VEP's position.
- [x] ~~Spot-check variant projection~~ (`T-3ff5a0be`) — done; findings below.
- [x] ~~Document filters, tiers and sources~~ (`T-8b1bd7ce`) and
      ~~About / how-to-cite page~~ (`T-61172302`) — `#/about`; footer now
      credits CIViC, LitVar2 and RCSB PDB too.
- [x] ~~Add a LICENSE file~~ — MIT for the code. The footer also says
      "cartoons CC BY 4.0"; that is stated only in the footer, with no
      licence file of its own.
- [ ] **Confirm the Pages deploy is live and the weekly build runs**
      (`T-ddf57853`) — after the launch steps above.
- [ ] **Feedback from 2–3 lab members** (`T-8c8b1910`), then fix what they hit.
- [ ] **Announce** (`T-0bfe53ed`).

Four `answer` records are waiting to be written up in `research/`:
composition verified, structure explorer ready, mutation data ready, launched.

## Done this session (2026-09-30)

- Resolved all 7 `needs_review` curation items using the reviews in `lit/` plus
  Mashtalir 2018 Fig. 6. ncBAF is now SMARCC1-only and SMARCD1-only; PBAF
  SMARCA2 keeps both sides cited. Added 6 PubMed-verified references.
- Removed the mouse-defined esBAF / npBAF / nBAF complexes entirely.
- Cited the 3 previously unused references (Mashtalir 2020 → PDB 9A0K on cBAF,
  Xu 2026 → PDB 21VV on ncBAF, Gatchalian 2018 → ncBAF defining papers).
- **Illustrate-style 3D rendering**: every heavy atom as a flat sphere, carbons
  lighter than N/O/S, depth-step contour outlines, subunit outlines, soft
  shadows — after Goodsell & Olson, matching BC's `6LTJv32` render settings.
  Atoms ship as `<complex>.atoms.bin`; residue beads remain for morphs/cartoons.
- **BCL7A placed** into cBAF and PBAF from 9WBZ by superposing the shared
  ACTB/ACTL6A module (RMSD 1.6 Å), drawn paler + hatched with provenance.
- `pipeline/check_models.py` (`pixi run check-models`) — independent check of
  every shipped model against its source mmCIF, RCSB entity identity, the
  curated composition, UniProt residue identity and placed-chain provenance.
  Currently **0 errors**.
- Tooltips for TCGA cancer codes (SKCM → "Skin Cutaneous Melanoma", with counts
  and CI) and ClinVar/TCGA class codes; work on hover, keyboard and tap.
- Per-subunit **Citations** button → sheet grouping membership, structure,
  CIViC and data-source releases.
- Lighter morph animation (≤160 particles, batched fills, no trails) and
  adaptive 1x resolution when the 3D view's frames run slow — BC reported lag
  on a ThinkPad; **needs confirming on that machine**.
- Usability: raised controls to the 24x24 WCAG 2.2 minimum; fixed Compare
  wrongly reporting placed BCL7A as "resolved in 6LTJ".

## Watch out for

- **`placed` vs `predicted` vs `experimental`** is a real distinction the UI
  encodes. Anything borrowed or modelled must stay visually and textually
  distinct from experimental coordinates. `Compare.svelte` got this wrong once
  already (fixed in `26f593c`) — it derived "resolved" from mere presence in
  the model index rather than from the chain's tier.
- **Do not loosen the LitVar2 UniProt reference check.** Most unmatched protein
  strings (e.g. 3571 for PBRM1) are text-mining misassignments and are
  correctly rejected.
- `site/public/data/` is gitignored and rebuilt by CI, so only one data version
  ever ships. Locally it accumulates (a stale `v2026-09-29`, 6 MB, is sitting
  in `dist`); harmless, but do not mistake it for a production problem.
- Commits are authored by Brent Chick alone — no AI attribution anywhere.

## Parked

`../ap-1-baf-model` — FOS/JUN + nucleosome and FOS IDR + SMARCD SWIFT
modelling. Scaffolded with a full `CLAUDE.md` handoff; the Jain et al. 2026
paper is now in its `lit/`. Deliberately paused to focus on the portal. Note
`../swift_ap1` is BC's wet-lab project on the same paper and already holds
verified SWIFT boundaries and the R290W control.

## Spot-check findings (`T-3ff5a0be`)

Independent check against freshly fetched UniProt sequences, across all 29
genes. **One real bug, two fragile spots; everything else passed.**

Note the pipeline already asserts the reference residue at every projected
position (`project_coords.assert_ref`, build fails on mismatch), so the check
targeted what that does *not* cover: displayed strings, 3'-shift behaviour,
feature intervals, TCGA arithmetic and the 3D numbering.

### Bug: 18 multi-nucleotide missense variants plot one residue too far left

**Verified first-hand.** VEP returns `protein_start` at the first *codon* an
MNV overlaps; the build stores that as `pos`, and `Lollipop.svelte` draws at
`v.pos`. When the first residue of the pair is unchanged, the lollipop sits one
residue left of the residue its own tooltip names.

```
SMARCA4  stored pos 345  label p.His346Asn  ref/alt LH -> LN
SMARCA4  stored pos 508  label p.Ala509Thr  ref/alt HA -> HT
SMARCA4  stored pos 104  label p.Gly105Trp  ref/alt AG -> AW
```

Because `ref` is the two-residue string and its first residue *is* correct at
`pos`, the reference assertion passes and the pipeline never notices.

Counts (18 total): SMARCA4 10, ARID1B 2, SMARCE1 2, ACTL6B 1, ARID1A 1,
BICRA 1, SMARCC2 1. None of the 18 changes domain assignment, so the visible
impact is one pixel plus a self-contradicting tooltip.

**Proposed fix** — left-trim in the pipeline, the standard normalisation: while
`ref` and `alt` share a leading residue, drop it and advance `pos`. Add a
regression test asserting that for every missense variant the residue number in
`p` equals `pos`. *Not done — left for you, because it is entangled with the
convention question below and it moves displayed positions.*

### Fragile: 3'-shift divergence in low-complexity runs

316 truncating and 273 inframe variants have `pos` disagreeing with the first
residue named in `p`, by up to ±16. Worst: ARID1B `p.Gln200_Gln214dup` stored
at 214; a cluster of ARID1B polyQ variants stored at 204 but labelled
Gln208–Gln214. Confined to ARID1A/ARID1B/SMARCA2/SMARCA4 repeats.

Genomic 3'-shift and HGVS *protein* 3'-shift are different rules, so both
numbers are defensible and the residue identity is the same across the run —
but position and label visibly disagree. **This is a convention decision for
you**: move the plotted position to match the label, relabel to match the
position, or leave it and note it in the docs. Worth deciding together with the
MNV fix, since both are "position vs. label" questions.

### Also fragile

- **`renumber_hgvsp` regex.** SMARCD2 carries a malformed HGVS passed through
  from VEP (`p.MetSerGlyArgGly1_?5`). Harmless here because SMARCD2's alignment
  is identity, but the regex would silently rewrite the `Gly1` token on a gene
  where it is not.
- **`App.svelte:414`** reads `alignment.blocks[0][2]` assuming `blocks[0]`
  starts at (1,1). True for all three current cases, but `difflib` is a
  heuristic, not a global aligner; an N-terminal difference would make the
  isoform sentence silently wrong.
- **`stop_lost` at L+1.** 16 records sit at exactly protein length + 1 (the
  stop codon). Deliberate — `Alignment.__call__` maps `len+1 -> len+1` — but
  the lollipop x-scale is `[1, L]`, so they render marginally past the right
  edge. Cosmetic.

### Passed

- **Reference residues: 0 mismatches in all 29 genes**, for both the `ref`
  field and every residue encoded in the displayed `p` string (9,824 missense
  strings parsed), and likewise for the TCGA/ODbL files.
- **Hotspots land correctly.** SMARCA4 K785 is the Walker A lysine of `GxGKT`
  (781–789 `MGLGKTIQT`); T910 is in helicase motif III; R1192 is motif VI
  `R…GQ` in the helicase C-terminal domain — all matching Hodges and Kadoch.
  K785R, T910M, R1192C/H all present with sensible cancer-type spreads.
  ARID1A's known hotspots (D1850fs, R1989*, F2141fs, K1072fs, R1721*) are the
  top recurrent ones, 69% of TCGA patient-events truncating — the expected
  tumour-suppressor pattern.
- **Feature/domain intervals:** 0 violations across every gene.
- **MANE alignment:** only ARID1B, PBRM1, SMARCC2 differ; the site's
  "numbering differs after residue N" claim is correct in all three, and the 13
  dropped `not_in_canonical` variants are confined to exactly those genes.
- **TCGA arithmetic:** per-study k/n sum exactly to gene totals, no k > n, no
  per-variant count exceeding its study. BRCA n = 1066 matches the published
  TCGA BRCA PanCancer Atlas count.
- **3D numbering:** all 60 chains across the three complexes have strictly
  increasing `res`, every value within its chain's protein length, every chain
  accession matching `composition.yaml`. SMARCB1 confirms the construct gap
  independently: cBAF chain M has **0 beads numbered 114–171**, while PBAF
  chain V *does* number 137–171 — a cross-structure difference that shows the
  numbering is genuine rather than an alignment artefact.
- **Expected gaps, not problems:** ARID1A is modelled only as 1639–2285, so its
  own ARID domain (1017–1109) is unmodelled and only 212/1355 germline variants
  sit on a bead. BCL7A is correctly the only non-experimental chain.

### Not checked

The upstream fetches themselves (whether ClinVar/cBioPortal returned every
record the APIs hold), the 10,433 denominator against cBioPortal directly
(only internal consistency plus the BRCA cross-check), and bead-to-atom
correspondence inside the `.atoms.bin` files.
