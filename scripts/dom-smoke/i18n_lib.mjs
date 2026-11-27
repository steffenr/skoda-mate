// What the translation tools share: finding the frontend's keys, and checking a catalog against the key list.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const STATIC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../skoda_mate/static');
export const KEYS_FILE = `${STATIC}/i18n/keys.json`;

/** {relative path: source} of every module whose texts are translated. */
export function sources() {
  const files = ['app.js', 'i18n.js', ...['lib', 'pages'].flatMap((d) => fs.readdirSync(`${STATIC}/${d}`).sort().map((f) => `${d}/${f}`))];
  return Object.fromEntries(files.filter((f) => f.endsWith('.js')).map((f) => [f, fs.readFileSync(`${STATIC}/${f}`, 'utf8')]));
}

const LITERAL = `(?:'((?:[^'\\\\\\n]|\\\\.)*)'|"((?:[^"\\\\\\n]|\\\\.)*)")`;
const unescape = (s) => s.replace(/\\(.)/g, (m, c) => (c === 'n' ? '\n' : c));
const text = (match, at) => unescape(match[at] ?? match[at + 1]);

/** {key: {files, one?}}: literal t(), N_() and tParts() texts, both tn() texts (keyed by the plural) and the nav labels.
 *  A text that reaches t() through a variable must be marked with N_ where it is written. */
export function scan(files = sources()) {
  const keys = {};
  const add = (key, file, one) => {
    const entry = (keys[key] ||= { files: [] });
    if (!entry.files.includes(file)) entry.files.push(file);
    if (one !== undefined) entry.one = one;
  };
  for (const [file, source] of Object.entries(files)) {
    const src = source.replace(/^\s*(?:\/\/|\/\*|\*).*$/gm, '');  // a call shown in a comment is not a key
    for (const m of src.matchAll(new RegExp(`(?<![\\w$.])(?:t|N_|tParts)\\(\\s*${LITERAL}\\s*[,)]`, 'g'))) add(text(m, 1), file);
    for (const m of src.matchAll(new RegExp(`(?<![\\w$.])tn\\(\\s*${LITERAL}\\s*,\\s*${LITERAL}\\s*,`, 'g'))) add(text(m, 3), file, text(m, 1));
    if (file === 'app.js') for (const m of src.matchAll(/\blabel:\s*'([^']+)'/g)) add(m[1], file);
  }
  for (const entry of Object.values(keys)) entry.files.sort();
  return keys;
}

const placeholders = (s) => [...new Set([...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]))].sort();
const same = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);

const isSingleNumber = (locale, category) => {
  const rules = new Intl.PluralRules(locale);
  return Array.from({ length: 1001 }, (_, n) => n).filter((n) => rules.select(n) === category).length === 1;
};

/** Problems as printed lines: the language first, never cut off (the placeholders stand at the end). */
export const problemLines = (what, problems, limit) => problems.slice(0, limit).map((line) => `  ${what}: ${line}`);

/** What is wrong with a catalog, one line each; an empty list means it is complete for the locale. */
export function compare(keys, catalog, locale) {
  const problems = [];
  const categories = new Intl.PluralRules(locale).resolvedOptions().pluralCategories;
  for (const [key, entry] of Object.entries(keys)) {
    const value = catalog[key];
    if (!Object.hasOwn(catalog, key) || value === '') { problems.push(`missing: ${key}`); continue; }
    const english = key.replace(/##.*$/s, '');
    const wanted = placeholders(english);
    if (entry.one === undefined) {
      if (typeof value !== 'string') problems.push(`not a text: ${key}`);
      else if (!same(placeholders(value), wanted)) problems.push(`placeholders: ${key} has {${placeholders(value)}}`);
      continue;
    }
    if (!value || typeof value !== 'object') { problems.push(`not plural forms: ${key}`); continue; }
    for (const category of categories) if (!value[category]) problems.push(`plural form ${category} missing: ${key}`);
    for (const [category, form] of Object.entries(value)) {
      if (!categories.includes(category)) { problems.push(`plural form ${category} unknown in ${locale}: ${key}`); continue; }
      const has = placeholders(String(form));
      // The count may be left out ("one day") only where the form stands for a single number: German "one" is just 1,
      // Ukrainian "one" is also 21 and French "one" also 0. The general form needs everything.
      const optional = category !== 'other' && isSingleNumber(locale, category);
      const missing = wanted.filter((p) => !has.includes(p) && !(p === 'n' && optional));
      if (missing.length || has.some((p) => !wanted.includes(p) && p !== 'n')) problems.push(`placeholders: ${key} (${category}) has {${has}}`);
    }
  }
  for (const key of Object.keys(catalog)) if (!Object.hasOwn(keys, key)) problems.push(`extra: ${key}`);
  return problems;
}

/** keys.json as it is on disk; each extractor rewrites its own section. */
export function readKeys() {
  return fs.existsSync(KEYS_FILE) ? JSON.parse(fs.readFileSync(KEYS_FILE, 'utf8')) : { backend: {}, frontend: {} };
}

/** The same layout the Python extractor writes: sections and keys sorted, one key per line. */
export function serialise(all) {
  const section = (name) => {
    const lines = Object.keys(all[name] || {}).sort().map((k) => `  ${JSON.stringify(k)}: ${JSON.stringify(all[name][k])}`);
    return ` ${JSON.stringify(name)}: {${lines.length ? `\n${lines.join(',\n')}\n ` : ''}}`;
  };
  return `{\n${section('backend')},\n${section('frontend')}\n}\n`;
}
