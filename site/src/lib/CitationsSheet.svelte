<script>
  // Every source behind one subunit's page, grouped, in a sheet: complex
  // membership, the structure it is drawn from, clinical evidence, and the
  // databases the mutation data comes from.
  //   groups: [{title, note?, items: [{pmid} | {text, url?, pmids?}]}]
  import { fly, fade } from 'svelte/transition';
  import { backOut, cubicOut } from 'svelte/easing';

  let { subject = '', groups = [], refs = {}, onclose = () => {} } = $props();
  const reduce = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  let closeBtn = $state();
  $effect(() => { closeBtn?.focus(); });
  function onkey(e) { if (e.key === 'Escape') { e.stopPropagation(); onclose(); } }
  const count = $derived(groups.reduce((n, g) => n + g.items.length, 0));
</script>

{#snippet paper(p)}
  {@const r = refs[p]}
  <a href="https://pubmed.ncbi.nlm.nih.gov/{p}/" target="_blank" rel="noopener" class:retracted={r?.retracted}>
    {r ? r.text : `PMID ${p}`}</a>
  <span class="mono muted">PMID {p}</span>{#if r?.retracted}<b class="retr"> retracted</b>{/if}
{/snippet}

<svelte:window onkeydown={onkey} />
<div class="scrim" transition:fade={{ duration: reduce ? 0 : 160 }} onclick={onclose} aria-hidden="true"></div>
<div class="sheet" role="dialog" aria-modal="true" aria-labelledby="cite-title"
     in:fly={{ y: 28, duration: reduce ? 0 : 380, easing: backOut }} out:fly={{ y: 16, duration: reduce ? 0 : 160, easing: cubicOut }}>
  <header>
    <div>
      <p class="eyebrow">Citations · {count}</p>
      <h2 id="cite-title">{subject}</h2>
    </div>
    <button class="btn" bind:this={closeBtn} onclick={onclose} aria-label="Close citations">×</button>
  </header>
  <div class="body">
    {#each groups.filter((g) => g.items.length) as g (g.title)}
      <section>
        <h3>{g.title}</h3>
        {#if g.note}<p class="muted small">{g.note}</p>{/if}
        <ol>
          {#each g.items as it, i (i)}
            <li>
              {#if it.pmid}{@render paper(it.pmid)}{#if it.label}<span class="muted small label">{it.label}</span>{/if}
              {:else}
                {#if it.url}<a href={it.url} target="_blank" rel="noopener">{it.text}</a>{:else}{it.text}{/if}
                {#if it.detail}<span class="muted small label">{it.detail}</span>{/if}
                {#if it.pmids?.length}
                  <details><summary class="small">{it.pmids.length} papers</summary>
                    <ol class="inner">{#each it.pmids as p (p)}<li>{@render paper(p)}</li>{/each}</ol>
                  </details>
                {/if}
              {/if}
            </li>
          {/each}
        </ol>
      </section>
    {/each}
  </div>
</div>

<style>
  .scrim { position: fixed; inset: 0; background: rgb(0 0 0 / 28%); z-index: 50; }
  .sheet {
    position: fixed; z-index: 51; left: 50%; bottom: 0; translate: -50% 0;
    width: min(720px, 100vw); max-height: min(80vh, 760px); display: flex; flex-direction: column;
    background: var(--surface); color: var(--ink); border-radius: 16px 16px 0 0;
    box-shadow: 0 -8px 30px rgb(0 0 0 / 20%);
  }
  header { display: flex; justify-content: space-between; align-items: start; gap: 12px; padding: 18px 20px 10px; border-bottom: 1px solid var(--line); }
  h2 { margin: 2px 0 0; font-size: 20px; }
  .body { overflow: auto; padding: 6px 20px 22px; }
  section { margin-top: 14px; }
  h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-3); margin: 0 0 6px; }
  ol { margin: 0; padding-left: 20px; }
  li { margin: 6px 0; font-size: 14px; line-height: 1.4; }
  .inner li { font-size: 13px; }
  .mono { font-family: var(--mono, ui-monospace, monospace); font-size: 12px; margin-left: 6px; }
  .retracted { text-decoration: line-through; }
  .label::before { content: '·'; margin: 0 6px; }
  .retr { color: var(--c-plp); font-size: 12px; }
  summary { cursor: pointer; color: var(--ink-3); margin-top: 2px; }
  @media (max-width: 520px) { header, .body { padding-left: 16px; padding-right: 16px; } }
</style>
