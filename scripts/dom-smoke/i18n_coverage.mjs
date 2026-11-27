// German translation coverage: every t('English') literal in the frontend should have a German entry.
//   node i18n_coverage.mjs          (reports; exit 1 if anything is missing)
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const STATIC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../skoda_mate/static');
const de = JSON.parse(fs.readFileSync(`${STATIC}/i18n/de.json`, 'utf8'));
const hasDE = (key) => Object.hasOwn(de, key);
const files = ['app.js', ...fs.readdirSync(`${STATIC}/lib`).map((f) => `lib/${f}`), ...fs.readdirSync(`${STATIC}/pages`).map((f) => `pages/${f}`)]
  .filter((f) => f.endsWith('.js'));
const missing = new Map();

// Navigation labels are passed to t() as variables, so a literal scan cannot see them: read them off the PAGES table.
const appSrc = fs.readFileSync(`${STATIC}/app.js`, 'utf8');
for (const m of appSrc.matchAll(/label:\s*'([^']+)'/g)) {
  const key = m[1];
  if (hasDE(key)) continue;
  (missing.get(key) || missing.set(key, new Set()).get(key)).add('app.js (nav)');
}

// t('...') with a plain single-quoted or double-quoted literal (template strings are dynamic and skipped)
const re = /\bt\(\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")\s*[,)]/g;
let total = 0;
for (const f of files) {
  const src = fs.readFileSync(`${STATIC}/${f}`, 'utf8');
  for (const m of src.matchAll(re)) {
    const key = (m[1] ?? m[2]).replace(/\\'/g, "'").replace(/\\"/g, '"');
    total++;
    if (!hasDE(key)) (missing.get(key) || missing.set(key, new Set()).get(key)).add(f);
  }
}
// A key that starts in lower case is usually a piece of a sentence, which another language cannot reorder. These are the
// ones that stand on their own, each group with the reason.
const STANDALONE = new Set([
  // a chip, a table cell or the value beside a label
  'yes', 'no', 'on', 'off', 'unknown', 'none', 'free', 'all', 'manual', 'sent', 'failed', 'active', 'idle', 'present', 'inferred', 'estimated',
  'expired', 'approx', 'guess', 'history only', 'supported', 'not supported', 'unknown yet', 'cable locked', 'cable unlocked', 'end estimated',
  'unsaved changes', 'at the current position', 'marked as reviewed', 'review undone', 'looks implausible', 'below the detection floor',
  // a unit
  'kWh/day',
  // the caption under or over a number, a whole phrase
  'commands supported', 'data parts available', 'per hour per car', 'included in the cost', 'counted once', 'new trips', 'already known',
  'completed with the car’s figures', 'repeated in your files', 'reported by the car', 'at home price', 'from fuel level',
  'estimated from battery level', 'inferred (from battery level)', 'home price', 'public DC price', 'public AC price',
  'the duration of the trip; charging happened somewhere during it', 'the car stood here; charging happened somewhere in it',
  // a label followed by a colon and a value
  'time windows', 'timers', 'outliers left out:', 'requests used this hour', 'just now',
]);
const lowercase = new Map();
for (const f of files) {
  const src = fs.readFileSync(`${STATIC}/${f}`, 'utf8');
  for (const m of src.matchAll(/\b(?:t|N_|tn)\(\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")/g)) {
    const key = (m[1] ?? m[2]).replace(/\\(['"])/g, '$1');
    // The Home Assistant guide writes "<b>Label</b>: description."; the description is a whole sentence.
    // A key with placeholders is a whole phrase: a translation can move its parts.
    if (/^\p{Ll}/u.test(key) && !/\{\w+\}/.test(key) && !STANDALONE.has(key) && !(f === 'pages/settings.js' && key.endsWith('.'))) (lowercase.get(key) || lowercase.set(key, new Set()).get(key)).add(f);
  }
}
for (const [k, where] of lowercase) console.log(`  piece of a sentence? [${[...where]}] ${k}`);
console.log(`${lowercase.size} lowercase key(s) that are not known to stand alone`);

console.log(`${total} t('…') literals, ${missing.size} distinct without a German entry`);
for (const [k, fs_] of [...missing].slice(0, +process.env.SHOW || 40)) console.log(`  [${[...fs_].join(',')}] ${k.slice(0, 110)}`);
process.exit(missing.size || lowercase.size ? 1 : 0);
