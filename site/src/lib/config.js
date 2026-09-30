// Site-wide settings.

// GitHub repository that receives "Suggest edit" issues (issue form:
// .github/ISSUE_TEMPLATE/data-correction.yml). While the repository is
// private, only collaborators can file them.
export const REPO = 'bchick/baf-portal';

// Optional address shown as an alternative to GitHub; empty hides it.
export const CONTACT_EMAIL = '';

// Affinage (Whitehead / MIT): literature-grounded mechanistic annotation for
// every human protein-coding gene. All curated BAF subunits have an entry
// (checked 2026-09-30); the subunit card links the subunit and its paralogs.
export const AFFINAGE = 'https://affinage.wi.mit.edu';
export const affinageUrl = (symbol) => `${AFFINAGE}/gene/${encodeURIComponent(symbol)}`;
