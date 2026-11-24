// Opens every page in German in a real browser and lists visible text that is still English.
//   BASE=http://localhost:8793 node german_leaks.mjs      (needs a DEMO server; changes the demo's language setting)
import puppeteer from 'puppeteer-core';
const BASE = process.env.BASE || 'http://localhost:8793';
const ROUTES = ['', 'trips', 'trips/5', 'charges', 'charges/3', 'battery', 'control', 'stats', 'map', 'events', 'settings', 'system', 'system/capabilities', 'system/calls', 'system/diagnostics', 'import'];
const b = await puppeteer.launch({ executablePath: process.env.CHROME || '/Applications/Chromium.app/Contents/MacOS/Chromium', headless: 'new', args: ['--no-sandbox'], defaultViewport: { width: 1280, height: 900 } });
const p = await b.newPage();
await p.goto(BASE + '/', { waitUntil: 'networkidle0' });
await p.evaluate(() => fetch('/api/settings', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ language: 'de' }) }));
const STOP = /\b(the|and|is|are|not|no|this|that|for|with|your|from|has|have|was|were|will|can|to|of|in|on|it|its|or|if|a|an)\b/i;
const seen = new Map();
for (const r of ROUTES) {
  await p.goto(`${BASE}/#/${r}`, { waitUntil: 'networkidle0' }); await p.reload({ waitUntil: 'networkidle0' }); await new Promise((x) => setTimeout(x, 2200));
  const leaks = await p.evaluate(async () => {
    const { dictionary } = await import('/static/i18n.js');
    const DE = dictionary();
    const english = new Map(Object.entries(DE).filter(([k, v]) => k !== v).map(([k]) => [k, true]));
    const out = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const el = n.parentElement;
      if (!el || /^(SCRIPT|STYLE|CODE|PRE)$/.test(el.tagName) || el.closest('.leaflet-container, code, pre, .tip')) continue;
      const s = n.textContent.replace(/\s+/g, ' ').trim();
      if (s.length < 2) continue;
      if (english.has(s)) out.push(['in-dictionary-but-untranslated', s]);
      else if (/^[A-Z][A-Z0-9_]{2,}$/.test(s)) out.push(['raw-enum', s]);
      else if (s.split(' ').length >= 3 && /\b(the|and|is|are|not|this|for|with|your|from|was|will|can)\b/i.test(s) && !/[äöüß]/i.test(s)) out.push(['english-sentence', s.slice(0, 110)]);
    }
    for (const el of document.querySelectorAll('[title],[aria-label],[placeholder]')) for (const a of ['title', 'aria-label', 'placeholder']) { const s = (el.getAttribute(a) || '').trim(); if (s && english.has(s)) out.push(['attr-untranslated', `${a}: ${s}`]); }
    return out;
  });
  for (const [kind, s] of leaks) { const key = JSON.stringify([kind, s]); if (!seen.has(key)) seen.set(key, r); }
}
await p.evaluate(() => fetch('/api/settings', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ language: 'en' }) }));
await b.close();
for (const [k, r] of seen) console.log(`#/${r.padEnd(12)} ${JSON.parse(k).join('  ')}`);
console.log(seen.size ? `\n${seen.size} possible leak(s)` : '\nno English text found in German mode');
process.exit(seen.size ? 1 : 0);
