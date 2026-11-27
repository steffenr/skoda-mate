// What the translation tools share: finding the frontend's keys, and checking a catalog against the key list.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const STATIC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../skoda_mate/static');
export const KEYS_FILE = `${STATIC}/i18n/keys.json`;
const LANGUAGES_PY = path.resolve(STATIC, '../languages.py');

/** The languages registered in skoda_mate/languages.py: [{code, name, locale}]. */
export function languages(source = fs.readFileSync(LANGUAGES_PY, 'utf8')) {
  return [...source.matchAll(/Language\("([^"]+)",\s*"([^"]+)",\s*"([^"]+)"\)/g)].map(([, code, name, locale]) => ({ code, name, locale }));
}

/** Catalog codes that languages.py does not know: their locale, and so their plural forms, cannot be checked. */
export const unregistered = (codes, registered) => codes.filter((c) => !registered.some((l) => l.code === c))
  .map((c) => `${c}: in CATALOGS but not in skoda_mate/languages.py`);

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

// ------------------------------------------------------------------ translating: the brief, assembly and lint
export const NOTES = path.resolve(STATIC, '../../scripts/i18n_notes.json');

/** {path: source} of everything a key can come from: the dashboard modules and the Python package. */
export function allSources() {
  const root = path.resolve(STATIC, '..');
  const python = ['', 'routers/'].flatMap((dir) => fs.readdirSync(`${root}/${dir}`).filter((f) => f.endsWith('.py')).map((f) => `${dir}${f}`));
  return { ...sources(), ...Object.fromEntries(python.map((f) => [f, fs.readFileSync(`${root}/${f}`, 'utf8')])) };
}

/** The forms a locale needs, each with a few numbers that use it, so a translator knows what a form is for. */
function categoryExamples(locale) {
  const rules = new Intl.PluralRules(locale);
  const examples = {};
  for (const category of rules.resolvedOptions().pluralCategories) examples[category] = [];
  for (const n of [...Array(201).keys(), 1.5, 1000000]) {
    const list = examples[rules.select(n)];
    if (list.length < 6) list.push(n);
  }
  return Object.fromEntries(Object.entries(examples).sort(([a], [b]) => a.localeCompare(b)));
}

function sourceLine(key, files, from) {
  const forms = [`'${key.replaceAll('\\', '\\\\').replaceAll("'", "\\'")}'`, `"${key.replaceAll('"', '\\"')}"`];
  for (const file of files) {
    const line = (from[file] || '').split('\n').find((l) => forms.some((q) => l.includes(q)));
    if (!line) continue;
    const text = line.trim();
    const at = Math.max(...forms.map((q) => text.indexOf(q)));
    return text.length <= 220 ? text : text.slice(Math.max(0, at - 100), at + 120);
  }
  return undefined;
}

/** What a translator gets for each key: the English, where and how it is shown, the forms the locale needs and a note.
 *  It reads no catalog, so no other translation can leak into the new one. */
export function brief(keys, from, locale, notes) {
  const categories = categoryExamples(locale);
  return Object.keys(keys).sort().map((key) => {
    const { files, one } = keys[key];
    const entry = { key, english: key.replace(/##.*$/s, '') };
    if (one !== undefined) Object.assign(entry, { one: one.replace(/##.*$/s, ''), categories });
    entry.files = files;
    const line = sourceLine(key, files, from);
    if (line) entry.line = line;
    if (notes[key]) entry.note = notes[key];
    return entry;
  });
}

/** The keys of a JSON object's top level as they are written, repeats included (JSON.parse keeps only the last). */
function writtenKeys(text) {
  const found = [];
  let depth = 0;
  for (const m of text.matchAll(/"(?:[^"\\]|\\.)*"(\s*:)?|[{}[\]]/g)) {
    if (m[0] === '{' || m[0] === '[') depth++;
    else if (m[0] === '}' || m[0] === ']') depth--;
    else if (m[1] && depth === 1) found.push(JSON.parse(m[0].slice(0, -m[1].length)));
  }
  return found;
}

/** Joins the parts a translator wrote and checks the result against the key list. */
export function assemble(parts, keys, locale) {
  const catalog = {};
  const problems = [];
  for (const [name, text] of Object.entries(parts)) {
    let part;
    try { part = JSON.parse(text); } catch (e) { problems.push(`${name}: not valid JSON (${e.message.slice(0, 80)})`); continue; }
    const here = new Set();
    for (const key of writtenKeys(text)) {
      if (here.has(key) || Object.hasOwn(catalog, key)) problems.push(`${name}: twice: ${key}`);
      here.add(key);
    }
    Object.assign(catalog, part);
  }
  return { catalog, problems: [...problems, ...compare(keys, catalog, locale)] };
}

// Words and shapes a translation keeps as they are.
const PRODUCTS = ['Škoda', 'MyŠkoda', 'Home Assistant', 'Mosquitto', 'MQTT', 'Node-RED', 'n8n', 'Mate'];
const PROTECTED = [/\{\w+\}\/[\w/…{}-]+/g, /\b[A-Z_]{3,}=\w+/g, /\b[a-z]+_[a-z_]+\b/g, /\b(?:[A-Z]{2,}_[A-Z0-9_]+|PERMANENT|OFF|REDUCED|MAXIMUM|HEATING|VENTILATION|MONDAY|SUNDAY|RECURRING)\b/g];
const SAME_IS_FINE = /^(?:[^\p{L}]|\{\w+\}|\b(?:AC|DC|kWh|kW|km|mi|h|min|s|VIN|URL|TLS|API|S-PIN|OK|CSV|SoC|Ac|Dc|Cng|Lpg|MQTT)\b)*$/u;

/** Texts to read again: copied English, and product names, paths, settings and API values that went missing.
 *  A list for a person, not a gate: some words are the same in two languages. */
export function lint(keys, catalog) {
  const found = [];
  for (const key of Object.keys(keys)) {
    const value = catalog[key];
    if (value === undefined) continue;
    const english = key.replace(/##.*$/s, '');
    const texts = typeof value === 'string' ? [value] : Object.values(value);
    if (texts.includes(english) && !SAME_IS_FINE.test(english) && !PRODUCTS.includes(english)) found.push(`same as English: ${key}`);
    const tokens = new Set([...PRODUCTS.filter((p) => new RegExp(`(?<![\\p{L}])${p}`, 'u').test(english)), ...PROTECTED.flatMap((re) => english.match(re) || [])]);
    const general = typeof value === 'string' ? value : value.other;
    for (const token of tokens) if (!String(general).includes(token)) found.push(`lost "${token}": ${key.slice(0, 120)}`);
  }
  return found;
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
