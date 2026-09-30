<script>
  // cBAF cartoon traced from the 6LTJ cryo-EM projection (pipeline/cartoon_layout.py).
  // One <a> per subunit shape, drawn back-to-front by depth; the nucleosome is
  // context; unresolved members are translucent "ghost" shapes.
  //
  // Motion: selecting a subunit tweens the camera (viewBox) onto it, the rest of
  // the complex explodes outward in a distance-ordered wave, and a shockwave
  // ring fires from the hit. All of it collapses to instant under
  // prefers-reduced-motion.
  import { line, curveCatmullRomClosed, curveBasis } from 'd3-shape';
  import { Tween } from 'svelte/motion';
  import { cubicInOut } from 'svelte/easing';
  import { colorOf } from './colors.js';
  import { href } from './router.svelte.js';

  let { layout, complex, selected = null, dataGenes = [] } = $props();

  const closed = line().curve(curveCatmullRomClosed.alpha(0.5));
  const open = line().curve(curveBasis);

  // slot lookup: which members share a modelled shape
  const slotOf = $derived.by(() => {
    const m = {};
    for (const s of complex.slots) for (const g of s.members) m[g] = s;
    return m;
  });

  let hovered = $state(null);

  const reduce = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const FULL = [0, 0, layout.width, layout.height];
  const EXPLODE = 110;     // px the unselected subunits are pushed out
  const WAVE = 220;        // ms from nearest to farthest subunit

  // Bounding box of everything that represents the selection: every hull in
  // the selected slot, or the ghost anchor for an unmodelled member.
  const focus = $derived.by(() => {
    if (!selected) return null;
    const pts = layout.subunits.filter((s) => isActive(s.symbol)).flatMap((s) => s.hull);
    const g = layout.ghosts.find((g) => g.members.includes(selected));
    if (g) pts.push([g.anchor[0] - 70, g.anchor[1] - 60], [g.anchor[0] + 70, g.anchor[1] + 60]);
    if (!pts.length) return null;
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const b = { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) };
    return { ...b, cx: (b.x0 + b.x1) / 2, cy: (b.y0 + b.y1) / 2 };
  });

  // Camera: pad the focus box, keep the layout's aspect ratio, and never zoom
  // past ~2.2x so the exploded neighbours stay in frame as context.
  function frame(f) {
    const aspect = layout.width / layout.height;
    let w = Math.max((f.x1 - f.x0) * 1.9, (f.y1 - f.y0) * 1.9 * aspect, layout.width / 2.2);
    w = Math.min(w, layout.width);
    const h = w / aspect;
    return [f.cx - w / 2, f.cy - h / 2, w, h];
  }
  const cam = new Tween(FULL, { duration: reduce ? 0 : 800, easing: cubicInOut });
  $effect(() => { cam.target = focus ? frame(focus) : FULL; });

  // Per-shape offset away from the focus centre, with a wave delay.
  function explode(c, active) {
    if (!focus || active) return { t: 'translate(0px, 0px)', d: 0 };
    const dx = c[0] - focus.cx, dy = c[1] - focus.cy;
    const r = Math.hypot(dx, dy) || 1;
    const k = EXPLODE * (0.6 + 0.4 * Math.min(1, r / 400));
    const maxR = Math.hypot(layout.width, layout.height) / 2;
    return { t: `translate(${(dx / r) * k}px, ${(dy / r) * k}px)`, d: Math.round((r / maxR) * WAVE) };
  }

  // Shockwave rings fired on click.
  let pulses = $state([]);
  let pulseId = 0;
  function fire(x, y, sym) {
    if (reduce) return;
    const id = ++pulseId;
    pulses.push({ id, x, y, color: colorOf(sym) });
    setTimeout(() => { pulses = pulses.filter((p) => p.id !== id); }, 900);
  }

  const shapes = $derived(layout.subunits.map((s, i) => ({
    ...s,
    key: s.chain,
    path: closed(s.hull),
    slot: slotOf[s.symbol],
    first: layout.subunits.findIndex((t) => t.symbol === s.symbol) === i,
  })));

  // label positions: average centroid over all chains of a subunit
  const labelsBase = $derived.by(() => {
    const acc = {};
    for (const s of layout.subunits) {
      (acc[s.symbol] ||= []).push(s.centroid);
    }
    return Object.entries(acc).map(([sym, pts]) => ({
      sym,
      x: pts.reduce((a, p) => a + p[0], 0) / pts.length,
      y: pts.reduce((a, p) => a + p[1], 0) / pts.length,
      slot: slotOf[sym],
    }));
  });
  const labels = $derived(labelsBase.map((l) => ({ ...l, active: isActive(l.sym), ex: explode([l.x, l.y], isActive(l.sym)) })));

  function ghostPath(cx, cy, r) {
    const pts = [];
    for (let k = 0; k < 9; k++) {
      const a = (k / 9) * Math.PI * 2;
      const rr = r * (0.82 + 0.18 * Math.sin(a * 3 + cx));
      pts.push([cx + Math.cos(a) * rr * 1.25, cy + Math.sin(a) * rr]);
    }
    return closed(pts);
  }

  function isActive(sym) {
    if (!selected) return false;
    const sl = slotOf[sym];
    return sym === selected || (sl && sl.members.includes(selected));
  }

  function slotLabel(sym) {
    const sl = slotOf[sym];
    if (!sl || sl.members.length === 1) return '';
    return sl.members.filter((m) => m !== sym).join(' · ');
  }

  function aria(sym) {
    const sl = slotOf[sym];
    const alt = sl && sl.members.length > 1 ? `, slot shared with ${sl.members.filter((m) => m !== sym).join(', ')}` : '';
    return `${sym}${alt}. Open subunit.`;
  }

  // For a slot, link to the member that has mutation data when possible.
  function target(sym) {
    const sl = slotOf[sym];
    if (dataGenes.includes(sym)) return sym;
    const alt = sl?.members.find((m) => dataGenes.includes(m));
    return alt || sym;
  }
</script>

<figure class="cartoon" class:focused={!!selected} aria-label="Cartoon of the canonical BAF complex bound to a nucleosome">
  <svg viewBox={cam.current.join(' ')} role="group" aria-label="cBAF subunits">
    <defs>
      <filter id="soft" x="-20%" y="-20%" width="140%" height="140%">
        <feDropShadow dx="0" dy="6" stdDeviation="8" flood-color="#000" flood-opacity="0.18" />
      </filter>
      <filter id="lift" x="-30%" y="-30%" width="160%" height="160%">
        <feDropShadow dx="0" dy="14" stdDeviation="14" flood-color="#000" flood-opacity="0.28" />
      </filter>
      {#each labels as l}
        <radialGradient id="g-{l.sym}" cx="35%" cy="28%" r="85%">
          <stop offset="0%" stop-color="white" stop-opacity="0.55" />
          <stop offset="45%" stop-color={colorOf(l.sym)} stop-opacity="1" />
          <stop offset="100%" stop-color={colorOf(l.sym)} stop-opacity="1" />
        </radialGradient>
      {/each}
      <radialGradient id="g-nuc" cx="40%" cy="35%" r="80%">
        <stop offset="0%" stop-color="var(--surface)" stop-opacity="0.9" />
        <stop offset="100%" stop-color="var(--nuc-fill)" stop-opacity="1" />
      </radialGradient>
      <linearGradient id="shade" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#000" stop-opacity="0" />
        <stop offset="100%" stop-color="#000" stop-opacity="0.22" />
      </linearGradient>
    </defs>

    <!-- nucleosome context -->
    <g class="nucleosome" aria-hidden="true" class:dim={!!selected}
       style:transform={explode(layout.nucleosome.centroid, false).t}>
      <path d={closed(layout.nucleosome.hull)} fill="url(#g-nuc)" stroke="var(--line-2)" stroke-width="2" />
      {#each layout.nucleosome.dna_path as p}
        <path d={open(p)} fill="none" stroke="var(--nuc-dna)" stroke-width="9" stroke-linecap="round" opacity="0.8" />
      {/each}
      <text x={layout.nucleosome.centroid[0]} y={layout.nucleosome.centroid[1] + 6} class="ctx-label">nucleosome</text>
    </g>

    <!-- subunits, back to front -->
    <g class="float">
    {#each shapes as s (s.key)}
      {@const active = isActive(s.symbol)}
      {@const ex = explode(s.centroid, active)}
      <a
        href={href(complex.id, target(s.symbol))}
        class="subunit"
        class:hovered={hovered === s.symbol}
        class:active
        class:dim={selected && !active}
        style:transform={ex.t}
        style:transition-delay="{ex.d}ms"
        onclick={() => fire(s.centroid[0], s.centroid[1], s.symbol)}
        data-subunit={s.symbol}
        aria-label={aria(s.symbol)}
        tabindex={s.first ? 0 : -1}
        onmouseenter={() => (hovered = s.symbol)}
        onmouseleave={() => (hovered = null)}
        onfocus={() => (hovered = s.symbol)}
        onblur={() => (hovered = null)}
      >
        <g class="lifter">
          <path d={s.path} fill="url(#g-{s.symbol})" class="body" />
          <path d={s.path} fill="url(#shade)" class="shade" />
          <path d={s.path} fill="none" class="rim" />
        </g>
      </a>
    {/each}

    <!-- ghosts: members not resolved in the model -->
    {#each layout.ghosts as g}
      {@const sym = g.members[0]}
      {@const gActive = !!selected && g.members.includes(selected)}
      {@const gx = explode(g.anchor, gActive)}
      <a href={href(complex.id, sym)} class="ghost" data-subunit={sym}
         class:active={gActive} class:dim={selected && !gActive}
         style:transform={gx.t} style:transition-delay="{gx.d}ms"
         onclick={() => fire(g.anchor[0], g.anchor[1], sym)}
         aria-label="{g.members.join(' or ')}: present in cBAF, not modelled in {layout.pdb}. Open subunit.">
        <path d={ghostPath(g.anchor[0], g.anchor[1], 46)} fill={colorOf(sym)} />
        <text x={g.anchor[0]} y={g.anchor[1] - 2} class="label ghost-label">{g.slot}</text>
        <text x={g.anchor[0]} y={g.anchor[1] + 16} class="sub-label">not resolved</text>
      </a>
    {/each}

    <!-- labels on top -->
    <g class="labels" aria-hidden="true">
      {#each labels as l (l.sym)}
        <g class="label-g" class:active={l.active} class:dim={selected && !l.active}
           style:transform={l.ex.t} style:transition-delay="{l.ex.d}ms">
          <text x={l.x} y={l.y} class="label" class:has-data={dataGenes.includes(target(l.sym))}>{l.sym}</text>
          {#if slotLabel(l.sym)}
            <text x={l.x} y={l.y + 17} class="sub-label">| {slotLabel(l.sym)}</text>
          {/if}
        </g>
      {/each}
    </g>
    </g>

    <!-- shockwaves -->
    <g aria-hidden="true">
      {#each pulses as p (p.id)}
        <circle class="shock" cx={p.x} cy={p.y} r="60" stroke={p.color} />
        <circle class="shock late" cx={p.x} cy={p.y} r="60" stroke={p.color} />
      {/each}
    </g>
  </svg>
  <figcaption>
    Traced from the cryo-EM structure <a href="https://www.rcsb.org/structure/{layout.pdb}" target="_blank" rel="noopener">{layout.pdb}</a>
    (He et al. 2020). Paralogs share a slot's shape. Dashed shapes are members not resolved in the model.
  </figcaption>
</figure>

<style>
  .cartoon { margin: 0; }
  svg { width: 100%; height: auto; display: block; overflow: visible; }
  .subunit, .ghost, .label-g, .nucleosome {
    transition: transform 700ms cubic-bezier(.34,1.3,.5,1), opacity 500ms ease;
  }
  .subunit { cursor: pointer; outline: none; }
  .nucleosome.dim { opacity: 0.35; }
  .label-g.dim { opacity: 0; }
  .label-g.active .label { font-size: 22px; }

  /* idle "menu screen" float, paused once something is selected */
  .float { animation: float 6s ease-in-out infinite; }
  .focused .float { animation-play-state: paused; }
  @keyframes float { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-5px); } }

  .shock {
    fill: none; stroke-width: 5; pointer-events: none;
    transform-box: fill-box; transform-origin: center;
    animation: shock 800ms cubic-bezier(.1,.7,.3,1) forwards;
  }
  .shock.late { stroke-width: 3; animation-delay: 110ms; opacity: 0; }
  @keyframes shock {
    0% { transform: scale(0.15); opacity: 0.9; }
    100% { transform: scale(3.2); opacity: 0; }
  }
  .subunit.active .rim { animation: glow 1.8s ease-in-out infinite; }
  @keyframes glow { 0%, 100% { stroke-opacity: 1; stroke-width: 3.5; } 50% { stroke-opacity: 0.45; stroke-width: 7; } }
  .subunit .lifter {
    transition: transform 220ms cubic-bezier(.2,.8,.2,1), filter 220ms;
    transform-box: fill-box; transform-origin: center;
    filter: url(#soft);
  }
  .subunit .body { stroke: none; }
  .subunit .shade { mix-blend-mode: multiply; pointer-events: none; }
  .subunit .rim { stroke: var(--shape-stroke); stroke-width: 1.5; }
  .subunit.hovered .lifter, .subunit:focus-visible .lifter {
    transform: translateY(-6px) scale(1.035);
    filter: url(#lift);
  }
  .subunit:focus-visible .rim { stroke: var(--focus); stroke-width: 4; }
  .subunit.active .rim { stroke: var(--ink); stroke-width: 3.5; }
  .subunit.dim { opacity: 0.32; }
  .subunit.dim.hovered { opacity: 0.7; }
  .ghost.dim { opacity: 0.3; }
  .ghost.active path { fill-opacity: 0.4; stroke: var(--ink); stroke-opacity: 1; }
  .ghost path {
    fill-opacity: 0.16; stroke: currentColor; stroke-opacity: 0.55; stroke-width: 2;
    stroke-dasharray: 7 6; color: var(--ink-2); transition: fill-opacity 200ms;
  }
  .ghost:hover path, .ghost:focus-visible path { fill-opacity: 0.32; }
  .ghost:focus-visible { outline: none; }
  .ghost:focus-visible path { stroke: var(--focus); stroke-opacity: 1; stroke-width: 3; }
  .label {
    font: 600 17px var(--font); fill: var(--ink); text-anchor: middle; pointer-events: none;
    paint-order: stroke; stroke: var(--label-halo); stroke-width: 4px; stroke-linejoin: round;
    letter-spacing: 0.01em;
  }
  .label.has-data::after { content: '•'; }
  .sub-label {
    font: 500 12px var(--font); fill: var(--ink-2); text-anchor: middle; pointer-events: none;
    paint-order: stroke; stroke: var(--label-halo); stroke-width: 3.5px;
  }
  .ghost-label { font-size: 16px; fill: var(--ink-2); }
  .ctx-label {
    font: 500 14px var(--font); fill: var(--ink-3); text-anchor: middle; letter-spacing: 0.08em;
    text-transform: uppercase;
  }
  figcaption { font-size: 12.5px; color: var(--ink-3); margin-top: 6px; text-align: center; }
</style>
