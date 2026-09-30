<script>
  // Spinning BAF complex in the style of Goodsell & Olson's Illustrate, WebGL2:
  //   pass 1  instanced atom spheres (every heavy atom; <name>.atoms.bin from
  //           pipeline/bead_model.py), flat colour with carbons lighter than
  //           N/O/S, true sphere depth. Writes colour and a per-chain id with
  //           16-bit depth packed alongside into two targets at once (MRT).
  //           Until a model's atoms arrive, its residue beads are drawn instead.
  //   pass 2  full-screen: subunit outlines wherever the id changes, contour
  //           outlines wherever depth steps back (Illustrate's z-derivative
  //           outlines), and soft shadows from nearby atoms in front
  //   overlay 2D canvas for unmodelled "ghost" members and the swap scan line
  // Chains borrowed from another structure ("placed") or predicted are drawn
  // paler and hatched. The id target doubles as a pixel-exact hover picker.
  //
  // Every camera quantity is a critically damped spring, so any route change
  // (select -> complex -> subunit, and back, even mid-flight) just retargets
  // springs and never jumps. Swapping models plays a scan-line "beam in".
  import { onMount } from 'svelte';
  import { colorOf } from './colors.js';

  const ATOM_URLS = import.meta.glob('./models/*.atoms.bin', { query: '?url', import: 'default', eager: true });
  const ATOM_R = [1.6, 1.5, 1.8];   // Å: carbon, other, sulfur (Illustrate's enlarged radii)
  const TIER = { experimental: 0, placed: 1, predicted: 2 };
  const ZSPAN = 1200;               // Å of view depth packed into the id target's 16 bits
  let {
    model, mode = 'complex', selected = null, highlight = null, complex = null,
    onpick = () => {}, onhover = () => {}, onmorphsource = () => {}, onglfail = () => {},
  } = $props();

  const reduce = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const BEAD = 3.9;          // Å, bead radius
  const EXPLODE = 30;        // Å, how far unselected chains move out
  const SPIN = 0.5;          // rad/s on the select screen
  const TAU = Math.PI * 2;
  const MAXC = 32;           // chains per model (shader uniform arrays)

  let wrap, cvs, ink;
  let gl, inkCtx, prog, edgeProg, fb, quad;
  let W = 0, H = 0, PR = 1;
  let glFailed = $state(false);

  // ---- springs -------------------------------------------------------------
  const spring = (v, k) => ({ v, vel: 0, t: v, k });
  const S = {
    yaw: spring(-0.5, 55), pitch: spring(-0.22, 70), zoom: spring(0.8, 80),
    tx: spring(0, 70), ty: spring(0, 70), tz: spring(0, 70),
    explode: spring(0, 90), focus: spring(0, 110), labels: spring(0, 120),
  };
  function step(s, dt) {
    if (reduce) { s.v = s.t; s.vel = 0; return; }
    const a = s.k * (s.t - s.v) - 2 * Math.sqrt(s.k) * s.vel;
    s.vel += a * dt; s.v += s.vel * dt;
  }
  const settled = () => Object.values(S).every((s) => Math.abs(s.t - s.v) < 1e-3 && Math.abs(s.vel) < 1e-3);

  // ---- model preparation ---------------------------------------------------
  const prepCache = new WeakMap();
  function prepare(m) {
    if (prepCache.has(m)) return prepCache.get(m);
    const n = m.beads.length / 4;
    if (m.chains.length > MAXC) throw new Error(`${m.complex}: ${m.chains.length} chains > ${MAXC}`);
    let mx = 0, my = 0, mz = 0;
    for (let i = 0; i < n; i++) { mx += m.beads[4 * i]; my += m.beads[4 * i + 1]; mz += m.beads[4 * i + 2]; }
    const center = [mx / n, my / n, mz / n];
    // framing radius: 99th percentile, so a few stray beads don't shrink the model
    const dist = new Float32Array(n);
    for (let i = 0; i < n; i++)
      dist[i] = Math.hypot(m.beads[4 * i] - center[0], m.beads[4 * i + 1] - center[1], m.beads[4 * i + 2] - center[2]);
    dist.sort();
    const R = dist[Math.floor(0.99 * (n - 1))];
    const chains = m.chains.map((c, i) => ({ ...c, i }));
    const syms = [...new Set(chains.filter((c) => c.kind === 'subunit').map((c) => c.symbol))];
    const ghosts3d = [], ghostsFlat = [];
    for (const g of m.ghosts ?? []) {
      const anchors = chains.filter((c) => g.anchor_subunits?.includes(c.symbol));
      if (!anchors.length) { ghostsFlat.push(g); continue; }
      const a = [0, 1, 2].map((k) => anchors.reduce((s, c) => s + c.centroid[k], 0) / anchors.length);
      const d = a.map((v, k) => v - center[k]), dn = Math.hypot(...d) || 1;
      ghosts3d.push({ ...g, pos: a.map((v, k) => v + (d[k] / dn) * 22) });
    }
    const p = {
      src: m, n, center, R, chains, syms, ghosts3d, ghostsFlat,
      beads: new Float32Array(m.beads),
      res: Int32Array.from(m.res ?? []),       // UniProt residue per bead (0 = unmapped)
      hover: new Float32Array(MAXC), off: new Float32Array(MAXC * 3),
      act: new Float32Array(MAXC), vao: null,
      tier: Float32Array.from({ length: MAXC }, (_, i) => TIER[chains[i]?.tier] ?? 0),
      atoms: null, atomVao: null,
    };
    prepCache.set(m, p);
    loadAtoms(p);
    return p;
  }

  // <name>.atoms.bin: uint32 n | int16 xyz[3n] (0.1 Å) | uint8 chain[n] | uint8 elem[n]
  function loadAtoms(p) {
    const url = ATOM_URLS[`./models/${p.src.complex}.atoms.bin`];
    if (!url) return;
    fetch(url).then((r) => { if (!r.ok) throw new Error(`${url}: ${r.status}`); return r.arrayBuffer(); }).then((buf) => {
      const n = new DataView(buf).getUint32(0, true);
      const q = new Int16Array(buf, 4, 3 * n);
      const ch = new Uint8Array(buf, 4 + 6 * n, n), el = new Uint8Array(buf, 4 + 7 * n, n);
      const inst = new Float32Array(5 * n);
      for (let i = 0; i < n; i++) {
        inst[5 * i] = q[3 * i] / 10; inst[5 * i + 1] = q[3 * i + 1] / 10; inst[5 * i + 2] = q[3 * i + 2] / 10;
        inst[5 * i + 3] = ch[i]; inst[5 * i + 4] = el[i];
      }
      p.atoms = { n, inst };
      kick();
    }).catch((e) => console.warn('atoms unavailable, drawing residue beads', e));
  }

  let cur = $state.raw(null);      // prepared model on stage
  let next = $state.raw(null);     // incoming model during a swap
  let swapT = 1;

  $effect(() => {
    const p = prepare(model);
    if (!cur) { cur = p; return; }
    if (p === cur || p === next) return;
    if (reduce) { cur = p; return; }
    if (next) cur = next;          // swap interrupted: settle the previous one
    next = p; swapT = 0; kick();
  });

  // ---- selection geometry ----------------------------------------------------
  function slotMates(sym) {
    const sl = complex?.slots?.find((s) => s.members.includes(sym));
    return sl ? sl.members : [sym];
  }
  function focusOf(p, sym) {
    if (!sym) return null;
    const mates = slotMates(sym);
    const act = new Set(p.chains.filter((c) => mates.includes(c.symbol)).map((c) => c.i));
    if (act.size) {
      let w = 0; const f = [0, 0, 0];
      for (const i of act) { const c = p.chains[i]; for (let k = 0; k < 3; k++) f[k] += c.centroid[k] * c.n; w += c.n; }
      const cen = f.map((v) => v / w);
      let ext = 0;
      for (let i = 0; i < p.n; i++) if (act.has(p.beads[4 * i + 3]))
        ext = Math.max(ext, Math.hypot(p.beads[4 * i] - cen[0], p.beads[4 * i + 1] - cen[1], p.beads[4 * i + 2] - cen[2]));
      return { cen, ext, act };
    }
    const g = p.ghosts3d.find((g) => g.members.includes(sym));
    return g ? { cen: g.pos, ext: 30, act: new Set() } : null;
  }

  // Morph source: when a subunit gets selected, hand its beads' current
  // on-screen positions and UniProt residue numbers to the page (before the
  // camera starts moving), so they can fly onto the subunit's domain map.
  // Only the selected symbol's own chains are used: a paralog's modelled
  // chain has different residue numbers.
  let lastSelected = null;
  function screenPoints(p, sym) {
    if (!cvs || !W) return [];
    const cam = camera(p), rect = cvs.getBoundingClientRect(), out = [];
    for (let i = 0; i < p.n; i++) {
      const c = p.chains[p.beads[4 * i + 3]];
      if (c.symbol !== sym || !p.res[i]) continue;
      const [sx, sy, , k] = proj(cam, p.beads[4 * i] + p.off[3 * c.i], p.beads[4 * i + 1] + p.off[3 * c.i + 1],
        p.beads[4 * i + 2] + p.off[3 * c.i + 2]);
      out.push({ x: rect.left + sx, y: rect.top + sy, r: BEAD * cam.scale * k, u: p.res[i] });
    }
    return out;
  }

  let userYaw = 0, userPitch = -0.05;
  // Retarget springs whenever mode / selection / model change.
  $effect(() => {
    const p = next ?? cur;
    if (!p) return;
    if (mode === 'complex' && selected && selected !== lastSelected && !reduce) {
      const points = screenPoints(p, selected);
      if (points.length) onmorphsource?.({ sym: selected, points, color: colorOf(selected) });
    }
    lastSelected = mode === 'complex' ? selected : null;
    const f = mode === 'complex' ? focusOf(p, selected) : null;
    for (const q of [cur, next]) if (q) {
      const fq = q === p ? f : mode === 'complex' ? focusOf(q, selected) : null;
      q.act.fill(0);
      if (fq) for (const i of fq.act) q.act[i] = 1;
    }
    if (mode === 'select') {
      S.pitch.t = -0.22; S.zoom.t = 0.8; S.explode.t = 0; S.focus.t = 0; S.labels.t = 0;
      [S.tx.t, S.ty.t, S.tz.t] = p.center;
    } else if (f) {
      // orbit so the subunit faces the viewer, choosing the nearest equivalent yaw
      const face = Math.atan2(-(f.cen[0] - p.center[0]), f.cen[2] - p.center[2]);
      S.yaw.t = face + TAU * Math.round((S.yaw.v - face) / TAU);
      S.pitch.t = -0.08;
      S.zoom.t = Math.max(1.35, Math.min(2.4, (0.72 * p.R) / Math.max(f.ext, 25)));
      [S.tx.t, S.ty.t, S.tz.t] = f.cen;
      S.explode.t = 1; S.focus.t = 1; S.labels.t = 1;
    } else {
      S.yaw.t = TAU * Math.round(S.yaw.v / TAU) + userYaw;   // settle to the layout's front view
      S.pitch.t = userPitch; S.zoom.t = 1.02;
      [S.tx.t, S.ty.t, S.tz.t] = p.center;
      S.explode.t = 0; S.focus.t = 0; S.labels.t = 1;
    }
    kick();
  });

  // ---- palette (re-read on theme change) --------------------------------------
  let pal = null;
  function readPalette() {
    const cs = getComputedStyle(document.documentElement);
    const probe = document.createElement('canvas').getContext('2d', { willReadFrequently: true });
    const rgb = (css) => {
      probe.clearRect(0, 0, 1, 1); probe.fillStyle = '#000'; probe.fillStyle = css.trim();
      probe.fillRect(0, 0, 1, 1); const d = probe.getImageData(0, 0, 1, 1).data; return [d[0] / 255, d[1] / 255, d[2] / 255];
    };
    pal = {
      bg: rgb(cs.getPropertyValue('--bg')), ink: rgb(cs.getPropertyValue('--bead-ink')),
      histone: rgb(cs.getPropertyValue('--histone')), dna: rgb(cs.getPropertyValue('--dna')),
      unassigned: rgb(cs.getPropertyValue('--c-other')), rgb,
    };
    for (const p of [cur, next]) if (p) p.base = null;
    kick();
  }
  function baseColors(p) {
    if (p.base) return p.base;
    const a = new Float32Array(MAXC * 3);
    for (const c of p.chains) {
      const v = c.kind === 'subunit' ? pal.rgb(colorOf(c.symbol))
        : c.kind === 'histone' ? pal.histone : c.kind === 'dna' ? pal.dna : pal.unassigned;
      a.set(v, 3 * c.i);
    }
    return (p.base = a);
  }

  // ---- WebGL -----------------------------------------------------------------------
  const VS = `#version 300 es
    layout(location=0) in vec2 corner;
    layout(location=1) in vec4 bead;          // xyz (Å), chain index
    layout(location=2) in float elem;         // 0 carbon, 1 other, 2 sulfur (beads: 0)
    uniform mat3 rot; uniform vec3 target; uniform float scale, F, R; uniform vec3 radii; uniform vec2 halfPx;
    uniform vec3 offs[${MAXC}]; uniform float hov[${MAXC}];
    out vec2 uv; flat out int chain; flat out float kind; out float pz, rw;
    void main() {
      int c = int(bead.w + 0.5);
      int e = int(elem + 0.5);
      vec3 p = rot * (bead.xyz + offs[c] - target);
      float k = F / (F - p.z);
      rw = (e == 0 ? radii.x : e == 1 ? radii.y : radii.z) * (1.0 + 0.12 * hov[c]);
      vec2 s = p.xy * scale * k + corner * rw * scale * k;
      gl_Position = vec4(s.x / halfPx.x, -s.y / halfPx.y, clamp(-(p.z + rw) / (R * 2.5), -1.0, 1.0), 1.0);
      uv = corner; chain = c; kind = float(e); pz = p.z;
    }`;
  const FS = `#version 300 es
    precision highp float;
    in vec2 uv; flat in int chain; flat in float kind; in float pz, rw;
    uniform vec3 col[${MAXC}]; uniform float act[${MAXC}]; uniform float hov[${MAXC}]; uniform float tier[${MAXC}];
    uniform vec3 bg; uniform float focus, which, scanY, scanDir, H, R, cue, PR;
    layout(location=0) out vec4 outColor;
    layout(location=1) out vec4 outId;
    void main() {
      float d2 = dot(uv, uv);
      if (d2 > 1.0) discard;
      float y = H - gl_FragCoord.y;
      if (scanDir > 0.5 && y > scanY) discard;
      if (scanDir < -0.5 && y <= scanY) discard;
      float z = pz + rw * sqrt(1.0 - d2);                 // sphere surface, toward the viewer
      gl_FragDepth = 0.5 + 0.5 * clamp(-z / (R * 2.5), -1.0, 1.0);
      vec3 c = col[chain];
      if (kind > 0.5) c *= 0.84;                          // N, O, S, P darker than carbon
      float t = tier[chain];
      if (t > 0.5) {                                      // borrowed or predicted: paler, hatched
        c = mix(c, t > 1.5 ? bg : vec3(1.0), t > 1.5 ? 0.45 : 0.3);
        if (mod(gl_FragCoord.x + gl_FragCoord.y, 7.0 * PR) < 1.6 * PR) c *= 0.86;
      }
      c = mix(c, bg, 0.68 * focus * (1.0 - act[chain]));
      c = mix(c, vec3(1.0), 0.28 * hov[chain]);
      float depth01 = clamp((z + R) / (2.0 * R), 0.0, 1.0);
      c = mix(bg, c, 1.0 - cue + cue * depth01);
      // materialising glow just behind the scan line on the incoming model
      if (scanDir > 0.5) c = mix(c, vec3(0.55, 0.95, 1.0), 0.6 * exp(-abs(scanY - y) / 18.0));
      outColor = vec4(c, 1.0);
      // id: chain+1, model; depth (0 near .. 1 far) packed into 16 bits
      float dq = floor(clamp(0.5 - z / ${ZSPAN}.0, 0.0, 1.0) * 65535.0 + 0.5);
      outId = vec4(float(chain + 1) / 255.0, which / 255.0, floor(dq / 256.0) / 255.0, mod(dq, 256.0) / 255.0);
    }`;
  const EVS = `#version 300 es
    layout(location=0) in vec2 corner;
    void main() { gl_Position = vec4(corner, 0.0, 1.0); }`;
  // Post pass, after Illustrate's outline and shadow model (depths in Å):
  //   subunit outline  the chain id differs from a neighbour k px away
  //   contour outline  summed depth steps to the 8 neighbours (each capped at
  //                    zCap) ramp from lo to hi -> grey to ink
  //   shadow           fraction of 12 samples within sR Å that sit well in front
  const EFS = `#version 300 es
    precision highp float;
    uniform sampler2D colTex, idTex; uniform float k, pxPerA, lo, hi, zCap, sR, sMax, contour;
    uniform vec3 ink;
    uniform float faintA[${MAXC}], faintB[${MAXC}];
    out vec4 outColor;
    const float FAR = 1e5;
    const ivec2 NB[8] = ivec2[8](ivec2(1, 0), ivec2(-1, 0), ivec2(0, 1), ivec2(0, -1),
                                 ivec2(1, 1), ivec2(-1, 1), ivec2(1, -1), ivec2(-1, -1));
    vec4 at(ivec2 q) { return texelFetch(idTex, q, 0); }
    float depthOf(vec4 id) { return id.r == 0.0 ? FAR : (id.b * 255.0 * 256.0 + id.a * 255.0) / 65535.0 * ${ZSPAN}.0; }
    void main() {
      ivec2 q = ivec2(gl_FragCoord.xy);
      vec4 id = at(q);
      if (id.r == 0.0) { outColor = vec4(0.0); return; }
      int ik = int(k);
      float z = depthOf(id);
      bool edge = false; float steps = 0.0;
      for (int j = 0; j < 8; j++) {
        vec4 n = at(q + NB[j] * ik);
        if (j < 4) edge = edge || any(notEqual(id.rg, n.rg));
        steps += clamp(depthOf(n) - z, 0.0, zCap);
      }
      vec3 c = texelFetch(colTex, q, 0).rgb;
      // soft shadow from atoms in front, on a ring of sR Å
      float occ = 0.0;
      float rp = sR * pxPerA;
      for (int j = 0; j < 12; j++) {
        float a = float(j) * 0.5236 + 0.37;
        float rr = rp * (0.45 + 0.55 * fract(float(j) * 0.618));
        vec4 n = at(q + ivec2(round(vec2(cos(a), sin(a)) * rr)));
        occ += smoothstep(1.0, 6.0, z - depthOf(n));
      }
      c *= 1.0 - sMax * occ / 12.0;
      int ch = int(id.r * 255.0 + 0.5) - 1;
      float fa = int(id.g * 255.0 + 0.5) == 2 ? faintB[ch] : faintA[ch];
      float line = contour * smoothstep(lo, hi, steps);
      if (edge) line = 1.0;
      c = mix(c, ink, line * fa);
      outColor = vec4(c, 1.0);
    }`;

  function compile(vs, fs) {
    const mk = (type, src) => {
      const sh = gl.createShader(type); gl.shaderSource(sh, src); gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(sh));
      return sh;
    };
    const pr = gl.createProgram();
    gl.attachShader(pr, mk(gl.VERTEX_SHADER, vs)); gl.attachShader(pr, mk(gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(pr);
    if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(pr));
    const u = {};
    for (let i = 0, n = gl.getProgramParameter(pr, gl.ACTIVE_UNIFORMS); i < n; i++) {
      const name = gl.getActiveUniform(pr, i).name.replace(/\[0\]$/, '');
      u[name] = gl.getUniformLocation(pr, name);
    }
    return { pr, u };
  }

  function initGL() {
    gl = cvs.getContext('webgl2', { alpha: true, premultipliedAlpha: true, antialias: false, preserveDrawingBuffer: false });
    if (!gl) throw new Error('WebGL2 unavailable');
    prog = compile(VS, FS);
    edgeProg = compile(EVS, EFS);
    quad = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, quad);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    fb = { fbo: gl.createFramebuffer(), col: gl.createTexture(), id: gl.createTexture(), depth: gl.createRenderbuffer(), w: 0, h: 0 };
    edgeVao = gl.createVertexArray();
    gl.bindVertexArray(edgeVao);
    gl.bindBuffer(gl.ARRAY_BUFFER, quad);
    gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.bindVertexArray(null);
  }
  let edgeVao;

  function sizeTargets(w, h) {
    if (fb.w === w && fb.h === h) return;
    fb.w = w; fb.h = h;
    for (const t of [fb.col, fb.id]) {
      gl.bindTexture(gl.TEXTURE_2D, t);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    }
    gl.bindRenderbuffer(gl.RENDERBUFFER, fb.depth);
    gl.renderbufferStorage(gl.RENDERBUFFER, gl.DEPTH_COMPONENT24, w, h);
    gl.bindFramebuffer(gl.FRAMEBUFFER, fb.fbo);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, fb.col, 0);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT1, gl.TEXTURE_2D, fb.id, 0);
    gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.RENDERBUFFER, fb.depth);
    gl.drawBuffers([gl.COLOR_ATTACHMENT0, gl.COLOR_ATTACHMENT1]);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  }

  function makeVao(data, stride) {
    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, quad);
    gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 4, gl.FLOAT, false, stride * 4, 0);
    gl.vertexAttribDivisor(1, 1);
    if (stride === 5) {
      gl.enableVertexAttribArray(2); gl.vertexAttribPointer(2, 1, gl.FLOAT, false, 20, 16);
      gl.vertexAttribDivisor(2, 1);
    } else {
      gl.disableVertexAttribArray(2); gl.vertexAttrib1f(2, 0);
    }
    gl.bindVertexArray(null);
    return vao;
  }
  // atoms once loaded, residue beads until then
  function geometry(p) {
    if (p.atoms) return { vao: (p.atomVao ??= makeVao(p.atoms.inst, 5)), n: p.atoms.n, atoms: true };
    return { vao: (p.vao ??= makeVao(p.beads, 4)), n: p.n, atoms: false };
  }

  // ---- camera ----------------------------------------------------------------------
  function camera(p) {
    const cy = Math.cos(S.yaw.v), sy = Math.sin(S.yaw.v), cp = Math.cos(S.pitch.v), sp = Math.sin(S.pitch.v);
    // rot = Rx(pitch) * Ry(yaw), column-major for GLSL
    const m = [cy, sp * sy, -cp * sy, 0, cp, sp, sy, -sp * cy, cp * cy];
    const scale = (Math.min(W, H) * 0.47 * S.zoom.v) / p.R;
    return { m, scale, F: p.R * 5, t: [S.tx.v, S.ty.v, S.tz.v] };
  }
  function proj(cam, x, y, z) {
    const [a, b, c, d, e, f, g, h, i] = cam.m;
    x -= cam.t[0]; y -= cam.t[1]; z -= cam.t[2];
    const X = a * x + d * y + g * z, Y = b * x + e * y + h * z, Z = c * x + f * y + i * z;
    const k = cam.F / (cam.F - Z);
    return [W / 2 + X * cam.scale * k, H / 2 + Y * cam.scale * k, Z, k];
  }

  // per-chain explode offsets (away from the focus point) and hover easing
  function animateChains(p, dt) {
    const e = S.explode.v * EXPLODE;
    const hs = hoverSym ?? highlight;
    const hm = hs ? new Set(slotMates(hs)) : null;
    let busy = false;
    for (const c of p.chains) {
      let ox = 0, oy = 0, oz = 0;
      if (e > 0.01 && !p.act[c.i]) {
        const d = [c.centroid[0] - S.tx.t, c.centroid[1] - S.ty.t, c.centroid[2] - S.tz.t];
        const dn = Math.hypot(...d) || 1;
        ox = (d[0] / dn) * e; oy = (d[1] / dn) * e; oz = (d[2] / dn) * e;
      }
      p.off[3 * c.i] = ox; p.off[3 * c.i + 1] = oy; p.off[3 * c.i + 2] = oz;
      const target = hm && c.kind === 'subunit' && hm.has(c.symbol) ? 1 : 0;
      const h = p.hover[c.i];
      p.hover[c.i] = reduce ? target : h + (target - h) * (1 - Math.exp(-dt * 16));
      if (Math.abs(p.hover[c.i] - target) > 0.002) busy = true;
    }
    return busy;
  }

  function drawModel(p, cam, which, scanDir, scanY) {
    const u = prog.u;
    gl.uniformMatrix3fv(u.rot, false, cam.m);
    gl.uniform3fv(u.target, cam.t);
    gl.uniform1f(u.scale, cam.scale * PR); gl.uniform1f(u.F, cam.F); gl.uniform1f(u.R, p.R);
    const g = geometry(p);
    gl.uniform3fv(u.radii, g.atoms ? ATOM_R : [BEAD, BEAD, BEAD]);
    gl.uniform2f(u.halfPx, (W * PR) / 2, (H * PR) / 2);
    gl.uniform3fv(u.offs, p.off); gl.uniform1fv(u.hov, p.hover);
    gl.uniform3fv(u.col, baseColors(p)); gl.uniform1fv(u.act, p.act); gl.uniform1fv(u.tier, p.tier);
    gl.uniform3fv(u.bg, pal.bg); gl.uniform1f(u.focus, S.focus.v);
    gl.uniform1f(u.which, which); gl.uniform1f(u.scanY, scanY * PR); gl.uniform1f(u.scanDir, scanDir);
    gl.uniform1f(u.H, H * PR); gl.uniform1f(u.PR, PR);
    gl.uniform1f(u.cue, g.atoms ? 0.22 : 0.5);          // depth cue: Illustrate uses (almost) none
    gl.bindVertexArray(g.vao);
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, g.n);
    return g.atoms;
  }

  // ---- interaction -------------------------------------------------------------
  let hoverSym = $state(null);
  let pointer = null;                  // {x, y} in CSS px
  let drag = null;
  let ghostHits = [];                  // [{x, y, r, sym}] screen space
  const px1 = new Uint8Array(4);

  function pick(x, y) {
    for (const g of ghostHits) if (Math.hypot(x - g.x, y - g.y) < g.r) return g.sym;
    if (!gl || !fb.w) return null;
    const ix = Math.floor(x * PR), iy = fb.h - 1 - Math.floor(y * PR);
    if (ix < 0 || iy < 0 || ix >= fb.w || iy >= fb.h) return null;
    gl.bindFramebuffer(gl.READ_FRAMEBUFFER, fb.fbo);
    gl.readBuffer(gl.COLOR_ATTACHMENT1);
    gl.readPixels(ix, iy, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px1);
    gl.bindFramebuffer(gl.READ_FRAMEBUFFER, null);
    if (!px1[0]) return null;
    const p = px1[1] === 2 ? next : cur;
    const c = p?.chains[px1[0] - 1];
    return c && c.kind === 'subunit' ? c.symbol : null;
  }
  function setHover(sym) {
    if (sym === hoverSym) return;
    hoverSym = sym; onhover(sym); kick();
  }
  function onmove(e) {
    const r = cvs.getBoundingClientRect();
    pointer = { x: e.clientX - r.left, y: e.clientY - r.top };
    if (drag) {
      if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) > 4) drag.moved = true;
      if (drag.moved && mode === 'complex') {
        const dx = (e.clientX - drag.lx) * 0.009;
        S.yaw.t += dx; userYaw += dx;
        S.pitch.t = Math.max(-1.1, Math.min(1.1, S.pitch.t + (e.clientY - drag.ly) * 0.006));
        userPitch = S.pitch.t;
        drag.vx = e.clientX - drag.lx;
      }
      drag.lx = e.clientX; drag.ly = e.clientY;
      kick();
      return;
    }
    wantPick = true; kick();
  }
  function ondown(e) {
    drag = { x: e.clientX, y: e.clientY, lx: e.clientX, ly: e.clientY, moved: false, vx: 0 };
    cvs.setPointerCapture(e.pointerId);
  }
  function onup(e) {
    const d = drag; drag = null;
    if (!d) return;
    if (d.moved) { S.yaw.t += d.vx * 0.03; userYaw += d.vx * 0.03; kick(); return; }   // inertia
    const r = cvs.getBoundingClientRect();
    onpick(mode === 'select' ? '__complex__' : pick(e.clientX - r.left, e.clientY - r.top));
  }
  function onleave() { pointer = null; if (!drag) setHover(null); }
  let wantPick = false;

  // ---- render loop ----------------------------------------------------------------
  let raf = 0, last = 0;
  // Adaptive resolution: if animated frames keep running slow (integrated GPUs
  // on high-DPI screens), drop to 1 device pixel per CSS pixel for the session.
  let slowEma = 0, slowN = 0, lowPower = false;
  function watchFrameTime(ms) {
    if (lowPower || PR <= 1) return;
    slowEma = slowN ? slowEma * 0.9 + ms * 0.1 : ms; slowN++;
    if (slowN > 30 && slowEma > 24) {
      lowPower = true; resize();
      console.info(`3D view: frames averaged ${slowEma.toFixed(0)} ms, rendering at 1x resolution`);
    }
  }
  function kick() { if (!raf && gl) { last = performance.now(); raf = requestAnimationFrame(frame); } }

  function frame(now) {
    raf = 0;
    const raw = now - last;
    const dt = Math.min(1 / 30, raw / 1000); last = now;
    if (raw > 0 && raw < 250) watchFrameTime(raw);
    if (mode === 'select' && !reduce && !drag) S.yaw.t += SPIN * dt;
    for (const s of Object.values(S)) step(s, dt);
    if (next) {
      swapT = Math.min(1, swapT + dt / 0.6);
      if (swapT >= 1) { cur = next; next = null; }
    }
    const busy = draw(dt);
    if (mode === 'select' || !settled() || next || busy || drag) raf = requestAnimationFrame(frame);
  }

  let labelEls = $state({});
  function draw(dt) {
    if (!gl || !cur || !pal || !W) return false;
    const w = Math.round(W * PR), h = Math.round(H * PR);
    sizeTargets(w, h);
    const pA = cur, pB = next;
    const camA = camera(pA);
    let busy = animateChains(pA, dt);
    if (pB) busy = animateChains(pB, dt) || busy;

    // pass 1: beads -> colour + id
    gl.bindFramebuffer(gl.FRAMEBUFFER, fb.fbo);
    gl.viewport(0, 0, w, h);
    gl.clearBufferfv(gl.COLOR, 0, [0, 0, 0, 0]);
    gl.clearBufferfv(gl.COLOR, 1, [0, 0, 0, 0]);
    gl.clearBufferfv(gl.DEPTH, 0, [1]);
    gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LESS);
    gl.useProgram(prog.pr);
    let scan = 0, atoms;
    if (pB) {
      const camB = camera(pB);
      const t = 1 - Math.pow(1 - swapT, 3);
      const top = H / 2 - pB.R * camB.scale * 1.05, bot = H / 2 + pB.R * camB.scale * 1.05;
      scan = top + (bot - top) * t;
      drawModel(pA, camA, 1, -1, scan);
      atoms = drawModel(pB, camB, 2, 1, scan);
    } else {
      atoms = drawModel(pA, camA, 1, 0, 0);
    }
    gl.disable(gl.DEPTH_TEST);

    // pass 2: outlines -> screen
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, w, h);
    gl.useProgram(edgeProg.pr);
    const eu = edgeProg.u;
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, fb.col); gl.uniform1i(eu.colTex, 0);
    gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, fb.id); gl.uniform1i(eu.idTex, 1);
    gl.uniform1f(eu.k, Math.max(1, Math.round(PR * 1.15)));
    gl.uniform3fv(eu.ink, pal.ink);
    gl.uniform1f(eu.pxPerA, camA.scale * PR);
    // Illustrate contour card "3.0,10.0,4,0.0,5.0": ramp lo..hi, steps capped at 5 Å
    gl.uniform1f(eu.lo, 3.0); gl.uniform1f(eu.hi, 10.0); gl.uniform1f(eu.zCap, 5.0);
    gl.uniform1f(eu.contour, atoms ? 1 : 0);
    gl.uniform1f(eu.sR, 7.0); gl.uniform1f(eu.sMax, atoms ? 0.38 : 0);
    const faint = (p) => { const a = new Float32Array(MAXC); for (let i = 0; i < MAXC; i++) a[i] = 0.9 - 0.62 * S.focus.v * (1 - (p?.act[i] ?? 0)); return a; };
    gl.uniform1fv(eu.faintA, faint(pA)); gl.uniform1fv(eu.faintB, faint(pB));
    gl.bindVertexArray(edgeVao);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    gl.bindVertexArray(null);

    // overlay: ghosts + scan line
    inkCtx.clearRect(0, 0, ink.width, ink.height);
    const shown = pB && swapT > 0.5 ? pB : pA;
    ghosts(shown, camera(shown));
    if (pB) {
      const gr = inkCtx.createLinearGradient(0, (scan - 14) * PR, 0, (scan + 14) * PR);
      gr.addColorStop(0, 'rgba(60,200,210,0)'); gr.addColorStop(0.5, 'rgba(90,220,230,0.9)'); gr.addColorStop(1, 'rgba(60,200,210,0)');
      inkCtx.fillStyle = gr; inkCtx.fillRect(0, (scan - 14) * PR, ink.width, 28 * PR);
    }
    positionLabels(pB ?? pA, camera(pB ?? pA));
    if (pointer && !drag && (wantPick || busy || mode === 'select' || !settled())) { wantPick = false; setHover(pick(pointer.x, pointer.y)); }
    return busy;
  }

  function ghosts(p, cam) {
    ghostHits = [];
    for (const g of p.ghosts3d) {
      const [sx, sy, , k] = proj(cam, ...g.pos);
      const r = 17 * cam.scale * k;
      const on = selected && g.members.includes(selected);
      const dim = mode === 'complex' && selected && !on;
      inkCtx.save();
      inkCtx.globalAlpha = (dim ? 0.35 : 1) * (mode === 'select' ? 0.6 : 1);
      inkCtx.fillStyle = colorOf(g.members[0]) + (on ? '66' : '2e');
      inkCtx.strokeStyle = on ? `rgb(${pal.ink.map((v) => v * 255).join(',')})` : colorOf(g.members[0]);
      inkCtx.lineWidth = (on ? 3 : 2) * PR;
      inkCtx.setLineDash([6 * PR, 5 * PR]);
      inkCtx.beginPath(); inkCtx.arc(sx * PR, sy * PR, r * PR, 0, TAU); inkCtx.fill(); inkCtx.stroke();
      inkCtx.restore();
      ghostHits.push({ x: sx, y: sy, r, sym: g.members[0] });
    }
  }

  // Labels: DOM overlay, positioned every frame without touching Svelte state.
  function positionLabels(p, cam) {
    for (const sym of p.syms) {
      const el = labelEls[sym];
      if (!el) continue;
      let x = 0, y = 0, z = 0, n = 0;
      for (const c of p.chains) if (c.symbol === sym) {
        x += (c.centroid[0] + p.off[3 * c.i]) * c.n; y += (c.centroid[1] + p.off[3 * c.i + 1]) * c.n;
        z += (c.centroid[2] + p.off[3 * c.i + 2]) * c.n; n += c.n;
      }
      const [sx, sy, sz] = proj(cam, x / n, y / n, z / n);
      el.style.transform = `translate(${sx}px, ${sy}px) translate(-50%, -50%)`;
      el.style.opacity = String(S.labels.v * (sz > -p.R * 0.55 ? 1 : 0.35));
    }
  }

  const activeSet = $derived(new Set(selected ? slotMates(selected) : []));

  function resize() {
    const r = wrap.getBoundingClientRect();
    W = r.width; H = r.height;
    PR = lowPower ? 1 : Math.min(window.devicePixelRatio || 1, 2);
    for (const c of [cvs, ink]) { c.width = Math.round(W * PR); c.height = Math.round(H * PR); }
    kick();
  }

  onMount(() => {
    try { initGL(); } catch (e) { console.warn(e); glFailed = true; onglfail(); return; }
    inkCtx = ink.getContext('2d');
    readPalette();
    const ro = new ResizeObserver(resize);
    ro.observe(wrap);
    const mo = new MutationObserver(readPalette);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    const mq = matchMedia('(prefers-color-scheme: dark)');
    mq.addEventListener('change', readPalette);
    const lost = (e) => { e.preventDefault(); glFailed = true; onglfail(); };
    cvs.addEventListener('webglcontextlost', lost);
    kick();
    return () => {
      ro.disconnect(); mo.disconnect(); mq.removeEventListener('change', readPalette);
      cvs.removeEventListener('webglcontextlost', lost); cancelAnimationFrame(raf);
    };
  });
</script>

<div class="stage3d" class:select={mode === 'select'} class:grab={mode === 'complex'} class:pointing={!!hoverSym} bind:this={wrap}>
  <div class="pedestal" aria-hidden="true"></div>
  <canvas bind:this={cvs} aria-hidden="true"
          onpointermove={onmove} onpointerdown={ondown} onpointerup={onup} onpointerleave={onleave}></canvas>
  <canvas bind:this={ink} class="ink" aria-hidden="true"></canvas>
  {#if glFailed}
    <p class="nogl">3D view needs WebGL2. Use the subunit list to explore this complex.</p>
  {/if}
  {#if cur}
    <div class="labels" aria-hidden="true">
      {#each (next ?? cur).syms as sym (sym)}
        <span class="lbl" bind:this={labelEls[sym]}
              class:on={activeSet.has(sym)} class:hot={hoverSym === sym || highlight === sym}
              class:off={mode === 'complex' && selected && !activeSet.has(sym) && hoverSym !== sym}>{sym}</span>
      {/each}
    </div>
    {#if mode === 'complex' && cur.src.chains.some((c) => c.source)}
      <p class="borrowed">
        <span class="swatch-hatch" aria-hidden="true"></span>
        Paler, hatched:
        {#each cur.src.chains.filter((c) => c.source) as c, i (c.chain)}{i ? '; ' : ''}{c.symbol} placed from
          {c.source.pdb} (aligned on {c.source.fit_on.join('/')}, RMSD {c.source.rmsd} Å){/each}
      </p>
    {/if}
    {#if mode === 'complex' && cur.ghostsFlat.length}
      <div class="unresolved">
        <span class="muted">Not resolved in {cur.src.pdb}:</span>
        {#each cur.ghostsFlat as g (g.slot)}
          <button class="chip" class:on={g.members.includes(selected)} onclick={() => onpick(g.members[0])}>{g.slot}</button>
        {/each}
      </div>
    {/if}
    <ul class="sr-only">
      {#each cur.syms as sym (sym)}<li><button onclick={() => onpick(sym)}>{sym}</button></li>{/each}
    </ul>
  {/if}
</div>

<style>
  .stage3d { position: relative; width: 100%; aspect-ratio: 1 / 1; max-height: calc(100vh - 120px); user-select: none; touch-action: none; }
  canvas { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
  .ink { pointer-events: none; }
  .grab canvas { cursor: grab; }
  .grab canvas:active { cursor: grabbing; }
  .pointing canvas, .select canvas { cursor: pointer; }
  .pedestal {
    position: absolute; left: 12%; right: 12%; bottom: 3%; height: 16%;
    background: radial-gradient(closest-side, color-mix(in srgb, var(--accent) 30%, transparent), transparent 72%);
    opacity: 0; transform: scale(0.7); transition: opacity 600ms, transform 700ms cubic-bezier(.3,1.4,.5,1);
    filter: blur(2px);
  }
  .select .pedestal { opacity: 1; transform: scale(1); }
  .nogl { position: absolute; inset: 40% 10% auto; text-align: center; color: var(--ink-3); }
  .labels { position: absolute; inset: 0; pointer-events: none; overflow: hidden; }
  .lbl {
    position: absolute; left: 0; top: 0; white-space: nowrap; opacity: 0;
    font: 600 12.5px var(--font); letter-spacing: 0.02em; color: var(--ink);
    padding: 1px 7px; border-radius: 999px;
    background: color-mix(in srgb, var(--surface) 78%, transparent);
    box-shadow: 0 1px 3px rgb(0 0 0 / 12%);
    transition: font-size 250ms, padding 250ms, background 250ms, scale 250ms cubic-bezier(.3,1.6,.5,1), visibility 0s;
    will-change: transform;
  }
  .lbl.on { font-size: 15px; padding: 3px 10px; background: var(--ink); color: var(--bg); }
  .lbl.hot { scale: 1.12; background: var(--surface); box-shadow: 0 3px 12px rgb(0 0 0 / 22%); }
  .lbl.off { visibility: hidden; }
  .unresolved {
    position: absolute; left: 0; right: 0; bottom: 8px; display: flex; flex-wrap: wrap; gap: 6px;
    justify-content: center; align-items: center; font-size: 12.5px;
  }
  .unresolved .chip { cursor: pointer; border-style: dashed; }
  .borrowed {
    position: absolute; left: 0; right: 0; bottom: 40px; margin: 0; text-align: center;
    font-size: 12px; color: var(--ink-3); pointer-events: none;
  }
  .swatch-hatch {
    display: inline-block; width: 12px; height: 12px; border-radius: 3px; vertical-align: -2px; margin-right: 4px;
    background: repeating-linear-gradient(135deg, var(--ink-3) 0 1.5px, transparent 1.5px 5px);
    border: 1px solid var(--line);
  }
</style>
