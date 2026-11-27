// Trip detail: stats, start/end map (straight line only), editable note, explanations, charges during the trip, prev/next.
import { h, mount } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { asyncButton, banner, button, card, chip, confirmDialog, empty, enableOnChange, field, kv, loading, stat, toast } from '../lib/ui.js';
import { mapView } from '../lib/mapview.js';
import * as f from '../lib/format.js';
import { t } from '../i18n.js';
import { approxChip, APPROX_TIP } from './trips.js';

export default async function trip(root, ctx) {
  const id = +ctx.params[0];
  ctx.setTitle(`${t('Trip')} #${id}`);
  mount(root, loading());
  let x, siblings = [];
  try {
    [x, siblings] = await Promise.all([
      ctx.api.get(`/api/vehicles/${ctx.vid}/trips/${id}`),
      ctx.api.get(`/api/vehicles/${ctx.vid}/trips?limit=500`).then((r) => r.items).catch(() => []),
    ]);
  } catch (e) {
    mount(root, h('div', null, backLink()), e.status === 404 ? empty(t('This trip does not exist'), t('It may have been removed.##trip'), 'route')
      : banner('bad', `${t('Could not load this trip')}: ${e.message}`), e.status === 404 ? null : button(t('Try again'), { onClick: () => trip(root, ctx), ic: 'refresh' }));
    return;
  }

  function backLink() { return h('a', { class: 'a-back', href: '#/trips' }, icon('left', { size: 16 }), t('Back to trips')); }
  const i = siblings.findIndex((s) => s.id === id);
  const newer = i > 0 ? siblings[i - 1] : null, older = i >= 0 ? siblings[i + 1] : null;
  const navBtn = (s, label, ic, right) => s ? h('a', { class: 'btn sm', href: `#/trips/${s.id}`, title: `${label}: ${f.dayLabel(s.started_at)} ${f.time(s.started_at)}` },
    right ? [label, icon(ic, { size: 15 })] : [icon(ic, { size: 15 }), label]) : h('span', { class: 'btn sm a-disabled', 'aria-disabled': 'true' }, right ? [label, icon(ic, { size: 15 })] : [icon(ic, { size: 15 }), label]);

  const approx = !!x.approx;
  const speedBad = x.avg_speed_kmh != null && x.avg_speed_kmh > 250;
  const tilde = approx ? '≈ ' : '';
  const place = (p) => (p ? f.shortPlace(p) : t('Unknown place'));

  // ---- merge: a short stop can split one drive in two; merging is reversible
  const gapH = newer ? (new Date(newer.started_at) - new Date(x.ended_at)) / 36e5 : null;
  const canMerge = newer && x.ended_at && gapH != null && gapH >= -0.05 && gapH <= 6;
  const mergeBox = (canMerge || x.merged_parts > 0) ? h('div', { class: 'row tight' },
    canMerge ? asyncButton(t('Merge with the next trip'), async () => {
      if (!await confirmDialog(t('Merge these trips?'), `${f.shortPlace(x.start_place)} → ${f.shortPlace(x.end_place)} + ${f.shortPlace(newer.start_place)} → ${f.shortPlace(newer.end_place)}. ${t('Distance and energy are added up. You can undo this.')}`, { confirmLabel: t('Merge') })) return;
      await ctx.api.post(`/api/vehicles/${ctx.vid}/trips/merge`, { ids: [x.id, newer.id] });
      toast(t('Trips merged'), 'good'); trip(root, ctx);
    }, { ic: 'route', size: 'sm' }) : null,
    x.merged_parts > 0 ? asyncButton(`${t('Undo merge')} (${x.merged_parts})`, async () => {
      await ctx.api.post(`/api/vehicles/${ctx.vid}/trips/${x.id}/unmerge`);
      toast(t('Merge undone'), 'good'); trip(root, ctx);
    }, { ic: 'refresh', size: 'sm' }) : null) : null;

  // ---- header
  const head = h('div', { class: 'stack' },
    h('div', { class: 'row between' }, backLink(), h('div', { class: 'row tight' }, navBtn(older, t('Older trip'), 'left', false), navBtn(newer, t('Newer trip'), 'right', true))),
    mergeBox,
    h('div', { class: 'a-title' }, h('h1', null, `${place(x.start_place)} → ${place(x.end_place)}`),
      h('div', { class: 'muted' }, `${f.date(x.started_at, { dateStyle: "full" })} · ${tilde}${f.time(x.started_at)} – ${tilde}${f.time(x.ended_at)}`,
        x.open ? ' ' : null, x.open ? chip(t('Driving now'), 'info', 'route') : null, approx ? ' ' : null, approx ? approxChip() : null)));

  // ---- stats
  const cap = ctx.overview?.needs_capacity;
  const stats = h('div', { class: 'grid auto' },
    card(null, stat(t('Distance'), f.num(f.toDist(x.distance_km), 1), { unit: f.distUnit(), ic: 'route', sub: x.odo_start != null && x.odo_end != null ? `${t('Odometer')} ${f.num(f.toDist(x.odo_start), 0)} → ${f.num(f.toDist(x.odo_end), 0)}` : null })),
    card(null, stat(t('Duration'), tilde + f.duration(x.duration_min), { ic: 'clock', sub: approx ? t('estimated') : null })),
    card(null, stat(t('Average speed'), x.avg_speed_kmh != null ? tilde + f.num(f.toDist(x.avg_speed_kmh), 0) : '–', { unit: x.avg_speed_kmh != null ? (f.getUnits() === 'mi' ? 'mph' : 'km/h') : null, ic: 'gauge', sub: speedBad ? t('looks implausible') : null })),
    card(null, stat(t('Energy'), x.energy_kwh != null ? f.num(x.energy_kwh, 1) : '–', { unit: x.energy_kwh != null ? 'kWh' : null, ic: 'bolt', sub: x.energy_kwh != null ? (x.energy_basis === 'fuel' ? t('from fuel level') : t('estimated from battery level')) : t('unknown') })),
    card(null, stat(t('Consumption'), x.avg_kwh_100km != null ? f.num(f.getUnits() === 'mi' ? x.avg_kwh_100km / 0.621371 : x.avg_kwh_100km, 1) : '–', { unit: x.avg_kwh_100km != null ? f.consUnit() : null, ic: 'leaf' })),
    card(null, stat(t('Cost'), x.cost != null ? f.money(x.cost, ctx.currency) : '–', { ic: 'coin', sub: x.cost != null ? t('at home price') : null })),
    card(null, stat(t('Battery start → end'), `${f.pct(x.start_soc)} → ${f.pct(x.end_soc)}`, { ic: 'battery' })));

  // ---- map
  const hasStart = x.start_lat != null && x.start_lon != null, hasEnd = x.end_lat != null && x.end_lon != null;
  const markers = [];
  if (hasStart) markers.push({ lat: x.start_lat, lon: x.start_lon, label: `${t('Start')}: ${x.start_place || ''}`.trim() });
  if (hasEnd) markers.push({ lat: x.end_lat, lon: x.end_lon, kind: 'b', label: `${t('End')}: ${x.end_place || ''}`.trim() });
  // Round trip: the car came back to where it started. Škoda reports only where the car is parked, never the road, so there is nothing to draw.
  const rad = (d) => (d * Math.PI) / 180;
  const gapKm = hasStart && hasEnd ? 6371 * 2 * Math.asin(Math.sqrt(Math.sin(rad(x.end_lat - x.start_lat) / 2) ** 2
    + Math.cos(rad(x.start_lat)) * Math.cos(rad(x.end_lat)) * Math.sin(rad(x.end_lon - x.start_lon) / 2) ** 2)) : null;
  const roundTrip = gapKm != null && gapKm < 0.3 && (x.distance_km ?? 0) >= 1;
  const mapCard = card(t('Route'), markers.length ? h('div', { class: 'stack' },
    roundTrip ? banner('info', h('b', null, t('Round trip')), ': ', t('The trip ended where it started, so the line between start and end is just a point. Škoda only tells Mate where the car is parked, not which roads it took, so the route and any stops on the way cannot be shown. Distance and duration come from the odometer and the parked readings, energy from the change in battery level.')) : null,
    mapView({ height: '', markers, lines: hasStart && hasEnd && !roundTrip ? [[[x.start_lat, x.start_lon], [x.end_lat, x.end_lon]]] : [], dashed: true }),
    h('div', { class: 'small muted a-legend' }, h('span', { class: 'a-key start' }), t('Start'), h('span', { class: 'a-key end' }), t('End'), roundTrip ? null : [' · ', t('Straight line, the car’s route is not available'), '.']))
    : empty(t('No coordinates were recorded for this trip.'), null, 'map'), { ic: 'map' });

  // ---- note
  const ta = h('textarea', { rows: 3, maxlength: 500, placeholder: t('Add a note') }, '');
  ta.value = x.note || '';
  const noteBtn = asyncButton(t('Save note'), async () => { await ctx.api.put(`/api/trips/${id}/note`, { note: ta.value }); x.note = ta.value; resetNote(ta.value); toast(t('Note saved'), 'good'); }, { kind: 'primary', ic: 'check' });
  const resetNote = enableOnChange(noteBtn, ta, ta.value);
  const noteCard = card(t('Note'), h('div', { class: 'stack' }, field(t('Note'), ta),
    noteBtn), { ic: 'edit' });

  // ---- explanations
  const why = [];
  if (approx) why.push(banner('warn', h('b', null, t('Estimated trip')), ': ', t('Mate did not see this trip start or end. It noticed that the odometer had grown between two parked readings, so the start and end times are estimated, and the distance is the odometer difference.')));
  // The idle interval is a setting: say the one in use, and where to change it.
  const idleS = ctx.overview?.poller?.interval?.idle ?? ctx.settings?.poll_idle_s;
  const idleMin = idleS ? Math.max(1, Math.round(idleS / 60)) : null;
  if (roundTrip && (x.distance_km ?? 0) >= 2) why.push(banner('warn', h('b', null, t('May be two trips')), ': ',
    idleMin ? t('Mate reads a parked car about every {n} minutes.').replace('{n}', idleMin) : t('Mate reads a parked car only every few minutes.'), ' ',
    t('A drive to a place and back that fits between two readings is recorded as one trip, with its start estimated from the odometer. The real trip may be two shorter ones, each about half the distance.'), ' ',
    t('A shorter idle interval catches more of these drives, but every reading uses one of the about 20 requests per hour per car.'), ' ',
    h('a', { href: '#/settings' }, t('Change the polling interval'))));
  if (speedBad || (approx && x.distance_km > 1500)) why.push(banner('warn', t('This value looks implausible. Several drives may have been merged, or the odometer jumped.')));
  if (x.energy_kwh == null) {
    why.push(cap ? banner('info', t('Energy is unknown because Škoda does not report the battery size. Enter it in Settings to get energy, consumption and costs.'), ' ', h('a', { href: '#/settings' }, t('Set battery capacity')))
      : banner('info', t('Energy is unknown because the battery level was not reported at the start or end of this trip.')));
  } else {
    why.push(banner('info', x.energy_basis === 'fuel' ? t('Energy comes from the fuel level, not the battery.') : t('Energy is estimated from the change in battery level and your battery capacity. It is not measured.'), ' ', t('Cost = energy × your home price per kWh.')));
  }
  const whyCard = why.length ? card(t('About these numbers'), h('div', { class: 'stack' }, ...why), { ic: 'info' }) : null;

  // ---- charges during the trip
  const during = x.charge_during || [];
  const chargeCard = during.length ? card(t('Charging during this trip'), h('div', { class: 'stack' }, ...during.map((c) =>
    h('a', { class: 'a-linkrow', href: `#/charges/${c.id}` }, icon('plug', { size: 16 }), h('span', null, `${t('Charge')} · ${f.dateTime(c.started_at)}`), h('strong', null, f.kwh(c.energy_kwh)), icon('right', { size: 15 })))), { ic: 'plug' }) : null;

  mount(root, head, stats, h('div', { class: 'grid split' }, mapCard, h('div', { class: 'stack' }, noteCard, whyCard)), chargeCard);
}
