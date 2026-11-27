// Statistics → Charging: where, when, how fast and how expensive. All numbers come from /insights/charging.
import { h } from './dom.js';
import { banner, card, chip, empty, stat, table } from './ui.js';
import { barChart } from './charts.js';
import { heatmap } from './heatmap.js';
import * as f from './format.js';
import { t } from '../i18n.js';

const DASH = '–';

// A total that is missing some costs says "at least", an unknown one stays a dash.
const costText = (row, cur) => (row.cost == null ? DASH : `${row.cost_partial ? `${t('at least')} ` : ''}${f.money(row.cost, cur)}`);

function curveCard(title, bins) {
  const body = bins.length
    ? barChart({ categories: bins.map((b) => ({ label: `${b.soc_from}`, tip: `${b.soc_from}–${b.soc_to} % · ${b.samples}×`, values: [b.avg_kw] })),
      series: [{ name: t('Average kW') }], fmt: (v) => f.num(v, 0), height: 200 })
    : empty(t('Not enough readings for a charge curve'), null, 'bolt');
  return card(title, h('div', { class: 'stack' }, body,
    h('p', { class: 'small muted' }, t('Average charging power by charge level, in 5 % steps. Steps with fewer than three readings are hidden.'))), { ic: 'trend' });
}

export function renderCharging(data) {
  const tt = data.totals, cur = data.currency;
  if (!tt.sessions) return [empty(t('No charges in this period'), t('Pick a longer period to see charging insight.'), 'bolt')];

  const totals = h('div', { class: 'grid auto' },
    card(null, stat(t('Energy charged'), f.num(tt.energy_kwh, 0), { unit: 'kWh', ic: 'bolt', sub: `${tt.sessions} ${t('Charges').toLowerCase()}` })),
    card(null, stat(t('Charging cost'), costText(tt, cur), { ic: 'coin', sub: tt.cost_partial ? t('Some costs are unknown and not included.') : null })),
    card(null, stat(t('Cost per kWh'), f.money(tt.cost_per_kwh, cur, 3), { ic: 'coin' })),
    card(null, stat(t('Measured share'), tt.inferred_share == null ? DASH : f.num((1 - tt.inferred_share) * 100, 0), {
      unit: tt.inferred_share == null ? null : '%', ic: 'gauge', sub: `${f.kwh(tt.measured_kwh, 0)} ${t('of the energy')}` })),
    tt.session_fees > 0 ? card(null, stat(t('Session fees'), f.money(tt.session_fees, cur), { ic: 'coin', sub: t('included in the cost') })) : null);

  const inferred = tt.inferred_sessions ? banner('info', `${t('Inferred or imported charges in this period:')} ${tt.inferred_sessions} (${f.kwh(tt.inferred_kwh, 1)}). `,
    chip(t('inferred'), 'warn'), ' ', t('They count toward energy and cost, but not toward power, the charge curve or the heatmap, because Mate did not measure them.')) : null;

  const types = [['ac', t('AC')], ['dc', t('DC')], ['unknown', t('Unknown type')]]
    .map(([key, name]) => ({ name, ...data.types[key] })).filter((r) => r.sessions);
  const power = card(t('Charging power (measured)'), h('div', { class: 'stack' }, table([
    { label: t('Type'), render: (r) => r.name },
    { label: t('Charges'), render: (r) => r.sessions, num: true },
    { label: 'kWh', render: (r) => f.num(r.energy_kwh, 1), num: true, cls: 'nowrap' },
    { label: t('Average power'), render: (r) => f.kw(r.avg_power_kw), num: true, cls: 'nowrap' },
    { label: t('Peak power'), render: (r) => f.kw(r.peak_power_kw), num: true, cls: 'nowrap' },
  ], types, { label: t('Charging power (measured)'), emptyNode: empty(t('No measured charges in this period.'), null, 'bolt') }),
    h('p', { class: 'small muted' }, t('Average power is energy divided by charging time. Charges whose end Mate had to estimate are left out of it.'))), { ic: 'bolt' });

  const moneyColumns = [
    { label: t('Charges'), render: (r) => r.sessions, num: true },
    { label: 'kWh', render: (r) => f.num(r.energy_kwh, 1), num: true, cls: 'nowrap' },
    { label: t('Cost'), render: (r) => costText(r, cur), num: true, cls: 'nowrap' },
  ];
  const split = card(t('Home, public and other'), table([{ label: t('Where'), render: (r) => r.name }, ...moneyColumns],
    [['home', t('Home')], ['public', t('Public')], ['other', t('Other')]].map(([key, name]) => ({ name, ...data.split[key] })),
    { label: t('Home, public and other') }), { ic: 'home' });

  const places = card(t('Top charging places'), table([
    { label: t('Place'), render: (r) => (r.place_id ? h('a', { class: 'nowrap', href: `#/places/${r.place_id}` }, r.name) : r.name ? f.shortPlace(r.name) : t('Unknown place')) },
    ...moneyColumns,
  ], data.top_places, { label: t('Top charging places') }), { ic: 'pin' });

  const when = card(t('When charging starts'), heatmap(data.heatmap, { label: t('Measured charges by weekday and start hour') }), { ic: 'calendar' });

  return [inferred, totals, h('div', { class: 'grid g2' }, curveCard(t('Charge curve (AC)'), data.curve.ac), curveCard(t('Charge curve (DC)'), data.curve.dc)),
    power, h('div', { class: 'grid g2' }, split, places), when];
}
