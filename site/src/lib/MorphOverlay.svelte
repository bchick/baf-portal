<script>
  // Full-window particle layer for the stage -> domain-map morph.
  //
  // Each modelled residue of the selected subunit leaves its bead position in
  // the 3D view, lifts, and arcs to its own UniProt residue on the lollipop
  // backbone, sweeping N- to C-terminus. Folded, modelled regions fill in;
  // disordered stretches get no particles because the structure never
  // resolved them. Targets are re-read every frame (the panel is still sliding
  // in), and the lollipop is revealed as the particles land.
  let canvas;
  let ctx, raf = 0, job = null;

  const LIFT = 240;       // ms: particles rise off the model
  const SWEEP = 420;      // ms: N- to C-terminal launch stagger
  const FLY = 640;        // ms: flight per particle
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
    const us = src.points.map((p) => p.u);
    const umin = Math.min(...us), umax = Math.max(...us);
    // deterministic jitter per residue so the flight looks organic, not noisy
    const rnd = (u, k) => { const s = Math.sin(u * 12.9898 + k * 78.233) * 43758.5453; return s - Math.floor(s); };
    const parts = src.points.map((p) => ({
      ...p,
      delay: SWEEP * ((p.u - umin) / Math.max(1, umax - umin)),
      lift: { x: p.x + (rnd(p.u, 1) - 0.5) * 26, y: p.y - 22 - rnd(p.u, 2) * 22 },
      arc: 70 + rnd(p.u, 3) * 60,
      prev: null,
    }));
    job = { t0: performance.now(), tFly: null, parts, target, src, revealed: false, rgb: hex(src.color),
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
    for (const p of job.parts) {
      let x, y, r, alpha = 1, grey = 0;
      const a = Math.min(1, t / LIFT), ea = ease(a);
      const lx = lerp(p.x, p.lift.x, ea), ly = lerp(p.y, p.lift.y, ea), lr = lerp(p.r, p.r * 0.7, ea);
      if (job.tFly == null || !geo) {
        [x, y, r] = [lx, ly, lr];
      } else {
        const q = Math.max(0, Math.min(1, (t - job.tFly - p.delay) / FLY));
        const e = ease(q);
        const end = geo.at(p.u);
        grey = end.inDomain ? 0 : e;          // leave in the subunit colour, fade to grey if landing off-domain
        // quadratic Bezier arcing above the straight line
        const cx = (p.lift.x + end.x) / 2, cy = Math.min(p.lift.y, end.y) - p.arc;
        x = (1 - e) ** 2 * p.lift.x + 2 * (1 - e) * e * cx + e * e * end.x;
        y = (1 - e) ** 2 * p.lift.y + 2 * (1 - e) * e * cy + e * e * end.y;
        r = lerp(p.r * 0.7, 2.6, e);
        if (q >= 0.85) landed++;
        if (q >= 1) {
          const since = t - job.tFly - p.delay - FLY;
          alpha = Math.max(0, 1 - since / 260);          // the domain map takes over
          if (alpha === 0) done++;
        }
      }
      ctx.globalAlpha = alpha;
      const c = job.rgb.map((v, k) => Math.round(lerp(v, GREY[k], grey)));
      ctx.fillStyle = `rgb(${c[0]},${c[1]},${c[2]})`;
      if (p.prev && alpha > 0) {                          // short motion trail
        ctx.strokeStyle = ctx.fillStyle;
        ctx.globalAlpha = alpha * 0.35;
        ctx.lineWidth = r * 1.4;
        ctx.lineCap = 'round';
        ctx.beginPath(); ctx.moveTo(p.prev[0], p.prev[1]); ctx.lineTo(x, y); ctx.stroke();
        ctx.globalAlpha = alpha;
      }
      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
      p.prev = [x, y];
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
