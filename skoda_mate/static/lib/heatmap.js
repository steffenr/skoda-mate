// Weekday × hour counts as a CSS grid, with the same numbers as a table for anyone who cannot read the colours.
import { h } from './dom.js';
import { table } from './ui.js';
import * as f from './format.js';
import { t } from '../i18n.js';

// 2024-01-01 was a Monday, the first row the server sends.
const weekday = (i, style) => new Date(Date.UTC(2024, 0, 1 + i)).toLocaleDateString(f.getLocale(), { weekday: style, timeZone: 'UTC' });
const hour = (n) => String(n).padStart(2, '0');

/** heatmap(rows, {label}) — rows: 7 (Monday first) × 24 counts. */
export function heatmap(rows, { label }) {
  const max = Math.max(1, ...rows.flat());
  const cell = (n, day, at) => {
    const el = h('span', { class: 'heat-cell', title: `${weekday(day, 'long')} ${hour(at)}:00: ${n}` });
    if (n) el.style.background = `color-mix(in srgb, var(--chart-1) ${Math.round(25 + (n / max) * 75)}%, var(--surface-3))`;
    return el;
  };
  const hours = Array.from({ length: 24 }, (_, i) => i);
  const grid = h('div', { class: 'heat-grid', role: 'img', 'aria-label': label },
    h('span', null), ...hours.map((i) => h('span', { class: 'heat-hour' }, i % 6 === 0 ? hour(i) : '')),
    ...rows.flatMap((row, day) => [h('span', { class: 'heat-day' }, weekday(day, 'short')), ...row.map((n, at) => cell(n, day, at))]));
  const asTable = table(
    [{ label: t('Weekday'), render: (r) => weekday(r.day, 'short'), cls: 'nowrap' },
      ...hours.map((i) => ({ label: hour(i), render: (r) => r.counts[i] || '', num: true, cls: 'nowrap' }))],
    rows.map((counts, day) => ({ day, counts })), { label });
  return h('div', { class: 'heat stack' }, grid, h('p', { class: 'tiny muted' }, t('Darker means more often.')),
    h('details', null, h('summary', null, t('Show as table')), asTable));
}
