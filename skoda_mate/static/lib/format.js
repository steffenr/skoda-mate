// Number, date and unit formatting. Units (km/mi) and the BCP-47 locale come from Settings via setLocale().
import { t } from '../i18n.js';

let units = 'km';
let lang = 'en';  // BCP-47, what Intl and the toLocale* methods take
export function setLocale(opts) {
  if (opts.units) units = opts.units;
  if (opts.locale || opts.language) lang = opts.locale || opts.language;
}
export const getUnits = () => units;
export const getLocale = () => lang;

const DASH = '–';
const MI = 0.621371;

export function num(n, digits = 0) {
  if (n == null || Number.isNaN(+n)) return DASH;
  return new Intl.NumberFormat(lang, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(+n);
}

// distance
export const distUnit = () => (units === 'mi' ? 'mi' : 'km');
export const toDist = (km) => (km == null ? null : units === 'mi' ? km * MI : km);
export const km = (v, digits = 0) => (v == null ? DASH : `${num(toDist(v), digits)} ${distUnit()}`);
// consumption: kWh/100 km  <->  kWh/100 mi
export const consUnit = () => `kWh/100 ${distUnit()}`;
export const cons = (v, digits = 1) => (v == null ? DASH : `${num(units === 'mi' ? v / MI : v, digits)} ${consUnit()}`);
export const speed = (v) => (v == null ? DASH : `${num(toDist(v))} ${units === 'mi' ? 'mph' : 'km/h'}`);

export const kwh = (v, digits = 1) => (v == null ? DASH : `${num(v, digits)} kWh`);
export const kw = (v, digits = 1) => (v == null ? DASH : `${num(v, digits)} kW`);
export const pct = (v, digits = 0) => (v == null ? DASH : `${num(v, digits)} %`);
export const temp = (v) => (v == null ? DASH : `${num(v, 1)} °C`);

export function money(v, currency = 'EUR', digits = 2) {
  if (v == null) return DASH;
  try {
    return new Intl.NumberFormat(lang, { style: 'currency', currency, minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v);
  } catch { return `${num(v, digits)} ${currency}`; }
}

export function duration(min) {
  if (min == null) return DASH;
  const m = Math.round(min);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  return `${h} h ${String(m % 60).padStart(2, '0')} min`;
}

const parse = (iso) => (iso ? new Date(iso) : null);
export function dateTime(iso) {
  const d = parse(iso);
  return d ? d.toLocaleString(lang, { dateStyle: 'medium', timeStyle: 'short' }) : DASH;
}
export function date(iso, opts = { dateStyle: 'medium' }) {
  const d = parse(iso);
  return d ? d.toLocaleDateString(lang, opts) : DASH;
}
export function time(iso) {
  const d = parse(iso);
  return d ? d.toLocaleTimeString(lang, { timeStyle: 'short' }) : DASH;
}
export function monthLabel(ym) {
  const [y, m] = ym.split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString(lang, { month: 'short', year: '2-digit' });
}
export function dayLabel(iso) {
  const d = parse(iso);
  if (!d) return DASH;
  const today = new Date();
  const same = (a, b) => a.toDateString() === b.toDateString();
  const yest = new Date(today); yest.setDate(today.getDate() - 1);
  if (same(d, today)) return t('Today');
  if (same(d, yest)) return t('Yesterday');
  return d.toLocaleDateString(lang, { weekday: 'short', day: 'numeric', month: 'short' });
}

// "3 min ago" from an ISO string or a number of seconds
export function ago(src) {
  const s = typeof src === 'number' ? src : src ? (Date.now() - new Date(src).getTime()) / 1000 : null;
  if (s == null || Number.isNaN(s)) return DASH;
  const rtf = new Intl.RelativeTimeFormat(lang, { numeric: 'auto' });
  const a = Math.abs(s);
  if (a < 90) return t('just now');
  if (a < 5400) return rtf.format(-Math.round(s / 60), 'minute');
  if (a < 129600) return rtf.format(-Math.round(s / 3600), 'hour');
  return rtf.format(-Math.round(s / 86400), 'day');
}

export function inSeconds(s) {
  if (s == null) return DASH;
  if (s < 90) return `${Math.round(s)} s`;
  if (s < 5400) return `${Math.round(s / 60)} min`;
  return `${Math.round(s / 3600)} h`;
}

export function shortPlace(address) {
  if (!address) return DASH;
  const parts = address.split(',').map((x) => x.trim());
  return parts.length >= 2 ? `${parts[0]}, ${parts[1].replace(/^(?:\d{3}\s\d{2}|\d{4,6})\s*/, "")}` : parts[0];
}

export function localDay(iso) {
  const d = parse(iso);
  if (!d) return '';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** "20 % → 80 %", or "+80 %" when only the rise is known (a charge imported from a trip export). */
export function socText(c) {
  if (c.start_soc == null && c.end_soc == null && c.soc_gained != null) return `+${num(c.soc_gained, 0)} %`;
  return `${pct(c.start_soc)} → ${pct(c.end_soc)}`;
}
