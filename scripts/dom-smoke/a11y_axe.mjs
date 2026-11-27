// WCAG 2.2 AA check with axe-core in light and dark, desktop and phone, on every page. Usage: node a11y_axe.mjs http://localhost:8000 (a demo server). Needs: npm i puppeteer-core axe-core, and Chromium (set CHROME=...).
// Report, not gate: axe "incomplete" means it could not decide (printed grouped by cause); findings are filed as GitHub
// issues by a11y_issues.mjs (A11Y_JSON=...); the scripts always exit 0.
import puppeteer from 'puppeteer-core';
import fs from 'node:fs';
const B = process.argv[2] || 'http://localhost:8000';
const axeSrc = fs.readFileSync(new URL('./node_modules/axe-core/axe.min.js', import.meta.url), 'utf8');
const ROUTES = ['', 'trips', 'trips/3', 'charges', 'charges/3', 'prices', 'battery', 'control', 'stats', 'map', 'places', 'places/1', 'events', 'settings', 'system', 'system/capabilities', 'system/calls', 'system/diagnostics'];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const b = await puppeteer.launch({ executablePath: process.env.CHROME || '/Applications/Chromium.app/Contents/MacOS/Chromium', headless: 'new', args: ['--no-sandbox'] });
const found = new Map(); // key -> {rule, impact, help, nodes:Set, where:Set}
for (const theme of ['light', 'dark']) {
  for (const [vname, vp] of [['desktop', { width: 1280, height: 900 }], ['phone', { width: 390, height: 844, isMobile: true, hasTouch: true }]]) {
    const p = await b.newPage(); await p.setViewport(vp);
    await p.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: theme }]);
    for (const r of ROUTES) {
      await p.goto(`${B}/#/${r}`, { waitUntil: 'networkidle0' }); await sleep(1800);
      await p.evaluate((th) => { document.documentElement.dataset.theme = th; }, theme); await sleep(300);
      await p.evaluate(axeSrc);
      const res = await p.evaluate(() => axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'] }, resultTypes: ['violations', 'incomplete'] }));
      for (const v of [...res.violations, ...res.incomplete.filter((i) => i.id === 'color-contrast').map((i) => ({ ...i, id: 'INCOMPLETE-' + i.id }))]) for (const n of v.nodes) {
        const key = `${v.id}|${n.target.join(' ')}`;
        const e = found.get(key) || { rule: v.id, impact: v.impact, help: v.help, target: n.target.join(' '), html: n.html.slice(0, 140), summary: (n.any[0]?.message || n.all[0]?.message || n.none[0]?.message || '').slice(0, 160), where: new Set() };
        e.where.add(`${theme}/${vname}/${r || 'overview'}`); found.set(key, e);
      }
    }
    await p.close();
  }
}
await b.close();
if (process.env.A11Y_JSON) fs.writeFileSync(process.env.A11Y_JSON, JSON.stringify([...found.values()].map((e) => ({ ...e, where: [...e.where] })), null, 2));
const byRule = {};
for (const e of found.values()) (byRule[e.rule] ||= []).push(e);
const cause = (s) => {
  if (/image node/.test(s)) return 'contains an image node (charts, map)';
  if (/obscur/.test(s)) return 'partially obscured (scroll-clipped cells, floating bar)';
  if (/overlap/.test(s)) return 'overlapped by another element';
  if (/too short/.test(s)) return 'content too short to be sure it is text';
  if (/error/.test(s)) return 'axe error — check by hand';
  if (/non-text/.test(s)) return 'content is only non-text characters';
  return s.split('.').slice(0, 2).join('.');
};
for (const [rule, list] of Object.entries(byRule)) {
  console.log(`\n== ${rule} (${list[0].impact}) ${list[0].help} — ${list.length} element(s)`);
  if (rule.startsWith('INCOMPLETE-')) {
    const byCause = new Map();
    for (const e of list) { const c = cause(e.summary); (byCause.get(c) || byCause.set(c, []).get(c)).push(e); }
    for (const [c, items] of [...byCause.entries()].sort((a, b) => b[1].length - a[1].length)) {
      console.log(`  -- ${c}: ${items.length}`);
      const seen = new Map();
      for (const e of items) { const k = `${e.target}|${e.summary.slice(0, 60)}`; if (!seen.has(k)) seen.set(k, e); }
      for (const e of seen.values()) console.log(`    ${e.target}\n      ${e.summary}\n      ${e.html}\n      on: ${[...e.where].slice(0, 4).join(', ')}${e.where.size > 4 ? ` +${e.where.size - 4}` : ''}`);
    }
  } else for (const e of list) console.log(`  ${e.target}\n    ${e.summary}\n    ${e.html}\n    on: ${[...e.where].slice(0, 4).join(', ')}${e.where.size > 4 ? ` +${e.where.size - 4}` : ''}`);
}
console.log(`\nTOTAL distinct findings: ${found.size}`);
