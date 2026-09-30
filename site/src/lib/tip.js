// `use:tip={text}`: an instant tooltip (the native title attribute waits about
// a second and never shows on touch). One shared bubble, fixed-positioned so no
// card or table clips it; shown on hover, keyboard focus, or a tap.
let bubble, owner = null, seq = 0;

function ensure() {
  if (bubble) return bubble;
  bubble = document.createElement('div');
  bubble.className = 'tip-bubble';
  bubble.setAttribute('role', 'tooltip');
  bubble.id = 'tip-bubble';
  document.body.appendChild(bubble);
  addEventListener('scroll', () => owner && hide(owner), { passive: true, capture: true });
  return bubble;
}

function show(node, text) {
  if (!text) return;
  const b = ensure();
  owner = node; seq++;
  b.textContent = text;
  b.classList.add('on');
  node.setAttribute('aria-describedby', b.id);
  const r = node.getBoundingClientRect(), w = b.offsetWidth, h = b.offsetHeight;
  const x = Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width / 2 - w / 2));
  const below = r.top - h - 8 < 4;
  b.style.left = `${x}px`;
  b.style.top = `${below ? r.bottom + 8 : r.top - h - 8}px`;
}

function hide(node) {
  if (owner !== node) return;
  owner = null;
  bubble?.classList.remove('on');
  node.removeAttribute('aria-describedby');
}

export function tip(node, text) {
  let t = text;
  if (!node.hasAttribute('tabindex') && !/^(A|BUTTON|INPUT|SELECT|TEXTAREA)$/.test(node.tagName)) node.tabIndex = 0;
  const on = () => show(node, t), off = () => hide(node);
  const tap = (e) => { if (e.pointerType === 'touch') { owner === node ? off() : on(); } };
  node.addEventListener('pointerenter', (e) => e.pointerType !== 'touch' && on());
  node.addEventListener('pointerleave', off);
  node.addEventListener('focus', on);
  node.addEventListener('blur', off);
  node.addEventListener('pointerup', tap);
  return {
    update(v) { t = v; if (owner === node) show(node, t); },
    destroy() { off(); },
  };
}
