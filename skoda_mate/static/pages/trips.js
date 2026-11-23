// Trips: derived trips grouped by day, filters kept in the URL hash, month calendar, totals for the filtered set, CSV export.
import { h, mount, debounce } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { banner, button, card, chip, empty, field, loading, seg, stat } from '../lib/ui.js';
import * as f from '../lib/format.js';
import { extendDE, t } from '../i18n.js';

extendDE({
  'Trip search': 'Fahrten suchen', 'Search places and notes': 'Orte und Notizen suchen', 'From': 'Von', 'To': 'Bis', 'Min. distance': 'Mindeststrecke',
  'Reset filters': 'Filter zurücksetzen', 'List': 'Liste', 'Month': 'Monat', 'Export CSV': 'CSV exportieren', 'Import trips': 'Fahrten importieren', 'Trips found': 'Gefundene Fahrten',
  'Total distance': 'Gesamtstrecke', 'Total duration': 'Gesamtdauer', 'Total energy': 'Gesamtenergie', 'Average consumption': 'Ø Verbrauch', 'Total cost': 'Gesamtkosten',
  'Load more': 'Mehr laden', 'No trips found': 'Keine Fahrten gefunden', 'Try other filters, or wait for the next drive.': 'Andere Filter probieren oder auf die nächste Fahrt warten.',
  'Mate derives trips from the odometer and the car’s parked/driving state.': 'Mate leitet Fahrten aus Kilometerstand und Park-/Fahrzustand des Autos ab.',
  'approx': 'ca.', 'Estimated trip': 'Geschätzte Fahrt',
  'Found through an odometer jump; times are estimated.': 'Über einen Kilometersprung gefunden; die Zeiten sind geschätzt.',
  'Previous month': 'Voriger Monat', 'Next month': 'Nächster Monat', 'Trip calendar': 'Fahrtenkalender', 'trips': 'Fahrten', 'trip': 'Fahrt',
  'Energy is only counted for trips where it is known.': 'Energie wird nur für Fahrten mit bekanntem Wert gezählt.',
  'Showing the newest {n} of {total} trips. Narrow the filters to see the rest.': 'Zeigt die neuesten {n} von {total} Fahrten. Mit Filtern lässt sich der Rest eingrenzen.',
  'Totals cover only the loaded trips.': 'Die Summen gelten nur für die geladenen Fahrten.',
  'Could not load trips': 'Fahrten konnten nicht geladen werden', 'Try again': 'Erneut versuchen', 'Costs are estimated at your home tariff.': 'Kosten sind mit Ihrem Heimtarif geschätzt.',
  'of': 'von', 'with energy': 'mit Energie', 'Day': 'Tag', 'Show this day': 'Diesen Tag anzeigen',
});

const PAGE = 40;
export const APPROX_TIP = 'Found through an odometer jump; times are estimated.';

/** Replace the query part of the current hash without adding a history entry or re-rendering the page. */
export function setQuery(path, params) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== '' && v != null) qs.set(k, v);
  const s = qs.toString();
  try { window.history.replaceState(null, '', `#/${path}${s ? `?${s}` : ''}`); } catch { /* keep working without URL sync */ }
}

const pad = (n) => String(n).padStart(2, '0');
export const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const sum = (items, key) => items.reduce((a, x) => a + (+x[key] || 0), 0);
const monthBounds = (ym) => {
  const [y, m] = ym.split('-').map(Number);
  return { from: `${ym}-01`, to: ymd(new Date(y, m, 0)) };
};
const shiftMonth = (ym, d) => { const [y, m] = ym.split('-').map(Number); const x = new Date(y, m - 1 + d, 1); return `${x.getFullYear()}-${pad(x.getMonth() + 1)}`; };

export function groupByDay(items, key) {
  const days = [];
  const idx = new Map();
  for (const it of items) {
    const d = f.localDay(it[key]) || '?';
    if (!idx.has(d)) { idx.set(d, { day: d, iso: it[key], items: [] }); days.push(idx.get(d)); }
    idx.get(d).items.push(it);
  }
  return days;
}

export function approxChip() {
  return h('span', { class: 'chip warn a-approx', title: t(APPROX_TIP) }, '≈ ', t('approx'), h('span', { class: 'sr' }, ` ${t(APPROX_TIP)}`));
}

export default async function trips(root, ctx) {
  ctx.setTitle(t('Trips'));
  const q0 = ctx.query;
  const S = {
    q: q0.get('q') || '', from: q0.get('from') || '', to: q0.get('to') || '', min: q0.get('min_km') || '',
    view: q0.get('view') === 'month' ? 'month' : 'list',
    month: /^\d{4}-\d{2}$/.test(q0.get('month') || '') ? q0.get('month') : f.localDay(new Date().toISOString()).slice(0, 7),
    shown: PAGE, items: [], total: 0, error: null, loaded: false,
  };
  let seq = 0;
  const body = h('div', { class: 'stack' });

  const sync = () => setQuery('trips', { q: S.q, from: S.from, to: S.to, min_km: S.min, view: S.view === 'month' ? 'month' : '', month: S.view === 'month' ? S.month : '' });

  async function load() {
    const my = ++seq;
    S.error = null; S.loaded = false; paintBody();
    const range = S.view === 'month' ? monthBounds(S.month) : { from: S.from, to: S.to };
    const p = new URLSearchParams({ limit: '500' });
    if (range.from) p.set('from', range.from);
    if (range.to) p.set('to', range.to);
    if (S.q) p.set('q', S.q);
    if (S.min) p.set('min_km', S.min);
    try {
      const r = await ctx.api.get(`/api/vehicles/${ctx.vid}/trips?${p}`);
      if (my !== seq) return;
      S.items = r.items; S.total = r.total;
    } catch (e) { if (my !== seq) return; S.error = e.message || String(e); }
    S.loaded = true; S.shown = PAGE;
    paintBody();
  }

  // ---- filter bar
  const search = h('input', { type: 'search', value: S.q, placeholder: t('Search places and notes'), maxlength: 80, oninput: debounce((e) => { S.q = e.target.value.trim(); sync(); load(); }, 300) });
  const from = h('input', { type: 'date', value: S.from, onchange: (e) => { S.from = e.target.value; sync(); load(); } });
  const to = h('input', { type: 'date', value: S.to, onchange: (e) => { S.to = e.target.value; sync(); load(); } });
  const min = h('input', { type: 'number', min: 0, step: 1, inputmode: 'decimal', value: S.min, placeholder: f.distUnit(),
    oninput: debounce((e) => { const v = parseFloat(e.target.value); S.min = Number.isFinite(v) && v > 0 ? String(f.getUnits() === 'mi' ? +(v / 0.621371).toFixed(2) : v) : ''; sync(); load(); }, 300) });
  if (S.min) min.value = f.getUnits() === 'mi' ? String(+(S.min * 0.621371).toFixed(1)) : S.min;
  const reset = () => { Object.assign(S, { q: '', from: '', to: '', min: '' }); search.value = ''; from.value = ''; to.value = ''; min.value = ''; sync(); load(); };
  const onView = (v) => { S.view = v; sync(); load(); };
  const segBox = h('div');
  const drawSeg = () => mount(segBox, seg([['list', t('List')], ['month', t('Month')]], S.view, onView));
  drawSeg();
  const csv = h('a', { class: 'btn', href: `/api/vehicles/${ctx.vid}/export/trips.csv`, download: 'skoda-mate-trips.csv' }, icon('download', { size: 16 }), h('span', null, t('Export CSV')));

  const filters = card(null, h('div', { class: 'a-filters' },
    field(t('Trip search'), search), field(t('From'), from), field(t('To'), to), field(`${t('Min. distance')} (${f.distUnit()})`, min),
    h('div', { class: 'a-filter-actions' }, button(t('Reset filters'), { onClick: reset, ic: 'x', size: 'sm' }))), { cls: 'flat' });

  // ---- parts
  function totals(items) {
    const withE = items.filter((x) => x.energy_kwh != null && x.distance_km > 0);
    const kwh = sum(items, 'energy_kwh');
    const eKm = sum(withE, 'distance_km');
    const cons = eKm > 0 ? (sum(withE, 'energy_kwh') / eKm) * 100 : null;
    return h('div', { class: 'grid auto a-totals' },
      card(null, stat(t('Trips found'), f.num(S.total), { ic: 'route', sub: S.total > items.length ? `${t('of')} ${f.num(S.total)}` : null })),
      card(null, stat(t('Total distance'), f.num(f.toDist(sum(items, 'distance_km')), 0), { unit: f.distUnit(), ic: 'gauge' })),
      card(null, stat(t('Total duration'), f.duration(sum(items, 'duration_min')), { ic: 'clock' })),
      card(null, stat(t('Total energy'), withE.length ? f.num(kwh, 1) : '–', { unit: withE.length ? 'kWh' : null, ic: 'bolt', sub: withE.length && withE.length < items.length ? `${withE.length} ${t('of')} ${items.length} ${t('with energy')}` : null })),
      card(null, stat(t('Average consumption'), cons != null ? f.num(f.getUnits() === 'mi' ? cons / 0.621371 : cons, 1) : '–', { unit: cons != null ? f.consUnit() : null, ic: 'gauge' })),
      card(null, stat(t('Total cost'), withE.length ? f.money(sum(items, 'cost'), ctx.currency) : '–', { ic: 'coin', sub: withE.length ? t('Costs are estimated at your home tariff.') : null })));
  }

  const row = (x) => h('a', { class: ['a-row', x.approx ? 'approx' : ''], href: `#/trips/${x.id}` },
    h('div', { class: 'a-time' }, f.time(x.started_at), x.approx ? approxChip() : null),
    h('div', { class: 'a-route' }, h('strong', null, `${f.shortPlace(x.start_place)} → ${f.shortPlace(x.end_place)}`),
      x.note ? h('div', { class: 'tiny muted a-note' }, x.note) : null),
    h('dl', { class: 'a-metrics' },
      metric(t('Distance'), f.km(x.distance_km, 1)), metric(t('Duration'), f.duration(x.duration_min)), metric(t('Energy'), f.kwh(x.energy_kwh)),
      metric(t('Consumption'), x.avg_kwh_100km != null ? f.cons(x.avg_kwh_100km) : '–'), metric(t('Cost'), x.cost != null ? f.money(x.cost, ctx.currency) : '–')),
    icon('right', { size: 16 }));
  const metric = (k, v) => h('div', null, h('dt', null, k), h('dd', null, v));

  function listView() {
    const visible = S.items.slice(0, S.shown);
    const groups = groupByDay(visible, 'started_at');
    return h('div', { class: 'stack' },
      ...groups.map((g) => {
        // totals over the whole day, even when "load more" cut the day in half
        const whole = S.items.filter((x) => f.localDay(x.started_at) === g.day);
        const kwh = sum(whole, 'energy_kwh');
        return h('section', { class: 'a-day', 'aria-label': f.date(g.iso, { dateStyle: 'full' }) },
          h('header', { class: 'a-dayhead' }, h('h2', null, f.dayLabel(g.iso), h('span', { class: 'muted' }, /\d/.test(f.dayLabel(g.iso)) ? ` · ${f.date(g.iso, { year: 'numeric' })}` : ` · ${f.date(g.iso)}`)),
            h('span', { class: 'small muted' }, [f.km(sum(whole, 'distance_km'), 1), whole.some((x) => x.energy_kwh != null) ? f.kwh(kwh) : null, `${whole.length} ${whole.length === 1 ? t('trip') : t('trips')}`].filter(Boolean).join(' · '))),
          h('div', { class: 'card a-rows' }, ...g.items.map(row)));
      }),
      S.shown < S.items.length ? h('div', { class: 'center' }, button(`${t('Load more')} (${S.items.length - S.shown})`, { onClick: () => { S.shown += PAGE; paintBody(); } })) : null);
  }

  function monthView() {
    const [y, m] = S.month.split('-').map(Number);
    const byDay = new Map();
    for (const x of S.items) { const d = f.localDay(x.started_at); const e = byDay.get(d) || { n: 0, km: 0 }; e.n += 1; e.km += x.distance_km || 0; byDay.set(d, e); }
    const first = new Date(y, m - 1, 1);
    const lead = (first.getDay() + 6) % 7;  // Monday first
    const days = new Date(y, m, 0).getDate();
    const maxKm = Math.max(1, ...[...byDay.values()].map((e) => e.km));
    const lang = f.getLang();
    const cells = [];
    for (let i = 0; i < lead; i++) cells.push(h('div', { class: 'a-cell blank', 'aria-hidden': 'true' }));
    for (let d = 1; d <= days; d++) {
      const key = `${S.month}-${pad(d)}`, e = byDay.get(key);
      const label = new Date(y, m - 1, d).toLocaleDateString(lang, { dateStyle: 'medium' });
      if (!e) { cells.push(h('div', { class: 'a-cell' }, h('span', { class: 'a-dnum' }, d))); continue; }
      cells.push(h('button', { type: 'button', class: 'a-cell has', style: { '--a-level': String(Math.max(0.18, e.km / maxKm)) }, title: t('Show this day'),
        'aria-label': `${label}: ${e.n} ${e.n === 1 ? t('trip') : t('trips')}, ${f.km(e.km, 0)}`,
        onclick: () => { S.view = 'list'; S.from = key; S.to = key; from.value = key; to.value = key; drawSeg(); sync(); load(); } },
      h('span', { class: 'a-dnum' }, d), h('span', { class: 'a-km' }, f.num(f.toDist(e.km), 0)), h('span', { class: 'a-unit' }, f.distUnit())));
    }
    const wd = Array.from({ length: 7 }, (_, i) => new Date(2024, 0, 1 + i).toLocaleDateString(lang, { weekday: 'short' }));
    return card(null, h('div', { class: 'stack' },
      h('div', { class: 'row between' },
        button('', { ic: 'left', onClick: () => { S.month = shiftMonth(S.month, -1); sync(); load(); }, title: t('Previous month'), size: 'sm' }),
        h('strong', { 'aria-live': 'polite' }, first.toLocaleDateString(lang, { month: 'long', year: 'numeric' })),
        button('', { ic: 'right', onClick: () => { S.month = shiftMonth(S.month, 1); sync(); load(); }, title: t('Next month'), size: 'sm' })),
      h('div', { class: 'a-cal', role: 'group', 'aria-label': t('Trip calendar') }, ...wd.map((x) => h('div', { class: 'a-wd', 'aria-hidden': 'true' }, x)), ...cells)));
  }

  function paintBody() {
    if (S.error) { mount(body, banner('bad', `${t('Could not load trips')}: ${S.error}`), h('div', null, button(t('Try again'), { onClick: load, ic: 'refresh' }))); return; }
    if (!S.loaded) { mount(body, loading()); return; }
    const cap = S.total > S.items.length ? banner('info', t('Showing the newest {n} of {total} trips. Narrow the filters to see the rest.').replace('{n}', S.items.length).replace('{total}', S.total), ' ', t('Totals cover only the loaded trips.')) : null;
    if (!S.items.length) {
      mount(body, S.view === 'month' ? monthView() : null, empty(t('No trips found'), S.q || S.from || S.to || S.min ? t('Try other filters, or wait for the next drive.') : t('Mate derives trips from the odometer and the car’s parked/driving state.'), 'route'));
      return;
    }
    mount(body, totals(S.items), cap, S.view === 'month' ? monthView() : null, S.view === 'month' ? null : listView(),
      S.view === 'month' ? h('div', { class: 'tiny muted' }, t('Energy is only counted for trips where it is known.')) : null);
  }

  mount(root, h('div', { class: 'row between' }, h('h1', null, t('Trips')), h('div', { class: 'row' }, segBox,
    h('a', { class: 'btn', href: '#/import' }, icon('upload', { size: 16 }), h('span', null, t('Import trips'))), csv)), filters, body);
  await load();
}
