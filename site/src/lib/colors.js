// One colour per subunit, stable across every complex view. Paralogs share a
// hue family and differ in lightness so a slot reads as one module.
export const SUBUNIT_COLOR = {
  SMARCA4: '#0e7c86', SMARCA2: '#3aa6ad',
  ARID1A: '#d9822b', ARID1B: '#e8a55a', ARID2: '#b8641c',
  SMARCC1: '#7a5cc7', SMARCC2: '#9a82dc',
  SMARCD1: '#2f6fd6', SMARCD2: '#5a8fe3', SMARCD3: '#86aeee',
  SMARCE1: '#d0508f',
  SMARCB1: '#df4a3a',
  DPF1: '#3e9e58', DPF2: '#56b36d', DPF3: '#7fc890',
  SS18: '#c9a227', SS18L1: '#dcbd57',
  ACTL6A: '#5d7185', ACTL6B: '#8193a6', ACTB: '#9aa7b4',
  BCL7A: '#b07cc6', BCL7B: '#c59ad6', BCL7C: '#d7b7e3',
  PBRM1: '#a23b72', BRD7: '#c9577f', PHF10: '#6aa84f',
  BICRA: '#8c6d31', BICRAL: '#b09155', BRD9: '#3d8fb8',
};

export function colorOf(sym) { return SUBUNIT_COLOR[sym] || '#8a8f98'; }

// ClinVar germline classes -> palette key (ordered by severity for "worst class" rollups)
export const CLASS_ORDER = ['P/LP', 'Conflicting', 'VUS', 'B/LB', 'Other'];
export const CLASS_COLOR = {
  'P/LP': 'var(--c-plp)', Conflicting: 'var(--c-conf)', VUS: 'var(--c-vus)',
  'B/LB': 'var(--c-blb)', Other: 'var(--c-other)', TCGA: 'var(--c-tcga)', UniProt: 'var(--c-uniprot)',
};

export function classKey(v) {
  const c = v?.cv?.germ?.c || '';
  if (/^(Pathogenic|Likely pathogenic|Pathogenic\/Likely pathogenic)/i.test(c)) return 'P/LP';
  if (/conflicting/i.test(c)) return 'Conflicting';
  if (/uncertain/i.test(c)) return 'VUS';
  if (/benign/i.test(c)) return 'B/LB';
  if (!v.cv && v.up) return /pathogenic/i.test(v.up.desc) ? 'P/LP' : 'Other';
  return 'Other';
}
