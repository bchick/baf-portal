<script>
  // Flat 2D cartoon of a complex (pipeline/cartoon2d.py): each colour region is
  // the part of a subunit visible from the front, in the same frame as the 3D
  // view's front camera, so the stage can cross-fade between them.
  // Labels sit inside a region when they fit, otherwise in side callout
  // columns with leader lines. Subunits are links; hover and selection follow
  // the 3D view's behaviour, and selecting a subunit emits morph source points
  // (its beads' screen positions + UniProt residues) like Complex3D does.
  import { colorOf } from './colors.js';

  let {
    cartoon, model = null, complex = null, selected = null, highlight = null, mode = 'complex',
    onpick = () => {}, onhover = () => {}, onmorphsource = null,
  } = $props();

  const reduce = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  let svg = $state(), width = $state(600);
  const [fx, fy, fs] = $derived(cartoon.frame);
  const px = $derived(width / fs);                  // screen px per Angstrom
  const LABEL_PX = 12.5;

  function slotMates(sym) {
    const sl = complex?.slots?.find((s) => s.members.includes(sym));
    return sl ? sl.members : [sym];
  }
  const active = $derived(new Set(selected ? slotMates(selected) : []));
  let hoverSym = $state(null);
  const hot = $derived(new Set(hoverSym ?? highlight ? slotMates(hoverSym ?? highlight) : []));

  const bySym = $derived.by(() => {
    const m = new Map();
    for (const p of cartoon.pieces) if (p.sym) (m.get(p.sym) ?? m.set(p.sym, []).get(p.sym)).push(p);
    return [...m];
  });

  // one label per subunit: its largest visible piece
  const labels = $derived.by(() => {
    const best = {};
    for (const p of cartoon.pieces) if (p.sym && (!best[p.sym] || p.area > best[p.sym].area)) best[p.sym] = p;
    const out = [];
    for (const [sym, p] of Object.entries(best)) {
      const mates = slotMates(sym).filter((m) => m !== sym);
      const w = (sym.length * 0.62 * LABEL_PX + 10) / px;          // label width in Angstrom
      const inside = p.r_in * 2 >= w * 0.9 && p.r_in * px >= LABEL_PX * 0.9;
      out.push({ sym, mates, anchor: p.anchor, inside, w });
    }
    // callouts: left/right of the complex centre, spread to avoid collisions
    const gap = (LABEL_PX * 1.9) / px;
    for (const side of ['L', 'R']) {
      const col = out.filter((l) => !l.inside && (l.anchor[0] < cartoon.center[0]) === (side === 'L'))
        .sort((a, b) => a.anchor[1] - b.anchor[1]);
      let y = fy + 48 / px;               // clear of the 3D | Cartoon switch in the corner
      for (const l of col) {
        l.side = side;
        l.ty = Math.max(l.anchor[1], y);
        y = l.ty + gap;
      }
      const overflow = y - gap - (fy + fs - gap);
      if (overflow > 0) for (const l of col) l.ty -= overflow;
      for (const l of col) l.tx = side === 'L' ? fx + 8 / px : fx + fs - 8 / px;
    }
    return out;
  });

  function pick(sym) { onpick(sym); }

  // ---- morph source (same contract as Complex3D) --------------------------------
  let lastSelected = null;
  $effect(() => {
    const sel = mode === 'complex' ? selected : null;
    if (sel && sel !== lastSelected && onmorphsource && model && svg && !reduce) {
      const ctm = svg.getScreenCTM();
      if (ctm) {
        const res = model.res ?? [], b = model.beads, pts = [];
        const pt = svg.createSVGPoint();
        for (let i = 0; i < res.length; i++) {
          if (!res[i] || model.chains[b[4 * i + 3]].symbol !== sel) continue;
          pt.x = b[4 * i]; pt.y = b[4 * i + 1];
          const q = pt.matrixTransform(ctm);
          pts.push({ x: q.x, y: q.y, r: 3.9 * ctm.a, u: res[i] });
        }
        if (pts.length) onmorphsource({ sym: sel, points: pts, color: colorOf(sel) });
      }
    }
    lastSelected = sel;
  });

  // ---- export -----------------------------------------------------------------------
  export function saveSvg() {
    const clone = svg.cloneNode(true);
    const cs = getComputedStyle(svg);
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    clone.querySelectorAll('.focus-ring, .hit').forEach((e) => e.remove());
    clone.querySelectorAll('[data-fill]').forEach((e) => e.setAttribute('fill', e.getAttribute('data-fill')));
    const style = document.createElementNS('http://www.w3.org/2000/svg', 'style');
    style.textContent = `path{stroke:${cs.getPropertyValue('--bead-ink')};stroke-width:1.1;stroke-linejoin:round}
      text{font-family:Inter,Helvetica,Arial,sans-serif;font-weight:600;fill:#1b1f24}
      .lead{stroke:#1b1f24;stroke-width:0.5;fill:none}.ghost circle{fill:none;stroke:#666;stroke-dasharray:4 3}`;
    clone.prepend(style);
    const blob = new Blob([new XMLSerializer().serializeToString(clone)], { type: 'image/svg+xml' });
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: `${cartoon.complex}-${cartoon.pdb}-cartoon.svg` });
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
</script>

<div class="cartoon2d" bind:clientWidth={width} class:focused={!!selected}>
  <svg bind:this={svg} viewBox="{fx} {fy} {fs} {fs}" role="group" aria-label="{cartoon.complex} cartoon, front view of {cartoon.pdb}">
    <defs>
      <filter id="c2d-shadow" x="-10%" y="-10%" width="120%" height="120%">
        <feDropShadow dx="0" dy={3 / px} stdDeviation={4 / px} flood-color="#000" flood-opacity="0.16" />
      </filter>
    </defs>

    <g filter="url(#c2d-shadow)">
      {#each cartoon.pieces as p, i (i)}
        {#if p.sym}
          <path d={p.d} fill-rule="evenodd" class="piece" data-fill={colorOf(p.sym)} style:fill={colorOf(p.sym)}
                class:active={active.has(p.sym)} class:dim={selected && !active.has(p.sym)} class:hot={hot.has(p.sym)} />
        {:else}
          <path d={p.d} fill-rule="evenodd" class="piece ctx {p.kind}" data-fill={p.kind === 'dna' ? '#b7a27e' : p.kind === 'histone' ? '#e3d6bd' : '#c3c7cc'}
                class:dim={!!selected} />
        {/if}
      {/each}
    </g>

    <!-- invisible hit targets per subunit (keyboard + pointer), drawn on top -->
    {#each bySym as [sym, ps] (sym)}
      <a href="#/" class="hit" role="button" tabindex="0" aria-label="{sym}. Open subunit."
         onclick={(e) => { e.preventDefault(); pick(sym); }}
         onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), pick(sym))}
         onpointerenter={() => { hoverSym = sym; onhover(sym); }} onpointerleave={() => { hoverSym = null; onhover(null); }}
         onfocus={() => { hoverSym = sym; onhover(sym); }} onblur={() => { hoverSym = null; onhover(null); }}>
        {#each ps as p}<path d={p.d} fill-rule="evenodd" />{/each}
      </a>
    {/each}

    {#each cartoon.ghosts as g (g.slot)}
      {@const on = g.members.includes(selected)}
      <a href="#/" class="ghost" class:on class:dim={selected && !on} role="button" tabindex="0"
         aria-label="{g.members.join(' or ')}: not resolved in {cartoon.pdb}. Open subunit."
         onclick={(e) => { e.preventDefault(); pick(g.members[0]); }}
         onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), pick(g.members[0]))}>
        <circle cx={g.pos[0]} cy={g.pos[1]} r={g.r} style:stroke={colorOf(g.members[0])} style:fill={colorOf(g.members[0]) + '26'} />
        <text x={g.pos[0]} y={g.pos[1] + 4 / px} style:font-size="{11 / px}px">{g.slot}</text>
      </a>
    {/each}

    <!-- labels -->
    <g class="labels" aria-hidden="true">
      {#each labels as l (l.sym)}
        {@const dim = selected && !active.has(l.sym)}
        {#if l.inside}
          <text x={l.anchor[0]} y={l.anchor[1] + 4.3 / px} class="lbl in" class:dim class:on={active.has(l.sym)}
                style:font-size="{LABEL_PX / px}px" style:stroke-width="{3 / px}px">{l.sym}</text>
        {:else}
          <path class="lead" class:dim d="M{l.anchor[0]} {l.anchor[1]}L{l.tx + (l.side === 'L' ? l.w : -l.w)} {l.ty}"
                style:stroke-width="{1 / px}px" />
          <circle cx={l.anchor[0]} cy={l.anchor[1]} r={2 / px} class="dot" class:dim />
          <text x={l.tx} y={l.ty + 4.3 / px} class="lbl out {l.side}" class:dim class:on={active.has(l.sym)}
                style:font-size="{LABEL_PX / px}px" style:stroke-width="{3 / px}px">{l.sym}</text>
        {/if}
        {#if l.mates.length && !dim}
          <text x={l.inside ? l.anchor[0] : l.tx} y={(l.inside ? l.anchor[1] : l.ty) + 17 / px}
                class="mates {l.inside ? 'in' : 'out ' + l.side}" style:font-size="{10 / px}px" style:stroke-width="{2.5 / px}px">
            | {l.mates.join(' · ')}</text>
        {/if}
      {/each}
    </g>
  </svg>
</div>

<style>
  .cartoon2d { position: relative; width: 100%; aspect-ratio: 1 / 1; max-height: calc(100vh - 120px); }
  svg { width: 100%; height: 100%; display: block; overflow: visible; }
  .piece {
    stroke: var(--bead-ink); stroke-width: 1.1px; vector-effect: non-scaling-stroke; stroke-linejoin: round;
    transition: opacity 320ms ease, filter 200ms ease;
  }
  .piece.ctx.histone { fill: var(--histone); }
  .piece.ctx.dna { fill: var(--dna); }
  .piece.ctx.unassigned { fill: var(--c-other); }
  .piece.dim { opacity: 0.28; }
  .piece.hot { filter: brightness(1.13) saturate(1.05); }
  .piece.active { stroke-width: 2.4px; }
  .hit path { fill: transparent; stroke: none; cursor: pointer; }
  .hit { outline: none; }
  .hit:focus-visible path { stroke: var(--focus); stroke-width: 3px; vector-effect: non-scaling-stroke; }
  .ghost circle { stroke-width: 1.6px; vector-effect: non-scaling-stroke; stroke-dasharray: 5 4; cursor: pointer; transition: opacity 300ms; }
  .ghost.on circle { stroke: var(--ink) !important; stroke-width: 2.4px; }
  .ghost.dim { opacity: 0.35; }
  .ghost text { text-anchor: middle; fill: var(--ink-2); font-weight: 600; pointer-events: none; }
  .ghost:focus-visible { outline: none; }
  .ghost:focus-visible circle { stroke: var(--focus) !important; }
  .lbl, .mates {
    font-family: var(--font); font-weight: 650; fill: var(--ink); pointer-events: none;
    paint-order: stroke; stroke: var(--label-halo); stroke-linejoin: round; transition: opacity 300ms;
  }
  .lbl.in, .mates.in { text-anchor: middle; }
  .lbl.out.L, .mates.out.L { text-anchor: start; }
  .lbl.out.R, .mates.out.R { text-anchor: end; }
  .lbl.on { font-weight: 800; }
  .mates { font-weight: 500; fill: var(--ink-2); }
  .lead { stroke: var(--ink-2); fill: none; vector-effect: non-scaling-stroke; transition: opacity 300ms; }
  .dot { fill: var(--ink); transition: opacity 300ms; }
  .dim { opacity: 0.25; }
</style>
