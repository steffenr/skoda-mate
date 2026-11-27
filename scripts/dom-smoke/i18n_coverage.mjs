// Translation coverage: every catalog against static/i18n/keys.json (written by i18n_extract.mjs and
// scripts/i18n_backend.py), and a check for sentences pieced together from several keys.
//   node i18n_coverage.mjs          (reports per language; exit 1 on any problem)
//   SHOW=500 node i18n_coverage.mjs (list more problems)
import fs from 'node:fs';
import { CATALOGS } from '../../skoda_mate/static/i18n.js';
import { compare, languages, problemLines, readKeys, scan, STATIC, unregistered } from './i18n_lib.mjs';

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
  'requests used this hour', 'just now', 'new', 'completed', 'known',
  // a label followed by a colon and a value
  'time windows', 'timers', 'outliers left out:',
]);

const fresh = scan();
const keys = readKeys();
const all = { ...keys.backend, ...keys.frontend };
let failed = 0;
const report = (what, lines) => {
  console.log(`${what}: ${lines.length} problem(s)`);
  for (const line of problemLines(what, lines, +process.env.SHOW || 40)) console.log(line);
  failed += lines.length;
};

report('keys.json (frontend)', JSON.stringify(Object.keys(fresh).sort()) === JSON.stringify(Object.keys(keys.frontend).sort())
  ? [] : ['stale: run node i18n_extract.mjs']);

// The Home Assistant guide writes "<b>Label</b>: description."; the description is a whole sentence. Backend values
// written in lower case are cells of the Capabilities tables. A key with placeholders is a whole phrase.
report('pieces of sentences', Object.entries(fresh)
  .filter(([k, e]) => /^\p{Ll}/u.test(k) && !/\{\w+\}/.test(k) && !STANDALONE.has(k) && !(e.files.includes('pages/settings.js') && k.endsWith('.')))
  .map(([k, e]) => `[${e.files}] ${k}`));

const registered = languages();
report('languages.py', unregistered(Object.keys(CATALOGS), registered));
for (const { code, locale } of registered.filter((l) => Object.hasOwn(CATALOGS, l.code))) {
  const catalog = JSON.parse(fs.readFileSync(`${STATIC}/i18n/${code}.json`, 'utf8'));
  report(code, compare(all, catalog, locale));
}
console.log(failed ? `${failed} problem(s)` : `all catalogs complete: ${Object.keys(all).length} keys`);
process.exit(failed ? 1 : 0);
