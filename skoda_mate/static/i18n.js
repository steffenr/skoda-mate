// Minimal i18n: pages write English with t('English text'); a catalog looks it up by that exact string and falls back
// to English, so a missing entry is never an error. One catalog is loaded at a time; English needs none.
// Placeholders are {named}. A key may carry a context, 'Open##action', when one English text needs two translations.
// The translations live in ./i18n/<code>.json.

/** @typedef {Record<string, string | Record<string, string>>} Catalog  an object value holds plural forms */
const CATALOG_TIMEOUT_MS = 5000;  // the first page waits for the catalog: better English than a blank screen
export const jsonCatalog = (code, timeout = CATALOG_TIMEOUT_MS) => async () => {
  const response = await fetch(`/static/i18n/${code}.json`, { signal: AbortSignal.timeout(timeout) });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
};
/** @type {Record<string, () => Promise<Catalog>>} */
export const CATALOGS = { de: jsonCatalog('de') };

let lang = 'en';
let locale = 'en';
let current = {};
let latest = 0;

/** Switch language. The page keeps its old texts until the catalog is there; when switches overlap, the last one wins.
 *  A catalog that cannot be had leaves English throughout: getLang() and getLocale() then say 'en', so that dates,
 *  numbers and the page's lang attribute follow. */
export async function setLang(code, bcp47) {
  const mine = ++latest;
  let next = { lang: code, locale: bcp47 ?? code, catalog: {} };
  if (Object.hasOwn(CATALOGS, code)) {
    try {
      const loaded = await CATALOGS[code]();
      if (!loaded || typeof loaded !== 'object' || Array.isArray(loaded)) throw new Error('not a catalog');
      next.catalog = loaded;
    } catch (e) {
      console.warn(`translation ${code} not loaded, showing English`, e);
      next = { lang: 'en', locale: 'en', catalog: {} };
    }
  }
  if (mine !== latest) return;
  ({ lang, locale, catalog: current } = next);
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

/** A backend message, {message, params}; a parameter that is a message itself is translated too. */
export function tm({ message, params = {} }) {
  const vars = Object.fromEntries(Object.entries(params).map(([k, v]) => [k, v && typeof v === 'object' && v.message ? tm(v) : v]));
  return t(message, vars);
}

/** A text field of a server answer in the user's language: obj.error_i18n if the server sent one, else obj.error as is. */
export function tx(obj, field = 'error') {
  const template = obj?.[`${field}_i18n`];
  return template ? tm(template) : obj?.[field] ?? null;
}

/** Marks a text that reaches t() through a variable, so the extractor sees it. */
export const N_ = (key) => key;
export const hasKey = (key) => Object.hasOwn(current, key);

/** The English wording of the raw Škoda API values that translations know. */
export const ENUM_LABELS = {
  AC: N_('Ac'), ACTIVATED: N_('Activated'), CELSIUS: N_('Celsius'), CHARGING: N_('Charging##value'), CHARGING_INTERRUPTED: N_('Charging interrupted'),
  CLOSED: N_('Closed'), CNG: N_('Cng'), COMPLETED: N_('Completed'), CONNECTED: N_('Connected'), CONNECT_CABLE: N_('Connect cable'),
  CONSERVING: N_('Conserving'), COOLING: N_('Cooling'), DC: N_('Dc'), DEACTIVATED: N_('Deactivated'), DIESEL: N_('Diesel'),
  DISCHARGING: N_('Discharging'), DISCONNECTED: N_('Disconnected'), ELECTRIC: N_('Electric'), FAHRENHEIT: N_('Fahrenheit'), FRIDAY: N_('Friday'),
  GASOLINE: N_('Gasoline'), HEATING: N_('Heating'), HEATING_AUXILIARY: N_('Heating auxiliary'),
  HOME_STORAGE_CHARGING: N_('Home storage charging'), HYBRID: N_('Hybrid'), IMMEDIATE_DISCHARGING: N_('Immediate discharging'), INVALID: N_('Invalid'),
  IN_MOTION: N_('In motion'), LOCKED: N_('Locked'), LPG: N_('Lpg'), MANUAL: N_('Manual'), MAXIMUM: N_('Maximum'), MONDAY: N_('Monday'), NO: N_('No'),
  OFF: N_('Off'), ON: N_('On'), ONE_OFF: N_('One off'), ONLY_OWN_CURRENT: N_('Only own current'), OPEN: N_('Open'), OPENED: N_('Opened'),
  PARKED: N_('Parked'), PERMANENT: N_('Permanent'), PREFERRED_CHARGING_TIMES: N_('Preferred charging times'), PREHEATING: N_('Preheating'),
  READY_FOR_CHARGING: N_('Ready for charging'), RECURRING: N_('Recurring'), REDUCED: N_('Reduced'), SATURDAY: N_('Saturday'), SUNDAY: N_('Sunday'),
  THURSDAY: N_('Thursday'), TIMER: N_('Timer'), TIMER_CHARGING_WITH_CLIMATISATION: N_('Timer charging with climatisation'),
  TRUNK_OPENED: N_('Trunk opened##value'), TUESDAY: N_('Tuesday'), UNKNOWN: N_('Unknown'), UNLOCKED: N_('Unlocked'), UNSUPPORTED: N_('Unsupported'),
  VENTILATION: N_('Ventilation##value'), WEDNESDAY: N_('Wednesday'), YES: N_('Yes'),
};

/** A raw Škoda API value (READY_FOR_CHARGING, CLOSED, …) as readable text in the current language. */
export function tEnum(v) {
  if (typeof v !== 'string' || !/^[A-Z][A-Z0-9_]+$/.test(v)) return v;
  if (Object.hasOwn(ENUM_LABELS, v)) return t(ENUM_LABELS[v]);
  return v.charAt(0) + v.slice(1).toLowerCase().replaceAll('_', ' ');
}
