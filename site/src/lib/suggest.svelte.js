// One shared "Suggest edit" sheet; any SuggestButton opens it with context.
//   ctx = { subject, section, current, page, dataVersion }
export const suggest = $state({ open: false, ctx: null });

export function openSuggest(ctx) {
  suggest.ctx = { page: location.href, ...ctx };
  suggest.open = true;
}

export function closeSuggest() {
  const origin = suggest.ctx?.origin;
  suggest.open = false;
  origin?.focus?.();          // return focus to the button that opened the sheet
}
