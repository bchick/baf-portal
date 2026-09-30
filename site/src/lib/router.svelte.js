// Minimal hash router: #/cBAF, #/cBAF/SMARCA4, #/gene/SMARCA4/p.Arg1192His
export const route = $state({ parts: [] });

function parse() {
  const h = location.hash.replace(/^#\/?/, '');
  route.parts = h.split('/').filter(Boolean).map(decodeURIComponent);
}

export function go(path) {
  location.hash = '#/' + path.split('/').map(encodeURIComponent).join('/');
}

export function href(...parts) {
  return '#/' + parts.map(encodeURIComponent).join('/');
}

if (typeof window !== 'undefined') {
  window.addEventListener('hashchange', parse);
  parse();
}
