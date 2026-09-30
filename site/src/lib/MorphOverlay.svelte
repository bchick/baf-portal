<script>
  // Full-window particle layer for the stage -> domain-map morph.
  //
  // Modelled residues of the selected subunit (evenly sampled, at most MAX)
  // leave their bead positions in the 3D view, lift, and arc to their own
  // UniProt residue on the lollipop backbone, sweeping N- to C-terminus.
  // Disordered stretches get no particles because the structure never resolved
  // them. Targets are re-read every frame (the panel is still sliding in), and
  // the lollipop is revealed as the particles land. Kept cheap for integrated
  // GPUs: no trails, and every frame is a handful of batched fills (particles
  // bucketed by colour and fade step) rather than one draw call per particle.
  let canvas;
  let ctx, raf = 0, job = null;

  const MAX = 160;        // particles, sampled evenly along the chain
  const LIFT = 180;       // ms: particles rise off the model
  const SWEEP = 320;      // ms: N- to C-terminal launch stagger
  const FLY = 520;        // ms: flight per particle
  const STEPS = 4;        // alpha buckets for the landing fade
  const WAIT = 1800;      // ms: give up if the domain map never appears
  const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
  const lerp = (a, b, t) => a + (b - a) * t;
  const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const GREY = [154, 161, 171];     // residues landing outside any domain

  function size() {
    const pr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(innerWidth * pr);
    canvas.height = Math.round(innerHeight * pr);
    ctx = canvas.getContext('2d');
    ctx.setTransform(pr, 0, 0, pr, 0, 0);
  }

  export function cancel() {
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    job?.reveal?.();
    job = null;
    ctx?.clearRect(0, 0, innerWidth, innerHeight);
  }

  // src: {points: [{x, y, r, u}], color}; target(): {geometry(), reveal()} | null
  export function run(src, target) {
    cancel();
    if (!canvas) return;
    size();
    const all = [...src.points].sort((a, b) => a.u - b.u);
    const pts = all.length <= MAX ? all : Array.from({ length: MAX }, (_, i) => all[Math.round((i * (all.length - 1)) / (MAX - 1))]);
    const us = pts.map((p) => p.u);
    const umin = Math.min(...us), umax = Math.max(...us);
    // deterministic jitter per residue so the flight looks organic, not noisy
    const rnd = (u, k) => { const s = Math.sin(u * 12.9898 + k * 78.233) * 43758.5453; return s - Math.floor(s); };
    const parts = pts.map((p) => ({
      ...p,
      delay: SWEEP * ((p.u - umin) / Math.max(1, umax - umin)),
      lift: { x: p.x + (rnd(p.u, 1) - 0.5) * 26, y: p.y - 22 - rnd(p.u, 2) * 22 },
      arc: 70 + rnd(p.u, 3) * 60,
    }));
    const rgb = hex(src.color);
    job = { t0: performance.now(), tFly: null, parts, target, src, revealed: false,
            fills: [`rgb(${rgb.join(',')})`, `rgb(${GREY.join(',')})`],
            reveal: () => target()?.reveal() };
    raf = requestAnimationFrame(frame);
  }

  function frame(now) {
    raf = 0;
    if (!job) return;
    const t = now - job.t0;
    const tgt = job.target();
    const geo = tgt?.geometry();
    if (job.tFly == null && geo && t >= LIFT) job.tFly = t;
    if (job.tFly == null && t > WAIT) { cancel(); return; }       // domain map never showed: bail out cleanly
    ctx.clearRect(0, 0, innerWidth, innerHeight);

    let landed = 0, done = 0;
    // buckets[colour][alpha step] -> flat [x, y, r, ...]
    const buckets = [[], []].map(() => Array.from({ length: STEPS + 1 }, () => []));
    for (const p of job.parts) {
      let x, y, r, alpha = 1, grey = 0;
      const a = Math.min(1, t / LIFT), ea = ease(a);
      if (job.tFly == null || !geo) {
        x = lerp(p.x, p.lift.x, ea); y = lerp(p.y, p.lift.y, ea); r = lerp(p.r, p.r * 0.7, ea);
      } else {
        const q = Math.max(0, Math.min(1, (t - job.tFly - p.delay) / FLY));
        const e = ease(q);
        const end = geo.at(p.u);
        grey = !end.inDomain && e > 0.5 ? 1 : 0;      // off-domain landings turn grey halfway
        // quadratic Bezier arcing above the straight line
        const cx = (p.lift.x + end.x) / 2, cy = Math.min(p.lift.y, end.y) - p.arc;
        x = (1 - e) ** 2 * p.lift.x + 2 * (1 - e) * e * cx + e * e * end.x;
        y = (1 - e) ** 2 * p.lift.y + 2 * (1 - e) * e * cy + e * e * end.y;
        r = lerp(p.r * 0.7, 2.6, e);
        if (q >= 0.85) landed++;
        if (q >= 1) {
          alpha = Math.max(0, 1 - (t - job.tFly - p.delay - FLY) / 220);   // the domain map takes over
          if (alpha === 0) { done++; continue; }
        }
      }
      buckets[grey][Math.round(alpha * STEPS)].push(x, y, Math.max(1.2, r));
    }
    for (let g = 0; g < 2; g++) {
      ctx.fillStyle = job.fills[g];
      for (let k = 1; k <= STEPS; k++) {
        const b = buckets[g][k];
        if (!b.length) continue;
        ctx.globalAlpha = k / STEPS;
        ctx.beginPath();
        for (let i = 0; i < b.length; i += 3) { ctx.moveTo(b[i] + b[i + 2], b[i + 1]); ctx.arc(b[i], b[i + 1], b[i + 2], 0, Math.PI * 2); }
        ctx.fill();
      }
    }
    ctx.globalAlpha = 1;
    if (!job.revealed && landed >= job.parts.length * 0.55) { job.revealed = true; job.reveal(); }
    if (done === job.parts.length) { ctx.clearRect(0, 0, innerWidth, innerHeight); job = null; return; }
    raf = requestAnimationFrame(frame);
  }
</script>

<svelte:window onresize={() => job && size()} />
<canvas bind:this={canvas} class="morph" aria-hidden="true"></canvas>

<style>
  .morph { position: fixed; inset: 0; width: 100vw; height: 100vh; pointer-events: none; z-index: 30; }
</style>
