<script>
  // The shared suggestion sheet. The site is static, so a suggestion becomes a
  // pre-filled GitHub issue (form: .github/ISSUE_TEMPLATE/data-correction.yml;
  // query parameters are its field ids), or copied text for any other channel.
  import { fly, fade } from 'svelte/transition';
  import { backOut, cubicOut } from 'svelte/easing';
  import { suggest, closeSuggest } from './suggest.svelte.js';
  import { REPO, CONTACT_EMAIL } from './config.js';

  const reduce = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const KINDS = ['Correction', 'Missing data', 'Other'];

  let kind = $state('Correction');
  let details = $state('');
  let evidence = $state('');
  let copied = $state(false);
  let textarea = $state();

  // fresh form each time the sheet opens for a new context
  let lastCtx = null;
  $effect(() => {
    if (suggest.open && suggest.ctx !== lastCtx) {
      lastCtx = suggest.ctx;
      kind = 'Correction'; details = ''; evidence = ''; copied = false;
      queueMicrotask(() => textarea?.focus());
    }
  });

  const ctx = $derived(suggest.ctx ?? {});
  const title = $derived(`[${kind}] ${ctx.subject ?? ''} · ${ctx.section ?? ''}`);
  const issueUrl = $derived.by(() => {
    const q = new URLSearchParams({
      template: 'data-correction.yml', title, kind, subject: ctx.subject ?? '', section: ctx.section ?? '',
      current: ctx.current ?? '', details, evidence, page: ctx.page ?? '', data_version: ctx.dataVersion ?? '',
    });
    return `https://github.com/${REPO}/issues/new?${q}`;
  });
  const asText = $derived([
    `${title}`, '',
    `What should change:\n${details || '(not filled in)'}`, '',
    `Source: ${evidence || '(none given)'}`, '',
    ctx.current ? `The site currently shows:\n${ctx.current}\n` : '',
    `Page: ${ctx.page ?? ''}`, `Data version: ${ctx.dataVersion ?? ''}`,
  ].join('\n'));

  async function copy() {
    try { await navigator.clipboard.writeText(asText); copied = true; setTimeout(() => (copied = false), 1800); }
    catch { copied = false; }
  }
  function submitted() { setTimeout(closeSuggest, 150); }
</script>

{#if suggest.open}
  <div class="scrim" transition:fade={{ duration: reduce ? 0 : 160 }} onclick={closeSuggest} aria-hidden="true"></div>
  <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="suggest-title"
       in:fly={{ y: 28, duration: reduce ? 0 : 420, easing: backOut }} out:fly={{ y: 16, duration: reduce ? 0 : 180, easing: cubicOut }}>
    <header>
      <div>
        <p class="eyebrow">Suggest an edit</p>
        <h2 id="suggest-title">{ctx.subject}</h2>
        <p class="section">{ctx.section}</p>
      </div>
      <button class="x" onclick={closeSuggest} aria-label="Close">×</button>
    </header>

    {#if ctx.current}
      <details class="current">
        <summary>What the site shows now</summary>
        <pre>{ctx.current}</pre>
      </details>
    {/if}

    <div class="kinds" role="radiogroup" aria-label="Kind of suggestion">
      {#each KINDS as k}
        <button role="radio" aria-checked={kind === k} class:on={kind === k} onclick={() => (kind = k)}>{k}</button>
      {/each}
    </div>

    <label class="field">
      <span>What should change?</span>
      <textarea bind:this={textarea} bind:value={details} rows="4"
                placeholder={kind === 'Missing data' ? 'What is missing, and where should it appear?' : 'What is wrong, and what should it say instead?'}></textarea>
    </label>
    <label class="field">
      <span>Source <i>(PMID, DOI or link)</i></span>
      <input bind:value={evidence} placeholder="e.g. PMID 29907796" />
    </label>

    <p class="note">Opens a pre-filled issue on GitHub (a free account is needed). Suggestions are public and are
      checked by the curator against the source before anything on the site changes.</p>

    <div class="actions">
      <a class="btn primary" class:disabled={!details.trim()} href={details.trim() ? issueUrl : undefined}
         aria-disabled={!details.trim()} target="_blank" rel="noopener" onclick={submitted}>
        Open on GitHub <span aria-hidden="true">↗</span>
      </a>
      <button class="btn" onclick={copy} disabled={!details.trim()}>{copied ? 'Copied ✓' : 'Copy as text'}</button>
    </div>
    {#if CONTACT_EMAIL}
      <p class="note">No GitHub account? Copy the text and email it to <b>{CONTACT_EMAIL}</b>.</p>
    {/if}
  </div>
{/if}

<style>
  .scrim { position: fixed; inset: 0; z-index: 40; background: rgb(10 14 20 / 18%); backdrop-filter: blur(1.5px); }
  .sheet {
    position: fixed; z-index: 41; right: max(16px, env(safe-area-inset-right)); bottom: max(16px, env(safe-area-inset-bottom));
    width: min(430px, calc(100vw - 32px)); max-height: calc(100vh - 32px); overflow: auto;
    background: var(--surface); border: 1px solid var(--line); border-radius: 18px; box-shadow: 0 24px 60px rgb(0 0 0 / 25%);
    padding: 18px 20px 16px;
  }
  header { display: flex; justify-content: space-between; gap: 10px; }
  .eyebrow { margin: 0; font-size: 11.5px; letter-spacing: 0.07em; text-transform: uppercase; color: var(--accent); font-weight: 700; }
  h2 { margin: 2px 0 0; font-size: 20px; }
  .section { margin: 2px 0 0; color: var(--ink-2); font-size: 13px; }
  .x { all: unset; cursor: pointer; font-size: 22px; line-height: 1; color: var(--ink-3); padding: 0 4px; align-self: start; }
  .x:hover { color: var(--ink); }
  .current { margin: 12px 0 0; font-size: 12.5px; }
  .current summary { cursor: pointer; color: var(--ink-2); }
  .current pre { white-space: pre-wrap; font: 12px var(--mono); background: var(--surface-2); border: 1px solid var(--line);
    border-radius: 8px; padding: 8px 10px; margin: 6px 0 0; max-height: 140px; overflow: auto; }
  .kinds { display: flex; gap: 4px; margin: 14px 0 10px; background: var(--bg-2); padding: 3px; border-radius: 10px; }
  .kinds button { all: unset; flex: 1; text-align: center; font-size: 13px; padding: 6px 4px; border-radius: 8px; cursor: pointer;
    color: var(--ink-2); transition: background 180ms, color 180ms, box-shadow 180ms; }
  .kinds button.on { background: var(--surface); color: var(--ink); font-weight: 600; box-shadow: 0 1px 3px rgb(0 0 0 / 12%); }
  .kinds button:focus-visible { outline: 2px solid var(--focus); }
  .field { display: grid; gap: 4px; margin: 10px 0 0; font-size: 13px; color: var(--ink-2); }
  .field i { color: var(--ink-3); font-style: normal; }
  textarea, input { font: 14px var(--font); color: var(--ink); background: var(--surface-2); border: 1px solid var(--line-2);
    border-radius: 10px; padding: 8px 10px; resize: vertical; }
  textarea:focus, input:focus { outline: 2px solid color-mix(in srgb, var(--accent) 60%, transparent); outline-offset: 0; border-color: transparent; }
  .note { font-size: 12px; color: var(--ink-3); margin: 10px 0 0; }
  .actions { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
  .btn { font-size: 13.5px; padding: 8px 14px; }
  .btn.primary { background: var(--ink); color: var(--bg); border-color: var(--ink); font-weight: 600; }
  .btn.primary:hover { text-decoration: none; transform: translateY(-1px); }
  .btn.disabled, .btn:disabled { opacity: 0.45; pointer-events: none; }
</style>
