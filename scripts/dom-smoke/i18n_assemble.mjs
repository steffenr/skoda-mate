// Joins a translator's parts into one catalog, checks it against the key list and lists texts to read again.
//   node i18n_assemble.mjs <code> <folder with <code>.part<n>.json> [<output file>]
// The file is written only when there is no problem; without an output file nothing is written.
import fs from 'node:fs';
import { assemble, languages, lint, problemLines, readKeys } from './i18n_lib.mjs';

const [code, folder, out] = process.argv.slice(2);
if (!code || !folder) { console.error('usage: node i18n_assemble.mjs <code> <folder> [<output file>]'); process.exit(2); }
// plain string checks, so no regular expression is built from the command-line argument
const prefix = `${code}.part`;
const names = fs.readdirSync(folder)
  .filter((f) => f.startsWith(prefix) && f.endsWith('.json') && /^\d+$/.test(f.slice(prefix.length, -'.json'.length)))
  .sort((a, b) => a.localeCompare(b, 'en', { numeric: true }));
if (!names.length) { console.error(`no ${code}.part<n>.json in ${folder}`); process.exit(2); }
const { backend, frontend } = readKeys();
const keys = { ...backend, ...frontend };
// a language that is not registered yet is checked with its code as the locale
const locale = languages().find((l) => l.code === code)?.locale ?? code.replace('_', '-');
const { catalog, problems } = assemble(Object.fromEntries(names.map((n) => [n, fs.readFileSync(`${folder}/${n}`, 'utf8')])), keys, locale);
console.log(`${names.length} parts, ${Object.keys(catalog).length} of ${Object.keys(keys).length} keys, ${problems.length} problem(s)`);
for (const line of problemLines(code, problems, +process.env.SHOW || 60)) console.log(line);
const review = lint(keys, catalog);
console.log(`${review.length} text(s) to read again`);
for (const line of problemLines(code, review, +process.env.SHOW || 80)) console.log(line);
if (!problems.length && out) {
  const lines = Object.keys(catalog).sort().map((k) => ` ${JSON.stringify(k)}: ${JSON.stringify(catalog[k])}`);
  fs.writeFileSync(out, `{\n${lines.join(',\n')}\n}\n`);
  console.log(`written: ${out}`);
}
process.exit(problems.length ? 1 : 0);
