// Pure-function checks for the frontend libraries (no DOM, no server): node unit.mjs
process.env.TZ = 'Europe/Berlin';  // a zone with DST, set before any Date exists
import assert from 'node:assert/strict';
import { niceScale } from '../../skoda_mate/static/lib/charts.js';
import { barBox, clockAt, dayStartMs, monthsAgo } from '../../skoda_mate/static/lib/dates.js';

const s = niceScale(0, 0);
assert.ok(s.min === 0 && s.max >= 1 && s.ticks.every((t) => t >= 0), 'a flat zero series must not produce negative ticks');
const flat = niceScale(36, 36);
assert.ok(flat.min < 36 && flat.max > 36, 'a flat non-zero series still gets a range');
const t = niceScale(0, 97, 5);
assert.deepEqual([t.min, t.max], [0, 100]);
assert.ok(t.ticks.includes(0) && t.ticks.includes(100));
assert.deepEqual(niceScale(NaN, 1).ticks, [0, 1]);

// Timeline bars sit in the server's day (local midnight at the request's tz_offset), never in the browser's own midnight:
// across the 2026-03-29 DST change in Europe/Berlin a day of the week keeps its 24 h and its bars do not move by an hour.
const WINTER = -60;  // getTimezoneOffset() the request carried (the week is asked for in winter time)
const d29 = dayStartMs('2026-03-29', WINTER), d30 = dayStartMs('2026-03-30', WINTER);
assert.equal(dayStartMs('2026-03-28', WINTER), Date.UTC(2026, 2, 27, 23), 'the server day starts at the shifted UTC midnight');
assert.equal((d30 - d29) / 3600000, 24, 'a server day is 24 h even across the DST change');
const nine = new Date(d30 + 9 * 3600000).toISOString();
assert.equal(barBox(nine, 60, d30, dayStartMs('2026-03-31', WINTER)).left, 37.5, '09:00 into the day sits at 37.5 %');
assert.notEqual(new Date(2026, 2, 30).getTime(), d30, 'the browser-local midnight differs from the server day start across DST');
assert.equal(barBox(nine, 60, d30, d30 + 1500 * 60000).left, 540 / 1500 * 100, 'a 25 h day (explicit end) scales to its own length');
assert.equal(barBox(new Date(d30 - 3600000).toISOString(), 120, d30, d30 + 1440 * 60000).left, 0, 'a piece started before the day is clipped to 0');
assert.equal(barBox(nine, 99999, d30, d30 + 1440 * 60000).width, 62.5, 'a bar never runs past the end of its day');

// Printed interval times use the request's fixed offset, so they agree with the bar position even after the DST change.
const after = new Date(d30 + 9 * 3600000).toISOString();  // the bar at 09:00 on the server's (winter-time) axis
assert.equal(clockAt(after, WINTER, 'en-GB'), '09:00', 'a time after the DST change prints on the same axis as its bar');
assert.notEqual(new Date(after).toLocaleTimeString('en-GB', { timeStyle: 'short' }), '09:00', 'the browser clock would print 10:00 here');
assert.equal(clockAt(after, WINTER, 'en-US').replace(/\s/g, ' '), '9:00 AM', 'the language still shapes the clock');
assert.equal(clockAt('nope', WINTER, 'en'), '–', 'an unparseable time prints a dash');
assert.equal(clockAt(after, NaN, 'en'), '–', 'a NaN offset prints a dash, not "Invalid Date"');
assert.equal(clockAt(after, undefined, 'en'), '–', 'a missing offset prints a dash');
assert.equal(clockAt(after, Infinity, 'en'), '–', 'an infinite offset prints a dash');
assert.equal(clockAt(after, WINTER, 'de'), '09:00', 'German prints the 24-hour clock on the same axis');

// Period start: 31 March minus one month is the end of February, not 3 March
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
assert.equal(iso(monthsAgo(new Date(2026, 2, 31), 1)), '2026-02-28');
assert.equal(iso(monthsAgo(new Date(2028, 2, 31), 1)), '2028-02-29');
assert.equal(iso(monthsAgo(new Date(2026, 6, 31), 6)), '2026-01-31');
assert.equal(iso(monthsAgo(new Date(2026, 4, 31), 12)), '2025-05-31');
assert.equal(iso(monthsAgo(new Date(2026, 0, 15), 6)), '2025-07-15');

// ------------------------------------------------------------------ translation loader
const i18n = await import('../../skoda_mate/static/i18n.js');
const use = (code, entries) => { i18n.CATALOGS[code] = async () => entries; };

await i18n.setLang('en');
assert.equal(i18n.t('{n} cars', { n: 2 }), '2 cars', 'placeholders are filled in English');
assert.equal(i18n.t('Open##action'), 'Open', 'the context suffix is not part of the English text');
assert.equal(i18n.N_('Anything##x'), 'Anything##x', 'N_ only marks a string');
assert.equal(i18n.tn('{n} day', '{n} days', 1), '1 day');
assert.equal(i18n.tn('{n} day', '{n} days', 0), '0 days');
assert.equal(i18n.tn('{n} day', '{n} days', 2), '2 days');
assert.equal(i18n.tn('{n} day##x', '{n} days##x', 2), '2 days');

use('xx', { 'Open##action': 'Öffnen', 'Hi {name}': 'Hallo {name}' });
await i18n.setLang('xx');
assert.equal(i18n.getLang(), 'xx');
assert.equal(i18n.getLocale(), 'xx', 'the locale defaults to the code');
assert.equal(i18n.t('Open##action'), 'Öffnen', 'a catalog entry for the full key wins');
assert.equal(i18n.t('Missing##ctx'), 'Missing', 'a missing key falls back to English without its context');
assert.equal(i18n.t('constructor'), 'constructor', 'an object property is not a translation');
assert.equal(i18n.t('Hi {name}', { name: '{x} <b>', x: 'no' }), 'Hallo {x} <b>', 'a value is inserted literally, once');
assert.equal(i18n.t('Keep {like this} and {other}', { n: 1 }), 'Keep {like this} and {other}', 'an unknown placeholder stays');
assert.ok(i18n.hasKey('Hi {name}') && !i18n.hasKey('Missing'));
assert.equal(i18n.catalog()['Hi {name}'], 'Hallo {name}');

// plural forms follow the locale's CLDR rules, not "is it 1?"
use('uu', { '{n} days': { one: 'one {n}', few: 'few {n}', many: 'many {n}', other: 'other {n}' } });
await i18n.setLang('uu', 'uk');
assert.equal(i18n.getLocale(), 'uk');
for (const [n, form] of [[1, 'one'], [21, 'one'], [2, 'few'], [22, 'few'], [5, 'many'], [11, 'many'], [1.5, 'other']]) {
  assert.equal(i18n.tn('{n} day', '{n} days', n), `${form} ${n}`, `Ukrainian plural for ${n}`);
}
assert.equal(i18n.tn('{n} day', '{n} days', 5, { n: '5,0' }), 'many 5,0', 'a formatted number is shown, the raw one picks the form');
use('uv', { '{n} days': { other: 'only {n}' } });
await i18n.setLang('uv', 'uk');
assert.equal(i18n.tn('{n} day', '{n} days', 2), 'only 2', 'a missing category falls back to other');

// a catalog that cannot be loaded leaves the page in English
i18n.CATALOGS.broken = async () => { throw new Error('offline'); };
const warn = console.warn; console.warn = () => {};
await i18n.setLang('broken');
console.warn = warn;
assert.equal(i18n.t('Hi {name}', { name: 'A' }), 'Hi A');

// two quick switches: the last choice wins even when the first catalog arrives later
let release;
i18n.CATALOGS.slow = () => new Promise((r) => { release = () => r({ Word: 'slow' }); });
use('fast', { Word: 'fast' });
const first = i18n.setLang('slow');
await i18n.setLang('fast');
release();
await first;
assert.deepEqual([i18n.getLang(), i18n.t('Word')], ['fast', 'fast']);

// ------------------------------------------------------------------ formats and raw API values
const f = await import('../../skoda_mate/static/lib/format.js');
use('zz', { Today: 'T!', Yesterday: 'Y!', 'just now': 'J!', 'Connect cable': 'Kabel anschließen' });
await i18n.setLang('zz', 'en-GB');
f.setLocale({ language: 'zz', locale: 'en-GB' });
assert.equal(f.getLocale(), 'en-GB', 'formats take the BCP-47 locale, not the language code');
const noonToday = new Date(); noonToday.setHours(12, 0, 0, 0);
const noonBefore = new Date(noonToday); noonBefore.setDate(noonToday.getDate() - 1);
assert.deepEqual([f.dayLabel(noonToday.toISOString()), f.dayLabel(noonBefore.toISOString()), f.ago(10)], ['T!', 'Y!', 'J!'],
  'today, yesterday and "just now" come from the catalog');
assert.equal(i18n.tEnum('CONNECT_CABLE'), 'Kabel anschließen');
await i18n.setLang('en');
f.setLocale({ language: 'en', locale: 'en' });
assert.equal(i18n.tEnum('CONNECT_CABLE'), 'Connect cable');
assert.equal(i18n.tEnum('AC'), 'Ac', 'the English wording stays as it was');
assert.equal(i18n.tEnum('NEW_VALUE'), 'New value', 'a value the table does not know yet is made readable');
assert.deepEqual([i18n.tEnum('Plain text'), i18n.tEnum(5), i18n.tEnum(null)], ['Plain text', 5, null], 'only raw API values are touched');
const KNOWN = ('YES NO ON OFF OPEN OPENED CLOSED LOCKED UNLOCKED UNKNOWN UNSUPPORTED INVALID TRUNK_OPENED PARKED IN_MOTION CONNECTED '
  + 'DISCONNECTED CHARGING READY_FOR_CHARGING CONNECT_CABLE CONSERVING DISCHARGING CHARGING_INTERRUPTED AC DC COOLING HEATING HEATING_AUXILIARY '
  + 'VENTILATION PREHEATING COMPLETED MANUAL TIMER TIMER_CHARGING_WITH_CLIMATISATION PREFERRED_CHARGING_TIMES ONLY_OWN_CURRENT '
  + 'IMMEDIATE_DISCHARGING HOME_STORAGE_CHARGING PERMANENT MAXIMUM REDUCED ACTIVATED DEACTIVATED ELECTRIC GASOLINE DIESEL CNG LPG HYBRID '
  + 'RECURRING ONE_OFF CELSIUS FAHRENHEIT MONDAY TUESDAY WEDNESDAY THURSDAY FRIDAY SATURDAY SUNDAY').split(' ');
assert.deepEqual(KNOWN.filter((v) => !i18n.ENUM_LABELS[v]), [], 'every value that had a German word still has a label');
const german = JSON.parse((await import('node:fs')).readFileSync(new URL('../../skoda_mate/static/i18n/de.json', import.meta.url), 'utf8'));
i18n.CATALOGS.de = async () => german;
await i18n.setLang('de');
assert.deepEqual(['CHARGING', 'VENTILATION', 'OPEN', 'AC', 'CELSIUS'].map(i18n.tEnum), ['Lädt', 'Lüften', 'Offen', 'AC', '°C'],
  'German values read as before, also where the same English word means something else elsewhere');
assert.deepEqual(Object.keys(german).filter((k) => k.startsWith('enum:')), [], 'no enum: keys are left');

// ------------------------------------------------------------------ messages from the backend
use('mm', { '{vin}: {error}': '{vin} – {error}', 'Place not found.': 'Ort nicht gefunden.' });
await i18n.setLang('mm', 'de');
assert.equal(i18n.tm({ message: '{vin}: {error}', params: { vin: 'TMB…1', error: { message: 'Place not found.', params: {} } } }),
  'TMB…1 – Ort nicht gefunden.', 'a parameter that is a message is translated too');
assert.equal(i18n.tm({ message: 'New in the server {n}', params: { n: '{x}' } }), 'New in the server {x}');
assert.equal(i18n.tm({ message: 'Place not found.' }), 'Ort nicht gefunden.', 'params may be missing');
assert.equal(i18n.tx({ error: 'Place not found.', error_i18n: { message: 'Place not found.', params: {} } }), 'Ort nicht gefunden.');
assert.equal(i18n.tx({ error: 'Plain from an older server' }), 'Plain from an older server', 'without a template the text stays');
assert.equal(i18n.tx({ message: 'Hi', message_i18n: { message: 'Place not found.', params: {} } }, 'message'), 'Ort nicht gefunden.');
assert.deepEqual([i18n.tx({ error: null }), i18n.tx(null), i18n.tx(undefined)], [null, null, null]);

// ------------------------------------------------------------------ keys and catalogs
const { compare, scan } = await import('./i18n_lib.mjs');
const found = scan({ 'pages/a.js': "// t('In a comment')\n /** tn('{n} x', '{n} xs', 1) */\nt('Hello {name}', { name }); N_('Marked'); tn('{n} day', '{n} days', n); t(variable); const x = tn(\n 'one {n}', 'many {n}', 2);\nt('It\\'s')",
  'app.js': "{ path: 'x', name: 'x', label: 'Nav label' }; t('Hello {name}')" });
assert.deepEqual(Object.keys(found).sort(), ['Hello {name}', "It's", 'Marked', 'Nav label', 'many {n}', '{n} days']);
assert.deepEqual(found['Hello {name}'], { files: ['app.js', 'pages/a.js'] });
assert.deepEqual(found['{n} days'], { files: ['pages/a.js'], one: '{n} day' });
const keys = { 'A {lo}': { files: [] }, B: { files: [] }, '{n} days': { files: [], one: '{n} day' }, '{x} of {n} files': { files: [], one: '{x} of {n} file' } };
const good = { 'A {lo}': 'a {lo}', B: 'b', '{n} days': { one: 'ein Tag', other: '{n} Tage' }, '{x} of {n} files': { one: '{x} von {n}', other: '{x} von {n}' } };
assert.deepEqual(compare(keys, good, 'de'), []);
const problems = (catalog, locale = 'de') => compare(keys, { ...good, ...catalog }, locale).join('\n');
assert.match(compare(keys, { B: 'b' }, 'de').join('\n'), /missing: A \{lo\}/);
assert.match(problems({ Old: 'alt' }), /extra: Old/);
assert.match(problems({ 'A {lo}': 'a {low}' }), /placeholders: A \{lo\}/);
assert.match(problems({ 'A {lo}': 'a' }), /placeholders: A \{lo\}/);
assert.match(problems({ B: '' }), /missing: B/);
assert.match(problems({ B: { one: 'b', other: 'b' } }), /not a text: B/);
assert.match(problems({ '{n} days': 'Tage' }), /not plural forms: \{n\} days/);
assert.match(problems({}, 'uk'), /plural form few missing: \{n\} days/);
assert.match(problems({ '{n} days': { one: '{n} Tag', other: 'Tage {x}' } }), /placeholders: \{n\} days \(other\)/);
assert.match(problems({ '{x} of {n} files': { one: 'eine', other: '{x} von {n}' } }), /placeholders: \{x\} of \{n\} files \(one\)/, 'only the count may be left out of a form');


// the import preview's status chips reach t() through a table: each must be extracted and have its German
const everything = scan();
for (const [key, word] of [['new', 'neu'], ['completed', 'ergänzt'], ['known', 'bekannt']]) {
  assert.ok(everything[key]?.files.includes('pages/import.js'), `the import status "${key}" is extracted`);
  assert.equal(german[key], word, `the import status "${key}" reads in German`);
}

// the distance explanations are whole German sentences: the relative clause has its pronoun and the verb its place
const sentences = Object.entries(german).filter(([k]) => /^(The distance is the sum of the trips Mate has recorded|These statistics cover only what Mate has recorded)/.test(k));
assert.equal(sentences.length, 5);
for (const [key, text] of sentences) {
  if (key.includes('{odometer} the car has driven') && key.startsWith('The distance')) {
    assert.match(text, /von den \{odometer\}, die das Auto insgesamt gefahren ist \(Kilometerstand\)\./, key);
  }
  if (key.startsWith('The distance') && key.includes('{date}')) assert.match(text, /die Mate seit \{date\} aufgezeichnet hat:/, key);
  if (key.startsWith('These statistics')) {
    assert.match(text, /was Mate seit dem \{date\} erfasst hat: \{recorded\} von den insgesamt gefahrenen \{odometer\} \(Kilometerstand\)\./, key);
  }
}

// {n} may be left out only where the plural form stands for exactly one number
const one = { '{n} trips': { files: [], one: '{n} trip' } };
const forms = (locale, extra) => ({ '{n} trips': Object.fromEntries(new Intl.PluralRules(locale).resolvedOptions().pluralCategories.map((c) => [c, extra[c] ?? '{n} x'])) });
assert.deepEqual(compare(one, forms('de', { one: 'eine Fahrt' }), 'de'), [], 'German "one" is only 1');
assert.match(compare(one, forms('uk', { one: 'одна поїздка' }), 'uk').join(), /placeholders: \{n\} trips \(one\)/, 'Ukrainian "one" is also 21');
assert.match(compare(one, forms('fr', { one: 'un trajet' }), 'fr').join(), /placeholders: \{n\} trips \(one\)/, 'French "one" is also 0');

// a problem line names the language, the key and the placeholders, however long the key is
const { problemLines } = await import('./i18n_lib.mjs');
const long = `${'A long sentence. '.repeat(20)}{odometer}`;
const [line] = problemLines('xx', compare({ [long]: { files: [] } }, { [long]: 'kurz {ort}' }, 'de'), 40);
assert.ok(line.includes('xx: ') && line.includes(long) && line.includes('{ort}'), line);

// the plural rules come from the locale registered in languages.py, not from a guess about the file name
const { languages, unregistered } = await import('./i18n_lib.mjs');
assert.deepEqual(languages('LANGUAGES = (\n    Language("en", "English", "en"),\n    Language("no", "Norsk bokmål", "nb"),\n    Language("zh_Hans", "简体中文", "zh-Hans"),\n)'),
  [{ code: 'en', name: 'English', locale: 'en' }, { code: 'no', name: 'Norsk bokmål', locale: 'nb' }, { code: 'zh_Hans', name: '简体中文', locale: 'zh-Hans' }]);
assert.deepEqual(languages().slice(0, 2).map((l) => [l.code, l.locale]), [['en', 'en'], ['de', 'de']], 'languages.py is read');
assert.deepEqual(unregistered(['de', 'xx'], languages()), ['xx: in CATALOGS but not in skoda_mate/languages.py']);

// a catalog that fails, hangs or is not an object leaves a page that is English throughout: texts, formats and lang
const quiet = console.warn; console.warn = () => {};
for (const [what, load] of [['rejects', async () => { throw new Error('offline'); }], ['is null', async () => null], ['is a list', async () => []],
  ['is a string', async () => '<html>error</html>']]) {
  i18n.CATALOGS.bad = load;
  await i18n.setLang('bad', 'de');
  assert.deepEqual([i18n.getLang(), i18n.getLocale(), i18n.t('Word'), i18n.tn('{n} day', '{n} days', 2)], ['en', 'en', 'Word', '2 days'], `a catalog that ${what}`);
}
const realFetch = globalThis.fetch;
let asked;
globalThis.fetch = (url, options) => new Promise((resolve, reject) => {
  asked = url;
  options?.signal?.addEventListener('abort', () => reject(options.signal.reason));
});
i18n.CATALOGS.hangs = i18n.jsonCatalog('hangs', 30);
const gaveUp = await Promise.race([i18n.setLang('hangs', 'de').then(() => true), new Promise((r) => setTimeout(r, 1000, false))]);
globalThis.fetch = realFetch;
assert.ok(gaveUp, 'a request that never answers is given up');
assert.equal(asked, '/static/i18n/hangs.json');
assert.deepEqual([i18n.getLang(), i18n.getLocale()], ['en', 'en']);
console.warn = quiet;

// ------------------------------------------------------------------ what another language needs
const modules = (await import('./i18n_lib.mjs')).sources();
const found3 = scan(modules);
for (const key of ['Reviewed {date}', '{n} inferred', '{n} changed', '{n} reviewed', 'and {n} more', '{n} Running', '{n} Important', '{n} Info']) {
  assert.ok(found3[key], `${key} is one key`);
}
for (const key of ['{n} inferred', '{n} changed', '{n} reviewed', 'and {n} more', '{n} Running', '{n} Important', '{n} Info']) {
  assert.ok(found3[key].one, `${key} has plural forms: other languages inflect it`);
}
for (const [file, src] of Object.entries(modules)) assert.doesNotMatch(src, /\}\. \$\{t\(/, `${file}: two translations are not joined with ". "`);
assert.match(modules['pages/events.js'], /h\('span', null, t\('24 h'\)\)/, 'the 24 h legend is translated');
use('nf', { 'between {lo} and {hi}, {port}, {name}': '{lo} bis {hi}, {port}, {name}' });
await i18n.setLang('nf', 'de');
assert.equal(i18n.tm({ message: 'between {lo} and {hi}, {port}, {name}', params: { lo: 15.5, hi: 30, port: 1883, name: '2.5' } }),
  '15,5 bis 30, 1883, 2.5', 'a fraction is written the way the locale writes it; whole numbers and texts stay');

// browsers without AbortSignal.timeout (Safari before 16) still load their translation, and still give up on a hang
const timeoutFn = AbortSignal.timeout;
const fetchAsIs = globalThis.fetch, warnAsIs = console.warn;
delete AbortSignal.timeout;
try {
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ Word: 'Wort' }) });
  i18n.CATALOGS.old = i18n.jsonCatalog('old', 30);
  console.warn = () => {};
  await i18n.setLang('old', 'de');
  assert.equal(i18n.t('Word'), 'Wort', 'the catalog loads without AbortSignal.timeout');
  globalThis.fetch = (url, options) => new Promise((resolve, reject) => options?.signal?.addEventListener('abort', () => reject(new Error('aborted'))));
  const done = await Promise.race([i18n.setLang('old', 'de').then(() => true), new Promise((r) => setTimeout(r, 1000, false))]);
  assert.ok(done && i18n.getLang() === 'en', 'and a hanging request is still given up');
} finally {
  AbortSignal.timeout = timeoutFn;
  globalThis.fetch = fetchAsIs;
  console.warn = warnAsIs;
}
assert.ok(scan((await import('./i18n_lib.mjs')).sources())['{n} without distance (skipped)']?.one, 'the count of skipped rows has plural forms');
await i18n.setLang('en');
console.log('frontend unit checks OK');
