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
await i18n.setLang('en');
console.log('frontend unit checks OK');
