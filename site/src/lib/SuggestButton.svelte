<script>
  // Small "Suggest edit" affordance next to any piece of subunit-level data.
  // `ctx` is a function so the snapshot of what the page shows is taken on click.
  import { openSuggest, suggest } from './suggest.svelte.js';

  let { ctx, label = 'Suggest edit', compact = false } = $props();
  let el;
  const active = $derived(suggest.open && suggest.ctx?.origin === el);
</script>

<button bind:this={el} class="suggest" class:compact class:active type="button"
        title="Suggest a correction or addition for this section"
        aria-label="{label}: {ctx().section} for {ctx().subject}"
        onclick={() => openSuggest({ ...ctx(), origin: el })}>
  <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
    <path d="M11.3 1.7a1.6 1.6 0 0 1 2.3 2.3l-8 8L2.5 13l1-3.1 7.8-8.2z" fill="none" stroke="currentColor"
          stroke-width="1.5" stroke-linejoin="round" />
  </svg>
  {#if !compact}<span>{label}</span>{/if}
</button>

<style>
  .suggest {
    display: inline-flex; align-items: center; gap: 5px; flex: none;
    font: 500 11.5px var(--font); color: var(--ink-3); background: transparent;
    border: 1px solid transparent; border-radius: 999px; padding: 2px 8px; cursor: pointer;
    transition: color 160ms, border-color 160ms, background 160ms, transform 220ms cubic-bezier(.3,1.6,.5,1);
  }
  .suggest:hover, .suggest:focus-visible, .suggest.active {
    color: var(--accent); border-color: color-mix(in srgb, var(--accent) 45%, transparent);
    background: color-mix(in srgb, var(--accent) 8%, transparent);
  }
  .suggest:active { transform: scale(0.94); }
  .suggest.compact { padding: 3px; }
</style>
