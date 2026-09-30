<script>
  // App shell. One persistent 3D stage is shared by the character-select screen
  // and the complex view, so moving between them (and into a subunit) is a
  // continuous camera move, never a page swap. The side panel cross-fades.
  //
  // Routes: #/ (select) · #/cBAF · #/cBAF/SMARCA4 · #/gene/SMARCA4[/p.Arg1192His]
  // Keys:   ←/→ choose complex · Enter select · Esc back out one level
  import { fly, fade } from 'svelte/transition';
  import { backOut, cubicOut } from 'svelte/easing';
  import { Tween } from 'svelte/motion';
  import Complex3D from './lib/Complex3D.svelte';
  import Cartoon2D from './lib/Cartoon2D.svelte';
  import Compare from './lib/Compare.svelte';
  import Lollipop from './lib/Lollipop.svelte';
  import MutationPanel from './lib/MutationPanel.svelte';
  import MorphOverlay from './lib/MorphOverlay.svelte';
  import SuggestButton from './lib/SuggestButton.svelte';
  import SuggestSheet from './lib/SuggestSheet.svelte';
  import { suggest, closeSuggest } from './lib/suggest.svelte.js';
  import { affinageUrl } from './lib/config.js';
  import { route, href, go } from './lib/router.svelte.js';
  import * as data from './lib/data.js';
  import { colorOf, classKey, CLASS_ORDER, CLASS_COLOR } from './lib/colors.js';
  import { tip } from './lib/tip.js';
  import { CLINVAR_TIP, cancerName } from './lib/glossary.js';
  import CitationsSheet from './lib/CitationsSheet.svelte';

  // 3D models: the small index (structure, chain symbols) and cBAF's beads load
  // up front; PBAF / ncBAF beads are separate chunks prefetched once idle.
  import MODEL_INDEX from './lib/models/index.json';
  import cBAFModel from './lib/models/cBAF.json';
  const LAZY_MODELS = import.meta.glob(['./lib/models/*.json', '!./lib/models/cBAF.json', '!./lib/models/index.json'],
    { import: 'default' });
  let models = $state.raw({ cBAF: cBAFModel });

  // Stage view: spinning 3D model or flat 2D cartoon (complex view only; the
  // select screen always spins). Remembered per browser; cartoon is forced when
  // WebGL is unavailable.
  const CARTOONS = import.meta.glob('./lib/cartoons/*.json', { import: 'default' });
  let cartoons = $state.raw({});
  let viewMode = $state((() => { try { return localStorage.getItem('stageMode') || '3d'; } catch { return '3d'; } })());
  let noGL = $state(false);
  let cartoonScale = $state((() => { try { return localStorage.getItem('cartoonScale') || 'fit'; } catch { return 'fit'; } })());
  $effect(() => { try { localStorage.setItem('cartoonScale', cartoonScale); } catch {} });
  $effect(() => { try { localStorage.setItem('stageMode', viewMode); } catch {} });
  const showCartoon = $derived((viewMode === 'cartoon' || noGL) && view.kind === 'complex');
  function loadCartoon(id) {
    if (cartoons[id]) return;
    CARTOONS[`./lib/cartoons/${id}.json`]?.().then((c) => { cartoons = { ...cartoons, [id]: c }; });
  }
  $effect(() => {
    if (view.kind === 'compare') TABS.forEach(loadCartoon);
    else if (view.kind === 'complex' && (viewMode === 'cartoon' || noGL)) loadCartoon(view.id);
  });
  let cartoonEl = $state();
  const loading = {};
  function loadModel(id) {
    if (models[id]) return Promise.resolve(models[id]);
    const f = LAZY_MODELS[`./lib/models/${id}.json`];
    if (!f) return Promise.reject(new Error(`no 3D model for ${id}`));
    return (loading[id] ??= f().then((m) => { models = { ...models, [id]: m }; return m; }));
  }
  $effect(() => {
    const idle = window.requestIdleCallback ?? ((cb) => setTimeout(cb, 1200));
    idle(() => TABS.forEach((id) => loadModel(id).catch(() => {})));
  });
  const TABS = ['cBAF', 'PBAF', 'ncBAF'];
  // Variant classes drawn on the lollipop (mirrors pipeline/build.py SHOWN).
  const SHOWN = new Set(['missense', 'truncating', 'inframe', 'splice', 'stop_lost']);

  let comp = $state(null);
  let baseRefs = $state({});     // composition + cohort papers (refs.json)
  let geneRefs = $state({});     // variant-level papers for the open gene (<GENE>.refs.json)
  const refs = $derived({ ...baseRefs, ...geneRefs });
  let manifest = $state(null);
  let loadError = $state(null);
  // Subunits with mutation data: whatever the data build produced.
  const DATA_GENES = $derived(manifest ? Object.keys(manifest.genes) : []);

  $effect(() => {
    Promise.all([data.complexes(), data.refs(), data.manifest()])
      .then(([c, r, m]) => { comp = c; baseRefs = r; manifest = m; })
      .catch((e) => { loadError = e.message; });
  });

  // ---- routing -------------------------------------------------------------
  const view = $derived.by(() => {
    const [a, b, c] = route.parts;
    if (!a) return { kind: 'select' };
    if (a === 'compare') return { kind: 'compare' };
    if (a === 'gene' && b) return { kind: 'gene', sym: b, pchange: c ?? null };
    if (TABS.includes(a)) return { kind: 'complex', id: a, sym: b ?? null, pchange: (b && c) || null };
    return { kind: 'missing', path: route.parts.join('/') };
  });

  // Character select: which complex is previewed on the stage.
  let pickId = $state('cBAF');
  const onStage = $derived(view.kind === 'select' || view.kind === 'complex');
  const stageId = $derived(view.kind === 'complex' ? view.id : pickId);
  $effect(() => { if (view.kind === 'complex') pickId = view.id; });
  // Keep showing the last model until the requested one arrives (then it beams in).
  let shownModel = $state.raw(cBAFModel);
  $effect(() => {
    const id = stageId;
    if (models[id]) shownModel = models[id];
    else loadModel(id).then((m) => { if (stageId === id) shownModel = m; }).catch(() => {});
  });

  // Stage -> domain-map morph: Complex3D hands over the selected subunit's
  // bead positions; the overlay flies them to the Lollipop once it is ready.
  let overlay;
  let morphSrc = $state.raw(null);   // {sym, points, color} while a morph is pending
  let lolli = $state.raw(null);      // target API of the mounted Lollipop
  function startMorph(src) {
    if (!DATA_GENES.includes(src.sym)) return;
    morphSrc = src;
    overlay?.run(src, () => {
      if (lolli?.gene !== src.sym) return null;
      return { geometry: lolli.geometry, reveal: () => { lolli.reveal(); if (morphSrc === src) morphSrc = null; } };
    });
  }
  $effect(() => { if (morphSrc && morphSrc.sym !== sym) { overlay?.cancel(); morphSrc = null; } });

  let hot3d = $state(null);     // subunit under the cursor in 3D
  let hotList = $state(null);   // subunit under the cursor in the side panel

  function onpick(s) {
    if (s === '__complex__') return go(pickId);
    if (view.kind !== 'complex') return;
    if (!s) return sym ? go(view.id) : null;
    const sl = slotFor(complex, s);
    // open the slot member that has mutation data when the modelled one has none
    const t = DATA_GENES.includes(s) ? s : sl?.members.find((m) => DATA_GENES.includes(m)) ?? s;
    go(`${view.id}/${t}`);
  }

  // Context for a "Suggest edit" button: what the section shows right now.
  function sctx(subject, section, current) {
    return () => ({ subject, section, dataVersion: manifest?.data_version,
                    current: typeof current === 'function' ? current() : current });
  }
  const refList = (pmids) => [...new Set(pmids ?? [])].map((p) => `PMID ${p}`).join(', ');

  // ---- citations sheet: every source behind one subunit page ---------------------
  let citeFor = $state(null);          // {s, c} while the sheet is open
  const uniq = (a) => [...new Set(a.filter(Boolean))];
  function citationGroups(s, c) {
    const groups = [];
    const sl = c && slotFor(c, s.symbol);
    if (sl) {
      const notes = (sl.contested_notes ?? []).flatMap((n) => n.pmids);
      groups.push({ title: `Membership in ${c.id}`, note: `${s.symbol} fills the ${sl.slot} slot`
          + (sl.members.length > 1 ? ` (with ${sl.members.filter((m) => m !== s.symbol).join(', ')})` : '') + '.',
        items: uniq([...sl.pmids, ...notes]).map((pmid) => ({ pmid })) });
    }
    if (c) {
      const m = models[c.id], idx = MODEL_INDEX[c.id];
      const own = m?.chains.find((ch) => ch.symbol === s.symbol);
      const items = [];
      if (own?.source) items.push({ pmid: own.source.pmid, label: `${s.symbol} placed from PDB ${own.source.pdb} by superposition` });
      else if (own || idx?.chains.some((ch) => ch.symbol === s.symbol)) items.push({ pmid: idx.pmid, label: `3D model: PDB ${idx.pdb}` });
      groups.push({ title: 'Structure', note: items.length ? '' : `${s.symbol} is not resolved in the ${c.id} structure (PDB ${idx?.pdb}).`, items });
    }
    if (gene?.civic?.length) groups.push({ title: 'Clinical evidence (CIViC)',
      items: Object.values(gene.civic.reduce((by, e) => {
        (by[e.pmid] ??= { pmid: e.pmid, eids: [] }).eids.push(`EID${e.eid} ${e.civic_variant}`); return by;
      }, {})).map(({ pmid, eids }) => ({ pmid, label: eids.join('; ') })) });
    const src = manifest?.sources ?? {};
    const data = [];
    data.push({ text: `UniProtKB ${s.uniprot}`, url: `https://www.uniprot.org/uniprotkb/${s.uniprot}`,
      detail: `release ${src.uniprot?.release ?? ''}, ${src.uniprot?.license ?? ''}; sequence, domains, UniProt variants` });
    if (src.interpro) data.push({ text: 'InterPro / Pfam', url: `https://www.ebi.ac.uk/interpro/protein/UniProt/${s.uniprot}/`,
      detail: `InterPro ${src.interpro.interpro?.version ?? ''}, Pfam ${src.interpro.pfam?.version ?? ''}; domains UniProt does not annotate` });
    if (DATA_GENES.includes(s.symbol)) {
      data.push({ text: 'NCBI ClinVar', url: `https://www.ncbi.nlm.nih.gov/clinvar/?term=${s.symbol}%5Bgene%5D`,
        detail: `updated ${src.clinvar?.last_update ?? ''}; germline classifications` });
      if (tcga) data.push({ text: 'TCGA PanCancer Atlas via cBioPortal', url: 'https://www.cbioportal.org/',
        detail: `cBioPortal ${src.cbioportal?.portal_version ?? ''}, ${src.cbioportal?.license ?? ''}; somatic mutations`,
        pmids: uniq(Object.values(tcga.per_study).flatMap((st) => st.pmids ?? [])) });
      if (src.litvar2) data.push({ text: 'NCBI LitVar2', url: 'https://www.ncbi.nlm.nih.gov/research/litvar2/',
        detail: 'variant-to-paper links (per-variant citations are listed on each variant)' });
      if (src.ensembl_vep) data.push({ text: 'Ensembl VEP', url: 'https://www.ensembl.org/vep',
        detail: `release ${src.ensembl_vep.software}; variant consequences and MANE numbering` });
    }
    groups.push({ title: 'Data sources', items: data });
    return groups;
  }

  function onkey(e) {
    if (suggest.open) { if (e.key === 'Escape') closeSuggest(); return; }
    if (e.target.closest?.('input, textarea')) return;
    if (e.key === 'Escape') {
      if (view.kind === 'complex' && view.sym) go(view.id);
      else if (view.kind === 'complex' || view.kind === 'compare') location.hash = '#/';
    } else if (view.kind === 'select' && (e.key === 'ArrowRight' || e.key === 'ArrowLeft')) {
      const i = TABS.indexOf(pickId), d = e.key === 'ArrowRight' ? 1 : -1;
      pickId = TABS[(i + d + TABS.length) % TABS.length];
    } else if (view.kind === 'select' && e.key === 'Enter' && !e.target.closest?.('a, button')) {
      go(pickId);
    }
  }

  // Character-card stats, scaled against the largest complex.
  function stats(id) {
    const c = comp.complexes[id], m = MODEL_INDEX[id];
    const inModel = new Set(m.chains.map((ch) => ch.symbol));
    return [
      { k: 'Subunit slots', v: c.slots.length, max: 12 },
      { k: 'Paralog combinations', v: c.slots.reduce((a, sl) => a * sl.members.length, 1), max: 1728, log: true },
      { k: 'Slots resolved in ' + m.pdb, v: c.slots.filter((sl) => sl.members.some((x) => inModel.has(x))).length, max: c.slots.length },
      { k: 'Subunits with mutation data', v: c.slots.flatMap((sl) => sl.members).filter((x) => DATA_GENES.includes(x)).length,
        max: c.slots.flatMap((sl) => sl.members).length },
    ];
  }

  const complex = $derived(view.kind === 'complex' && comp ? { id: view.id, ...comp.complexes[view.id] } : null);
  const sym = $derived(view.kind === 'complex' || view.kind === 'gene' ? view.sym : null);
  const subunit = $derived(sym && comp ? comp.subunits[sym] ?? null : null);

  // ---- per-gene data (loaded on demand) ------------------------------------
  let gene = $state(null);
  let tcga = $state(null);
  $effect(() => {
    const s = sym;
    gene = null; tcga = null; geneRefs = {};
    if (!s || !DATA_GENES.includes(s)) return;
    data.gene(s).then((g) => { if (sym === s) gene = g; });
    data.geneRefs(s).then((r) => { if (sym === s) geneRefs = r; }).catch(() => {});
    data.tcga(s).then((t) => { if (sym === s) tcga = t; });
  });

  const classCounts = $derived.by(() => {
    if (!gene) return null;
    const n = Object.fromEntries(CLASS_ORDER.map((k) => [k, 0]));
    for (const v of gene.variants) if (SHOWN.has(v.cls) || v.up) n[classKey(v)]++;
    return n;
  });
  const classTotal = $derived(classCounts ? Object.values(classCounts).reduce((a, b) => a + b, 0) : 0);

  const topStudies = $derived.by(() => {
    if (!tcga) return [];
    return Object.values(tcga.per_study)
      .filter((s) => s.k > 0 && s.n >= 50)
      .sort((a, b) => b.k / b.n - a.k / a.n)
      .slice(0, 6);
  });

  // Variant named in the route: germline (ClinVar/UniProt) and/or TCGA somatic.
  const variant = $derived.by(() => {
    if (!view.pchange || !gene) return null;
    const q = view.pchange;
    const germ = gene.variants.find((v) => v.p === q || v.mane === q) ?? null;
    const som = tcga?.variants.find((v) => v.p === q || v.mane === q) ?? null;
    if (!germ && !som) return 'none';
    return { ...(germ ?? som), germ, som };
  });
  const variantBase = $derived(view.kind === 'complex' ? view.id : 'gene');
  function selectVariant(p) { if (p && sym) go(`${variantBase}/${sym}/${p}`); }

  // ---- motion --------------------------------------------------------------
  const reduce = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const ms = (d) => (reduce ? 0 : d);
  // Numbers count up when a subunit card opens.
  const freqT = new Tween(0, { duration: ms(1100), easing: cubicOut });
  const totalT = new Tween(0, { duration: ms(900), easing: cubicOut });
  $effect(() => { freqT.set(0, { duration: 0 }); if (tcga) freqT.target = tcga.k / tcga.n; });
  $effect(() => { totalT.set(0, { duration: 0 }); if (classCounts) totalT.target = classTotal; });

  // ---- helpers -------------------------------------------------------------
  // Wilson score interval, 95%.
  function wilson(k, n, z = 1.96) {
    if (!n) return [0, 0];
    const p = k / n, d = 1 + (z * z) / n;
    const c = (p + (z * z) / (2 * n)) / d;
    const h = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / d;
    return [Math.max(0, c - h), Math.min(1, c + h)];
  }
  const pct = (x, d = 1) => (100 * x).toFixed(d) + '%';

  function refShort(pmid) {
    const r = refs[pmid];
    return r ? `${r.first_author.split(' ')[0]} ${r.year}` : `PMID ${pmid}`;
  }

  function slotFor(c, s) { return c?.slots.find((sl) => sl.members.includes(s)); }

  function contestedNote(slot, member) {
    return (slot.contested_notes ?? []).find((n) =>
      n.member == null || n.member === member || (Array.isArray(n.member) && n.member.includes(member)));
  }

  // ---- theme ---------------------------------------------------------------
  const THEMES = ['system', 'light', 'dark'];
  let theme = $state((() => { try { return localStorage.getItem('theme') || 'system'; } catch { return 'system'; } })());
  $effect(() => {
    const el = document.documentElement;
    if (theme === 'system') delete el.dataset.theme; else el.dataset.theme = theme;
    try { localStorage.setItem('theme', theme); } catch {}
  });
</script>

{#snippet cite(pmids)}
  <span class="cites">
    {#each [...new Set(pmids)] as p (p)}
      {@const r = refs[p]}
      <a class="cite" class:retracted={r?.retracted} href="https://pubmed.ncbi.nlm.nih.gov/{p}/"
         target="_blank" rel="noopener" title={r ? r.text : `PMID ${p}`}>
        {refShort(p)}{#if r?.retracted}<span class="sr-only"> (retracted)</span> ⚠{/if}
      </a>
    {/each}
  </span>
{/snippet}

{#snippet composition(c)}
  <section class="card panel">
    <header class="panel-head">
      <p class="eyebrow">{c.species} · {c.structures.map((s) => s.pdb).join(', ')}</p>
      <h2>{c.name} <span class="muted">({c.id})</span></h2>
      <p class="defined">Defined by {@render cite(c.defining_pmids)}</p>
    </header>
    <ol class="slots">
      {#each c.slots as sl (sl.slot)}
        <li class="slot">
          <div class="slot-name">
            {sl.slot}
            {#if sl.contested}<span class="chip warn" title="Literature disagrees; see notes">contested</span>{/if}
            <span class="grow"></span>
            <SuggestButton compact ctx={sctx(`${sl.members.join(' | ')} in ${c.id}`, `Complex composition · ${sl.slot} slot`,
              () => [`Members: ${sl.members.join(', ')}`, sl.stoichiometry && `Stoichiometry: ${sl.stoichiometry}`,
                     sl.contested && `Contested: ${(sl.contested_notes ?? []).map((n) => n.claim).join(' / ')}`,
                     `Sources: ${refList(sl.pmids)}`].filter(Boolean).join('\n'))} />
          </div>
          <div class="members">
            {#each sl.members as m (m)}
              {@const note = contestedNote(sl, m)}
              <a class="member" href={href(c.id, m)} class:has-data={DATA_GENES.includes(m)}
                 class:hot={hot3d === m} onmouseenter={() => (hotList = m)} onmouseleave={() => (hotList = null)}
                 class:contested={note && note.member != null}>
                <span class="swatch" style:background={colorOf(m)}></span>{m}
              </a>
            {/each}
          </div>
          {#if sl.stoichiometry}<p class="note">{sl.stoichiometry}</p>{/if}
          {#each sl.contested_notes ?? [] as n}
            <p class="note contest">{n.claim} {@render cite(n.pmids)}
              {#if n.needs_review}<span class="chip review">needs review</span>{/if}</p>
          {/each}
          <p class="slot-cite">{@render cite(sl.pmids)}</p>
        </li>
      {/each}
    </ol>
    {#if c.absent?.length}
      <p class="absent"><span class="muted">Not in {c.id}:</span> {c.absent.join(', ')}
        <SuggestButton compact ctx={sctx(c.id, 'Subunits absent from this complex', `Not in ${c.id}: ${c.absent.join(', ')}`)} /></p>
    {/if}
    <p class="legend"><span class="dot"></span> mutation data available</p>
  </section>
{/snippet}

{#snippet subunitPanel(s, c)}
  {@const sl = slotFor(c, s.symbol)}
  <section class="card panel">
    <header class="panel-head">
      <div class="head-suggest">
        <button class="btn cite-btn" onclick={() => (citeFor = { s, c })}>Citations</button>
        <SuggestButton ctx={sctx(s.symbol, 'Subunit identity (name, aliases, identifiers)',
          () => [`Symbol: ${s.symbol}${s.common_name ? ` (${s.common_name})` : ''}`, `Name: ${s.name}`,
                 `UniProt: ${s.uniprot} (${s.uniprot_length} aa)`, `HGNC: ${s.hgnc_id}`,
                 `Aliases: ${(s.aliases ?? []).join(', ') || '-'}`,
                 `Previous symbols: ${(s.previous_symbols ?? []).join(', ') || '-'}`].join('\n'))} />
      </div>
      <p class="eyebrow">
        {#if c}<a href={href(c.id)}>← {c.id}</a> · {/if}
        {sl ? sl.slot : 'subunit'}
      </p>
      <h2><span class="swatch lg" style:background={colorOf(s.symbol)}></span>{s.symbol}
        {#if s.common_name && s.common_name !== s.symbol}<span class="muted">({s.common_name})</span>{/if}</h2>
      <p class="fullname">{s.name}</p>
      <p class="ids">
        <a href="https://www.uniprot.org/uniprotkb/{s.uniprot}" target="_blank" rel="noopener" class="mono">{s.uniprot}</a>
        · {s.uniprot_length} aa
        · <a href="https://www.genenames.org/data/gene-symbol-report/#!/hgnc_id/{s.hgnc_id}" target="_blank" rel="noopener" class="mono">{s.hgnc_id}</a>
      </p>
      {#if s.aliases?.length}<p class="aliases muted">Also: {s.aliases.join(', ')}</p>{/if}
      <p class="learn">
        <span class="muted">Learn more on Affinage:</span>
        {#each [s.symbol, ...(sl?.members ?? []).filter((m) => m !== s.symbol)] as m, i (m)}
          {#if i}<span class="muted" aria-hidden="true">·</span>{/if}
          <a href={affinageUrl(m)} target="_blank" rel="noopener" class:self={m === s.symbol}
             title="{m} on Affinage: mechanistic annotation from the literature{m === s.symbol ? '' : ' (paralog in this slot)'}">
            {m}<span aria-hidden="true"> ↗</span>
          </a>
        {/each}
      </p>
    </header>

    {#if sl && sl.members.length > 1}
      <p class="paralogs">Shares the <b>{sl.slot}</b> slot with
        {#each sl.members.filter((m) => m !== s.symbol) as m, i}{#if i}, {/if}<a href={href(c.id, m)}>{m}</a>{/each}
        <SuggestButton compact ctx={sctx(`${s.symbol} in ${c.id}`, `Complex membership · ${sl.slot} slot`,
          () => `Slot ${sl.slot} in ${c.id}: ${sl.members.join(', ')}\nSources: ${refList(sl.pmids)}`)} /></p>
    {/if}

    {#if !DATA_GENES.includes(s.symbol)}
      <p class="empty">No mutation data for {s.symbol} yet.
        <SuggestButton label="Suggest data to include" ctx={sctx(s.symbol, 'Mutation and disease data', 'No mutation data shown yet')} /></p>
    {:else if !gene}
      <p class="empty">Loading {s.symbol} variants…</p>
    {:else}
      {#if !gene.projection.alignment.identical}
        <p class="note isoform">
          Positions are on UniProt canonical ({gene.uniprot.length} aa). MANE Select
          {gene.projection.mane_select.refseq} is {gene.projection.mane_select.length} aa, so MANE numbering
          differs after residue {gene.projection.alignment.blocks[0][2]}. Both notations are shown per variant.
        </p>
      {/if}

      <div class="sub-row">
        <h3 class="sub">Domain map & mutations</h3>
        <SuggestButton ctx={sctx(s.symbol, 'Domain map & mutations',
          () => 'Domains: ' + (gene.features.filter((f) => f.type === 'Domain' || f.type === 'Repeat')
            .map((f) => `${f.desc} ${f.start}–${f.end}`).join('; ') || '-')
            + `\nUniProt ${gene.uniprot.accession} release entry v${gene.uniprot.entry_version}; InterPro/Pfam where UniProt has none`)} />
      </div>
      <Lollipop {gene} {tcga} color={colorOf(s.symbol)} selectedP={view.pchange} onselect={selectVariant}
                awaitMorph={morphSrc?.sym === s.symbol} onready={(api) => (lolli = api)} />

      {#if view.pchange}
        {#key view.pchange}
          <div in:fly={{ y: 14, duration: ms(420), easing: backOut }}>
            {#if variant === 'none'}
              <p class="variant"><b class="mono">{view.pchange}</b> is not among the mapped {s.symbol} variants.</p>
            {:else if variant}
              <MutationPanel {variant} {gene} {tcga} {refs} symbol={s.symbol} civicGene={gene.civic ?? []}
                             dataVersion={manifest?.data_version}
                             closeHref={href(variantBase, s.symbol)} onselect={selectVariant} />
            {/if}
          </div>
        {/key}
      {/if}

      <div class="sub-row">
        <h3 class="sub">ClinVar & UniProt variants <span class="muted num">({Math.round(totalT.current)})</span></h3>
        <SuggestButton ctx={sctx(s.symbol, 'ClinVar & UniProt variant summary',
          () => CLASS_ORDER.map((k) => `${k}: ${classCounts[k]}`).join(', ') + ` (ClinVar ${manifest?.sources.clinvar.last_update ?? ''})`)} />
      </div>
      <div class="stack" role="img" aria-label={CLASS_ORDER.map((k) => `${k} ${classCounts[k]}`).join(', ')}>
        {#each CLASS_ORDER as k}
          {#if classCounts[k]}<span style:flex-grow={classCounts[k]} style:background={CLASS_COLOR[k]}></span>{/if}
        {/each}
      </div>
      <ul class="stack-legend">
        {#each CLASS_ORDER as k}
          <li><span class="dot" style:background={CLASS_COLOR[k]}></span><span class="has-tip" use:tip={CLINVAR_TIP[k]}>{k}</span> <span class="num muted">{classCounts[k]}</span></li>
        {/each}
      </ul>

      {#if tcga}
        {@const [lo, hi] = wilson(tcga.k, tcga.n)}
        <div class="sub-row">
          <h3 class="sub">TCGA PanCancer Atlas</h3>
          <SuggestButton ctx={sctx(s.symbol, 'TCGA PanCancer Atlas frequency',
            () => `${tcga.k} / ${tcga.n} patients (${pct(tcga.k / tcga.n)}); top: `
              + topStudies.map((st) => `${st.cancer_type.toUpperCase()} ${st.k}/${st.n}`).join(', '))} />
        </div>
        <p class="freq">
          <b class="num">{pct(freqT.current)}</b>
          <span class="num muted">{tcga.k.toLocaleString()} / {tcga.n.toLocaleString()} patients · 95% CI {pct(lo)}–{pct(hi)}</span>
        </p>
        <table class="studies">
          <tbody>
            {#each topStudies as st (st.cancer_type)}
              {@const [l2, h2] = wilson(st.k, st.n)}
              <tr>
                <td class="ct"><span class="has-tip" use:tip={`${cancerName(st)} · ${st.k} of ${st.n} patients, 95% CI ${pct(l2)}–${pct(h2)}`}>{st.cancer_type.toUpperCase()}</span></td>
                <td class="bar"><span style:width={pct(Math.min(1, st.k / st.n / 0.25))}></span></td>
                <td class="num">{pct(st.k / st.n)}</td>
                <td class="num muted">{st.k}/{st.n}</td>
              </tr>
            {/each}
          </tbody>
        </table>
        <p class="muted small">Protein-affecting mutations, one count per patient; denominator is patients profiled for {s.symbol}. Cancer types with n ≥ 50 shown; bars are scaled to 25%.</p>
      {/if}

      {#if gene.civic?.length}
        <div class="sub-row">
          <h3 class="sub">Clinical evidence · CIViC <span class="muted num">({gene.civic.length})</span></h3>
          <SuggestButton ctx={sctx(s.symbol, 'Clinical evidence (CIViC)',
            () => gene.civic.map((e) => `EID${e.eid} ${e.civic_variant}: ${e.type} ${e.level}, ${e.significance}, ${e.disease} (PMID ${e.pmid})`).join('\n'))} />
        </div>
        <p class="muted small">Accepted CIViC evidence about {s.symbol} as a whole (a category such as loss or inactivating
          mutation), not about any single variant.</p>
        <ul class="civic">
          {#each gene.civic as e (e.eid)}
            <li>
              <div class="civic-top">
                <span class="lvl lvl-{e.level}" title="CIViC evidence level {e.level}">{e.level}</span>
                <b>{e.civic_variant}</b>
                <span class="muted">· {e.type} · {e.significance}</span>
              </div>
              <div class="civic-dis">{e.disease}{#if e.therapies}{' · '}<i>{e.therapies}</i>{/if}</div>
              <div class="small"><a href={e.url} target="_blank" rel="noopener">EID{e.eid}</a></div>
            </li>
          {/each}
        </ul>
      {/if}

    {/if}
  </section>
{/snippet}

{#snippet selectPanel()}
  {@const c = comp.complexes[pickId]}
  <section class="card panel select-panel">
    <p class="eyebrow">Choose a complex</p>
    <div class="who">
      {#key pickId}
        <h2 class="big" in:fly={{ y: 14, duration: ms(380), easing: backOut }}>{pickId}</h2>
      {/key}
      <p class="fullname">{c.name} · <span class="muted">{c.species}</span></p>
    </div>
    <ul class="stats">
      {#each stats(pickId) as st (st.k)}
        <li>
          <span class="st-k">{st.k}</span>
          <span class="st-bar"><span style:width={pct(st.log ? Math.log(st.v) / Math.log(st.max) : st.v / st.max)}></span></span>
          <span class="st-v num">{st.v.toLocaleString()}</span>
        </li>
      {/each}
    </ul>
    <div class="roster" role="listbox" aria-label="Complexes">
      {#each TABS as id (id)}
        <a class="pick" href={href(id)} role="option" aria-selected={pickId === id}
           class:on={pickId === id}
           onmouseenter={() => (pickId = id)} onfocus={() => (pickId = id)}>
          <span class="pick-dots" aria-hidden="true">
            {#each comp.complexes[id].slots.slice(0, 6) as sl}<i style:background={colorOf(sl.members[0])}></i>{/each}
          </span>
          <b>{id}</b>
          <span class="muted">{MODEL_INDEX[id].pdb}</span>
        </a>
      {/each}
    </div>
    <div class="go-row">
      <a class="btn go" href={href(pickId)}>Select {pickId} <span aria-hidden="true">▶</span></a>
      <span class="muted small">←/→ to browse · Enter to select · Esc to back out</span>
    </div>
  </section>
{/snippet}

<svelte:window onkeydown={onkey} />
<MorphOverlay bind:this={overlay} />
<SuggestSheet />
{#if citeFor}
  <CitationsSheet subject="{citeFor.s.symbol}{citeFor.c ? ` in ${citeFor.c.id}` : ''}" groups={citationGroups(citeFor.s, citeFor.c)}
                  {refs} onclose={() => (citeFor = null)} />
{/if}

<header class="top">
  <a class="brand" href="#/">
    <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden="true">
      <circle cx="12" cy="14" r="9" fill="#0e7c86" /><circle cx="21" cy="18" r="8" fill="#d9822b" fill-opacity=".85" />
    </svg>
    BAF-portal
  </a>
  <nav aria-label="Complexes">
    {#each TABS as t}
      <a href={href(t)} class="tab" aria-current={view.id === t ? 'page' : undefined}>{t}</a>
    {/each}
    <a href={href('compare')} class="tab" aria-current={view.kind === 'compare' ? 'page' : undefined}
       title="cBAF, PBAF and ncBAF side by side">Compare</a>
  </nav>
  <button class="btn theme" onclick={() => (theme = THEMES[(THEMES.indexOf(theme) + 1) % 3])}
          aria-label="Colour theme: {theme}. Change.">
    {theme === 'dark' ? '☾' : theme === 'light' ? '☀' : '◐'} <span class="theme-name">{theme}</span>
  </button>
</header>

<main>
  {#if loadError}
    <div class="card panel error">
      <h2>Data not found</h2>
      <p>{loadError}</p>
      <p class="muted">Generate it with <code>pixi run build-data</code>, which writes <code>site/public/data/</code>.</p>
    </div>
  {:else if !comp}
    <p class="empty">Loading…</p>
  {:else if onStage}
    <div class="arena" class:selecting={view.kind === 'select'}>
      <div class="stage">
        {#if view.kind === 'complex' && !noGL}
          <div class="mode-switch" role="radiogroup" aria-label="Stage view">
            {#each [['3d', '3D'], ['cartoon', 'Cartoon']] as [m, label]}
              <button role="radio" aria-checked={viewMode === m} class:on={viewMode === m} onclick={() => (viewMode = m)}>{label}</button>
            {/each}
          </div>
        {/if}
        {#if showCartoon}
          <div class="mode-switch scale-switch" role="radiogroup" aria-label="Cartoon scale"
               transition:fly={{ y: -6, duration: ms(220) }}>
            {#each [['fit', 'Fit'], ['shared', 'Same scale']] as [m, label]}
              <button role="radio" aria-checked={cartoonScale === m} class:on={cartoonScale === m}
                      title={m === 'shared' ? 'Same scale and position for cBAF, PBAF and ncBAF (aligned on the nucleosome)' : 'Fit this complex to the view'}
                      onclick={() => (cartoonScale = m)}>{label}</button>
            {/each}
          </div>
        {/if}
        <div class="layer" class:hidden-layer={showCartoon} inert={showCartoon}>
          <Complex3D model={shownModel} mode={view.kind === 'select' ? 'select' : 'complex'}
                     selected={sym} highlight={hotList} complex={{ id: stageId, ...comp.complexes[stageId] }}
                     {onpick} onhover={(s) => (hot3d = s)} onmorphsource={showCartoon ? null : startMorph}
                     onglfail={() => (noGL = true)} />
        </div>
        {#if showCartoon && cartoons[stageId]}
          <div class="layer cartoon-layer" transition:fade={{ duration: ms(320) }}>
            <Cartoon2D bind:this={cartoonEl} cartoon={cartoons[stageId]} model={models[stageId]} scaleMode={cartoonScale}
                       complex={{ id: stageId, ...comp.complexes[stageId] }} selected={sym} highlight={hotList}
                       {onpick} onhover={(s) => (hot3d = s)} onmorphsource={startMorph} />
            {#if cartoons[stageId].ghosts_flat.length}
              <div class="unresolved">
                <span class="muted">Not resolved in {cartoons[stageId].pdb}:</span>
                {#each cartoons[stageId].ghosts_flat as g (g.slot)}
                  <button class="chip" class:on={g.members.includes(sym)} onclick={() => onpick(g.members[0])}>{g.slot}</button>
                {/each}
              </div>
            {/if}
          </div>
        {/if}
        {#if showCartoon && cartoons[stageId]}
          <p class="stage-hint cartoon-caption">
            Front view of <a href="https://www.rcsb.org/structure/{cartoons[stageId].pdb}" target="_blank" rel="noopener">{cartoons[stageId].pdb}</a>.
            Each colour is the part of a subunit visible from this side; dashed circles are members not resolved in the structure.
            {#if cartoonScale === 'shared'}Same scale as the other complexes, aligned on the nucleosome.{/if}
            <button class="linkish" onclick={() => cartoonEl?.saveSvg()}>Save SVG</button>
            · <a href={href('compare')}>Compare all three</a>
          </p>
        {:else}
          <p class="stage-hint" class:gone={view.kind !== 'select'}>
            {MODEL_INDEX[stageId].pdb} · drag to rotate after selecting
          </p>
        {/if}
      </div>
      <aside class="deck">
        {#key view.kind === 'select' ? 'select' : `${complex.id}/${sym ?? ''}`}
          <div class="card-in"
               in:fly={{ x: 60, duration: ms(560), delay: ms(view.kind === 'select' ? 120 : sym ? 240 : 160), easing: backOut }}
               out:fly={{ x: -40, duration: ms(220), easing: cubicOut }}>
            {#if view.kind === 'select'}
              {@render selectPanel()}
            {:else if subunit}
              {@render subunitPanel(subunit, complex)}
            {:else if sym}
              <div class="card panel"><p>{sym} is not a curated BAF subunit.</p></div>
            {:else}
              {@render composition(complex)}
            {/if}
          </div>
        {/key}
      </aside>
    </div>
  {:else if view.kind === 'gene'}
    <div class="narrow">
      {#if subunit}
        {@render subunitPanel(subunit, null)}
      {:else}
        <div class="card panel"><p>{view.sym} is not a curated BAF subunit.</p></div>
      {/if}
    </div>
  {:else if view.kind === 'compare'}
    <Compare {comp} {cartoons} modelIndex={MODEL_INDEX} ids={TABS} onopen={(id, s) => go(`${id}/${s}`)} />
  {:else if view.kind === 'missing'}
    <div class="card panel narrow"><p>No page at <code>#/{view.path}</code>. <a href={href('cBAF')}>Go to cBAF</a>.</p></div>
  {/if}
</main>

{#if manifest}
  {@const src = manifest.sources}
  <footer>
    <p>
      Data <b class="mono">v{manifest.data_version}</b> · built {manifest.built.slice(0, 10)} ·
      composition curated by {comp?.version ? `B. Chick (${comp.version})` : 'B. Chick'}
    </p>
    <p class="sources">
      UniProt {src.uniprot.release} (CC BY 4.0) · InterPro {src.interpro.interpro.version} / Pfam {src.interpro.pfam.version} (CC0) ·
      ClinVar {src.clinvar.last_update.slice(0, 10)} (public domain) · Ensembl VEP {src.ensembl_vep.software} ·
      cBioPortal {src.cbioportal.portal_version}, TCGA PanCancer Atlas (ODbL 1.0, <code>{src.cbioportal.path}</code>) ·
      PubMed via NCBI ESummary
    </p>
    <p class="muted">Code MIT · cartoons CC BY 4.0 · COSMIC and OncoKB are linked, not redistributed.</p>
  </footer>
{/if}

<style>
  .top {
    position: sticky; top: 0; z-index: 10;
    display: flex; align-items: center; gap: 20px; flex-wrap: wrap;
    padding: 12px clamp(16px, 4vw, 40px);
    background: color-mix(in srgb, var(--bg) 88%, transparent);
    backdrop-filter: blur(10px); border-bottom: 1px solid var(--line);
  }
  .brand { display: flex; align-items: center; gap: 8px; font-weight: 700; font-size: 17px; color: var(--ink); letter-spacing: -0.01em; }
  .brand:hover { text-decoration: none; }
  nav { display: flex; gap: 4px; flex-wrap: wrap; flex: 1; }
  .tab { padding: 6px 12px; border-radius: 999px; color: var(--ink-2); font-weight: 500; font-size: 14px; }
  .tab:hover { background: var(--bg-2); text-decoration: none; }
  .tab[aria-current='page'] { background: var(--ink); color: var(--bg); }
  @media (max-width: 640px) {
    .top { gap: 10px 14px; }
    nav { order: 3; flex: 1 0 100%; flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; margin: 0 -4px; }
    .tab { white-space: nowrap; }
    .theme { margin-left: auto; }
    .theme-name { display: none; }
  }
  .theme-name { font-size: 12px; color: var(--ink-3); text-transform: capitalize; }

  main { padding: 24px clamp(16px, 4vw, 40px) 40px; max-width: 1440px; margin: 0 auto; }

  .arena { display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(340px, 1fr); gap: 28px; align-items: start; }
  .arena > * { min-width: 0; }
  .arena .stage {
    position: sticky; top: 76px; border-radius: 22px;
    background: radial-gradient(circle at 50% 45%, color-mix(in srgb, var(--surface) 90%, transparent), transparent 70%);
    transition: background 600ms;
  }
  .arena .stage { isolation: isolate; }
  .layer { transition: opacity 320ms ease, transform 420ms cubic-bezier(.3,1.2,.5,1); }
  .hidden-layer { opacity: 0; transform: scale(0.97); pointer-events: none; }
  .cartoon-layer { position: absolute; inset: 0 0 auto 0; }
  .cartoon-layer .unresolved { position: absolute; left: 0; right: 0; bottom: 8px; display: flex; flex-wrap: wrap; gap: 6px;
    justify-content: center; align-items: center; font-size: 12.5px; }
  .cartoon-layer .unresolved .chip { cursor: pointer; border-style: dashed; }
  .mode-switch { position: absolute; top: 8px; right: 8px; z-index: 5; display: flex; gap: 2px; padding: 3px;
    border-radius: 999px; background: color-mix(in srgb, var(--surface) 85%, transparent); border: 1px solid var(--line);
    box-shadow: 0 2px 8px rgb(0 0 0 / 8%); backdrop-filter: blur(6px); }
  .scale-switch { top: 46px; }
  .scale-switch button { font-size: 11.5px; padding: 3px 10px; }
  .mode-switch button { all: unset; cursor: pointer; font-size: 12.5px; font-weight: 600; padding: 4px 12px; border-radius: 999px;
    color: var(--ink-2); transition: background 200ms, color 200ms; }
  .mode-switch button.on { background: var(--ink); color: var(--bg); }
  .mode-switch button:focus-visible { outline: 2px solid var(--focus); }
  .cartoon-caption { max-width: 560px; margin: 4px auto 0; line-height: 1.5; }
  .linkish { all: unset; cursor: pointer; color: var(--accent); font-weight: 600; margin-left: 4px; }
  .linkish:hover { text-decoration: underline; }
  .stage-hint { text-align: center; font-size: 12px; color: var(--ink-3); margin: 4px 0 0; letter-spacing: 0.04em; transition: opacity 400ms; }
  .stage-hint.gone { opacity: 0; }
  /* in/out panels share one grid cell so they cross-fade without layout jumps */
  .deck { display: grid; }
  .deck > :global(*) { grid-area: 1 / 1; }
  @media (max-width: 960px) {
    .arena { grid-template-columns: minmax(0, 1fr); }
    .arena .stage { position: relative; top: 0; }
  }

  .select-panel .big { font-size: 56px; letter-spacing: -0.03em; line-height: 1; }
  .who { margin: 6px 0 18px; }
  .stats { list-style: none; padding: 0; margin: 0 0 20px; display: grid; gap: 10px; }
  .stats li { display: grid; grid-template-columns: 1fr 1.1fr auto; gap: 12px; align-items: center; font-size: 13px; }
  .st-k { color: var(--ink-2); }
  .st-bar { height: 8px; border-radius: 4px; background: var(--bg-2); overflow: hidden; }
  .st-bar span { display: block; height: 100%; border-radius: 4px; background: linear-gradient(90deg, var(--accent), color-mix(in srgb, var(--accent) 55%, #fff));
    transition: width 650ms cubic-bezier(.3,1.35,.5,1); }
  .st-v { min-width: 44px; text-align: right; font-weight: 600; }
  .roster { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
  .pick {
    display: grid; gap: 2px; padding: 12px 14px; border-radius: 14px; color: var(--ink);
    border: 1.5px solid var(--line); background: var(--surface-2);
    transition: transform 260ms cubic-bezier(.3,1.5,.5,1), border-color 200ms, box-shadow 260ms, background 200ms;
  }
  .pick:hover { text-decoration: none; }
  .pick.on { border-color: var(--accent); transform: translateY(-3px) scale(1.03); box-shadow: 0 10px 26px color-mix(in srgb, var(--accent) 25%, transparent); background: var(--surface); }
  .pick b { font-size: 15px; }
  .pick span { font-size: 12px; }
  .pick-dots { display: flex; gap: 3px; margin-bottom: 4px; }
  .pick-dots i { width: 10px; height: 10px; border-radius: 50%; background: var(--line-2); }
  .go-row { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-top: 18px; }
  .go { background: var(--ink); color: var(--bg); border-color: var(--ink); font-weight: 600; padding: 9px 18px; font-size: 14px; }
  .go:hover { background: var(--ink); text-decoration: none; transform: translateY(-1px); }
  .member.hot { text-decoration: underline; text-decoration-thickness: 2px; }
  .narrow { max-width: 760px; margin: 0 auto; }

  .panel { padding: 22px 24px; }

  /* staggered "card deal": each block of the opened panel rises in turn */
  .card-in .panel > :global(*) { animation: rise 520ms cubic-bezier(.2,.9,.3,1.2) both; }
  .card-in .panel > :global(*:nth-child(2)) { animation-delay: 380ms; }
  .card-in .panel > :global(*:nth-child(3)) { animation-delay: 440ms; }
  .card-in .panel > :global(*:nth-child(4)) { animation-delay: 500ms; }
  .card-in .panel > :global(*:nth-child(5)) { animation-delay: 560ms; }
  .card-in .panel > :global(*:nth-child(6)) { animation-delay: 620ms; }
  .card-in .panel > :global(*:nth-child(7)) { animation-delay: 680ms; }
  .card-in .panel > :global(*:nth-child(n+8)) { animation-delay: 740ms; }
  .card-in .panel > :global(*:first-child) { animation-delay: 320ms; }
  @keyframes rise { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }
  @keyframes grow { from { transform: scaleX(0); } to { transform: scaleX(1); } }
  .panel-head { margin-bottom: 14px; position: relative; }
  .head-suggest { position: absolute; top: -6px; right: -8px; display: flex; gap: 6px; align-items: center; }
  .cite-btn { font-size: 12.5px; padding: 4px 10px; }
  .sub-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin: 22px 0 8px; }
  .sub-row .sub { margin: 0; }
  .grow { flex: 1; }
  .eyebrow { margin: 0 0 4px; font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--ink-3); font-weight: 600; }
  h2 { font-size: 24px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  h2 .muted { font-weight: 500; font-size: 18px; }
  h3 { font-size: 16px; }
  .sub { margin: 22px 0 8px; font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--ink-2); }
  .fullname { margin: 4px 0 0; color: var(--ink-2); }
  .ids, .aliases, .defined { margin: 6px 0 0; font-size: 13.5px; }
  .small { font-size: 12.5px; }
  .empty { color: var(--ink-3); padding: 12px 0; }

  .swatch { display: inline-block; width: 10px; height: 10px; border-radius: 3px; flex: none; }
  .swatch.lg { width: 16px; height: 16px; border-radius: 5px; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--accent); margin-right: 6px; }

  .cites { display: inline; }
  .cite { display: inline-flex; align-items: center; min-height: 24px; padding: 0 2px; font-size: 12.5px; white-space: nowrap; }
  .cite + .cite::before { content: ' · '; color: var(--ink-3); }
  .cite.retracted { color: var(--c-plp); text-decoration: line-through; }

  .slots { list-style: none; padding: 0; margin: 0; display: grid; gap: 2px; }
  .slot { padding: 10px 0; border-top: 1px solid var(--line); }
  .slot-name { font-size: 12.5px; font-weight: 600; color: var(--ink-3); text-transform: uppercase; letter-spacing: 0.05em; display: flex; gap: 8px; align-items: center; }
  .members { display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 4px; }
  .member { display: inline-flex; align-items: center; gap: 6px; min-height: 24px; padding: 1px 2px; color: var(--ink); font-weight: 500; }
  .member.has-data::after { content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--accent); }
  .member.contested { font-style: italic; color: var(--ink-2); }
  .note { font-size: 13px; color: var(--ink-2); margin: 6px 0 0; }
  .note.contest { border-left: 3px solid var(--c-conf); padding-left: 10px; }
  .note.isoform { border-left: 3px solid var(--accent); padding-left: 10px; margin: 0 0 12px; }
  .slot-cite { margin: 4px 0 0; }
  .chip.warn { border-color: var(--c-conf); color: var(--c-conf); background: transparent; font-size: 11px; text-transform: none; letter-spacing: 0; }
  .chip.review { border-style: dashed; font-size: 11px; }
  .absent { font-size: 13px; margin: 14px 0 0; padding-top: 12px; border-top: 1px solid var(--line); }
  .legend { font-size: 12.5px; color: var(--ink-3); margin: 10px 0 0; }
  .paralogs { font-size: 14px; margin: 0 0 14px; }
  .learn { margin: 8px 0 0; font-size: 13px; display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: baseline; }
  .learn a { font-weight: 500; }
  .learn a.self { font-weight: 700; }

  .stack { display: flex; height: 12px; border-radius: 6px; overflow: hidden; gap: 2px; background: var(--bg-2); }
  .stack { transform-origin: left; animation: grow 900ms cubic-bezier(.2,.9,.3,1.1) 600ms both; }
  .stack span { min-width: 3px; }
  .stack-legend { list-style: none; padding: 0; margin: 8px 0 0; display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 13px; }
  .stack-legend .dot { margin-right: 5px; }

  .civic { list-style: none; padding: 0; margin: 6px 0 0; display: grid; gap: 10px; }
  .civic li { font-size: 13.5px; }
  .civic-top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .civic-dis { color: var(--ink-2); margin-top: 2px; }
  .lvl { display: inline-grid; place-items: center; width: 20px; height: 20px; border-radius: 6px; font-weight: 700; font-size: 12px; color: #fff; background: var(--ink-3); }
  .lvl-A { background: #1f7a4d; } .lvl-B { background: #2f6fd6; } .lvl-C { background: #7a5cc7; } .lvl-D { background: #b0703a; } .lvl-E { background: #8a8f98; }
  .freq { margin: 0 0 8px; display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
  .freq b { font-size: 26px; letter-spacing: -0.02em; }
  .freq span { font-size: 13px; }
  .studies { width: 100%; border-collapse: collapse; font-size: 13px; }
  .studies td { padding: 3px 0; }
  .studies .ct { width: 56px; font-weight: 600; color: var(--ink-2); font-family: var(--mono); font-size: 12px; }
  .studies .bar span { transform-origin: left; animation: grow 700ms cubic-bezier(.2,.9,.3,1.2) both; }
  .studies tr:nth-child(1) .bar span { animation-delay: 700ms; }
  .studies tr:nth-child(2) .bar span { animation-delay: 760ms; }
  .studies tr:nth-child(3) .bar span { animation-delay: 820ms; }
  .studies tr:nth-child(4) .bar span { animation-delay: 880ms; }
  .studies tr:nth-child(5) .bar span { animation-delay: 940ms; }
  .studies tr:nth-child(6) .bar span { animation-delay: 1000ms; }
  .studies .bar span { display: block; height: 8px; border-radius: 4px; background: var(--c-tcga); min-width: 2px; }
  .studies .num { text-align: right; width: 56px; padding-left: 8px; }

  .variant { margin: 12px 0 8px; padding: 14px 16px; border-radius: 10px; background: var(--surface-2); border: 1px solid var(--line); }




  .error { max-width: 560px; margin: 40px auto; }

  footer { border-top: 1px solid var(--line); padding: 20px clamp(16px, 4vw, 40px) 32px; font-size: 12.5px; color: var(--ink-2); max-width: 1440px; margin: 0 auto; }
  footer p { margin: 4px 0; }
  .sources { line-height: 1.7; }
</style>
