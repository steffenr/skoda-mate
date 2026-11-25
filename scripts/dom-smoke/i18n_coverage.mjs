// German translation coverage: every t('English') literal in the frontend should have a German entry.
//   node i18n_coverage.mjs          (reports; exit 1 if anything is missing)
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const STATIC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../skoda_mate/static');
const i18n = await import(`${STATIC}/i18n.js`);
const files = ['app.js', ...fs.readdirSync(`${STATIC}/lib`).map((f) => `lib/${f}`), ...fs.readdirSync(`${STATIC}/pages`).map((f) => `pages/${f}`)]
  .filter((f) => f.endsWith('.js'));
for (const f of files) if (f.startsWith('pages/') || f === 'app.js') await import(`${STATIC}/${f}`).catch(() => {});  // pages call extendDE on import

// Navigation labels are passed to t() as variables, so a literal scan cannot see them: read them off the PAGES table.
const appSrc = fs.readFileSync(`${STATIC}/app.js`, 'utf8');
for (const m of appSrc.matchAll(/label:\s*'([^']+)'/g)) {
  const key = m[1];
  if (i18n.hasDE(key)) continue;
  (missing.get(key) || missing.set(key, new Set()).get(key)).add('app.js (nav)');
}

// t('...') with a plain single-quoted or double-quoted literal (template strings are dynamic and skipped)
const re = /\bt\(\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")\s*[,)]/g;
const missing = new Map();
let total = 0;
for (const f of files) {
  const src = fs.readFileSync(`${STATIC}/${f}`, 'utf8');
  for (const m of src.matchAll(re)) {
    const key = (m[1] ?? m[2]).replace(/\\'/g, "'").replace(/\\"/g, '"');
    total++;
    if (!i18n.hasDE(key)) (missing.get(key) || missing.set(key, new Set()).get(key)).add(f);
  }
}
console.log(`${total} t('…') literals, ${missing.size} distinct without a German entry`);
for (const [k, fs_] of [...missing].slice(0, +process.env.SHOW || 40)) console.log(`  [${[...fs_].join(',')}] ${k.slice(0, 110)}`);
process.exit(missing.size ? 1 : 0);
