// Map: where the car parks, where it charged, and trip start/end pairs, with toggleable layers and a list beside the map.
import { h, mount } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { banner, button, card, empty, loading } from '../lib/ui.js';
import { mapView } from '../lib/mapview.js';
import * as f from '../lib/format.js';
import { extendDE, t } from '../i18n.js';

extendDE({
  'Map layers': 'Kartenebenen', 'Parked places': 'Parkplätze', 'Charge locations': 'Ladeorte', 'Trip start and end': 'Fahrtenstart und -ziel', 'Car now': 'Auto jetzt',
  'Places': 'Orte', 'readings while parked': 'Messungen im Stand', 'Show all': 'Alle zeigen', 'Show on map': 'Auf der Karte zeigen', 'last seen': 'zuletzt gesehen', 'first seen': 'zuerst gesehen',
  'Nothing to show on the map yet': 'Noch nichts auf der Karte', 'Mate collects places while the car is parked, charging or driving.': 'Mate sammelt Orte, solange das Auto parkt, lädt oder fährt.',
  'Could not load the map data': 'Kartendaten konnten nicht geladen werden', 'Try again': 'Erneut versuchen', 'The car is driving: its position is not reported while moving.': 'Das Auto fährt: Die Position wird während der Fahrt nicht gemeldet.',
  'Dashed lines connect the start and end of a trip. They are straight lines, not the route driven, which the car does not report.': 'Gestrichelte Linien verbinden Start und Ziel einer Fahrt. Es sind Luftlinien, nicht die gefahrene Route, denn diese meldet das Auto nicht.',
  'Places are grouped within about 100 m. The number counts readings taken while parked there, so it grows with parking time, not only with visits.': 'Orte werden im Umkreis von etwa 100 m zusammengefasst. Die Zahl zählt Messungen im Stand an diesem Ort und wächst daher mit der Parkdauer, nicht nur mit der Zahl der Besuche.',
  'Home': 'Zuhause', 'trips': 'Fahrten', 'trip': 'Fahrt', 'Charge': 'Ladevorgang', 'Unknown place': 'Unbekannter Ort', 'Start': 'Start', 'End': 'Ende', 'Position reported': 'Position gemeldet',
  'Showing only the newest 300 per layer.': 'Es werden nur die neuesten 300 je Ebene gezeigt.',
});

const LAYERS = [['parked', 'Parked places', 'a-k1'], ['charges', 'Charge locations', 'a-k3'], ['trips', 'Trip start and end', 'a-k2']];
const key = (lat, lon) => `${lat.toFixed(3)},${lon.toFixed(3)}`;
const ok = (lat, lon) => lat != null && lon != null;

export default async function mapPage(root, ctx) {
  ctx.setTitle(t('Map'));
  mount(root, loading());
  let data;
  const body = h('div');
  async function fetchData() {
    try { data = await ctx.api.get(`/api/vehicles/${ctx.vid}/map`); return true; } catch (e) {
      mount(root, h('h1', null, t('Map')), banner('bad', `${t('Could not load the map data')}: ${e.message}`), h('div', null, button(t('Try again'), { onClick: () => mapPage(root, ctx), ic: 'refresh' })));
      return false;
    }
  }
  if (!(await fetchData())) return;

  const on = { parked: true, charges: true, trips: true };
  let focus = null;  // {layer, i}
  let map = null;
  const cur = data.current && ok(data.current.lat, data.current.lon) ? data.current : null;
  const home = data.tariff && ok(data.tariff.home_lat, data.tariff.home_lon) ? [data.tariff.home_lat, data.tariff.home_lon] : null;
  const isHome = (lat, lon) => !!home && Math.abs(home[0] - lat) < 0.002 && Math.abs(home[1] - lon) < 0.002;

  // Plain-text labels only: Leaflet gets DOM text, never markup.
  const items = {
    parked: (data.parked || []).filter((p) => ok(p.lat, p.lon)).map((p) => ({ lat: p.lat, lon: p.lon, kind: '', n: p.n, title: p.address ? f.shortPlace(p.address) : t('Unknown place'),
      sub: `${p.n} ${t('readings while parked')} · ${t('last seen')} ${f.date(p.last_seen)}`, label: `${p.address || t('Unknown place')} · ${p.n} ${t('readings while parked')}`, home: isHome(p.lat, p.lon) })),
    charges: (data.charges || []).filter((c) => ok(c.lat, c.lon)).map((c) => ({ lat: c.lat, lon: c.lon, kind: 'c', href: `#/charges/${c.id}`, title: c.address ? f.shortPlace(c.address) : t('Unknown place'),
      sub: `${f.dateTime(c.started_at)} · ${f.kwh(c.energy_kwh)}${c.charge_type ? ` · ${c.charge_type}` : ''}`, label: `${t('Charge')}: ${c.address || t('Unknown place')} · ${f.kwh(c.energy_kwh)}`, home: isHome(c.lat, c.lon) })),
    trips: [],
  };
  const pairs = new Map();
  for (const x of data.trips || []) {
    if (!ok(x.start_lat, x.start_lon) || !ok(x.end_lat, x.end_lon)) continue;
    const k = `${key(x.start_lat, x.start_lon)}>${key(x.end_lat, x.end_lon)}`;
    const e = pairs.get(k) || { ...x, n: 0, km: 0, last: x.started_at };
    e.n += 1; e.km += x.distance_km || 0; pairs.set(k, e);
  }
  items.trips = [...pairs.values()].map((e) => ({ lat: e.end_lat, lon: e.end_lon, kind: 'b', line: [[e.start_lat, e.start_lon], [e.end_lat, e.end_lon]], start: [e.start_lat, e.start_lon], n: e.n,
    title: `${f.shortPlace(e.start_place)} → ${f.shortPlace(e.end_place)}`, sub: `${e.n} ${e.n === 1 ? t('trip') : t('trips')} · ${f.km(e.km / e.n, 1)} · ${t('last seen')} ${f.date(e.last)}`,
    label: `${t('End')}: ${e.end_place || t('Unknown place')}`, startLabel: `${t('Start')}: ${e.start_place || t('Unknown place')}`, href: `#/trips/${e.id}` }));

  function markers() {
    const m = [], lines = [];
    const only = focus ? [[focus.layer, items[focus.layer][focus.i]]] : LAYERS.filter(([k]) => on[k]).flatMap(([k]) => items[k].map((it) => [k, it]));
    for (const [layer, it] of only) {
      m.push({ lat: it.lat, lon: it.lon, kind: it.kind, label: it.label });
      if (layer === 'trips') { lines.push(it.line); m.push({ lat: it.start[0], lon: it.start[1], kind: '', label: it.startLabel }); }
    }
    if (cur) m.push({ lat: cur.lat, lon: cur.lon, kind: 'd', label: `${t('Car now')}: ${cur.address || ''}`.trim() });
    return { markers: m, lines };
  }

  function paintMap(first) {
    const o = markers();
    if (!map) map = mapView({ height: 'tall', ...o, dashed: true, zoom: 15 });
    else map.update({ ...o, dashed: true, fit: first || !!focus ? true : false, zoom: 15 });
  }

  const layerBox = h('div', { class: 'row tight', role: 'group', 'aria-label': t('Map layers') });
  const drawLayers = () => mount(layerBox, ...LAYERS.map(([k, label, cls]) => h('button', { type: 'button', class: 'a-fchip a-layer', 'aria-pressed': String(on[k]), onclick: () => { on[k] = !on[k]; focus = null; drawLayers(); drawList(); paintMap(); } },
    h('i', { class: ['a-dot', cls] }), `${t(label)} (${items[k].length})`)));

  const listBox = h('div', { class: 'stack' });
  function drawList() {
    const max = Math.max(1, ...items.parked.map((p) => p.n));
    const sections = LAYERS.filter(([k]) => on[k] && items[k].length).map(([k, label, cls]) => h('section', null,
      h('h3', { class: 'a-lh' }, h('i', { class: ['a-dot', cls] }), t(label)),
      h('ul', { class: 'a-list' }, ...items[k].map((it, i) => h('li', null,
        h('button', { type: 'button', class: ['a-item', focus && focus.layer === k && focus.i === i ? 'sel' : ''], title: t('Show on map'), onclick: () => { focus = { layer: k, i }; drawList(); paintMap(); } },
          h('span', { class: 'a-item-main' }, h('strong', null, it.title), it.home ? h('span', { class: 'chip good a-home' }, icon('home', { size: 12 }), t('Home')) : null,
            h('span', { class: 'tiny muted' }, it.sub),
            k === 'parked' ? h('span', { class: 'a-bar', 'aria-hidden': 'true' }, h('i', { style: { width: `${Math.max(4, (it.n / max) * 100)}%` } })) : null)),
        it.href ? h('a', { class: 'a-open', href: it.href, 'aria-label': `${it.title}: ${t('Details')}` }, icon('right', { size: 15 })) : null)))));
    mount(listBox, focus ? h('div', null, button(t('Show all'), { onClick: () => { focus = null; drawList(); paintMap(true); }, ic: 'map', size: 'sm' })) : null,
      ...sections, h('p', { class: 'tiny muted' }, t('Places are grouped within about 100 m. The number counts readings taken while parked there, so it grows with parking time, not only with visits.')),
      h('p', { class: 'tiny muted' }, t('Dashed lines connect the start and end of a trip. They are straight lines, not the route driven, which the car does not report.')));
  }

  const none = !items.parked.length && !items.charges.length && !items.trips.length && !cur;
  if (none) { mount(root, h('h1', null, t('Map')), empty(t('Nothing to show on the map yet'), t('Mate collects places while the car is parked, charging or driving.'), 'map')); return; }
  const motion = ctx.overview?.sections?.position?.state === 'IN_MOTION' && !cur;
  const posLine = cur ? h('div', { class: 'small muted' }, icon('pin', { size: 14 }), ' ', `${t('Car now')}: ${cur.address ? f.shortPlace(cur.address) : `${cur.lat.toFixed(4)}, ${cur.lon.toFixed(4)}`}`, cur.captured_at ? ` · ${t('Position reported')} ${f.ago(cur.captured_at)}` : '') : null;

  paintMap(true); drawLayers(); drawList();
  const total = (data.parked || []).length >= 300 || (data.charges || []).length >= 300 || (data.trips || []).length >= 300;
  mount(root, h('div', { class: 'row between' }, h('h1', null, t('Map')), layerBox), motion ? banner('info', t('The car is driving: its position is not reported while moving.')) : null,
    h('div', { class: 'grid a-mapgrid' }, h('div', { class: 'stack' }, card(null, map, { cls: 'a-mapcard' }), posLine, total ? h('div', { class: 'tiny muted' }, t('Showing only the newest 300 per layer.')) : null), card(t('Places'), listBox, { ic: 'pin', cls: 'a-places' })));
}
