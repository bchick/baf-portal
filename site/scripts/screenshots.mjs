// Screenshot key routes (light/dark, desktop/phone) plus frames through the
// cartoon -> subunit transition.  Needs `npm run preview` on :4173.
//   npm run shots -- [outDir]      (default ../docs/screenshots)
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const OUT = process.argv[2] || new URL('../../docs/screenshots/', import.meta.url).pathname;
const BASE = process.env.BASE || 'http://localhost:4173/';
mkdirSync(OUT, { recursive: true });

const ROUTES = [
  ['select', '#/', 1400, 'light'],
  ['select-dark', '#/', 1400, 'dark'],
  ['cbaf', '#/cBAF', 1400, 'light'],
  ['ncbaf', '#/ncBAF', 1400, 'light'],
  ['smarca4', '#/cBAF/SMARCA4', 1400, 'light'],
  ['arid1b-dark', '#/cBAF/ARID1B', 1400, 'dark'],
  ['pbaf', '#/PBAF', 1400, 'light'],
  ['variant', '#/gene/SMARCA4/p.Arg1192His', 1400, 'light'],
  ['compare', '#/compare', 1440, 'light'],
  ['phone-compare', '#/compare', 400, 'light'],
  ['phone-smarcb1', '#/cBAF/SMARCB1', 400, 'light'],
];

const browser = await chromium.launch({ args: ['--enable-unsafe-swiftshader'] });
let bad = 0;
async function page(w, scheme) {
  const p = await browser.newPage({ viewport: { width: w, height: 1000 }, colorScheme: scheme });
  p.errs = [];
  p.on('pageerror', (e) => p.errs.push(e.message));
  p.on('console', (m) => m.type() === 'error' && p.errs.push(m.text()));
  return p;
}
for (const [name, hash, w, scheme] of ROUTES) {
  const p = await page(w, scheme);
  await p.goto(BASE + hash);
  await p.waitForTimeout(2200);
  await p.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
  const overflow = await p.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
  if (p.errs.length || overflow) bad++;
  console.log(name.padEnd(16), p.errs.length ? 'ERR ' + p.errs.join(' | ') : 'ok', overflow ? 'H-OVERFLOW' : '');
  await p.close();
}

// Cartoon (2D) view of each complex.
for (const id of ['cBAF', 'PBAF', 'ncBAF']) {
  const p = await page(1400, 'light');
  await p.addInitScript(() => localStorage.setItem('stageMode', 'cartoon'));
  await p.goto(BASE + '#/' + id);
  await p.waitForTimeout(2200);
  const ok = await p.evaluate(() => document.querySelectorAll('.cartoon2d .piece').length > 0);
  await p.screenshot({ path: `${OUT}/cartoon-${id}.png`, fullPage: true });
  if (p.errs.length || !ok) bad++;
  console.log(`cartoon-${id}`.padEnd(16), p.errs.length ? 'ERR ' + p.errs.join(' | ') : ok ? 'ok' : 'NO CARTOON');
  await p.close();
}

// Frame rate while spinning on the select screen (real clock).
{
  const p = await page(1400, 'light');
  await p.goto(BASE + '#/');
  await p.waitForTimeout(1500);
  const fps = await p.evaluate(() => new Promise((res) => {
    let n = 0; const t0 = performance.now();
    const f = () => { n++; performance.now() - t0 < 2000 ? requestAnimationFrame(f) : res(n / 2); };
    requestAnimationFrame(f);
  }));
  console.log('spin fps'.padEnd(16), fps.toFixed(1));
  await p.close();
}

// Film strips through select -> complex -> subunit (incl. the stage -> domain
// map morph) -> back. Page time runs on Playwright's fake clock so each frame
// is taken at exactly its labelled time; screenshots are too slow under a
// software renderer for real-time labels to mean anything. Navigation uses
// hash changes (the path a click takes); data fetches get real time to finish.
const p = await page(1400, 'light');
await p.clock.install();
await p.goto(BASE + '#/');
await p.waitForTimeout(2500);
await p.clock.pauseAt(await p.evaluate(() => Date.now() + 1000));
async function strip(label, hash, times) {
  await p.evaluate((h) => { location.hash = h; }, hash);
  await p.waitForTimeout(400);
  let t = 0;
  for (const at of times) {
    await p.clock.runFor(at - t); t = at;
    await p.screenshot({ path: `${OUT}/${label}-${String(at).padStart(4, '0')}ms.png` });
  }
}
await strip('t1-select-to-cbaf', '#/cBAF', [120, 350, 700, 1400]);
await strip('t2-cbaf-to-smarca4-morph', '#/cBAF/SMARCA4', [150, 450, 750, 1000, 1500]);
await strip('t3-smarca4-to-smarcb1-morph', '#/cBAF/SMARCB1', [300, 800, 1500]);
await strip('t4-back-to-select', '#/', [300, 1400]);
await p.hover('a.pick:nth-child(2)');
await p.clock.runFor(250);
await p.screenshot({ path: `${OUT}/t5-swap-to-pbaf-mid.png` });
await p.clock.runFor(1200);
await p.screenshot({ path: `${OUT}/t5-swap-to-pbaf-end.png` });
if (p.errs.length) bad++;
console.log('transitions'.padEnd(16), p.errs.length ? 'ERR ' + p.errs.join(' | ') : 'ok');
await browser.close();
process.exit(bad ? 1 : 0);
