<script>
  // cBAF, PBAF and ncBAF side by side: cartoons at one shared scale (the
  // structures are superposed on the nucleosome, so position matches too),
  // linked hover across panels, and a composition matrix underneath saying,
  // per complex, whether each subunit is resolved in the structure, placed
  // into it from another structure, a member not resolved, contested, or absent.
  import { fly } from 'svelte/transition';
  import { backOut } from 'svelte/easing';
  import Cartoon2D from './Cartoon2D.svelte';
  import { colorOf } from './colors.js';

  let { comp, cartoons, modelIndex, ids = ['cBAF', 'PBAF', 'ncBAF'], onopen = () => {} } = $props();

  const reduce = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  let hot = $state(null);
  const panels = {};

  // matrix rows: slots in first-seen order across complexes, members within each
  const rows = $derived.by(() => {
    const slots = new Map();
    for (const id of ids) for (const sl of comp.complexes[id].slots) {
      const e = slots.get(sl.slot) ?? slots.set(sl.slot, { slot: sl.slot, members: [] }).get(sl.slot);
      for (const m of sl.members) if (!e.members.includes(m)) e.members.push(m);
    }
    return [...slots.values()];
  });

  function cell(id, sym) {
    const c = comp.complexes[id];
    const sl = c.slots.find((s) => s.members.includes(sym));
    if (!sl) return { state: 'absent', label: `Not in ${id}` };
    const note = (sl.contested_notes ?? []).find((n) => n.member == null || n.member === sym
      || (Array.isArray(n.member) && n.member.includes(sym)));
    const ch = modelIndex[id].chains.find((x) => x.symbol === sym);
    const pdb = modelIndex[id].pdb;

    const state = !ch ? 'member' : ch.tier === 'experimental' ? 'resolved' : ch.tier;
    const where = state === 'resolved' ? `resolved in ${pdb}`
      : state === 'placed' ? `not resolved in ${pdb}; placed from ${ch.source_pdb ?? 'another structure'}`
      : state === 'predicted' ? `not resolved in ${pdb}; predicted model`
      : `member, not resolved in ${pdb}`;
    return {
      state, contested: !!note,
      label: `${sym} in ${id}: ${where}` + (note ? ` · contested: ${note.claim}` : ''),
    };
  }

  // one SVG with the three panels, titles and the shared scale bar
  export function saveFigure() {
    const W = 420, GAP = 24, TITLE = 34;
    const out = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    out.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    out.setAttribute('viewBox', `0 0 ${ids.length * W + (ids.length - 1) * GAP} ${W + TITLE}`);
    ids.forEach((id, i) => {
      const node = panels[id]?.exportNode();
      if (!node) return;
      node.setAttribute('x', i * (W + GAP)); node.setAttribute('y', TITLE);
      node.setAttribute('width', W); node.setAttribute('height', W);
      const t = document.createElementNS(out.namespaceURI, 'text');
      Object.entries({ x: i * (W + GAP) + 6, y: 22, 'font-family': 'Inter,Helvetica,Arial,sans-serif', 'font-size': 17,
                       'font-weight': 700, fill: '#1b1f24' }).forEach(([k, v]) => t.setAttribute(k, v));
      t.textContent = `${id} · ${cartoons[id].pdb}`;
      out.append(t, node);
    });
    const blob = new Blob([new XMLSerializer().serializeToString(out)], { type: 'image/svg+xml' });
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: 'BAF-complexes-compared.svg' });
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
</script>

<section class="compare">
  <header class="head">
    <div>
      <p class="eyebrow">Compare</p>
      <h2>cBAF · PBAF · ncBAF</h2>
      <p class="muted sub">Front views of 6LTJ, 7VDV and 9WBZ at the same scale, aligned on the nucleosome. Hover a subunit to find it in
        every complex; click to open it.</p>
    </div>
    <button class="btn" onclick={saveFigure} disabled={!ids.every((id) => cartoons[id])}>Save figure (SVG)</button>
  </header>

  <div class="panels">
    {#each ids as id, i (id)}
      <figure class="panel card" in:fly={{ y: 18, duration: reduce ? 0 : 480, delay: reduce ? 0 : 80 * i, easing: backOut }}>
        <figcaption>
          <a href="#/{id}" class="ptitle">{id}</a>
          <span class="muted">{comp.complexes[id].name} · {modelIndex[id].pdb}</span>
        </figcaption>
        {#if cartoons[id]}
          <Cartoon2D bind:this={panels[id]} cartoon={cartoons[id]} complex={{ id, ...comp.complexes[id] }}
                     scaleMode="shared" compact mode="compare" highlight={hot}
                     onhover={(s) => (hot = s)} onpick={(s) => onopen(id, s)} />
          {#if cartoons[id].ghosts_flat.length}
            <p class="unres muted">Not resolved: {cartoons[id].ghosts_flat.map((g) => g.slot).join(', ')}</p>
          {/if}
        {:else}
          <div class="loading">Loading…</div>
        {/if}
      </figure>
    {/each}
  </div>

  <div class="card matrix-card">
    <h3 class="mtitle">Composition</h3>
    <div class="matrix-wrap">
      <table class="matrix">
        <thead>
          <tr><th scope="col">Slot</th><th scope="col">Subunit</th>{#each ids as id}<th scope="col">{id}</th>{/each}</tr>
        </thead>
        <tbody>
          {#each rows as r (r.slot)}
            {#each r.members as sym, j (sym)}
              <tr class:hot={hot === sym} onmouseenter={() => (hot = sym)} onmouseleave={() => (hot = null)}>
                {#if j === 0}<th scope="rowgroup" rowspan={r.members.length} class="slot">{r.slot}</th>{/if}
                <th scope="row" class="sym"><span class="sw" style:background={colorOf(sym)}></span>{sym}</th>
                {#each ids as id}
                  {@const c = cell(id, sym)}
                  <td class={c.state} title={c.label}>
                    {#if c.state === 'absent'}
                      <span class="dash" aria-label={c.label}>—</span>
                    {:else}
                      <button class="mark {c.state}" style:--c={colorOf(sym)} aria-label={c.label} onclick={() => onopen(id, sym)}>
                        {#if c.contested}<span class="q" aria-hidden="true">?</span>{/if}
                      </button>
                    {/if}
                  </td>
                {/each}
              </tr>
            {/each}
          {/each}
        </tbody>
      </table>
    </div>
    <p class="legend muted">
      <span><i class="mark resolved" style:--c="var(--accent)"></i> resolved in the structure</span>
      <span><i class="mark member" style:--c="var(--accent)"></i> member, not resolved</span>
      <span><i class="mark placed" style:--c="var(--accent)"></i> placed from another structure</span>
      <span><i class="mark resolved" style:--c="var(--accent)"><span class="q">?</span></i> contested (hover for sources' disagreement)</span>
      <span>— not in the complex</span>
    </p>
  </div>
</section>

<style>
  .compare { display: grid; gap: 20px; min-width: 0; }
  .compare > * { min-width: 0; }
  .head > div { flex: 1 1 260px; min-width: 0; }
  .head { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap; }
  .eyebrow { margin: 0; font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--ink-3); font-weight: 600; }
  h2 { font-size: 26px; margin: 2px 0 0; }
  .sub { margin: 6px 0 0; max-width: 720px; font-size: 14px; }
  .panels { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
  @media (max-width: 900px) { .panels { grid-template-columns: minmax(0, 1fr); } }
  .panel { margin: 0; padding: 12px 14px 10px; }
  figcaption { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; font-size: 13px; }
  .ptitle { font-size: 18px; font-weight: 700; color: var(--ink); }
  .unres { font-size: 12px; margin: 4px 0 0; text-align: center; }
  .loading { aspect-ratio: 1; display: grid; place-items: center; color: var(--ink-3); }
  .matrix-card { padding: 16px 18px; }
  .mtitle { font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--ink-2); margin: 0 0 8px; }
  .matrix-wrap { overflow-x: auto; }
  .matrix { border-collapse: collapse; font-size: 13.5px; min-width: 480px; width: 100%; }
  .matrix th, .matrix td { padding: 5px 10px; border-bottom: 1px solid var(--line); text-align: left; }
  .matrix thead th { font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-3); }
  .matrix td, .matrix thead th:nth-child(n+3) { text-align: center; }
  .slot { color: var(--ink-3); font-weight: 600; font-size: 12px; vertical-align: top; }
  .sym { font-weight: 600; white-space: nowrap; }
  .sw { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 7px; vertical-align: -1px; }
  tr.hot td, tr.hot .sym { background: color-mix(in srgb, var(--accent) 9%, transparent); }
  .mark { all: unset; box-sizing: border-box; display: inline-grid; place-items: center; width: 18px; height: 18px; border-radius: 5px;
    cursor: pointer; vertical-align: middle; transition: transform 180ms cubic-bezier(.3,1.6,.5,1); }
  /* the drawn square stays 18px; the button's hit area meets the 24px minimum */
  button.mark { width: 24px; height: 24px; background-clip: content-box; padding: 3px; }
  i.mark { cursor: default; width: 14px; height: 14px; margin-right: 4px; vertical-align: -2px; }
  .mark.resolved { background: var(--c); }
  /* placed: filled, but hatched, matching the 3D view's treatment */
  .mark.placed { background: repeating-linear-gradient(135deg, var(--c) 0 3px, transparent 3px 6px); border: 1px solid var(--c); }
  .mark.member { border: 2px dashed var(--c); }
  button.mark:hover, button.mark:focus-visible { transform: scale(1.2); }
  button.mark:focus-visible { outline: 2px solid var(--focus); }
  .q { font-size: 11px; font-weight: 800; color: #fff; text-shadow: 0 0 2px rgb(0 0 0 / 50%); font-style: normal; }
  .mark.member .q { color: var(--ink); text-shadow: none; }
  .dash { color: var(--ink-3); }
  .legend { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 12.5px; margin: 10px 0 0; }
</style>
