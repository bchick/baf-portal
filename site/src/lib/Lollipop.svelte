<script>
  // Mirror lollipop on UniProt canonical coordinates:
  //   up    TCGA PanCancer somatic mutations, height by patients at the residue
  //   mid   backbone: thick where folded, thin where UniProt calls it disordered;
  //         domains (UniProt curated, Pfam where UniProt has none), motif ticks
  //   down  ClinVar / UniProt germline variants, coloured by the worst class
  // The residue window is a spring: drag to pan, Ctrl/Cmd-scroll to zoom,
  // click a domain to fly to it, double-click to zoom in. Letters appear when
  // zoomed to sequence level.
  import { Spring } from 'svelte/motion';
  import { ticks as niceTicks } from 'd3-array';
  import { classKey, CLASS_ORDER, CLASS_COLOR } from './colors.js';

  let { gene, tcga = null, color = 'var(--accent)', selectedP = null, onselect = () => {},
        awaitMorph = false, onready = () => {} } = $props();

  const reduce = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const L = $derived(gene.uniprot.length);
  const SEQ = $derived(gene.uniprot.sequence);
  const SHOWN = new Set(['missense', 'truncating', 'inframe', 'splice', 'stop_lost']);
  const SOM = ['missense', 'truncating', 'inframe'];
  const SOM_COLOR = { missense: 'var(--c-mis)', truncating: 'var(--c-trunc)', inframe: 'var(--c-inframe)' };
  const SOM_LABEL = { missense: 'Missense', truncating: 'Truncating', inframe: 'In-frame' };

  // Short community names for long Pfam / UniProt domain names.
  const TINY = { 'ATPase lobe 1': 'L1', 'ATPase lobe 2': 'L2', 'BAF250 C': 'C', 'WH DBD': 'DBD', 'Bromo': 'Br' };
  const SHORT = {
    'Helicase ATP-binding': 'ATPase lobe 1', 'Helicase C-terminal': 'ATPase lobe 2', 'BRK domain': 'BRK',
    'SNF2-related domain': 'SNF2', 'Snf2-ATP coupling, chromatin remodelling complex': 'SnAC',
    'SWI/SNF-like complex subunit BAF250/Osa': 'BAF250 C', 'SWI/SNF Subunit INI1, DNA binding domain': 'WH DBD',
    'SNF5 / SMARCB1 / INI1': 'SNF5', 'Bromodomain': 'Bromo', 'Helicase conserved C-terminal domain': 'Helicase C',
    'ARID/BRIGHT DNA binding domain': 'ARID', 'HSA domain': 'HSA',
  };

  // ---- tracks ------------------------------------------------------------------
  const domains = $derived.by(() => {
    const up = gene.features
      .filter((f) => f.type === 'Domain' || f.type === 'Repeat')
      .map((f) => ({ start: f.start, end: f.end, name: f.type === 'Repeat' ? `RPT${f.desc}` : f.desc, src: 'UniProt' }));
    const ov = (a, b) => Math.max(0, Math.min(a.end, b.end) - Math.max(a.start, b.start) + 1) / Math.min(a.end - a.start + 1, b.end - b.start + 1);
    const pf = gene.domains.filter((d) => d.db === 'pfam' && !up.some((u) => ov(u, d) >= 0.5))
      .map((d) => ({ start: d.start, end: d.end, name: d.name, src: `Pfam ${d.acc}` }));
    return [...up, ...pf].sort((a, b) => a.start - b.start).map((d) => {
      const short = SHORT[d.name] ?? d.name;
      return { ...d, short, tiny: TINY[short] ?? short.slice(0, 3) };
    });
  });
  const disordered = $derived(gene.features.filter((f) => f.type === 'Region' && f.desc === 'Disordered'));
  const motifs = $derived(gene.features.filter((f) => f.type === 'Motif'));

  let on = $state(new Set(['missense', 'truncating', 'inframe', 'P/LP', 'Conflicting', 'B/LB', 'Other']));
  function toggle(k) { const s = new Set(on); s.has(k) ? s.delete(k) : s.add(k); on = s; }

  const somatic = $derived.by(() => {
    const m = new Map();
    for (const v of tcga?.variants ?? []) {
      if (!SOM.includes(v.cls)) continue;
      const e = m.get(v.pos) ?? { pos: v.pos, n: 0, by: { missense: 0, truncating: 0, inframe: 0 }, vs: [] };
      e.by[v.cls] += v.n_pat; e.vs.push(v); m.set(v.pos, e);
    }
    return [...m.values()].map((e) => {
      const n = SOM.reduce((a, k) => a + (on.has(k) ? e.by[k] : 0), 0);
      const cls = SOM.filter((k) => on.has(k)).sort((a, b) => e.by[b] - e.by[a] || (b === 'truncating') - (a === 'truncating'))[0];
      return { ...e, n, cls, vs: e.vs.filter((v) => on.has(v.cls)).sort((a, b) => b.n_pat - a.n_pat) };
    }).filter((e) => e.n > 0);
  });
  const germline = $derived.by(() => {
    const m = new Map();
    for (const v of gene.variants) {
      if (!(SHOWN.has(v.cls) || v.up)) continue;
      const k = classKey(v);
      if (!on.has(k)) continue;
      const e = m.get(v.pos) ?? { pos: v.pos, n: 0, worst: k, vs: [] };
      e.n++; e.vs.push({ ...v, key: k });
      if (CLASS_ORDER.indexOf(k) < CLASS_ORDER.indexOf(e.worst)) e.worst = k;
      m.set(v.pos, e);
    }
    for (const e of m.values()) e.vs.sort((a, b) => CLASS_ORDER.indexOf(a.key) - CLASS_ORDER.indexOf(b.key));
    return [...m.values()];
  });
  const counts = $derived.by(() => {
    const c = {};
    for (const k of SOM) c[k] = (tcga?.variants ?? []).filter((v) => v.cls === k).reduce((a, v) => a + v.n_pat, 0);
    for (const k of CLASS_ORDER) c[k] = 0;
    for (const v of gene.variants) if (SHOWN.has(v.cls) || v.up) c[classKey(v)]++;
    return c;
  });
  // Level of detail: residues are pooled into bins ~4 px wide at the target
  // zoom. Bin width is a power of two anchored at residue 1, so it changes only
  // at doublings and panning never reshuffles bins. A bin is drawn at its
  // most-hit residue, so hotspots keep their exact position.
  const binAa = $derived.by(() => {
    const aaPer4px = ((win.target[1] - win.target[0]) * 4) / iw;
    return aaPer4px <= 1 ? 1 : 2 ** Math.ceil(Math.log2(aaPer4px));
  });
  function pool(entries, merge) {
    if (binAa === 1) return entries.map((e) => ({ ...e, key: `1:${e.pos}`, from: e.pos, to: e.pos }));
    const m = new Map();
    for (const e of entries) {
      const b = Math.floor((e.pos - 1) / binAa);
      const cur = m.get(b);
      m.set(b, cur ? merge(cur, e) : { ...e, key: `${binAa}:${b}`, top: e.n, from: e.pos, to: e.pos });
    }
    return [...m.values()];
  }
  const somBins = $derived(pool(somatic, (a, e) => {
    const by = { ...a.by }; for (const k of SOM) by[k] += e.by[k];
    const cls = SOM.filter((k) => on.has(k)).sort((x, y) => by[y] - by[x] || (y === 'truncating') - (x === 'truncating'))[0];
    const top = e.n > a.top;
    return { ...a, by, cls, n: a.n + e.n, pos: top ? e.pos : a.pos, top: Math.max(a.top, e.n),
             from: Math.min(a.from, e.pos), to: Math.max(a.to, e.pos), vs: [...a.vs, ...e.vs].sort((x, y) => y.n_pat - x.n_pat) };
  }));
  const germBins = $derived(pool(germline, (a, e) => {
    const worst = CLASS_ORDER.indexOf(e.worst) < CLASS_ORDER.indexOf(a.worst) ? e.worst : a.worst;
    const top = e.n > a.top;
    return { ...a, worst, n: a.n + e.n, pos: top ? e.pos : a.pos, top: Math.max(a.top, e.n),
             from: Math.min(a.from, e.pos), to: Math.max(a.to, e.pos),
             vs: [...a.vs, ...e.vs].sort((x, y) => CLASS_ORDER.indexOf(x.key) - CLASS_ORDER.indexOf(y.key)) };
  }));
  const somMax = $derived(Math.max(1, ...somBins.map((e) => e.n)));
  const germMax = $derived(Math.max(1, ...germBins.map((e) => e.n)));

  // selected variant (from the route)
  const selPos = $derived.by(() => {
    if (!selectedP) return null;
    const v = gene.variants.find((v) => v.p === selectedP || v.mane === selectedP)
      ?? tcga?.variants.find((v) => v.p === selectedP || v.mane === selectedP);
    return v?.pos ?? null;
  });

  // ---- geometry ------------------------------------------------------------------
  let width = $state(0);             // measured; 0 until mounted so it never forces its parent wider
  const M = { l: 10, r: 10 };
  const iw = $derived(Math.max(60, width - M.l - M.r));
  const SOM_H = 78, GERM_H = 78, BAR = 16;
  const Y_BAR = 18 + SOM_H + 12;                  // backbone centre
  const Y_AXIS = Y_BAR + BAR / 2 + 12 + GERM_H + 16;
  const Y_OV = Y_AXIS + 22;
  const HEIGHT = Y_OV + 14;

  const win = new Spring([0.5, 1000.5], { stiffness: 0.14, damping: 0.82 });
  let lastGene = null;
  let intro = $state(false);
  // `veiled`: a morph from the 3D stage is coming; stay hidden until its
  // particles land (reveal), with a fallback so the plot can never stay hidden.
  let veiled = $state(false);
  let fallback = 0;
  function playIntro() {
    veiled = false;
    if (reduce) return;
    intro = true;
    setTimeout(() => (intro = false), 1400);
  }
  $effect(() => {
    if (gene === lastGene) return;
    lastGene = gene;
    win.set([0.5, L + 0.5], { instant: true });
    clearTimeout(fallback);
    if (awaitMorph) { veiled = true; fallback = setTimeout(playIntro, 2400); } else playIntro();
  });
  $effect(() => () => clearTimeout(fallback));

  // Morph target API: page coordinates of a residue on the backbone, read
  // fresh each frame because the panel may still be sliding in.
  function geometry() {
    if (!svg) return null;
    const r = svg.getBoundingClientRect();
    if (!r.width) return null;
    const span = x1 - x0;
    return {
      at: (u) => ({ x: r.left + M.l + ((u - x0) / span) * iw, y: r.top + Y_BAR,
                    inDomain: domains.some((d) => u >= d.start && u <= d.end) }),
    };
  }
  $effect(() => {
    if (!svg) return;
    onready({ gene: gene.gene, geometry, reveal: () => { clearTimeout(fallback); if (veiled) playIntro(); } });
  });

  const x0 = $derived(win.current[0]), x1 = $derived(win.current[1]);
  const x = (p) => M.l + ((p - x0) / (x1 - x0)) * iw;
  const pxPerAa = $derived(iw / (x1 - x0));
  const zoomed = $derived(win.target[1] - win.target[0] < L - 1);

  function clampWin([a, b]) {
    let span = Math.max(20, Math.min(L, b - a));
    let s = Math.max(0.5, Math.min(L + 0.5 - span, a));
    return [s, s + span];
  }
  function fly(a, b) { win.set(clampWin([a, b]), { instant: reduce }); }
  function zoomAt(px, f) {
    const [a, b] = win.target;
    const c = a + ((px - M.l) / iw) * (b - a);
    fly(c - (c - a) * f, c + (b - c) * f);
  }

  const somY = (n) => (Math.log1p(n) / Math.log1p(somMax)) * (SOM_H - 10) + 10;
  const germY = (n) => (Math.log1p(n) / Math.log1p(germMax)) * (GERM_H - 10) + 10;
  const headR = (n, max) => 2.4 + 2.6 * Math.sqrt(n / max);

  const visSom = $derived(somBins.filter((e) => e.pos >= x0 - binAa && e.pos <= x1 + binAa));
  const visGerm = $derived(germBins.filter((e) => e.pos >= x0 - binAa && e.pos <= x1 + binAa));
  const axisTicks = $derived(niceTicks(Math.max(1, x0), Math.min(L, x1), Math.max(3, Math.round(iw / 90))));
  const letters = $derived(pxPerAa >= 9 ? Array.from({ length: Math.ceil(x1) - Math.floor(x0) + 1 }, (_, i) => Math.floor(x0) + i).filter((p) => p >= 1 && p <= L) : []);

  // ---- gestures ------------------------------------------------------------------
  let svg;
  let drag = $state(null);
  function pdown(e) {
    if (e.button !== 0 || e.target.closest('.hit, .dom, .ov')) return;
    drag = { x: e.clientX, win: [...win.target], moved: false };
    svg.setPointerCapture(e.pointerId);
  }
  function pmove(e) {
    if (drag) {
      const dx = e.clientX - drag.x;
      if (Math.abs(dx) > 3) drag.moved = true;
      const d = (dx / iw) * (drag.win[1] - drag.win[0]);
      win.set(clampWin([drag.win[0] - d, drag.win[1] - d]), { instant: true });
    }
  }
  function pup() { drag = null; }
  function wheel(e) {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      const r = svg.getBoundingClientRect();
      zoomAt(e.clientX - r.left, Math.exp(e.deltaY * 0.003));
    } else if (Math.abs(e.deltaX) > Math.abs(e.deltaY) && zoomed) {
      e.preventDefault();
      const [a, b] = win.target, d = (e.deltaX / iw) * (b - a);
      win.set(clampWin([a + d, b + d]), { instant: true });
    }
  }
  function dbl(e) {
    if (e.target.closest('.dom')) return;   // domain clicks already dive in
    const r = svg.getBoundingClientRect();
    zoomAt(e.clientX - r.left, 0.4);
  }
  // overview strip: click / drag to move the window
  function ovMove(e, force = false) {
    if (!force && !(e.buttons & 1)) return;
    const r = svg.getBoundingClientRect();
    const c = 0.5 + ((e.clientX - r.left - M.l) / iw) * L;
    const [a, b] = win.target, h = (b - a) / 2;
    win.set(clampWin([c - h, c + h]), { instant: e.type === 'pointermove' });
  }

  // ---- tooltip -------------------------------------------------------------------
  let tip = $state(null);
  function showTip(e, kind, entry) {
    const r = svg.getBoundingClientRect();
    tip = { kind, entry, x: e.clientX - r.left, y: e.clientY - r.top };
  }
  const resLabel = (p) => `${SEQ[p - 1] ?? '?'}${p}`;
  const binLabel = (e) => (e.from === e.to ? resLabel(e.from) : `residues ${e.from}–${e.to}`);
  function pick(entry) { onselect(entry.vs[0]?.p ?? null); }

  // First click frames the domain; further clicks inside a framed domain dive
  // in at the cursor, so repeated clicks reach sequence level.
  function domClick(d, e) {
    const pad = Math.max(8, (d.end - d.start) * 0.12);
    const [a, b] = win.target;
    if (a >= d.start - pad - 1 && b <= d.end + pad + 1 && e) {
      const r = svg.getBoundingClientRect();
      zoomAt(e.clientX - r.left, 0.45);
    } else fly(d.start - pad, d.end + pad);
  }
</script>

<div class="lolli" bind:clientWidth={width}>
  <div class="toolbar">
    <div class="chips" role="group" aria-label="Somatic classes">
      <span class="grp">TCGA</span>
      {#each SOM as k}
        <button class="chip" class:off={!on.has(k)} onclick={() => toggle(k)} aria-pressed={on.has(k)}>
          <i style:background={SOM_COLOR[k]}></i>{SOM_LABEL[k]} <span class="num">{counts[k]}</span>
        </button>
      {/each}
    </div>
    <div class="chips" role="group" aria-label="Germline classes">
      <span class="grp">ClinVar</span>
      {#each CLASS_ORDER as k}
        <button class="chip" class:off={!on.has(k)} onclick={() => toggle(k)} aria-pressed={on.has(k)}>
          <i style:background={CLASS_COLOR[k]}></i>{k} <span class="num">{counts[k]}</span>
        </button>
      {/each}
    </div>
  </div>

  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <svg bind:this={svg} width={width} height={HEIGHT} class:grabbing={!!drag} class:intro class:veiled
       onpointerdown={pdown} onpointermove={pmove} onpointerup={pup} onwheel={wheel} ondblclick={dbl}
       onpointerleave={() => (tip = null)} role="img"
       aria-label="{gene.gene} domain map with {somatic.length} somatic and {germline.length} germline mutated residues">
    <defs>
      <clipPath id="lp-clip"><rect x={M.l} y="0" width={iw} height={Y_AXIS} /></clipPath>
    </defs>
    <text x={M.l} y="11" class="side">▲ somatic · patients</text>
    <text x={M.l} y={Y_AXIS - 4} class="side">▼ germline · variants</text>

    <g clip-path="url(#lp-clip)">
      {#if selPos}
        <line class="guide" x1={x(selPos)} x2={x(selPos)} y1="14" y2={Y_AXIS - 12} />
      {/if}

      <!-- backbone: thin where disordered, thick where folded -->
      <rect x={x(0.5)} y={Y_BAR - BAR / 2 + 3} width={x(L + 0.5) - x(0.5)} height={BAR - 6} rx="3" class="bb" />
      {#each disordered as r}
        <rect x={x(r.start - 0.5)} y={Y_BAR - BAR / 2 + 2} width={Math.max(0, x(r.end + 0.5) - x(r.start - 0.5))} height={BAR - 4}
              class="idr-mask" />
        <line x1={x(r.start - 0.5)} x2={x(r.end + 0.5)} y1={Y_BAR} y2={Y_BAR} class="idr" />
      {/each}
      {#each domains as d, i (d.start + d.name)}
        {@const w = x(d.end + 0.5) - x(d.start - 0.5)}
        <g class="dom" style:--d="{120 + i * 60}ms" role="button" tabindex="0" aria-label="{d.name} {d.start}–{d.end}. Zoom to domain."
           onclick={(e) => domClick(d, e)} onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && domClick(d)}
           onpointerenter={(e) => showTip(e, 'dom', d)} onpointerleave={() => (tip = null)}>
          <rect x={x(d.start - 0.5)} y={Y_BAR - BAR / 2} width={Math.max(1, w)} height={BAR} rx="4" fill={color} />
          {#if w > d.short.length * 6.4 + 8}
            <text x={x(d.start - 0.5) + w / 2} y={Y_BAR + 4} class="dom-l">{d.short}</text>
          {:else if w > d.tiny.length * 6.4 + 6}
            <text x={x(d.start - 0.5) + w / 2} y={Y_BAR + 4} class="dom-l">{d.tiny}</text>
          {/if}
        </g>
      {/each}
      {#each motifs as m}
        <line x1={x((m.start + m.end) / 2)} x2={x((m.start + m.end) / 2)} y1={Y_BAR - BAR / 2 - 3} y2={Y_BAR + BAR / 2 + 3} class="motif" />
      {/each}
      {#each letters as p (p)}
        <text x={x(p)} y={Y_BAR + 4} class="aa" class:on-dom={domains.some((d) => p >= d.start && p <= d.end)}>{SEQ[p - 1]}</text>
      {/each}

      <!-- somatic (up) -->
      {#each visSom as e (e.key)}
        {@const h = somY(e.n)}
        {@const sx = x(e.pos)}
        <g class="pop up" class:sel={selPos != null && selPos >= e.from && selPos <= e.to} style:--d="{Math.round((e.pos / L) * 500)}ms">
          <line x1={sx} x2={sx} y1={Y_BAR - BAR / 2} y2={Y_BAR - BAR / 2 - h} class="stem" />
          <circle cx={sx} cy={Y_BAR - BAR / 2 - h} r={headR(e.n, somMax)} fill={SOM_COLOR[e.cls]} class="head" />
          <circle cx={sx} cy={Y_BAR - BAR / 2 - h} r="9" class="hit" role="button" tabindex="-1" aria-label="{binLabel(e)}: {e.n} patients"
                  onpointerenter={(ev) => showTip(ev, 'som', e)} onpointerleave={() => (tip = null)} onclick={() => pick(e)} onkeydown={() => {}} />
        </g>
      {/each}

      <!-- germline (down) -->
      {#each visGerm as e (e.key)}
        {@const h = germY(e.n)}
        {@const sx = x(e.pos)}
        <g class="pop down" class:sel={selPos != null && selPos >= e.from && selPos <= e.to} style:--d="{Math.round((e.pos / L) * 500) + 120}ms">
          <line x1={sx} x2={sx} y1={Y_BAR + BAR / 2} y2={Y_BAR + BAR / 2 + h} class="stem" />
          <circle cx={sx} cy={Y_BAR + BAR / 2 + h} r={headR(e.n, germMax)} fill={CLASS_COLOR[e.worst]} class="head" />
          <circle cx={sx} cy={Y_BAR + BAR / 2 + h} r="9" class="hit" role="button" tabindex="-1" aria-label="{binLabel(e)}: {e.n} variants"
                  onpointerenter={(ev) => showTip(ev, 'germ', e)} onpointerleave={() => (tip = null)} onclick={() => pick(e)} onkeydown={() => {}} />
        </g>
      {/each}
    </g>

    <!-- residue axis -->
    <g class="axis">
      {#each axisTicks as t (t)}
        <line x1={x(t)} x2={x(t)} y1={Y_AXIS - 10} y2={Y_AXIS - 6} />
        <text x={x(t)} y={Y_AXIS + 5}>{t}</text>
      {/each}
    </g>

    <!-- overview: whole protein, current window -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <g class="ov" onpointerdown={(e) => ovMove(e, true)} onpointermove={ovMove}>
      <rect x={M.l} y={Y_OV} width={iw} height="8" rx="4" class="ov-bg" />
      {#each domains as d}
        <rect x={M.l + ((d.start - 0.5) / L) * iw} y={Y_OV + 1} width={((d.end - d.start + 1) / L) * iw} height="6" rx="2" fill={color} opacity="0.55" />
      {/each}
      <rect x={M.l + ((x0 - 0.5) / L) * iw} y={Y_OV - 2} width={Math.max(4, ((x1 - x0) / L) * iw)} height="12" rx="5" class="ov-win" />
    </g>
  </svg>

  {#if tip}
    <div class="tip" style:left="{Math.min(tip.x, width - 230)}px" style:top="{tip.y + 14}px">
      {#if tip.kind === 'dom'}
        <b>{tip.entry.name}</b><span class="muted"> {tip.entry.start}–{tip.entry.end} · {tip.entry.src}</span>
        <div class="muted small">Click to zoom</div>
      {:else}
        <b class="mono">{binLabel(tip.entry)}</b>
        {#if tip.kind === 'som'}
          <span class="muted"> · {tip.entry.n} TCGA patient{tip.entry.n === 1 ? '' : 's'}</span>
          <ul>
            {#each tip.entry.vs.slice(0, 4) as v}
              <li><i style:background={SOM_COLOR[v.cls]}></i><span class="mono">{v.p}</span> <span class="muted">×{v.n_pat}</span></li>
            {/each}
          </ul>
        {:else}
          <span class="muted"> · {tip.entry.n} variant{tip.entry.n === 1 ? '' : 's'}</span>
          <ul>
            {#each tip.entry.vs.slice(0, 4) as v}
              <li><i style:background={CLASS_COLOR[v.key]}></i><span class="mono">{v.p ?? v.up?.desc}</span> <span class="muted">{v.key}</span></li>
            {/each}
          </ul>
        {/if}
        {#if tip.entry.vs.length > 4}<div class="muted small">+{tip.entry.vs.length - 4} more</div>{/if}
        <div class="muted small">Click for details</div>
      {/if}
    </div>
  {/if}

  <div class="foot">
    <span class="muted small">Drag to pan · {navigator.platform?.includes('Mac') ? '⌘' : 'Ctrl'}-scroll or double-click to zoom · click a domain to fly to it</span>
    {#if zoomed}<button class="btn small-btn" onclick={() => fly(0.5, L + 0.5)}>Reset <span class="num">1–{L}</span></button>{/if}
  </div>
</div>

<style>
  .lolli { position: relative; margin-top: 8px; min-width: 0; }
  .tip b + span { margin-left: 4px; }
  .toolbar { display: grid; gap: 6px; margin-bottom: 6px; }
  .chips { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; }
  .grp { font-size: 11px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-3); width: 56px; }
  .chip { cursor: pointer; font-size: 12px; padding: 1px 9px; gap: 5px; transition: opacity 200ms, background 200ms; }
  .chip i { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .chip.off { opacity: 0.45; background: transparent; }
  .chip.off i { background: var(--line-2) !important; }
  .chip .num { color: var(--ink-3); }

  svg { display: block; touch-action: pan-y; user-select: none; cursor: grab; overflow: visible; }
  svg.grabbing { cursor: grabbing; }
  .side { font: 600 10.5px var(--font); fill: var(--ink-3); letter-spacing: 0.05em; text-transform: uppercase; }
  .bb { fill: color-mix(in srgb, var(--ink) 16%, var(--surface)); }
  .idr-mask { fill: var(--surface); }
  .idr { stroke: color-mix(in srgb, var(--ink) 28%, var(--surface)); stroke-width: 2.5; stroke-linecap: round; }
  .dom { cursor: zoom-in; outline: none; }
  .dom rect { stroke: rgb(0 0 0 / 22%); transition: filter 160ms; }
  .dom:hover rect, .dom:focus-visible rect { filter: brightness(1.12) drop-shadow(0 2px 4px rgb(0 0 0 / 25%)); }
  .dom:focus-visible rect { stroke: var(--focus); stroke-width: 2; }
  .dom-l { font: 600 10.5px var(--font); fill: #fff; text-anchor: middle; pointer-events: none; paint-order: stroke; stroke: rgb(0 0 0 / 25%); stroke-width: 2px; }
  .motif { stroke: var(--ink); stroke-width: 1.5; opacity: 0.6; }
  .aa { font: 500 10px var(--mono); text-anchor: middle; fill: var(--ink-2); pointer-events: none; }
  .aa.on-dom { fill: #fff; }
  .stem { stroke: color-mix(in srgb, var(--ink) 26%, transparent); stroke-width: 1; }
  .head { stroke: var(--surface); stroke-width: 1; transition: r 200ms; }
  .hit { fill: transparent; cursor: pointer; outline: none; }
  .pop:hover .head { stroke: var(--ink); stroke-width: 1.5; }
  .pop.sel .head { stroke: var(--ink); stroke-width: 2.5; }
  .pop.sel .stem { stroke: var(--ink); stroke-width: 1.5; }
  .guide { stroke: var(--ink); stroke-width: 1; stroke-dasharray: 2 3; opacity: 0.5; }
  .axis line { stroke: var(--line-2); }
  .axis text { font: 500 10.5px var(--font); fill: var(--ink-3); text-anchor: middle; }
  .ov { cursor: pointer; }
  .ov-bg { fill: var(--bg-2); }
  .ov-win { fill: color-mix(in srgb, var(--accent) 18%, transparent); stroke: var(--accent); stroke-width: 1.5; }

  /* waiting for the 3D morph to land: backbone, domains and stems hidden */
  .veiled .dom, .veiled .motif, .veiled .pop { opacity: 0; }
  .veiled .bb, .veiled .idr { opacity: 0.35; }
  .bb, .idr { transition: opacity 300ms; }
  /* entrance: domains pop, stems rise from the backbone in a left-to-right wave */
  .intro .dom rect { transform-box: fill-box; transform-origin: center; animation: dom-in 480ms cubic-bezier(.3,1.5,.5,1) var(--d) both; }
  .intro .pop { transform-box: fill-box; animation: rise 520ms cubic-bezier(.3,1.4,.5,1) var(--d) both; }
  .intro .pop.up { transform-origin: bottom; }
  .intro .pop.down { transform-origin: top; }
  @keyframes dom-in { from { transform: scaleX(0.2); opacity: 0; } to { transform: none; opacity: 1; } }
  @keyframes rise { from { transform: scaleY(0); opacity: 0; } to { transform: none; opacity: 1; } }

  .tip {
    position: absolute; z-index: 5; pointer-events: none; min-width: 170px; max-width: 240px;
    background: var(--surface); border: 1px solid var(--line); border-radius: 10px; box-shadow: var(--shadow);
    padding: 8px 10px; font-size: 12.5px; animation: tip-in 140ms ease-out;
  }
  .tip ul { list-style: none; padding: 0; margin: 4px 0 0; }
  .tip li { display: flex; align-items: center; gap: 6px; }
  .tip li i { width: 7px; height: 7px; border-radius: 50%; flex: none; }
  .small { font-size: 11.5px; }
  @keyframes tip-in { from { opacity: 0; transform: translateY(-3px); } }
  .foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; margin-top: 4px; }
  .small-btn { font-size: 12px; padding: 3px 10px; }
</style>
