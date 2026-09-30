<script>
  // One variant: identity (all notations), classification, cancer frequency,
  // and evidence as tiered citations (plan: "graded citations"):
  //   1 Curated          UniProt ECO:0000269, ClinVar expert panel / practice guideline
  //   2 Submitter-cited  ClinVar SCVs with >=1 star, submitter named
  //   1 also CIViC accepted evidence matched to this exact variant
  //   3 Text-mined       LitVar2 (tmVar/rsID mentions), grey and collapsed
  //   4 Cohort           cBioPortal source studies: provenance, not evidence
  // Retracted papers stay visible but flagged, struck through, and uncounted.
  import { slide } from 'svelte/transition';
  import { cubicOut } from 'svelte/easing';
  import { CLASS_COLOR, classKey } from './colors.js';

  let { variant, gene, tcga = null, refs = {}, symbol, civicGene = [], closeHref, onselect = () => {} } = $props();

  const reduce = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const dur = reduce ? 0 : 260;

  const AA = { Ala: 'A', Arg: 'R', Asn: 'N', Asp: 'D', Cys: 'C', Gln: 'Q', Glu: 'E', Gly: 'G', His: 'H', Ile: 'I', Leu: 'L',
               Lys: 'K', Met: 'M', Phe: 'F', Pro: 'P', Ser: 'S', Thr: 'T', Trp: 'W', Tyr: 'Y', Val: 'V', Ter: '*' };
  const oneLetter = (p) => p?.replace(/^p\./, '').replace(/[A-Z][a-z]{2}/g, (m) => AA[m] ?? m).replace(/fs\*/, 'fs*');

  const germ = $derived(variant.germ);
  const som = $derived(variant.som);
  const cv = $derived(germ?.cv ?? null);
  const key = $derived(germ ? classKey(germ) : variant.up ? classKey(variant) : null);
  const short = $derived(oneLetter(variant.p));

  // ---- notations -----------------------------------------------------------------
  const legacy = $derived(som?.legacy_differs ? som.cbio_pc?.join(', ') : null);
  const spdi = $derived(germ?.spdi ?? null);
  const gnomad = $derived.by(() => {
    const m = spdi?.match(/^NC_0+(\d+)\.\d+:(\d+):([ACGT]):([ACGT])$/);
    if (!m) return null;
    const chr = m[1] === '23' ? 'X' : m[1] === '24' ? 'Y' : m[1];
    return `https://gnomad.broadinstitute.org/variant/${chr}-${+m[2] + 1}-${m[3]}-${m[4]}?dataset=gnomad_r4`;
  });
  const simpleMissense = $derived(variant.cls === 'missense' && /^[A-Z]\d+[A-Z]$/.test(short ?? ''));

  // ---- evidence tiers -------------------------------------------------------------
  // ClinVar placeholder traits carry no information
  const conditions = $derived((cv?.germ?.cond ?? []).filter((c) => !/^not (provided|specified)$/i.test(c.name ?? '')));

  const cites = $derived(germ?.cit ?? variant.cit ?? []);
  // Classification guidelines / methods papers (e.g. ACMG-AMP 2015) are cited by
  // submitters as the framework they used, not as evidence about the variant.
  // Detected from the resolved title; listed last and labelled.
  const METHOD = /standards (and guidelines|for (the )?interpretation)|interpretation (and reporting )?of sequence variat|variant classification criteria|clingen recommendations/i;
  const isMethod = (r) => !!r && METHOD.test(r.title ?? '');
  function group(tier) {
    const m = new Map();
    for (const c of cites.filter((c) => c.t === tier)) {
      const e = m.get(c.pmid) ?? { pmid: c.pmid, ref: refs[c.pmid], method: isMethod(refs[c.pmid]), by: [] };
      e.by.push(c); m.set(c.pmid, e);
    }
    return [...m.values()].sort((a, b) => (a.ref?.retracted ?? false) - (b.ref?.retracted ?? false)
      || a.method - b.method || (b.ref?.year ?? 0) - (a.ref?.year ?? 0));
  }
  const t1 = $derived(group(1));
  const t2 = $derived(group(2));
  const t3 = $derived(group(3));
  let showAll3 = $state(false);
  const litvarUrl = (id) => `https://www.ncbi.nlm.nih.gov/research/litvar2/docsum?variant=${encodeURIComponent(id)}`;
  const cohort = $derived.by(() => {
    if (!som || !tcga) return { studies: [], refs: [] };
    // spread the study first: its own `n` is the cohort size, not this variant's count
    const studies = Object.entries(som.studies).map(([id, n]) => ({ ...tcga.per_study[id], id, n, cohortN: tcga.per_study[id]?.n }))
      .sort((a, b) => b.n - a.n);
    const pm = [...new Set(studies.flatMap((s) => s.pmids ?? []))];
    return { studies, refs: pm.map((p) => ({ pmid: p, ref: refs[p] })).sort((a, b) => (a.ref?.retracted ?? false) - (b.ref?.retracted ?? false)) };
  });
  // evidence counts exclude retracted papers and methods/guideline citations
  const live = (list) => list.filter((e) => !e.ref?.retracted && !e.method).length;

  let open = $state({ 1: true, 2: true, 3: false, 4: false });
  let showAll2 = $state(false);
  const T2_PREVIEW = 5;

  // ---- same residue --------------------------------------------------------------
  const sameResidue = $derived.by(() => {
    const m = new Map();
    for (const v of gene.variants) if (v.pos === variant.pos && v.p) m.set(v.p, { p: v.p, key: classKey(v), n: 0 });
    for (const v of tcga?.variants ?? []) if (v.pos === variant.pos && v.p) {
      const e = m.get(v.p) ?? { p: v.p, key: null, n: 0 }; e.n += v.n_pat; m.set(v.p, e);
    }
    m.delete(variant.p);
    return [...m.values()].sort((a, b) => b.n - a.n);
  });

  const stars = (n) => '★'.repeat(n ?? 0) + '☆'.repeat(Math.max(0, 4 - (n ?? 0)));
  const pct = (x) => (100 * x).toFixed(x < 0.001 ? 3 : 2) + '%';
</script>

{#snippet refRow(e, children)}
  {@const r = e.ref}
  <li class="ref" class:retracted={r?.retracted}>
    <div class="ref-main">
      <a href="https://pubmed.ncbi.nlm.nih.gov/{e.pmid}/" target="_blank" rel="noopener" class="ref-who">
        {r ? `${r.first_author} ${r.year}` : `PMID ${e.pmid}`}
      </a>
      {#if r?.journal}<span class="muted"> · {r.journal}</span>{/if}
      {#if r?.retracted}<span class="flag">Retracted</span>{/if}
      {#if e.method}<span class="method" title="Cited as the classification framework, not as evidence about this variant">Methods/guideline</span>{/if}
    </div>
    {#if r?.title}<div class="ref-title">{r.title}</div>{/if}
    {@render children?.()}
  </li>
{/snippet}

{#snippet tierHead(n, label, badge, count, note)}
  <button class="tier-head" onclick={() => (open[n] = !open[n])} aria-expanded={open[n]}>
    <span class="badge t{n}">{badge}</span>
    <span class="tier-label">{label}</span>
    <span class="tier-count num">{count}</span>
    <span class="chev" class:open={open[n]} aria-hidden="true">›</span>
  </button>
  {#if note}<p class="tier-note">{note}</p>{/if}
{/snippet}

<article class="mp" style:--cls={key ? CLASS_COLOR[key] : 'var(--c-mis)'}>
  <header class="mp-head">
    <div>
      <p class="eyebrow">{symbol} · residue {variant.pos}</p>
      <h3 class="mono">{variant.p ?? variant.up?.desc}</h3>
      <p class="aliases">
        {#if short}<span class="mono">{short}</span>{/if}
        {#if variant.mane && variant.mane !== variant.p}<span class="mono" title="MANE Select numbering"> · MANE {variant.mane}</span>{/if}
        {#if legacy}<span class="mono" title="Legacy/cBioPortal numbering"> · legacy {legacy}</span>{/if}
      </p>
    </div>
    <a class="close" href={closeHref} aria-label="Close variant">×</a>
  </header>

  <!-- classification strip -->
  <div class="class-strip">
    {#if cv?.germ}
      <div class="cls-main">
        <span class="cls-pill">{cv.germ.c}</span>
        <span class="stars" title={cv.germ.r} aria-label="{cv.germ.s} of 4 ClinVar review stars">{stars(cv.germ.s)}</span>
      </div>
      <p class="muted small">ClinVar germline · {cv.germ.r}{#if cv.germ.d}{' · '}evaluated {cv.germ.d}{/if}</p>
    {:else if variant.up}
      <div class="cls-main"><span class="cls-pill">UniProt: {variant.up.desc}</span></div>
    {:else}
      <div class="cls-main"><span class="cls-pill neutral">Not in ClinVar</span></div>
      <p class="muted small">Observed somatically in TCGA only.</p>
    {/if}
    {#if cv?.som}<p class="small">Somatic clinical impact: <b>{cv.som.c}</b> <span class="stars">{stars(cv.som.s)}</span></p>{/if}
    {#if cv?.onc}<p class="small">Oncogenicity: <b>{cv.onc.c}</b> <span class="stars">{stars(cv.onc.s)}</span></p>{/if}
  </div>

  <dl class="facts">
    <dt>Genomic (GRCh38)</dt><dd class="mono">{variant.g ?? '—'}</dd>
    {#if germ?.c ?? som?.c}<dt>Coding</dt><dd class="mono">{germ?.c ?? som?.c}</dd>{/if}
    <dt>Consequence</dt><dd>{(germ?.csq ?? som?.csq ?? [variant.cls]).join(', ').replaceAll('_', ' ')}</dd>
    {#if conditions.length}
      <dt>Conditions</dt>
      <dd>
        {#each conditions as c, i}{#if i}{'; '}{/if}{#if c.mondo}<a href="https://monarchinitiative.org/{c.mondo}" target="_blank" rel="noopener">{c.name}</a>{:else}{c.name}{/if}{/each}
      </dd>
    {/if}
    {#if som && tcga}
      <dt>TCGA PanCancer</dt>
      <dd>
        <b class="num">{som.n_pat}</b> patient{som.n_pat === 1 ? '' : 's'}
        <span class="muted num">({pct(som.n_pat / tcga.n)} of {tcga.n.toLocaleString()} profiled)</span>
        <div class="studies">
          {#each cohort.studies as s (s.id)}
            <span class="chip" title="{s.name}: {s.n} of {s.cohortN} profiled patients">{s.cancer_type?.toUpperCase() ?? s.id} ×{s.n}</span>
          {/each}
        </div>
      </dd>
    {/if}
  </dl>

  {#if sameResidue.length}
    <div class="same">
      <span class="muted small">Same residue:</span>
      {#each sameResidue.slice(0, 8) as v (v.p)}
        <button class="chip" onclick={() => onselect(v.p)}>
          {#if v.key}<i style:background={CLASS_COLOR[v.key]}></i>{/if}<span class="mono">{oneLetter(v.p)}</span>{#if v.n}<span class="muted num"> ×{v.n}</span>{/if}
        </button>
      {/each}
    </div>
  {/if}

  <!-- evidence -->
  <section class="evidence" aria-label="Evidence">
    <h4>Evidence</h4>

    <div class="tier">
      {@render tierHead(1, 'Curated', 'Tier 1', live(t1), null)}
      {#if open[1]}
        <div transition:slide={{ duration: dur, easing: cubicOut }}>
          {#if t1.length}
            <ul class="refs">
              {#each t1 as e (e.pmid)}
                {#snippet by()}
                  <div class="by">
                    {#each e.by as c}
                      {#if c.src === 'CIViC'}
                        <a class="src solid" href={c.url} target="_blank" rel="noopener" title="Matched by {c.basis}">
                          CIViC EID{c.eid} · level {c.level} · {c.type}: {c.significance} · {c.disease}{#if c.therapies}{' · '}{c.therapies}{/if}
                        </a>
                      {:else}
                        <span class="src solid">{c.src}{#if c.sub} · {c.sub}{/if}{#if c.eco} · {c.eco}{/if}</span>
                      {/if}
                    {/each}
                  </div>
                {/snippet}
                {@render refRow(e, by)}
              {/each}
            </ul>
          {:else}
            <p class="empty">No curated citations for this variant.</p>
          {/if}
          {#if !cites.some((c) => c.src === 'CIViC')}
            <p class="pending">CIViC: no accepted evidence for this specific variant{#if civicGene.length}{' '}({civicGene.length} gene-level
              item{civicGene.length === 1 ? '' : 's'} for {symbol}, shown on the subunit card){/if}.</p>
          {/if}
        </div>
      {/if}
    </div>

    <div class="tier">
      {@render tierHead(2, 'Submitter-cited', 'Tier 2', live(t2), 'ClinVar submissions with ≥1 review star. The submitter cited the paper; it may not describe this exact variant.')}
      {#if open[2]}
        <div transition:slide={{ duration: dur, easing: cubicOut }}>
          {#if t2.length}
            <ul class="refs">
              {#each showAll2 ? t2 : t2.slice(0, T2_PREVIEW) as e (e.pmid)}
                {#snippet by()}
                  <div class="by">
                    {#each e.by as c}
                      <span class="src outline" title={c.scv}>{c.sub} <span class="stars">{stars(c.s)}</span>{#if c.cls} · {c.cls}{/if}</span>
                    {/each}
                  </div>
                {/snippet}
                {@render refRow(e, by)}
              {/each}
            </ul>
            {#if t2.length > T2_PREVIEW}
              <button class="more" onclick={() => (showAll2 = !showAll2)}>{showAll2 ? 'Show fewer' : `Show all ${t2.length}`}</button>
            {/if}
          {:else}
            <p class="empty">No ClinVar submitter citations.</p>
          {/if}
        </div>
      {/if}
    </div>

    <div class="tier">
      {@render tierHead(3, 'Text-mined', 'Tier 3', live(t3),
                        'Automated mentions (LitVar2), not reviewed. Papers already cited in a higher tier are omitted.')}
      {#if open[3]}
        <div transition:slide={{ duration: dur, easing: cubicOut }}>
          {#if t3.length}
            <ul class="refs mined">
              {#each showAll3 ? t3 : t3.slice(0, T2_PREVIEW) as e (e.pmid)}
                {#snippet by()}
                  <div class="by">
                    {#each e.by.slice(0, 1) as c}
                      <a class="src grey" href={litvarUrl(c.id)} target="_blank" rel="noopener">LitVar2 · matched on {c.basis}</a>
                    {/each}
                  </div>
                {/snippet}
                {@render refRow(e, by)}
              {/each}
            </ul>
            {#if t3.length > T2_PREVIEW}
              <button class="more" onclick={() => (showAll3 = !showAll3)}>{showAll3 ? 'Show fewer' : `Show all ${t3.length}`}</button>
            {/if}
          {:else}
            <p class="empty">No text-mined mentions beyond the papers above.</p>
          {/if}
        </div>
      {/if}
    </div>

    {#if cohort.refs.length}
      <div class="tier">
        {@render tierHead(4, 'Source studies', 'Cohort', live(cohort.refs), 'Publications describing the TCGA cohorts this variant was observed in. Provenance, not evidence about the variant.')}
        {#if open[4]}
          <div transition:slide={{ duration: dur, easing: cubicOut }}>
            <ul class="refs">
              {#each cohort.refs as e (e.pmid)}{@render refRow(e, null)}{/each}
            </ul>
          </div>
        {/if}
      </div>
    {/if}
  </section>

  <nav class="links" aria-label="External resources">
    {#if cv}<a href="https://www.ncbi.nlm.nih.gov/clinvar/variation/{cv.id}/" target="_blank" rel="noopener">ClinVar {cv.vcv}</a>{/if}
    {#if germ?.rs}<a href="https://www.ncbi.nlm.nih.gov/snp/rs{germ.rs}" target="_blank" rel="noopener">dbSNP rs{germ.rs}</a>{/if}
    {#if gnomad}<a href={gnomad} target="_blank" rel="noopener">gnomAD</a>{/if}
    <a href="https://www.uniprot.org/uniprotkb/{gene.uniprot.accession}/variant-viewer" target="_blank" rel="noopener">UniProt</a>
    {#if short}<a href="https://cancer.sanger.ac.uk/cosmic/search?q={symbol}+{encodeURIComponent(short)}" target="_blank" rel="noopener">COSMIC</a>{/if}
    {#if simpleMissense}<a href="https://www.oncokb.org/gene/{symbol}/{short}" target="_blank" rel="noopener">OncoKB</a>{/if}
    <span class="muted small">COSMIC and OncoKB are linked, not redistributed.</span>
  </nav>
</article>

<style>
  .mp {
    margin: 14px 0 8px; border-radius: 14px; background: var(--surface-2); border: 1px solid var(--line);
    overflow: hidden; box-shadow: inset 4px 0 0 var(--cls);
  }
  .mp > * { padding-left: 18px; padding-right: 16px; }
  .mp-head { display: flex; justify-content: space-between; gap: 10px; padding-top: 14px; }
  .eyebrow { margin: 0; font-size: 11.5px; letter-spacing: 0.07em; text-transform: uppercase; color: var(--ink-3); font-weight: 600; }
  h3 { font-size: 21px; margin: 2px 0 0; letter-spacing: -0.01em; }
  .aliases { margin: 2px 0 0; font-size: 13px; color: var(--ink-2); }
  .close { font-size: 22px; line-height: 1; color: var(--ink-3); padding: 0 4px; align-self: start; }
  .close:hover { color: var(--ink); text-decoration: none; }

  .class-strip { padding-top: 10px; padding-bottom: 10px; }
  .cls-main { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .cls-pill {
    display: inline-block; padding: 3px 12px; border-radius: 999px; font-weight: 600; font-size: 13.5px;
    background: var(--cls); color: #fff; animation: pop 420ms cubic-bezier(.3,1.6,.5,1) both;
  }
  .cls-pill.neutral { background: var(--line-2); color: var(--ink); }
  .stars { color: var(--c-conf); letter-spacing: 1px; font-size: 13px; }
  .small { font-size: 12.5px; margin: 4px 0 0; }
  @keyframes pop { from { transform: scale(0.6); opacity: 0; } }

  .facts { display: grid; grid-template-columns: auto 1fr; gap: 5px 14px; margin: 0; padding-top: 4px; padding-bottom: 10px; font-size: 13.5px; }
  dt { color: var(--ink-3); }
  dd { margin: 0; overflow-wrap: anywhere; }
  .studies { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 5px; }
  .studies .chip { font-size: 11.5px; padding: 0 8px; }

  .same { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; padding-bottom: 12px; }
  .same .chip { cursor: pointer; font-size: 12px; }
  .same .chip i { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }

  .evidence { border-top: 1px solid var(--line); padding-top: 12px; padding-bottom: 6px; }
  h4 { font-size: 12.5px; text-transform: uppercase; letter-spacing: 0.07em; color: var(--ink-2); margin: 0 0 6px; }
  .tier { border-bottom: 1px solid var(--line); }
  .tier:last-child { border-bottom: 0; }
  .tier-head {
    all: unset; box-sizing: border-box; width: 100%; display: flex; align-items: center; gap: 10px;
    padding: 9px 0; cursor: pointer;
  }
  .tier-head:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; border-radius: 6px; }
  .badge { font-size: 11px; font-weight: 700; padding: 1px 8px; border-radius: 6px; letter-spacing: 0.02em; min-width: 46px; text-align: center; }
  .badge.t1 { background: var(--accent); color: var(--accent-ink); }
  .badge.t2 { border: 1.5px solid var(--accent); color: var(--accent); }
  .badge.t3 { border: 1.5px dashed var(--ink-3); color: var(--ink-3); }
  .badge.t4 { background: var(--bg-2); color: var(--ink-2); }
  .tier-label { font-weight: 600; font-size: 14px; }
  .tier-count { margin-left: auto; color: var(--ink-3); font-size: 13px; }
  .chev { color: var(--ink-3); font-size: 18px; transition: transform 250ms cubic-bezier(.3,1.4,.5,1); }
  .chev.open { transform: rotate(90deg); }
  .tier-note { margin: -4px 0 8px; font-size: 12px; color: var(--ink-3); }

  .refs { list-style: none; padding: 0; margin: 0 0 8px; display: grid; gap: 8px; }
  .ref { font-size: 13px; animation: rise 360ms cubic-bezier(.2,.9,.3,1.2) both; }
  .ref:nth-child(2) { animation-delay: 40ms; } .ref:nth-child(3) { animation-delay: 80ms; }
  .ref:nth-child(4) { animation-delay: 120ms; } .ref:nth-child(n+5) { animation-delay: 160ms; }
  @keyframes rise { from { opacity: 0; transform: translateY(6px); } }
  .ref-who { font-weight: 600; }
  .ref-title { color: var(--ink-2); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .ref.retracted .ref-title, .ref.retracted .ref-who { text-decoration: line-through; opacity: 0.7; }
  .flag { margin-left: 6px; font-size: 11px; font-weight: 700; color: #fff; background: var(--c-plp); border-radius: 4px; padding: 0 6px; }
  .method { margin-left: 6px; font-size: 11px; font-weight: 600; color: var(--ink-2); border: 1px dashed var(--line-2); border-radius: 4px; padding: 0 6px; }
  .ref:has(.method) .ref-title { opacity: 0.7; }
  .by { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 3px; }
  .src { font-size: 11.5px; border-radius: 6px; padding: 1px 7px; }
  .src.solid { background: color-mix(in srgb, var(--accent) 16%, transparent); color: var(--ink); }
  .src.outline { border: 1px solid var(--line-2); color: var(--ink-2); }
  .src.grey { background: var(--bg-2); color: var(--ink-3); }
  a.src:hover { text-decoration: none; filter: brightness(0.96); }
  .mined .ref-who { color: var(--ink-2); }
  .src .stars { font-size: 10.5px; }
  .empty, .pending { font-size: 12.5px; color: var(--ink-3); margin: 0 0 10px; }
  .pending { font-style: italic; }
  .more { all: unset; cursor: pointer; font-size: 12.5px; color: var(--accent); margin: 0 0 10px; display: inline-block; }
  .more:hover { text-decoration: underline; }

  .links { display: flex; flex-wrap: wrap; gap: 6px 14px; align-items: center; border-top: 1px solid var(--line); padding-top: 10px; padding-bottom: 12px; font-size: 13px; }
</style>
