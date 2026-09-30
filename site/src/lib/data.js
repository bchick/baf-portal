// Static data loader. All files are versioned under public/data/v<date>/.
const base = import.meta.env.BASE_URL + 'data/';
const cache = new Map();

async function json(path) {
  if (!cache.has(path)) {
    cache.set(path, fetch(base + path).then((r) => {
      if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
      return r.json();
    }));
  }
  return cache.get(path);
}

export async function latest() { return json('latest.json'); }
export async function complexes() { const l = await latest(); return json(l.path + 'complexes.json'); }
export async function manifest() { const l = await latest(); return json(l.path + 'manifest.json'); }
export async function refs() { const l = await latest(); return json(l.path + 'refs.json'); }
export async function cohorts() { const l = await latest(); return json(l.odbl + 'cohorts.json'); }
export async function gene(sym) { const l = await latest(); return json(l.path + sym + '.json'); }
export async function geneRefs(sym) { const l = await latest(); return json(l.path + sym + '.refs.json'); }
export async function tcga(sym) { const l = await latest(); return json(l.odbl + sym + '.tcga.json'); }

