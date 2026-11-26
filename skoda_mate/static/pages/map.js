// Map: where the car parks, where it charged, and trip start/end pairs, with toggleable layers, one circle per place
// and a place list beside the map.
import { h, mount } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { banner, button, card, empty, loading } from '../lib/ui.js';
import { mapView } from '../lib/mapview.js';
import * as f from '../lib/format.js';
import { extendDE, t } from '../i18n.js';

extendDE({
  'Map layers': 'Kartenebenen', 'Parked places': 'Parkplätze', 'Charge locations': 'Ladeorte', 'Trip start and end': 'Fahrtenstart und -ziel', 'Car now': 'Auto jetzt',
  'Places': 'Orte', 'readings while parked': 'Messungen im Stand', 'Show all': 'Alle zeigen', 'Show everything': 'Alles anzeigen', 'Show on map': 'Auf der Karte zeigen',
  'Open place': 'Ort öffnen', 'Visits': 'Besuche', 'Days': 'Tage', 'last seen': 'zuletzt gesehen', 'first seen': 'zuerst gesehen',
  'Nothing to show on the map yet': 'Noch nichts auf der Karte', 'Mate collects places while the car is parked, charging or driving.': 'Mate sammelt Orte, solange das Auto parkt, lädt oder fährt.',
  'Could not load the map data': 'Kartendaten konnten nicht geladen werden', 'Try again': 'Erneut versuchen', 'The car is driving: its position is not reported while moving.': 'Das Auto fährt: Die Position wird während der Fahrt nicht gemeldet.',
  'Dashed lines connect the start and end of a trip. They are straight lines, not the route driven, which the car does not report.': 'Gestrichelte Linien verbinden Start und Ziel einer Fahrt. Es sind Luftlinien, nicht die gefahrene Route, denn diese meldet das Auto nicht.',
  'Places are grouped within about 100 m. The number counts readings taken while parked there, so it grows with parking time, not only with visits.': 'Orte werden im Umkreis von etwa 100 m zusammengefasst. Die Zahl zählt Messungen im Stand an diesem Ort und wächst daher mit der Parkdauer, nicht nur mit der Zahl der Besuche.',
  'Click a circle on the map, or choose the place from the list with the keyboard, to open it.': 'Klicken Sie auf der Karte auf einen Kreis oder wählen Sie den Ort mit der Tastatur in der Liste aus, um ihn zu öffnen.',
  'Home': 'Zuhause', 'trips': 'Fahrten', 'trip': 'Fahrt', 'Charge': 'Ladevorgang', 'Unknown place': 'Unbekannter Ort', 'Start': 'Start', 'End': 'Ende', 'Position reported': 'Position gemeldet',
  'Showing only the newest {n} per layer.': 'Es werden nur die neuesten {n} je Ebene gezeigt.',
  'Showing the newest {n} per layer.': 'Es werden die neuesten {n} je Ebene gezeigt.',
});

const LAYERS = [['parked', 'Parked places', 'a-k1'], ['charges', 'Charge locations', 'a-k3'], ['trips', 'Trip start and end', 'a-k2']];
const key = (lat, lon) => `${lat.toFixed(3)},${lon.toFixed(3)}`;
const ok = (lat, lon) => lat != null && lon != null;
// The demo's home place is stored as the English name; show it in the reader's language like the places page does.
const displayName = (p) => (p.kind === 'home' && p.name === 'Home' ? t('Home') : p.name);

export default async function mapPage(root, ctx) {
  ctx.setTitle(t('Map'));
  mount(root, loading());
  let data = null;
  let placeById = new Map();
  let items = { parked: [], charges: [], trips: [] };
  let parkedMarkers = [];
  const on = { parked: true, charges: true, trips: true };
  let focus = null;  // {layer, i}
  let map = null;
  let layerBox, listBox, capBox;

  const homeCoord = () => (data?.tariff && ok(data.tariff.home_lat, data.tariff.home_lon) ? [data.tariff.home_lat, data.tariff.home_lon] : null);
  const isHome = (lat, lon) => { const hc = homeCoord(); return !!hc && Math.abs(hc[0] - lat) < 0.002 && Math.abs(hc[1] - lon) < 0.002; };

  async function fetchData(nextLimit) {
    const next = await ctx.api.get(`/api/vehicles/${ctx.vid}/map?limit=${nextLimit}&tz_offset=${new Date().getTimezoneOffset()}`);
    data = next;
    build();
  }

  // One place list read from data.places, named on the markers by their place_id, geofence_id or trip endpoints.
  function build() {
    placeById = new Map((data.places || []).map((p) => [p.id, p]));
    const nameOf = (id) => { const p = id != null ? placeById.get(id) : null; return p ? displayName(p) : null; };

    const clusters = (data.parked || []).filter((p) => ok(p.lat, p.lon)).map((p) => {
      const place = p.place_id != null ? placeById.get(p.place_id) : null;
      const where = place ? displayName(place) : p.address ? f.shortPlace(p.address) : t('Unknown place');
      return { lat: p.lat, lon: p.lon, placeId: place ? place.id : null, n: p.n,
        title: where, home: (place && place.kind === 'home') || isHome(p.lat, p.lon),
        sub: `${p.n} ${t('readings while parked')} · ${t('last seen')} ${f.date(p.last_seen)}`,
        label: `${where} · ${p.n} ${t('readings while parked')}` };
    });
    parkedMarkers = clusters.map((c) => ({ lat: c.lat, lon: c.lon, kind: '', label: c.label }));

    // Readings taken while parked there, summed over the rounded clusters that fall inside the place.
    const readings = new Map();
    for (const c of clusters) if (c.placeId != null) readings.set(c.placeId, (readings.get(c.placeId) || 0) + c.n);
    const places = (data.places || []).filter((p) => ok(p.lat, p.lon)).map((p) => ({
      lat: p.lat, lon: p.lon, place: p, placeId: p.id, n: readings.get(p.id) || 0, href: `#/places/${p.id}`,
      title: displayName(p), home: p.kind === 'home',
      sub: `${p.visit_count ?? 0} ${t('Visits')} · ${p.day_count ?? 0} ${t('Days')} · ${t('last seen')} ${p.last_seen ? f.dateTime(p.last_seen) : '–'}`,
    }));
    const unmatched = clusters.filter((c) => c.placeId == null).map((c) => ({ ...c, href: null }));

    items = {
      parked: [...places, ...unmatched],
      charges: (data.charges || []).filter((c) => ok(c.lat, c.lon)).map((c) => {
        const place = c.geofence_id != null ? placeById.get(c.geofence_id) : null;
        const where = place ? displayName(place) : c.address ? f.shortPlace(c.address) : t('Unknown place');
        return { lat: c.lat, lon: c.lon, kind: 'c', href: `#/charges/${c.id}`, title: where, placeId: place ? place.id : null,
          sub: `${f.dateTime(c.started_at)} · ${f.kwh(c.energy_kwh)}${c.charge_type ? ` · ${c.charge_type}` : ''}`,
          label: `${t('Charge')}: ${where} · ${f.kwh(c.energy_kwh)}`, home: isHome(c.lat, c.lon) };
      }),
      trips: [],
    };

    const pairs = new Map();
    for (const x of data.trips || []) {
      if (!ok(x.start_lat, x.start_lon) || !ok(x.end_lat, x.end_lon)) continue;
      const k = `${key(x.start_lat, x.start_lon)}>${key(x.end_lat, x.end_lon)}`;
      const e = pairs.get(k) || { ...x, n: 0, km: 0, last: x.started_at };
      e.n += 1; e.km += x.distance_km || 0; pairs.set(k, e);
    }
    items.trips = [...pairs.values()].map((e) => {
      const from = nameOf(e.start_geofence_id) || (e.start_place ? f.shortPlace(e.start_place) : t('Unknown place'));
      const to = nameOf(e.end_geofence_id) || (e.end_place ? f.shortPlace(e.end_place) : t('Unknown place'));
      const endPlace = e.end_geofence_id != null ? placeById.get(e.end_geofence_id) : null;
      return { lat: e.end_lat, lon: e.end_lon, kind: 'b', line: [[e.start_lat, e.start_lon], [e.end_lat, e.end_lon]], start: [e.start_lat, e.start_lon], n: e.n,
        placeId: endPlace ? endPlace.id : null,
        title: `${from} → ${to}`,
        sub: `${e.n} ${e.n === 1 ? t('trip') : t('trips')} · ${f.km(e.km / e.n, 1)} · ${t('last seen')} ${f.date(e.last)}`,
        label: `${t('End')}: ${to}`, startLabel: `${t('Start')}: ${from}`, href: `#/trips/${e.id}` };
    });
  }

  // R12: a focused item fits only its own place's circle; an item without a place gets none. Without focus, every
  // place keeps its circle. Either way a circle keeps its id and click handler (R8).
  function circles() {
    const all = (data.places || []).filter((p) => ok(p.lat, p.lon)).map((p) => ({ lat: p.lat, lon: p.lon, radius: p.radius_m,
      color: p.color || undefined, label: displayName(p), id: p.id }));
    if (!focus) return all;
    const id = items[focus.layer]?.[focus.i]?.placeId;
    return id == null ? [] : all.filter((c) => c.id === id);
  }

  function pushItem(layer, it, m, lines) {
    if (layer === 'trips') {
      m.push({ lat: it.lat, lon: it.lon, kind: it.kind, label: it.label, noCluster: true });
      lines.push(it.line);
      m.push({ lat: it.start[0], lon: it.start[1], kind: '', label: it.startLabel, noCluster: true });
      return;
    }
    m.push({ lat: it.lat, lon: it.lon, kind: it.kind || '', label: it.label });
  }

  function markers() {
    const m = [], lines = [];
    if (focus) {
      const it = items[focus.layer]?.[focus.i];
      if (it) pushItem(focus.layer, it, m, lines);
    } else {
      for (const [k] of LAYERS) {
        if (!on[k]) continue;
        if (k === 'parked') for (const it of parkedMarkers) m.push({ lat: it.lat, lon: it.lon, kind: '', label: it.label });
        else for (const it of items[k]) pushItem(k, it, m, lines);
      }
    }
    const cur = data.current && ok(data.current.lat, data.current.lon) ? data.current : null;
    if (cur) m.push({ lat: cur.lat, lon: cur.lon, kind: 'd', label: `${t('Car now')}: ${cur.address || ''}`.trim() });
    return { markers: m, lines };
  }

  function paintMap(first) {
    const o = { ...markers(), circles: circles(), dashed: true, zoom: 15,
      onCircleClick: (id) => ctx.nav(`places/${id}`) };  // R8: only a circle with an id is interactive
    if (!map) map = mapView({ height: 'tall', ...o });
    else map.update({ ...o, fit: first || !!focus });
  }

  function drawLayers() {
    mount(layerBox, ...LAYERS.map(([k, label, cls]) => h('button', { type: 'button', class: 'a-fchip a-layer', 'aria-pressed': String(on[k]),
      onclick: () => { on[k] = !on[k]; focus = null; drawLayers(); drawList(); paintMap(); } },
      h('i', { class: ['a-dot', cls] }), `${t(label)} (${items[k].length})`)));
  }

  function bar(it, max) {
    return h('span', { class: 'a-bar', 'aria-hidden': 'true' }, h('i', { style: { width: `${Math.max(4, (it.n / max) * 100)}%` } }));
  }
  // Mark a custom-named home place; when the title is already the localized Home, a second badge would only repeat it.
  const homeChip = (it) => (it.home && it.title !== t('Home') ? h('span', { class: 'chip good a-home' }, icon('home', { size: 12 }), t('Home')) : null);

  function placeRow(it, max) {
    const p = it.place;
    return h('li', null,
      h('a', { class: 'a-linkrow', href: it.href, title: `${t('Open place')}: ${it.title}` },
        h('span', { class: 'a-item-main' },
          h('span', { class: 'row tight' }, h('i', { class: ['a-dot', p.color ? '' : 'a-k1'], style: p.color ? { background: p.color } : null }),
            h('strong', null, it.title), homeChip(it)),
          h('span', { class: 'tiny muted' }, it.sub),
          it.n ? bar(it, max) : null),
        icon('right', { size: 15 })));
  }

  function itemRow(layer, it, i, max) {
    const focused = focus && focus.layer === layer && focus.i === i;
    return h('li', null,
      h('button', { type: 'button', class: ['a-item', focused ? 'sel' : ''], title: t('Show on map'),
        onclick: () => { focus = { layer, i }; drawList(); paintMap(); } },
        h('span', { class: 'a-item-main' }, h('strong', null, it.title), homeChip(it),
          h('span', { class: 'tiny muted' }, it.sub),
          layer === 'parked' && it.n ? bar(it, max) : null)),
      it.href ? h('a', { class: 'a-open', href: it.href, 'aria-label': `${it.title}: ${t('Details')}` }, icon('right', { size: 15 })) : null);
  }

  function drawList() {
    const max = Math.max(1, ...items.parked.map((p) => p.n || 0));
    const sections = LAYERS.filter(([k]) => on[k] && items[k].length).map(([k, label, cls]) => h('section', null,
      h('h3', { class: 'a-lh' }, h('i', { class: ['a-dot', cls] }), t(label)),
      h('ul', { class: 'a-list' }, ...items[k].map((it, i) => (it.place ? placeRow(it, max) : itemRow(k, it, i, max))))));
    mount(listBox,
      focus ? h('div', null, button(t('Show everything'), { onClick: () => { focus = null; drawList(); paintMap(true); }, ic: 'map', size: 'sm' })) : null,
      ...sections,
      h('p', { class: 'tiny muted' }, t('Click a circle on the map, or choose the place from the list with the keyboard, to open it.')),
      h('p', { class: 'tiny muted' }, t('Places are grouped within about 100 m. The number counts readings taken while parked there, so it grows with parking time, not only with visits.')),
      h('p', { class: 'tiny muted' }, t('Dashed lines connect the start and end of a trip. They are straight lines, not the route driven, which the car does not report.')));
  }

  async function showAll() {
    try {
      await fetchData(2000);
      focus = null;
      drawLayers(); drawList(); paintMap(false); drawCap();
    } catch (e) {
      ctx.toast(`${t('Could not load the map data')}: ${e.message}`, 'bad');
    }
  }

  // The endpoint caps every layer at `limit`; the note says so and offers the server's wider limit once. No invented
  // backend cap: the comparison is the returned layer length against the limit the response reports.
  function drawCap() {
    const saturated = ['parked', 'charges', 'trips'].some((k) => (data[k] || []).length >= data.limit);
    if (!saturated) { mount(capBox, null); return; }
    const n = String(data.limit);
    if (data.limit >= 2000) { mount(capBox, h('p', { class: 'tiny muted' }, t('Showing the newest {n} per layer.').replace('{n}', n))); return; }
    mount(capBox, h('div', { class: 'row tight' },
      h('span', { class: 'tiny muted' }, t('Showing only the newest {n} per layer.').replace('{n}', n)),
      button(t('Show all'), { size: 'sm', ic: 'map', onClick: showAll })));
  }

  try {
    await fetchData(1000);
  } catch (e) {
    mount(root, h('h1', null, t('Map')), banner('bad', `${t('Could not load the map data')}: ${e.message}`),
      h('div', null, button(t('Try again'), { onClick: () => mapPage(root, ctx), ic: 'refresh' })));
    return;
  }

  const cur = data.current && ok(data.current.lat, data.current.lon) ? data.current : null;
  const none = !items.parked.length && !items.charges.length && !items.trips.length && !cur;
  if (none) { mount(root, h('h1', null, t('Map')), empty(t('Nothing to show on the map yet'), t('Mate collects places while the car is parked, charging or driving.'), 'map')); return; }
  const motion = ctx.overview?.sections?.position?.state === 'IN_MOTION' && !cur;
  const posLine = cur ? h('div', { class: 'small muted' }, icon('pin', { size: 14 }), ' ', `${t('Car now')}: ${cur.address ? f.shortPlace(cur.address) : `${cur.lat.toFixed(4)}, ${cur.lon.toFixed(4)}`}`, cur.captured_at ? ` · ${t('Position reported')} ${f.ago(cur.captured_at)}` : '') : null;

  layerBox = h('div', { class: 'row tight', role: 'group', 'aria-label': t('Map layers') });
  listBox = h('div', { class: 'stack' });
  capBox = h('div');
  paintMap(true); drawLayers(); drawList(); drawCap();
  mount(root, h('div', { class: 'row between' }, h('h1', null, t('Map')), layerBox), motion ? banner('info', t('The car is driving: its position is not reported while moving.')) : null,
    h('div', { class: 'grid a-mapgrid' }, h('div', { class: 'stack' }, card(null, map, { cls: 'a-mapcard' }), posLine, capBox), card(t('Places'), listBox, { ic: 'pin', cls: 'a-places' })));
}
