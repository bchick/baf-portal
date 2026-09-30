// Plain-language names for the codes the mutation views use.

export const CLINVAR_TIP = {
  'P/LP': 'Pathogenic or likely pathogenic: ClinVar germline classification',
  Conflicting: 'Conflicting classifications: ClinVar submitters disagree about pathogenicity',
  VUS: 'Variant of uncertain significance: not enough evidence to call it pathogenic or benign',
  'B/LB': 'Benign or likely benign: ClinVar germline classification',
  Other: 'Any other ClinVar classification (e.g. risk factor, drug response, not provided), or a UniProt variant not annotated as disease-causing',
};

export const SOM_TIP = {
  missense: 'Missense: a single amino acid substitution',
  truncating: 'Truncating: nonsense, frameshift or splice-site changes expected to cut the protein short',
  inframe: 'In-frame: insertions or deletions that keep the reading frame',
  splice: 'Splice: changes at an exon-intron boundary',
  stop_lost: 'Stop lost: the stop codon is removed, extending the protein',
};

// "Skin Cutaneous Melanoma (TCGA, PanCancer Atlas)" -> "Skin Cutaneous Melanoma"
export function cancerName(study) {
  return (study?.name ?? '').replace(/\s*\(TCGA, PanCancer Atlas\)\s*$/, '') || study?.cancer_type?.toUpperCase() || '';
}
