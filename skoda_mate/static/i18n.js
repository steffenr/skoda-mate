// Minimal i18n: pages write English with t('English text'); a catalog looks it up by that exact string and falls back
// to English, so a missing entry is never an error. One catalog is loaded at a time; English needs none.
// Placeholders are {named}. A key may carry a context, 'Open##action', when one English text needs two translations.
// The translations live in ./i18n/<code>.json.

/** @typedef {Record<string, string | Record<string, string>>} Catalog  an object value holds plural forms */
const jsonCatalog = (code) => async () => {
  const response = await fetch(`/static/i18n/${code}.json`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
};
/** @type {Record<string, () => Promise<Catalog>>} */
export const CATALOGS = { de: jsonCatalog('de') };

let lang = 'en';
let locale = 'en';
let current = {};
let latest = 0;

/** Switch language. The page keeps its old texts until the catalog is there; when switches overlap, the last one wins. */
export async function setLang(code, bcp47) {
  const mine = ++latest;
  let loaded = {};
  if (Object.hasOwn(CATALOGS, code)) {
    try { loaded = await CATALOGS[code](); } catch (e) { console.warn(`translation ${code} not loaded, showing English`, e); }
  }
  if (mine !== latest) return;
  lang = code;
  locale = bcp47 ?? code;
  current = loaded;
}
export const getLang = () => lang;
export const getLocale = () => locale;
export const catalog = () => current;

const lookup = (key) => (Object.hasOwn(current, key) ? current[key] : undefined);
const english = (key) => key.replace(/##.*$/s, '');
// One pass over the template: a value that itself looks like {a placeholder} stays as it is.
const fill = (template, vars) => (vars ? template.replace(/\{(\w+)\}/g, (m, k) => (Object.hasOwn(vars, k) ? String(vars[k]) : m)) : template);

export function t(key, vars) {
  const found = lookup(key);
  return fill(typeof found === 'string' && found ? found : english(key), vars);
}

/** A text with a count: tn('{n} day', '{n} days', days). The catalog entry sits under `other` and holds the forms its
 *  language has; the CLDR rules of the locale pick one. `vars.n` is shown instead of `n` (a formatted number). */
export function tn(one, other, n, vars) {
  const values = { n, ...vars };
  const forms = lookup(other);
  const form = forms && typeof forms === 'object' ? forms[new Intl.PluralRules(locale).select(Number(n))] ?? forms.other : undefined;
  if (form) return fill(form, values);
  return fill(english(new Intl.PluralRules('en').select(Number(n)) === 'one' ? one : other), values);
}

/** Marks a text that reaches t() through a variable, so the extractor sees it. */
export const N_ = (key) => key;
export const hasKey = (key) => Object.hasOwn(current, key);

/** A raw Škoda API value (READY_FOR_CHARGING, CLOSED, …) as readable text in the current language. */
export function tEnum(v) {
  if (typeof v !== 'string' || !/^[A-Z][A-Z0-9_]+$/.test(v)) return v;
  const human = v.charAt(0) + v.slice(1).toLowerCase().replaceAll('_', ' ');
  return lookup(`enum:${v}`) || human;
}
