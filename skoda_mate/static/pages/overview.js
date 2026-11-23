// Overview: the car, battery and range, charging, status, climate, position, last trip/charge, SoC history.
import { h, mount } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { asyncButton, card, chip, empty, kv, socBar, stat, toast } from '../lib/ui.js';
import { carView } from '../lib/car.js';
import { lineChart } from '../lib/charts.js';
import { mapView } from '../lib/mapview.js';
import * as f from '../lib/format.js';
import { extendDE, t } from '../i18n.js';
import { estimateNote, liveSoc } from '../lib/livesoc.js';

extendDE({ 'Power': 'Leistung', 'Until': 'Bis', 'Time left': 'Restzeit', 'Done at': 'Fertig um' });

const CHARGE_STATE = {
  CHARGING: ['Charging', 'good'], READY_FOR_CHARGING: ['Plugged in, not charging', 'info'], CONNECT_CABLE: ['Cable not connected', ''],
  CONSERVING: ['Conserving (battery care)', 'info'], DISCHARGING: ['Discharging', 'warn'], CHARGING_INTERRUPTED: ['Charging interrupted', 'warn'],
};

const CLIMATE_STATE = { COOLING: 'Cooling', HEATING: 'Heating', HEATING_AUXILIARY: 'Heating (auxiliary heater)', VENTILATION: 'Ventilation' };

export default async function overview(root, ctx) {
  ctx.setTitle(t('Overview'));
  let map = null;

  const state = (o) => {
    const s = o.snapshot || {};
    if (!s.recorded_at) return null;  // the DB column; `ts` only exists inside the poller
    return s;
  };

  async function draw() {
    const o = ctx.overview;
    const s = state(o);
    if (!s) { mount(root, empty(t('No reading yet'), t('Mate is asking Škoda for the first time. This takes a moment.'), 'refresh')); return; }
    const ch = o.sections.charging, st = o.sections.status, cl = o.sections.climate, pos = o.sections.position, fuel = o.sections.fuel;
    const hasBattery = o.parts.charging?.available;
    const history = await ctx.api.get(`/api/vehicles/${ctx.vid}/history?hours=48`).catch(() => []);
    const cs = CHARGE_STATE[s.charge_state];

    // --- hero: car + battery
    // Charging is shown once: state line, then power / time left / done at. Nothing repeats the battery number or limit.
    const showLimit = s.target_soc != null && s.target_soc > 0;
    const togo = s.charging && showLimit && s.soc != null && s.soc < s.target_soc;
    const typeLabel = s.charge_type && s.charge_type !== 'OFF' ? s.charge_type : null;
    const figs = s.charging ? [
      s.charge_power_kw != null ? [f.kw(s.charge_power_kw), t('Power'), false] : null,
      s.remaining_min != null ? [f.duration(s.remaining_min), showLimit ? `${t('Until')} ${Math.round(s.target_soc)} %` : t('Time left'), true] : null,
      ch?.fully_charged_at ? [f.time(ch.fully_charged_at), t('Done at'), false] : null,
    ].filter(Boolean) : [];
    const live = hasBattery ? liveSoc(s, o.vehicle?.capacity_kwh) : null;
    const shownSoc = live ? live.soc : s.soc;
    const estNote = estimateNote(live, s);
    const batteryCol = h('div', { class: 'stack' },
      hasBattery ? h('div', null,
        h('div', { class: 'stat' }, h('div', { class: 'label' }, icon('battery', { size: 15 }), t('Battery')),
          h('div', { class: 'row-base' },
            h('div', { class: 'value', style: { fontSize: '44px', marginTop: 0 } }, shownSoc != null ? `${live ? '≈ ' : ''}${Math.round(shownSoc)}` : '–', h('small', null, '%')),
            s.range_km != null ? h('span', { class: 'range' }, `${f.km(s.range_km)} ${t('range')}`) : null), estNote),
        socBar(shownSoc, s.target_soc, { togo: togo && shownSoc < s.target_soc }),
        showLimit ? h('div', { class: 'limit-lbl' }, h('span', { class: s.target_soc > 88 ? 'end' : '', style: s.target_soc > 88 ? null : { left: `${s.target_soc}%` } }, `${t('Charge limit')} ${Math.round(s.target_soc)} %`)) : null) : null,
      fuel ? h('div', null, stat(t('Fuel'), s.fuel_pct != null ? `${Math.round(s.fuel_pct)}` : '–', { unit: '%', ic: 'gauge', sub: s.fuel_range_km != null ? `${f.km(s.fuel_range_km)} ${t('range')}` : null })) : null,
      hasBattery && cs && s.charging ? h('div', { class: 'status-line' }, icon('bolt', { size: 16 }), t(cs[0]), typeLabel ? [h('span', { class: 'sep' }, '·'), h('span', { class: 'meta' }, typeLabel)] : null)
        : hasBattery && cs ? h('div', { class: 'row' }, chip(t(cs[0]), cs[1], 'plug'), typeLabel ? chip(typeLabel, '') : null) : null,
      figs.length ? h('div', { class: 'figs', style: { gridTemplateColumns: `repeat(${figs.length}, minmax(0, 1fr))` } },
        ...figs.map(([n, l, lead]) => h('div', { class: ['fig', lead ? 'lead' : ''] }, h('span', { class: 'n' }, n), h('span', { class: 'l' }, l)))) : null,
      !hasBattery && !fuel ? h('div', { class: 'muted' }, t('No battery or fuel data reported by this car.')) : null);
    const hero = card(null, h('div', { class: 'grid g2', style: { alignItems: 'center' } }, carView(o), batteryCol), { cls: 'hero' });

    // --- stat row
    const stats = h('div', { class: 'grid auto' },
      card(null, stat(t('Odometer'), s.mileage_km != null ? f.num(f.toDist(s.mileage_km)) : '–', { unit: f.distUnit(), ic: 'gauge', sub: o.sections.info?.license_plate })),
      card(null, stat(t('Climate'), cl ? (cl.running ? t(CLIMATE_STATE[cl.state] || 'Running') : t('Off')) : '–', {
        ic: 'thermo', sub: cl ? `${t('target')} ${f.temp(cl.target?.value ?? s.climate_target)}${cl.reach_at && cl.running ? ` · ${t('ready')} ${f.time(cl.reach_at)}` : ''}` : o.parts.airConditioning?.reason })),
      card(null, stat(t('Plug'), s.plug_connected == null ? '–' : s.plug_connected ? t('Connected') : t('Not connected'), {
        ic: 'plug', sub: s.plug_locked == null ? null : s.plug_locked ? t('cable locked') : t('cable unlocked') })));

    // --- position
    const place = pos?.state === 'IN_MOTION' ? t('Driving: the position is not reported while moving') : f.shortPlace(pos?.address);
    const markers = pos?.lat != null ? [{ lat: pos.lat, lon: pos.lon, label: pos.address || t('Parked here') }] : [];
    if (!map && markers.length) map = mapView({ height: 'short', markers, zoom: 15 });
    else if (map && markers.length) map.update({ markers });
    const posCard = card(t('Position'), h('div', { class: 'stack' }, markers.length ? map : empty(t('No position'), place, 'pin'),
      markers.length ? h('div', { class: 'small' }, icon('pin', { size: 14 }), ' ', place) : null,
      pos?.captured_at ? h('div', { class: 'tiny muted' }, `${t('reported')} ${f.ago(pos.captured_at)}`) : null), { ic: 'pin' });

    // --- last trip / charge
    const lt = o.last_trip, lc = o.last_charge, ot = o.open_trip;
    const tripCard = card(t('Last trip'), ot ? h('div', { class: 'stack' }, chip(t('Driving now'), 'info', 'route'), h('div', { class: 'small muted' }, `${t('since')} ${f.time(ot.started_at)} · ${f.shortPlace(ot.start_place)}`))
      : lt ? h('a', { href: `#/trips/${lt.id}`, style: { color: 'inherit', textDecoration: 'none' } }, h('div', { class: 'stack' },
        h('div', null, h('strong', null, `${f.shortPlace(lt.start_place)} → ${f.shortPlace(lt.end_place)}`), h('div', { class: 'small muted' }, `${f.dayLabel(lt.started_at)}, ${f.time(lt.started_at)}`)),
        kv([[t('Distance'), f.km(lt.distance_km, 1)], [t('Duration'), f.duration(lt.duration_min)], [t('Energy'), f.kwh(lt.energy_kwh)], [t('Consumption'), f.cons(lt.avg_kwh_100km)]])))
        : empty(t('No trips yet'), t('Mate derives trips from the odometer and the car’s parked/driving state.'), 'route'), { ic: 'route' });
    const chargeCard = card(t('Last charge'), lc ? h('a', { href: `#/charges/${lc.id}`, style: { color: 'inherit', textDecoration: 'none' } }, h('div', { class: 'stack' },
      h('div', null, h('strong', null, `${lc.open ? t('Charging now') : f.kwh(lc.energy_kwh)} ${lc.charge_type ? `· ${lc.charge_type}` : ''}`), h('div', { class: 'small muted' }, `${f.dayLabel(lc.started_at)}, ${f.time(lc.started_at)}`)),
      kv([[t('Battery'), `${f.pct(lc.start_soc)} → ${f.pct(lc.end_soc)}`], [t('Duration'), f.duration(lc.duration_min)], [t('Max power'), f.kw(lc.max_power_kw)],
        [t('Cost'), lc.cost != null ? f.money(lc.cost, ctx.currency) : '–']])))
      : empty(t('No charges yet'), t('Charges are detected while the car reports that it is charging.'), 'plug'), { ic: 'plug' });

    // --- history chart
    const chart = card(t('Battery, last 48 hours'), history.length > 1 ? lineChart({
      height: 210, yLeft: { min: 0, max: 100, fmt: (v) => `${v}%` }, yRight: { min: 0, fmt: (v) => `${v} kW` },
      series: [{ name: t('Battery'), data: history.map((p) => ({ x: p.t, y: p.soc })), area: true, fmt: (v) => f.pct(v) },
        // the power line (and its axis) only appears when the car actually charged in this window
        ...(history.some((p) => p.charging && p.p > 0) ? [{ name: t('Charging power'), data: history.map((p) => ({ x: p.t, y: p.charging ? p.p : 0 })), axis: 'right', color: 'var(--chart-3)', step: true, fmt: (v) => f.kw(v) }] : [])],
    }) : empty(t('Not enough readings yet'), t('The chart fills in as Mate reads the car.'), 'trend'), { ic: 'trend' });

    // --- quick controls
    const feat = o.features, call = (name, params) => async () => {
      const r = await ctx.api.post(`/api/vehicles/${ctx.vid}/command`, { name, params });
      if (r.ok) { toast(t('Sent. The car confirms on the next reading.'), 'good'); await ctx.refresh(); } else toast(r.error, 'bad');
    };
    const quick = [];
    const unplugged = s.plug_connected === false;
    const aux = ['HEATING_AUXILIARY', 'VENTILATION'].includes(cl?.state);
    const climateOn = !!cl?.running && !aux, ventOn = !!cl?.running && cl?.state === 'VENTILATION';
    // one toggle per function; Start is disabled (with the reason in its tooltip) when the car cannot do it right now
    if (feat.charge_control?.available) quick.push(s.charging ? asyncButton(t('Stop charging'), call('stop_charging'), { ic: 'stop', kind: 'danger' })
      : asyncButton(t('Start charging'), call('start_charging'), { ic: 'play', kind: 'primary', disabled: unplugged, title: unplugged ? t('Plug in the car to start charging.') : undefined }));
    if (feat.climate?.available) quick.push(climateOn ? asyncButton(t('Stop climate'), call('stop_climate'), { ic: 'x', kind: 'danger' })
      : asyncButton(`${t('Start climate')} ${f.num(cl?.target?.value ?? 21, 1)} °C`, call('start_climate', { temperature: cl?.target?.value ?? 21, without_external_power: unplugged }), { ic: 'thermo' }));
    if (feat.ventilation?.available) quick.push(ventOn ? asyncButton(t('Stop ventilation'), call('stop_ventilation'), { ic: 'x', kind: 'danger' }) : asyncButton(t('Start ventilation'), call('start_ventilation'), { ic: 'fan' }));
    const unpluggedHint = unplugged && feat.charge_control?.available ? h('div', { class: 'small muted' }, icon('info', { size: 14 }), ' ', t('Plug in the car to start charging.')) : null;
    const controls = card(t('Quick controls'), h('div', { class: 'stack' }, h('div', { class: 'row' }, ...quick), unpluggedHint,
      h('div', { class: 'tiny muted' }, t('Škoda confirms commands with a short delay. More options under Control.'))), { ic: 'sliders' });

    mount(root, hero, stats, h('div', { class: 'grid split' }, chart, quick.length ? controls : posCard),
      h('div', { class: 'grid g3' }, quick.length ? posCard : null, tripCard, chargeCard));
  }

  await draw();
  ctx.onTick(draw);
}
