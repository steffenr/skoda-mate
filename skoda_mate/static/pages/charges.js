// Charges: derived charging sessions with totals, filter chips, a pinned running session and CSV export.
import { h, mount } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { banner, button, card, chip, empty, field, loading, stat } from '../lib/ui.js';
import * as f from '../lib/format.js';
import { extendDE, t } from '../i18n.js';
import { setQuery } from './trips.js';

extendDE({
  'Charging during a trip': 'Laden während einer Fahrt', 'Trip to': 'Fahrt nach', 'Trip': 'Fahrt',
  'Time window': 'Zeitfenster', 'At': 'Bei',
  'inferred': 'abgeleitet', 'Not measured live: read off the battery level between two moments. The time window, the type and the energy are estimates.': 'Nicht live gemessen: aus dem Batteriestand zwischen zwei Zeitpunkten abgeleitet. Zeitfenster, Typ und Energie sind Schätzungen.',
  'Sessions': 'Ladevorgänge', 'Energy charged': 'Geladene Energie', 'Home vs public': 'Zuhause vs. öffentlich', 'AC vs DC': 'AC vs. DC', 'Filter charges': 'Ladevorgänge filtern',
  'All': 'Alle', 'No charges found': 'Keine Ladevorgänge gefunden', 'Try other filters.': 'Andere Filter probieren.', 'Charges are detected while the car reports that it is charging.': 'Ladevorgänge werden erkannt, solange das Auto meldet, dass es lädt.',
  'Charging now': 'Lädt gerade', 'Running': 'Läuft', 'live': 'live', 'Place unknown': 'Ort unbekannt', 'guess': 'Schätzung', 'manual': 'manuell',
  'Cost is a guess: the place is unknown, so the home price was used.': 'Die Kosten sind eine Schätzung: Der Ort ist unbekannt, daher wurde der Heimpreis verwendet.',
  'Cost entered by you': 'Von Ihnen eingetragene Kosten', 'Max power': 'Max. Leistung', 'Average power': 'Ø Leistung', 'Battery': 'Batterie', 'Load more': 'Mehr laden',
  'Could not load charges': 'Ladevorgänge konnten nicht geladen werden', 'Try again': 'Erneut versuchen', 'From': 'Von', 'To': 'Bis', 'Export CSV': 'CSV exportieren', 'Reset filters': 'Filter zurücksetzen',
  'Unknown place': 'Unbekannter Ort', 'of': 'von', 'Total cost': 'Gesamtkosten', 'Costs are estimates based on your tariff.': 'Kosten sind Schätzungen auf Basis Ihres Tarifs.',
  'Showing the newest {n} of {total} charges. Narrow the filters to see the rest.': 'Zeigt die neuesten {n} von {total} Ladevorgängen. Mit Filtern lässt sich der Rest eingrenzen.',
  'Place kind unknown': 'Ortsart unbekannt', 'unknown place': 'Ort unbekannt', 'Charging session': 'Ladevorgang',
});

const PAGE = 30;
const sum = (items, fn) => items.reduce((a, x) => a + (+fn(x) || 0), 0);
const FILTERS = [['', 'All'], ['home', 'Home'], ['public', 'Public'], ['AC', 'AC'], ['DC', 'DC']];

/** The Home/Public chip. A guess (unknown place, cost uses the home price) gets dashed styling and says so. */
/** Name and subtitle for a charge. A charge read off a trip export has no charger location: its "address" is the trip's destination. */
export function chargePlace(c) {
  if (c.source === 'import-trip') {
    const dest = (c.address || '').replace(/^Public charging (?:on the way to|during a trip)\s*/i, '').trim();
    return { title: t('Charging during a trip'), sub: dest ? `${t('Trip to')} ${f.shortPlace(dest)}` : null };
  }
  return { title: c.address ? f.shortPlace(c.address) : t('Unknown place'), sub: null };
}

export function placeChip(c) {
  if (c.cost_basis === 'tariff-guess' || c.place_kind_resolved === 'unknown') {
    return h('span', { class: 'chip a-guess', title: t('Cost is a guess: the place is unknown, so the home price was used.') }, icon('pin', { size: 13 }), t('Place unknown'), h('span', { class: 'sr' }, ` (${t('guess')})`));
  }
  return c.place_kind_resolved === 'home' ? chip(t('Home'), 'good', 'home') : chip(t('Public'), 'info', 'building');
}
export const typeChip = (c) => (c.inferred
  // Not measured live: the battery level rose between two moments with no driving in between.
  ? h('span', { class: 'chip info', title: t('Not measured live: read off the battery level between two moments. The time window, the type and the energy are estimates.') },
    icon('info', { size: 13 }), t('inferred'))
  : c.charge_type ? chip(c.charge_type, c.charge_type === 'DC' ? 'warn' : '', 'bolt') : null);

export default async function charges(root, ctx) {
  ctx.setTitle(t('Charges'));
  const q0 = ctx.query;
  const S = { kind: FILTERS.some(([k]) => k === q0.get('kind')) ? q0.get('kind') || '' : '', from: q0.get('from') || '', to: q0.get('to') || '', shown: PAGE, items: [], total: 0, error: null, loaded: false };
  let seq = 0;
  const body = h('div', { class: 'stack' });
  const sync = () => setQuery('charges', { kind: S.kind, from: S.from, to: S.to });

  async function load(silent = false) {
    const my = ++seq;
    S.error = null; if (!silent) { S.loaded = false; paint(); }
    const p = new URLSearchParams({ limit: '500' });
    if (S.from) p.set('from', S.from);
    if (S.to) p.set('to', S.to);
    if (S.kind === 'AC' || S.kind === 'DC') p.set('kind', S.kind);  // home/public are filtered here, see below
    try {
      const r = await ctx.api.get(`/api/vehicles/${ctx.vid}/charges?${p}`);
      if (my !== seq) return;
      // The server applies home/public after paging, which makes its total wrong; filter the loaded set ourselves.
      S.items = S.kind === 'home' || S.kind === 'public' ? r.items.filter((c) => c.place_kind_resolved === S.kind) : r.items;
      S.total = S.kind === 'home' || S.kind === 'public' ? S.items.length : r.total;
      S.fetched = r.items.length; S.serverTotal = r.total;
    } catch (e) { if (my !== seq) return; S.error = e.message || String(e); }
    S.loaded = true; if (!silent) S.shown = PAGE; paint();
  }

  const from = h('input', { type: 'date', value: S.from, onchange: (e) => { S.from = e.target.value; sync(); load(); } });
  const to = h('input', { type: 'date', value: S.to, onchange: (e) => { S.to = e.target.value; sync(); load(); } });
  const chipBox = h('div', { class: 'row tight', role: 'group', 'aria-label': t('Filter charges') });
  const drawChips = () => mount(chipBox, ...FILTERS.map(([k, label]) => h('button', { type: 'button', class: 'a-fchip', 'aria-pressed': String(S.kind === k), onclick: () => { S.kind = k; drawChips(); sync(); load(); } }, t(label))));
  drawChips();
  const csv = h('a', { class: 'btn', href: `/api/vehicles/${ctx.vid}/export/charges.csv`, download: 'skoda-mate-charges.csv' }, icon('download', { size: 16 }), h('span', null, t('Export CSV')));
  const reset = () => { Object.assign(S, { kind: '', from: '', to: '' }); from.value = ''; to.value = ''; drawChips(); sync(); load(); };

  const filters = card(null, h('div', { class: 'stack' }, chipBox, h('div', { class: 'a-filters two' }, field(t('From'), from), field(t('To'), to),
    h('div', { class: 'a-filter-actions' }, button(t('Reset filters'), { onClick: reset, ic: 'x', size: 'sm' })))), { cls: 'flat' });

  function totals(items) {
    const closed = items.filter((c) => !c.open);
    const kwh = sum(items, (c) => c.energy_kwh);
    const by = (fn) => sum(items.filter(fn), (c) => c.energy_kwh);
    const home = by((c) => c.place_kind_resolved === 'home'), pub = by((c) => c.place_kind_resolved === 'public'), unk = kwh - home - pub;
    const ac = by((c) => c.charge_type === 'AC'), dc = by((c) => c.charge_type === 'DC');
    const guess = items.some((c) => c.cost_basis === 'tariff-guess');
    return h('div', { class: 'grid auto a-totals' },
      card(null, stat(t('Sessions'), f.num(S.total), { ic: 'plug', sub: closed.length !== items.length ? `${items.length - closed.length} ${t('Running')}` : null })),
      card(null, stat(t('Energy charged'), f.num(kwh, 1), { unit: 'kWh', ic: 'bolt' })),
      card(null, stat(t('Total cost'), f.money(sum(items, (c) => c.cost), ctx.currency), { ic: 'coin', sub: guess ? t('Costs are estimates based on your tariff.') : null })),
      card(null, stat(t('Home vs public'), `${f.num(home, 0)} / ${f.num(pub, 0)}`, { unit: 'kWh', ic: 'home', sub: unk > 0.05 ? `+ ${f.num(unk, 0)} kWh ${t('unknown place')}` : null })),
      card(null, stat(t('AC vs DC'), `${f.num(ac, 0)} / ${f.num(dc, 0)}`, { unit: 'kWh', ic: 'bolt' })));
  }

  const metric = (k, v) => h('div', null, h('dt', null, k), h('dd', null, v));
  const row = (c) => {
    const guess = c.cost_basis === 'tariff-guess';
    return h('a', { class: ['a-row a-crow', c.open ? 'live' : ''], href: `#/charges/${c.id}` },
      h('div', { class: 'a-time' }, h('strong', null, f.dayLabel(c.started_at)), h('div', { class: 'tiny muted' }, f.time(c.started_at))),
      h('div', { class: 'a-route' }, h('strong', null, chargePlace(c).title), chargePlace(c).sub ? h('div', { class: 'tiny muted' }, chargePlace(c).sub) : null,
        h('div', { class: 'row tight a-chips' }, c.open ? h('span', { class: 'chip good' }, h('i', { class: 'dot good pulse' }), t('Charging now')) : null, typeChip(c), placeChip(c),
          c.cost_basis === 'manual' ? h('span', { class: 'chip', title: t('Cost entered by you') }, icon('edit', { size: 12 }), t('manual')) : null)),
      h('dl', { class: 'a-metrics' },
        metric(t('Energy'), f.kwh(c.energy_kwh)), metric(t('Battery'), f.socText(c)), metric(c.source === 'import-trip' ? t('Trip duration') : c.inferred ? t('Time window') : t('Duration'), c.open ? `${f.duration(c.duration_min)} …` : f.duration(c.duration_min)),
        // an inferred charge has no known power: the window is the parked time, so say what a typical wallbox would have needed
        c.inferred ? metric(`${t('At')} ${f.num(c.typical_wallbox_kw, 0)} kW`, c.hours_at_typical_wallbox != null ? `≈ ${f.duration(c.hours_at_typical_wallbox * 60)}` : '–')
          : metric(t('Average power'), f.kw(c.avg_power_kw)), metric(t('Cost'), c.cost != null ? `${guess ? '≈ ' : ''}${f.money(c.cost, ctx.currency)}` : '–')),
      icon('right', { size: 16 }));
  };

  function paint() {
    if (S.error) { mount(body, banner('bad', `${t('Could not load charges')}: ${S.error}`), h('div', null, button(t('Try again'), { onClick: () => load(), ic: 'refresh' }))); return; }
    if (!S.loaded) { mount(body, loading()); return; }
    if (!S.items.length) { mount(body, empty(t('No charges found'), S.kind || S.from || S.to ? t('Try other filters.') : t('Charges are detected while the car reports that it is charging.'), 'plug')); return; }
    const open = S.items.filter((c) => c.open), rest = S.items.filter((c) => !c.open);
    const visible = rest.slice(0, S.shown);
    const cap = S.serverTotal > S.fetched ? banner('info', t('Showing the newest {n} of {total} charges. Narrow the filters to see the rest.').replace('{n}', S.fetched).replace('{total}', S.serverTotal)) : null;
    mount(body, totals(S.items), cap,
      open.length ? h('div', { class: 'card a-rows a-pinned', 'aria-label': t('Charging now') }, ...open.map(row)) : null,
      visible.length ? h('div', { class: 'card a-rows' }, ...visible.map(row)) : null,
      S.shown < rest.length ? h('div', { class: 'center' }, button(`${t('Load more')} (${rest.length - S.shown})`, { onClick: () => { S.shown += PAGE; paint(); } })) : null);
  }

  mount(root, h('div', { class: 'row between' }, h('h1', null, t('Charges')), csv), filters, body);
  ctx.onTick(() => { if (S.loaded && S.items.some((c) => c.open)) load(true); });
  await load();
}
