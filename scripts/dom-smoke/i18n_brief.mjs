// The translator's input for one language: every key with its English, the line that shows it, the plural forms the
// locale needs and a note, in parts small enough to translate one at a time. See docs/TRANSLATIONS.md.
//   node i18n_brief.mjs <locale> <output folder>
import fs from 'node:fs';
import { allSources, brief, NOTES, readKeys } from './i18n_lib.mjs';

const PART = 240;
const [locale, out] = process.argv.slice(2);
if (!locale || !out) { console.error('usage: node i18n_brief.mjs <locale> <output folder>'); process.exit(2); }
const { backend, frontend } = readKeys();
const entries = brief({ ...backend, ...frontend }, allSources(), locale, JSON.parse(fs.readFileSync(NOTES, 'utf8')));
fs.mkdirSync(out, { recursive: true });
const parts = Math.ceil(entries.length / PART);
for (let i = 0; i < parts; i++) fs.writeFileSync(`${out}/brief.part${i + 1}.json`, `${JSON.stringify(entries.slice(i * PART, (i + 1) * PART), null, 1)}\n`);
console.log(`${entries.length} keys for ${locale} in ${parts} parts`);
