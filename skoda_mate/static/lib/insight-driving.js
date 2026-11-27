// Statistics → Driving: where the car goes, when, how far and how consumption moves. Mate knows no speed and no route.
import { h } from './dom.js';
import { card, empty, stat, table } from './ui.js';
import { barChart } from './charts.js';
import { heatmap } from './heatmap.js';
import * as f from './format.js';
import { t } from '../i18n.js';

const MI = 0.621371;
const DASH = '–';

export function renderDriving(data) {
  const tt = data.totals;
  if (!tt.trips) return [empty(t('No trips in this period'), t('Pick a longer period to see driving insight.'), 'route')];
  const unit = f.distUnit();
  const distance = (km) => f.num(f.toDist(km));

  const totals = h('div', { class: 'grid auto' },
    card(null, stat(t('Trips'), f.num(tt.trips), { ic: 'route' })),
    card(null, stat(t('Distance'), distance(tt.km), { unit, ic: 'gauge' })),
    card(null, stat(t('Average trip'), tt.avg_km == null ? DASH : f.km(tt.avg_km, 1), { ic: 'route',
      sub: tt.avg_duration_min == null ? null : `${t('average duration')} ${f.duration(tt.avg_duration_min)}` })),
    // shown only once the server has enough tracked days; it always says what it is
    data.projection ? card(null, stat(t('Projected distance per year'), distance(data.projection.annual_km), { unit, ic: 'trend',
      sub: `${t('A projection from the odometer over this many days:')} ${data.projection.days}` })) : null);

  const destinations = card(t('Top destinations'), table([
    { label: t('Destination'), render: (r) => (r.place_id ? h('a', { class: 'nowrap', href: `#/places/${r.place_id}` }, r.name) : r.name ? f.shortPlace(r.name) : t('Unknown place')) },
    { label: t('Trips'), render: (r) => r.trips, num: true },
    { label: unit, render: (r) => distance(r.km), num: true, cls: 'nowrap' },
  ], data.top_destinations, { label: t('Top destinations') }), { ic: 'pin' });

  const bucketLabel = (b) => (b.to_km == null ? `${distance(b.from_km)}+` : `${distance(b.from_km)}–${distance(b.to_km)}`);
  const buckets = card(`${t('Trip lengths')} (${unit})`, barChart({
    categories: data.buckets.map((b) => ({ label: bucketLabel(b), tip: `${bucketLabel(b)} ${unit} · ${f.km(b.km)}`, values: [b.trips] })),
    series: [{ name: t('Number of trips by distance') }], fmt: (v) => f.num(v, 0), height: 200 }), { ic: 'chart' });

  const where = (name) => (name ? f.shortPlace(name) : t('Unknown place'));
  const longest = card(t('Longest trips'), table([
    { label: t('Date'), render: (r) => h('a', { href: `#/trips/${r.id}` }, f.date(r.started_at)), cls: 'nowrap' },
    { label: t('Route'), render: (r) => `${where(r.start)} → ${where(r.end)}` },
    { label: unit, render: (r) => `${r.approx ? '≈ ' : ''}${distance(r.distance_km)}`, num: true, cls: 'nowrap' },
  ], data.longest, { label: t('Longest trips') }), { ic: 'route' });

  const used = data.consumption.filter((r) => r.kwh_100km != null);
  const conv = (v) => (f.getUnits() === 'mi' ? v / MI : v);
  const trend = card(`${t('Consumption trend')} (${f.consUnit()})`, used.length
    ? barChart({ categories: used.map((r) => ({ label: f.monthLabel(r.month), values: [conv(r.kwh_100km)] })),
      series: [{ name: t('Consumption'), color: 'var(--chart-2)' }], fmt: (v) => f.num(v, 1), height: 200 })
    : empty(t('No consumption yet'), null, 'gauge'), { ic: 'gauge' });

  const when = card(t('When you drive'), h('div', { class: 'stack' }, heatmap(data.heatmap, { label: t('Trips by weekday and start hour') }),
    data.heatmap_excluded ? h('p', { class: 'small muted' }, `${t('Trips with an estimated start time are left out of the heatmap:')} ${data.heatmap_excluded}`) : null), { ic: 'calendar' });

  return [totals, h('div', { class: 'grid g2' }, destinations, longest), h('div', { class: 'grid g2' }, buckets, trend), when];
}
