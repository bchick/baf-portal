<script>
  // About: what the data are, how variants get onto the map, what the evidence
  // tiers mean, each source's licence, and how to cite. Release numbers come
  // from the manifest so the page always describes the data actually shipped.
  import { CLINVAR_TIP, SOM_TIP } from './glossary.js';
  import { CLASS_ORDER, CLASS_COLOR } from './colors.js';

  let { manifest, refs = {}, modelIndex = {}, complexIds = [], compositionVersion = null } = $props();
  const src = $derived(manifest?.sources ?? {});
  const nGenes = $derived(manifest ? Object.keys(manifest.genes).length : 0);
  const version = $derived(manifest?.data_version ?? '');
  const siteUrl = typeof location !== 'undefined' ? location.origin + location.pathname : '';
  const year = $derived((manifest?.built ?? '').slice(0, 4));

  const structures = $derived(complexIds.filter((id) => modelIndex[id]).map((id) => ({
    id, pdb: modelIndex[id].pdb, ref: refs[modelIndex[id].pmid], pmid: modelIndex[id].pmid,
  })));

  const citeText = $derived(`Chick B. BAF-portal: human BAF (mSWI/SNF) complexes, subunit domain maps and disease mutations. `
    + `Data version ${version}. ${siteUrl} (accessed <date>).`);
  // In-page links: the hash is the router's, so scroll instead of using #anchors.
  function jump(id) {
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    document.getElementById(`about-${id}`)?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth' });
  }
  let copied = $state(false);
  function copyCite() {
    navigator.clipboard?.writeText(citeText).then(() => { copied = true; setTimeout(() => (copied = false), 1600); });
  }
</script>

<article class="about card">
  <p class="eyebrow">About</p>
  <h1>What is on this site, and where it comes from</h1>
  <p class="lede">
    BAF-portal shows the three human BAF (mSWI/SNF) chromatin-remodelling complexes, cBAF, PBAF and ncBAF,
    as 3D structures, with a domain map and the known disease variants for each of the {nGenes} curated subunits.
    Every variant links back to its source record, and every claim about it carries a citation.
  </p>
  <nav class="toc" aria-label="On this page">
    <button onclick={() => jump('composition')}>Composition</button>
    <button onclick={() => jump('structures')}>Structures</button>
    <button onclick={() => jump('variants')}>Which variants are shown</button>
    <button onclick={() => jump('positions')}>Positions</button>
    <button onclick={() => jump('classes')}>Classes</button>
    <button onclick={() => jump('tiers')}>Evidence tiers</button>
    <button onclick={() => jump('tcga')}>TCGA frequencies</button>
    <button onclick={() => jump('sources')}>Sources and licences</button>
    <button onclick={() => jump('cite')}>How to cite</button>
  </nav>

  <section id="about-composition">
    <h2>Complex composition</h2>
    <p>
      Which subunits belong to which complex is hand-curated
      {#if compositionVersion}({compositionVersion}){/if}
      from the primary literature and recent reviews. Each membership claim cites its papers (the <b>Citations</b>
      button on a subunit). Paralogs that fill the same position, such as SMARCA4 and SMARCA2, are grouped as one
      <i>slot</i>. Only human complexes are included; tissue-specific assemblies defined in mouse are not.
    </p>
  </section>

  <section id="about-structures">
    <h2>Structures</h2>
    <p>Each complex is drawn from one experimental cryo-EM structure:</p>
    <ul>
      {#each structures as s (s.id)}
        <li>
          <b>{s.id}</b>:
          <a href="https://www.rcsb.org/structure/{s.pdb}" target="_blank" rel="noopener">PDB {s.pdb}</a>
          {#if s.ref}· {s.ref.text}{:else}· PMID {s.pmid}{/if}
        </li>
      {/each}
    </ul>
    <p>Coordinates are shown in one of three tiers, which are always drawn and labelled differently:</p>
    <dl class="defs">
      <dt>Experimental</dt>
      <dd>Resolved in the complex's own structure. Full colour.</dd>
      <dt>Placed</dt>
      <dd>
        Resolved in a <i>different</i> experimental structure and moved into this one by superposing a module the two
        share. BCL7A in cBAF and PBAF is placed from PDB 9WBZ on the ACTB/ACTL6A module. Paler, hatched, and the
        subunit card names the source entry.
      </dd>
      <dt>Predicted</dt>
      <dd>Computational models (e.g. AlphaFold). Marked as predicted wherever they appear; never shown as experimental.</dd>
    </dl>
    <p>
      Subunits with no coordinates in any of these tiers appear as chips beside the structure. Residue numbering
      follows UniProt, so a variant and its bead in 3D refer to the same residue.
    </p>
  </section>

  <section id="about-variants">
    <h2>Which variants are shown</h2>
    <p>Variants come from two places, kept apart throughout the site:</p>
    <ul>
      <li>
        <b>Germline and clinical</b>: ClinVar records with an exact genomic allele (SPDI) of at most 100 changed bases,
        plus UniProt's curated natural variants.
      </li>
      <li>
        <b>Somatic</b>: mutations in the TCGA PanCancer Atlas (2018) studies on cBioPortal. Only protein-affecting
        types are counted: missense, nonsense, frameshift and in-frame indels, splice-site, nonstop and start-codon
        mutations.
      </li>
    </ul>
    <p>Only these consequence classes are drawn on the domain map:</p>
    <dl class="defs">
      {#each Object.entries(SOM_TIP) as [k, t] (k)}
        <dt>{t.split(':')[0]}</dt><dd>{t.split(': ').slice(1).join(': ')}</dd>
      {/each}
    </dl>
    <p>
      Synonymous, intronic, UTR and other non-coding changes are not shown. A variant is also dropped, and listed in
      the build report, when its residue exists only in the Ensembl MANE transcript and not in the UniProt canonical
      protein (see below).
    </p>
    <p class="note">
      <b>Licence filter.</b> Some aggregators mix in content we may not redistribute. Any record mentioning COSMIC,
      OncoKB, AACR GENIE, HGMD, REVEL or CADD is discarded, and OMIM identifiers are stripped from ClinVar
      condition names. COSMIC and OncoKB are linked from the variant panel, never copied.
    </p>
  </section>

  <section id="about-positions">
    <h2>How variants get their position</h2>
    <p>Protein positions are never copied from a source's own protein-change string. Each variant goes through the same steps:</p>
    <ol>
      <li>Its genomic allele on GRCh38 is annotated with Ensembl VEP. TCGA calls, which are on GRCh37, are lifted over first.</li>
      <li>VEP's consequence on the MANE Select transcript gives the protein change.</li>
      <li>The MANE protein is aligned to the UniProt canonical sequence and the position is carried across. The two are
        identical for most subunits. ARID1B, PBRM1 and SMARCC2 differ, and the subunit page says where the numbering
        starts to diverge.</li>
      <li>The reference residue is checked against UniProt. A mismatch stops the data build; nothing is shown with an
        unchecked residue.</li>
    </ol>
    <p>
      <b>The lollipop sits at the residue the label names.</b> Two cases need care. A change of two adjacent bases
      (for example <span class="mono">LH→LN</span>) is reported from the first codon touched, so it is trimmed to the
      residue that actually changes (<span class="mono">p.His346Asn</span> at 346). In repeats such as ARID1B's
      polyalanine and polyglutamine runs, an insertion or deletion could be placed anywhere along the run. Genomic and
      protein nomenclature place it differently, so the plotted position is set to the first residue the protein label
      names (<span class="mono">p.Gln200_Gln214dup</span> sits at 200). That residue is checked against UniProt too.
    </p>
  </section>

  <section id="about-classes">
    <h2>Pathogenicity classes</h2>
    <p>Germline variants are coloured by their ClinVar germline classification:</p>
    <dl class="defs">
      {#each CLASS_ORDER as k (k)}
        <dt><span class="dot" style:background={CLASS_COLOR[k]}></span>{k}</dt><dd>{CLINVAR_TIP[k]}</dd>
      {/each}
    </dl>
    <p>
      A UniProt variant with no ClinVar record counts as P/LP only when UniProt's description calls it pathogenic. ClinVar's
      review stars (★, out of 4) are shown beside each classification. Somatic clinical impact and oncogenicity
      classifications are shown separately when ClinVar has them.
    </p>
  </section>

  <section id="about-tiers">
    <h2>Evidence tiers</h2>
    <p>Papers about a variant are grouped by how directly they were linked to it:</p>
    <dl class="defs tiers">
      <dt>Tier 1 · Curated</dt>
      <dd>
        Linked by expert curators: UniProt's experimental evidence (ECO:0000269), accepted CIViC evidence about this
        specific allele, and ClinVar submissions from expert panels (3★, e.g. ClinGen VCEPs) or practice guidelines (4★).
      </dd>
      <dt>Tier 2 · Submitter-cited</dt>
      <dd>Cited by a ClinVar submitter with at least one review star. The paper may support the classification without describing this exact variant.</dd>
      <dt>Tier 3 · Text-mined</dt>
      <dd>
        Automated mentions from NCBI LitVar2, not reviewed by anyone. A mention is accepted only through an rsID that
        identifies exactly one of our variants, or through a simple protein change whose reference residue matches
        UniProt at that position. Papers already in a higher tier are omitted. Most rejected mentions name a residue
        the protein does not have there, which usually means a text-mining error.
      </dd>
      <dt>Cohort · Source studies</dt>
      <dd>The publications describing the TCGA cohorts a variant was seen in. This is provenance, not evidence about the variant.</dd>
    </dl>
    <p>
      Retracted papers are kept, so the record stays honest, but they are flagged, sorted last and left out of the
      counts. CIViC evidence about a whole gene (for example "Loss" or "Inactivating mutation") is shown on the subunit
      card and never attached to a single variant.
    </p>
  </section>

  <section id="about-tcga">
    <h2>TCGA frequencies</h2>
    <p>
      The somatic mutation rate counts <b>patients</b>, not samples, deduplicated across studies. The numerator is
      patients with at least one counted mutation in the gene. The denominator is patients with at least one sample
      profiled for that gene. Intervals are 95% Wilson score intervals. Per-cancer rows show studies with at least
      50 profiled patients.
    </p>
  </section>

  <section id="about-sources">
    <h2>Sources and licences</h2>
    <p>Data version <b class="mono">v{version}</b>, built {manifest?.built?.slice(0, 10)}. The data are rebuilt weekly from:</p>
    <div class="table-wrap">
      <table class="src-table">
        <thead><tr><th>Source</th><th>Used for</th><th>Release</th><th>Licence</th></tr></thead>
        <tbody>
          <tr><td><a href="https://www.uniprot.org" target="_blank" rel="noopener">UniProt</a></td>
            <td>Sequences, features, natural variants</td><td class="mono">{src.uniprot?.release}</td><td>CC BY 4.0</td></tr>
          <tr><td><a href="https://www.ebi.ac.uk/interpro/" target="_blank" rel="noopener">InterPro / Pfam</a></td>
            <td>Domain boundaries</td><td class="mono">{src.interpro?.interpro?.version} / {src.interpro?.pfam?.version}</td><td>CC0</td></tr>
          <tr><td><a href="https://www.ncbi.nlm.nih.gov/clinvar/" target="_blank" rel="noopener">ClinVar</a></td>
            <td>Germline and clinical variants, classifications, submitter citations</td>
            <td class="mono">{src.clinvar?.last_update?.slice(0, 10)}</td><td>Public domain (NCBI)</td></tr>
          <tr><td><a href="https://www.ensembl.org/info/docs/tools/vep/" target="_blank" rel="noopener">Ensembl VEP</a></td>
            <td>Consequences on MANE Select, liftover</td><td class="mono">{src.ensembl_vep?.software}</td><td>Apache 2.0</td></tr>
          <tr><td><a href="https://www.cbioportal.org" target="_blank" rel="noopener">cBioPortal</a>, TCGA PanCancer Atlas</td>
            <td>Somatic mutations and cohort sizes</td><td class="mono">{src.cbioportal?.portal_version}</td>
            <td>ODbL 1.0 (separate files under <code>{src.cbioportal?.path}</code>)</td></tr>
          <tr><td><a href="https://civicdb.org" target="_blank" rel="noopener">CIViC</a></td>
            <td>Curated clinical evidence (tier 1)</td><td class="mono">nightly</td><td>CC0</td></tr>
          <tr><td><a href="https://www.ncbi.nlm.nih.gov/research/litvar2/" target="_blank" rel="noopener">LitVar2</a></td>
            <td>Text-mined literature mentions (tier 3)</td><td class="mono">{src.litvar2?.last_modified?.slice(5, 16)}</td><td>Public domain (NCBI)</td></tr>
          <tr><td><a href="https://www.rcsb.org" target="_blank" rel="noopener">RCSB PDB</a></td>
            <td>3D structures ({structures.map((s) => s.pdb).join(', ')})</td><td class="mono">—</td><td>CC0</td></tr>
          <tr><td><a href="https://pubmed.ncbi.nlm.nih.gov" target="_blank" rel="noopener">PubMed</a></td>
            <td>Reference details and retraction status (NCBI ESummary)</td>
            <td class="mono">{src.pubmed?.resolved?.toLocaleString()} papers</td><td>Bibliographic metadata</td></tr>
        </tbody>
      </table>
    </div>
    <p>
      UniProt content is used under CC BY 4.0: <i>The UniProt Consortium, UniProt: the Universal Protein Knowledgebase,
      Nucleic Acids Res.</i> TCGA-derived files carry their own ODbL notice and stay separate from the rest of the data,
      so anything derived from them can be shared on the same terms.
    </p>
  </section>

  <section id="about-cite">
    <h2>How to cite</h2>
    <p>No paper describes the portal yet. Please cite the site with the data version you used:</p>
    <div class="cite">
      <p class="mono">{citeText}</p>
      <button class="btn" onclick={copyCite}>{copied ? 'Copied' : 'Copy'}</button>
    </div>
    <p>
      Please also cite the underlying resources your conclusions rest on: the structure papers above, the ClinVar
      records (by VCV accession), the TCGA PanCancer Atlas and cBioPortal, and UniProt. Each variant panel lists the
      exact records it shows.
    </p>
    <p>
      Found an error? Every section has a <b>Suggest edit</b> button that opens a pre-filled correction form with
      the data version attached.
    </p>
  </section>
</article>

<style>
  .about { max-width: 820px; margin: 0 auto; line-height: 1.6; padding: clamp(18px, 4vw, 36px) clamp(16px, 4vw, 44px); }
  .eyebrow { font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink-3); margin: 0; }
  h1 { font-size: clamp(24px, 4vw, 32px); letter-spacing: -0.02em; line-height: 1.2; margin: 4px 0 12px; }
  h2 { font-size: 19px; margin: 0 0 8px; letter-spacing: -0.01em; }
  section { padding-top: 22px; margin-top: 22px; border-top: 1px solid var(--line); scroll-margin-top: 80px; }
  @media (max-width: 640px) { section { scroll-margin-top: 130px; } }
  .lede { font-size: 16px; color: var(--ink-2); }
  .toc { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 14px; }
  .toc button { all: unset; cursor: pointer; font-size: 13px; padding: 4px 10px; min-height: 24px; box-sizing: border-box; border: 1px solid var(--line);
    border-radius: 999px; color: var(--ink-2); }
  .toc button:hover { background: var(--bg-2); }
  .toc button:focus-visible { outline: 2px solid var(--focus); }
  ul, ol { padding-left: 22px; }
  li { margin: 4px 0; }
  .defs { display: grid; grid-template-columns: max-content 1fr; gap: 6px 16px; margin: 10px 0; }
  .defs dt { font-weight: 600; white-space: nowrap; display: flex; align-items: baseline; gap: 6px; }
  .defs dd { margin: 0; color: var(--ink-2); }
  @media (max-width: 560px) {
    .defs { grid-template-columns: 1fr; gap: 2px; }
    .defs dd { margin-bottom: 8px; }
  }
  .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; flex: none; }
  .note { background: var(--bg-2); border-radius: 10px; padding: 10px 14px; font-size: 14px; }
  .mono { font-family: var(--mono); font-size: 0.92em; }
  .table-wrap { overflow-x: auto; margin: 10px 0; }
  .src-table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
  .src-table th, .src-table td { text-align: left; padding: 7px 10px 7px 0; border-bottom: 1px solid var(--line); vertical-align: top; }
  .src-table th { font-size: 12px; color: var(--ink-3); font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }
  .cite { display: flex; gap: 12px; align-items: flex-start; background: var(--bg-2); border-radius: 10px; padding: 12px 14px; }
  .cite p { margin: 0; flex: 1; font-size: 13px; overflow-wrap: anywhere; }
</style>
