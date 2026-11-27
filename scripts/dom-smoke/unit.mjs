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
console.log('frontend unit checks OK');
