// Battery → projected range: the range the car reports, scaled to 100 %. It is not a statement about the battery itself.
import { h } from './dom.js';
import { banner, card, empty, stat } from './ui.js';
import { lineChart } from './charts.js';
import * as f from './format.js';
import { t } from '../i18n.js';

const signed = (v, digits) => `${v > 0 ? '+' : ''}${f.num(v, digits)}`;
const noon = (day) => `${day}T12:00:00`;  // a bare date would be read as UTC and could show the day before

export function rangeCard(range) {
  const note = banner('info', h('strong', null, t('Projected range from reported range.')), ' ',
    t('It scales the range the car reports to 100 % charge. Temperature, load and driving style are unknown and move it, for example with the seasons.'));
  if (!range?.latest) {
    return card(t('Projected range'), h('div', { class: 'stack' },
      empty(t('No projected range yet'), t('It needs readings with a charge level of at least 20 % and a reported range.'), 'trend'), note), { ic: 'route' });
  }
  const change = range.degradation, trend = range.trend_km_per_year;
  return card(t('Projected range'), h('div', { class: 'stack' },
    h('div', { class: 'grid auto' },
      stat(t('At 100 % charge'), f.num(f.toDist(range.latest.range_km), 0), { unit: f.distUnit(), ic: 'route', sub: f.date(noon(range.latest.day)) }),
      stat(t('Readings used'), f.num(range.samples), { ic: 'chart', sub: range.rejected ? `${t('outliers left out:')} ${f.num(range.rejected)}` : null }),
      trend != null ? stat(t('Trend per year'), signed(f.toDist(trend), 0), { unit: f.distUnit(), ic: 'trend' }) : null,
      change ? stat(t('First to last 90 days'), signed(change.change_pct, 1), { unit: '%', ic: 'gauge', sub: `${f.km(change.first_km)} → ${f.km(change.last_km)}` }) : null),
    change ? null : h('p', { class: 'small muted' }, t('A comparison appears once two separate 90-day periods have enough readings.')),
    h('div', null, h('h3', { style: { marginBottom: '6px' } }, t('Projected range over time')),
      lineChart({ height: 190, yLeft: { fmt: (v) => f.num(v, 0) }, emptyText: t('Not enough readings yet'),
        series: [{ name: `${t('Projected range')} (${f.distUnit()})`, data: range.daily.map((p) => ({ x: noon(p.day), y: f.toDist(p.range_km) })), fmt: (v) => `${f.num(v, 0)} ${f.distUnit()}` }] })),
    note), { ic: 'route' });
}
