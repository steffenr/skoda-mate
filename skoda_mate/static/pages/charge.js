// Charge detail: stats, charging curve, cost basis with controls (Home/Public/Auto, manual cost, note), delivered vs battery.
import { h, mount } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { asyncButton, banner, button, card, chip, empty, enableOnChange, field, loading, seg, stat, toast } from '../lib/ui.js';
import { lineChart } from '../lib/charts.js';
import { mapView } from '../lib/mapview.js';
import * as f from '../lib/format.js';
import { t } from '../i18n.js';
import { chargePlace, placeChip, typeChip } from './charges.js';

// The demo's home place is stored as the English name; show it in the reader's language like the map and places pages.
const displayName = (p) => (p.kind === 'home' && p.name === 'Home' ? t('Home') : p.name);
const R = 6371000;
const dist = (a, b, c, d) => {
  const rad = Math.PI / 180, dLat = (c - a) * rad, dLon = (d - b) * rad;
  const x = Math.sin(dLat / 2) ** 2 + Math.cos(a * rad) * Math.cos(c * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
};

export default async function charge(root, ctx) {
  const id = +ctx.params[0];
  ctx.setTitle(`${t('Charge')} #${id}`);
  mount(root, loading());
  const base = `/api/vehicles/${ctx.vid}/charges/${id}`;
  let c;
  const back = () => h('a', { class: 'a-back', href: '#/charges' }, icon('left', { size: 16 }), t('Back to charges'));

  async function fetchIt() {
    try { c = await ctx.api.get(base); } catch (e) {
      mount(root, back(), e.status === 404 ? empty(t('This charge does not exist'), t('It may have been removed.'), 'plug')
        : banner('bad', `${t('Could not load this charge')}: ${e.message}`), e.status === 404 ? null : button(t('Try again'), { onClick: () => charge(root, ctx), ic: 'refresh' }));
      return false;
    }
    return true;
  }
  if (!(await fetchIt())) return;

  const patch = async (body, okMsg) => { c = await ctx.api.patch(base, body); if (okMsg) toast(okMsg, 'good'); draw(); };

  function costBlock() {
    const tar = ctx.overview?.tariff || {};
    const basis = c.cost_basis;
    const kind = c.place_kind_resolved;
    let explain;
    if (basis === 'manual') explain = banner('info', t('Cost entered by you. It replaces the calculation.'));
    else if (basis === 'tariff-guess') explain = banner('warn', t('Cost is a guess: the place is unknown, so the home price was used. Choose Home or Public, or tell Mate where home is.'));
    else if (basis === 'place') explain = banner('info', t('Cost uses the price of this place.'));
    else if (basis === 'tariff') {
      const price = kind === 'home' ? [tar.home_kwh, t('home price')] : c.charge_type === 'DC' ? [tar.public_dc_kwh, t('public DC price')] : [tar.public_ac_kwh, t('public AC price')];
      explain = banner('info', `${t('Calculated: delivered energy × your price')}: ${f.kwh(c.energy_kwh)} × ${price[0] != null ? f.money(price[0], ctx.currency, 3) : '–'} ${t('per kWh')} (${price[1]}).`);
    } else explain = banner('info', t('No cost: the delivered energy is unknown.'));

    const placeSeg = seg([['', t('Auto')], ['home', t('Home')], ['public', t('Public')]], c.place_kind || '', async (v) => {
      try { await patch({ place_kind: v }, t('Place saved')); } catch (e) { toast(e.message, 'bad'); draw(); }
    });
    const amount = h('input', { type: 'number', min: 0, max: 10000, step: '0.01', inputmode: 'decimal', value: c.cost_manual != null ? String(c.cost_manual) : '', placeholder: ctx.currency });
    const setCost = asyncButton(t('Set cost'), async () => {
      const v = parseFloat(amount.value);
      if (!Number.isFinite(v) || v < 0 || v > 10000) { toast(t('Enter a valid amount'), 'bad'); return; }
      await patch({ cost_manual: v }, t('Cost saved'));
    }, { kind: 'primary', ic: 'check' });
    setCost.disabled = amount.value.trim() === ''; amount.addEventListener('input', () => { setCost.disabled = amount.value.trim() === ''; });  // no amount, nothing to set
    const clearCost = c.cost_manual != null ? asyncButton(t('Clear manual cost'), () => patch({ clear_cost: true }, t('Manual cost removed')), { ic: 'x' }) : null;
    // The place a charge is linked to, with the same detail link the map uses.
    const placeLink = c.place ? h('div', { class: 'small' }, icon('pin', { size: 14 }), ' ',
      h('a', { href: `#/places/${c.place.id}` }, displayName(c.place) || t('Unknown place'))) : null;
    return card(t('Cost'), h('div', { class: 'stack' },
      h('div', { class: 'a-bigcost' }, c.cost != null ? `${basis === 'tariff-guess' ? '≈ ' : ''}${f.money(c.cost, ctx.currency)}` : '–'), explain, placeLink,
      h('div', null, h('div', { class: 'a-label' }, t('Where was this charged?')), placeSeg, h('div', { class: 'tiny muted', style: { marginTop: '4px' } }, t('Auto uses your home place from Charge prices.'))),
      field(`${t('Total cost (manual)')} (${ctx.currency})`, amount), h('div', { class: 'row' }, setCost, clearCost)), { ic: 'coin' });
  }

  function homeBlock() {
    if (c.place_kind_resolved !== 'unknown') return null;
    const known = c.lat != null && c.lon != null;
    const btn = asyncButton(t('This is where home is'), async () => { await ctx.api.post(`/api/vehicles/${ctx.vid}/home-here?charge_id=${c.id}`); toast(t('Home position saved'), 'good'); await ctx.refresh(); if (await fetchIt()) draw(); }, { ic: 'home', kind: 'primary', disabled: !known });
    return card(t('Home is not set for this place'), h('div', { class: 'stack' }, h('p', { class: 'small muted' }, t('Use the location of this charge as your home. Charges within the home radius then count as Home.')),
      btn, known ? null : h('div', { class: 'tiny muted' }, t('This charge has no known location.'))), { ic: 'home' });
  }

  function lossBlock() {
    if (c.energy_battery_kwh == null || c.energy_kwh == null) return null;
    const d = c.energy_kwh - c.energy_battery_kwh;
    const eff = c.energy_kwh > 0 ? (c.energy_battery_kwh / c.energy_kwh) * 100 : null;
    return card(t('Delivered vs into the battery'), h('div', { class: 'stack' },
      h('div', { class: 'grid g3' }, stat(t('Delivered (from the grid)'), f.num(c.energy_kwh, 1), { unit: 'kWh' }), stat(t('Into the battery'), f.num(c.energy_battery_kwh, 1), { unit: 'kWh' }),
        stat(t('Difference'), `${d >= 0 ? '' : '−'}${f.num(Math.abs(d), 1)}`, { unit: 'kWh', sub: d > 0 && eff != null ? `${t('efficiency')} ${f.num(eff, 0)} %` : null })),
      d < 0 ? banner('warn', t('Delivered energy is lower than the energy into the battery. That cannot be real: the power readings were too far apart to integrate well. Treat both numbers as rough estimates.'))
        : h('p', { class: 'small muted' }, t('The difference is charging loss (heat in the charger, cable and car), usually 5 to 15 %. Both values are estimates: delivered energy is integrated from the power readings, battery energy from the change in battery level and your battery capacity.'))), { ic: 'bolt' });
  }

  function draw() {
    const curve = c.curve || [], gaps = c.curve_gaps || [];
    const place = chargePlace(c), placeName = place.title, fromTrip = c.source === 'import-trip';
    const about = c.end_estimated ? '≈ ' : '';  // Mate saw no reading when it ended (issue #8)
    const head = h('div', { class: 'stack' }, back(),
      h('div', { class: 'a-title' }, h('h1', null, placeName), h('div', { class: 'muted' }, `${f.date(c.started_at, { dateStyle: "full" })} · ${fromTrip ? `${t('Trip')} ` : ''}${f.time(c.started_at)} – ${c.open ? '…' : `${about}${f.time(c.ended_at)}`}`),
        place.sub ? h('div', { class: 'small muted' }, place.sub) : null,
        h('div', { class: 'row tight', style: { marginTop: '6px' } }, c.open ? h('span', { class: 'chip good' }, h('i', { class: 'dot good pulse' }), t('Charging now')) : null, typeChip(c), placeChip(c))));
    const stats = h('div', { class: 'grid auto' },
      card(null, stat(t('Delivered energy'), c.energy_kwh != null ? f.num(c.energy_kwh, 1) : '–', { unit: c.energy_kwh != null ? 'kWh' : null, ic: 'bolt' })),
      card(null, stat(t('Battery start → end'), f.socText(c), { ic: 'battery', sub: c.target_soc != null ? `${t('Charge target')} ${f.pct(c.target_soc)}` : null })),
      card(null, stat(c.source === 'import-trip' ? t('Trip duration') : c.inferred ? t('Time window') : t('Duration'), c.open ? `${f.duration(c.duration_min)} …` : `${about}${f.duration(c.duration_min)}`,
        { ic: 'clock', sub: c.inferred ? (c.source === 'import-trip' ? t('the duration of the trip; charging happened somewhere during it') : t('the car stood here; charging happened somewhere in it'))
          : c.end_estimated ? t('end estimated') : null })),
      ...(c.inferred
        // Not measured: dividing the energy by the whole parked window would give a meaningless "average power".
        ? [card(null, stat(t('Charging power'), t('unknown'), { ic: 'gauge',
          sub: c.hours_at_typical_wallbox != null ? `${t('At')} ${f.num(c.typical_wallbox_kw, 0)} kW ${t('this takes about')} ${f.duration(c.hours_at_typical_wallbox * 60)}` : null }))]
        : [card(null, stat(t('Average power'), f.num(c.avg_power_kw, 1), { unit: c.avg_power_kw != null ? 'kW' : null, ic: 'gauge' })),
          card(null, stat(t('Max power'), f.num(c.max_power_kw, 1), { unit: c.max_power_kw != null ? 'kW' : null, ic: 'gauge' }))]));

    const chart = card(t('Charging curve'), curve.filter((p) => p.soc != null).length > 1 ? h('div', { class: 'stack' }, lineChart({
      height: 240, yLeft: { min: 0, max: 100, fmt: (v) => `${v}%` }, yRight: { min: 0, fmt: (v) => `${v} kW` }, gaps,
      series: [{ name: t('Battery'), data: curve.map((p) => ({ x: p.t, y: p.soc })), area: true, fmt: (v) => f.pct(v, 1) },
        { name: t('Charging power'), data: curve.map((p) => ({ x: p.t, y: p.p })), axis: 'right', color: 'var(--chart-3)', fmt: (v) => f.kw(v) }],
    }), h('div', { class: 'tiny muted' }, t('The curve is drawn from the readings Mate took during this session (a few minutes apart). It is not a continuous measurement, so short peaks can be missing.'),
      gaps.length ? ` ${t('Shaded: Mate has no readings from this time, so no line is drawn there.')}` : null,
      c.end_estimated ? ` ${t('Mate had no reading when the charge ended, so the end time is estimated from the last reading before it and the rise in battery level after it.')}` : null))
      : empty(t('Not enough readings for a curve'), t('Mate needs at least two readings during the session.'), 'trend'), { ic: 'trend' });

    const note = h('textarea', { rows: 3, maxlength: 500, placeholder: t('Add a note') }); note.value = c.note || '';
    const noteBtn = asyncButton(t('Save note'), async () => { await patch({ note: note.value }, t('Note saved')); resetNote(note.value); }, { ic: 'check' });
    const resetNote = enableOnChange(noteBtn, note, note.value);
    const noteCard = card(t('Note'), h('div', { class: 'stack' }, field(t('Note'), note),
      noteBtn), { ic: 'edit' });
    const tr = c.trip_route;
    const loc = c.lat != null
      ? card(t('Location'), h('div', { class: 'stack' }, mapView({ height: '', markers: [{ lat: c.lat, lon: c.lon, label: c.address || '' }], zoom: 16 }),
        c.address ? h('div', { class: 'small' }, icon('pin', { size: 14 }), ' ', c.address) : null), { ic: 'pin' })
      : tr ? card(t('Where it happened'), h('div', { class: 'stack' },
        mapView({ height: '', markers: [{ lat: tr.start_lat, lon: tr.start_lon, label: tr.start_place || t('Start') }, { lat: tr.end_lat, lon: tr.end_lon, kind: 'b', label: tr.end_place || t('End') }],
          lines: [[[tr.start_lat, tr.start_lon], [tr.end_lat, tr.end_lon]]], dashed: true }),
        h('div', { class: 'small muted' }, t('The export does not say where the charger was. It was somewhere on this trip (straight line between start and end).')),
        h('a', { href: `#/trips/${tr.id}` }, t('Open the trip'))), { ic: 'pin' }) : null;

    const tripNote = fromTrip ? banner('info', h('b', null, t('Read from a trip export.')), ' ',
      t('Charging happened somewhere during this trip. The export only says how much the battery level rose and how much energy that is, not where the car charged, the levels before and after, the power or the charger type. The times are the start and end of the trip, and the place shown is the trip destination. Charges Mate sees live include all of these.')) : null;
    const reasonText = { before_recording: t('Why: this happened before Mate started recording your car, so it had no readings from this time. Škoda’s API only reports the charge type (AC/DC) and power while the car is charging, and has no charging history to ask afterwards.'),
      no_polls: t('Why: Mate took no readings during this time (it was not running or could not reach Škoda), so it never saw the car charging. Škoda’s API reports the charge type (AC/DC) and power only while the car is charging.'),
      not_charging: t('Why: Mate took readings during this time, but none of them showed the car charging (the charge was probably shorter than the polling interval). Škoda’s API reports the charge type (AC/DC) and power only while the car is charging.') }[c.inferred_reason];
    const inferredNote = c.inferred && !fromTrip ? banner('info', h('b', null, t('Inferred charge.')), ' ',
      reasonText ? h('span', null, reasonText, ' ') : null,
      t('Mate did not see this charge happen. The battery level rose from the first to the second moment shown, with no driving in between, so the car must have been charged then. Read the time as “somewhere between”, the energy as the level change times your battery capacity (divided by a typical efficiency for the wall figure), and the type as unknown. A charge that Mate sees live is measured exactly and replaces an inferred one.')) : null;
    // the map comes first on the right: it was easy to miss at the bottom
    mount(root, head, tripNote || inferredNote, stats, chart, h('div', { class: 'grid split' }, h('div', { class: 'stack' }, costBlock(), c.inferred ? null : lossBlock()), h('div', { class: 'stack' }, loc, homeBlock(), noteCard)));
  }

  draw();
  ctx.onTick(async () => {
    const a = document.activeElement;
    if (a && root.contains(a) && ['INPUT', 'TEXTAREA'].includes(a.tagName)) return;  // do not wipe what the user is typing
    if (c.open) { try { c = await ctx.api.get(base); draw(); } catch { /* keep the last view */ } } });
}
