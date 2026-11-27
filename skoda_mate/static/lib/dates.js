// Pure date helpers with no DOM and no i18n, so node can check them (scripts/dom-smoke/unit.mjs).

const MIN = 60000;

/** The instant a local day starts, as the server defines it: that date's midnight shifted by the browser's
 * `getTimezoneOffset()` (minutes, UTC minus local), the same value the request sent as `tz_offset`. Unlike the
 * browser's own local midnight this never moves across a DST change, so bars line up with the server's day bounds. */
export function dayStartMs(isoDate, tzOffset) {
  const [y, m, d] = isoDate.split('-').map(Number);
  return Date.UTC(y, m - 1, d) + tzOffset * MIN;
}

/** The clock time of an instant on the server's day axis: the same fixed `tzOffset` the timeline request sent, not the
 * browser's local clock (which jumps an hour after a DST change while the bars do not). `lang` shapes the output like
 * `f.time`; an unparseable time or a non-finite offset prints a dash. */
export function clockAt(iso, tzOffset, lang) {
  const ms = new Date(iso).getTime();
  if (Number.isNaN(ms) || !Number.isFinite(tzOffset)) return '–';
  return new Date(ms - tzOffset * MIN).toLocaleTimeString(lang, { timeStyle: 'short', timeZone: 'UTC' });
}

/** `{ left, width }` in percent of a day for an interval, given the day's own start and end in ms. */
export function barBox(startIso, minutes, dayStart, dayEnd) {
  const dayMin = (dayEnd - dayStart) / MIN;
  const left = Math.min(100, Math.max(0, (new Date(startIso).getTime() - dayStart) / MIN / dayMin * 100));
  const width = Math.max(0, Math.min(minutes / dayMin * 100, 100 - left));
  return { left, width };
}

/** The date `n` calendar months before `d`, clamped to that month's last day (31 March minus one month is 28/29 February,
 * not 3 March, which `setMonth` would give). */
export function monthsAgo(d, n) {
  const first = new Date(d.getFullYear(), d.getMonth() - n, 1);
  const last = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
  return new Date(first.getFullYear(), first.getMonth(), Math.min(d.getDate(), last));
}
