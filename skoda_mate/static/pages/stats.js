// Statistics: totals and monthly charts derived by Mate from its own snapshots, trips and charges.
import { h, mount } from '../lib/dom.js';
import { banner, button, card, chip, empty, loading, modal, seg, stat, table } from '../lib/ui.js';
import { icon } from '../lib/icons.js';
import { barChart } from '../lib/charts.js';
import * as f from '../lib/format.js';
import { monthsAgo } from '../lib/dates.js';
import { belowFloor, floorValue, kwhText, medianLossStat } from '../lib/floor.js';
import { renderCharging } from '../lib/insight-charging.js';
import { renderDriving } from '../lib/insight-driving.js';
import { t, tn, N_ } from '../i18n.js';

const TABS = ['overview', 'charging', 'driving', 'parked'];
const PARKED_PAGE = 50;  // stands per page of the Parked table
const INSIGHTS = {
  charging: { render: renderCharging, error: N_('Could not load charging insight') },
  driving: { render: renderDriving, error: N_('Could not load driving insight') },
};

const MI = 0.621371;
const sum = (rows, k) => rows.reduce((a, r) => a + (r[k] || 0), 0);

export default async function stats(root, ctx) {
  ctx.setTitle(t('Statistics'));
  const base = `/api/vehicles/${ctx.vid}`;
  // Per-viewer conveniences: the period and the tab survive navigation; both work without sessionStorage.
  const recall = (key) => { try { return sessionStorage.getItem(key); } catch { return null; } };
  const remember = (key, v) => { try { sessionStorage.setItem(key, v); } catch { /* optional */ } };
  let months = +(recall('b-stats-months') || 12);
  if (![6, 12, 0].includes(months)) months = 12;
  let data = null;
  let tab = TABS.includes(recall('b-stats-tab')) ? recall('b-stats-tab') : 'overview';
  let parked = null;
  let parkedOffset = 0;
  let seq = 0;  // only the newest tab request may draw: a slow 12-month answer must not overwrite 6 months or another tab

  // The tab control stays in every state (loading, error, content): a failing tab never traps the viewer on it.
  const tabBar = () => h('div', { class: 'row', style: { marginBottom: '12px' } }, seg([['overview', t('Overview')], ['charging', t('Charging')], ['driving', t('Driving')], ['parked', t('Parked')]], tab,
    (v) => { tab = v; remember('b-stats-tab', v); show(); }, t('View')));
  const shell = (...body) => mount(root, tabBar(), ...body);
  const fail = (e, message, retry) => shell(h('div', { class: 'card' }, banner('bad', `${message}: ${e.message}`),
    h('div', { style: { marginTop: '12px' } }, button(t('Try again'), { ic: 'refresh', onClick: retry }))));

  // The period control, one for all tabs; `onChange` redraws or reloads the active tab.
  function periodControl(onChange) {
    const period = seg([[6, t('6 months')], [12, t('12 months')], [0, t('all')]], months, (v) => { months = v; remember('b-stats-months', v); onChange(); });
    period.setAttribute('aria-labelledby', 'b-period-label');
    return [h('span', { class: 'small muted', id: 'b-period-label' }, t('Period')), period];
  }

  // The small (i) next to the distance figures: what the number really is, and why it can be incomplete.
  // The intervals are settings: say the ones in use, and where to change them.
  function pollingLine() {
    const iv = ctx.overview?.poller?.interval || {};
    const idle = iv.idle ?? ctx.settings?.poll_idle_s, active = iv.active ?? ctx.settings?.poll_active_s;
    const min = (s) => Math.max(1, Math.round(s / 60));
    return h('span', null,
      idle && active ? t('Mate reads a parked car about every {idle} minutes and a driving or charging car about every {active} minutes, because Škoda allows around 20 requests per hour.').replace('{idle}', min(idle)).replace('{active}', min(active))
        : t('Mate reads the car only every few minutes, because Škoda allows around 20 requests per hour.'), ' ',
      t('A very short trip between two readings can be missed, or is only noticed from the odometer (marked ≈). Shorter intervals catch more, but use more of the request budget.'), ' ',
      h('a', { href: '#/settings' }, t('Change the polling interval')));
  }

  /** What the distance adds up, as one whole sentence per case: with or without a start date and an odometer total. */
  function distanceNote(tt) {
    const v = { distance: f.km(tt.km || 0), date: tt.since ? f.date(tt.since) : null, odometer: tt.odometer_km ? f.km(tt.odometer_km) : null };
    if (v.odometer) {
      return v.date ? t('The distance is the sum of the trips Mate has recorded since {date}: {distance} of the {odometer} the car has driven in total (odometer).', v)
        : t('The distance is the sum of the trips Mate has recorded: {distance} of the {odometer} the car has driven in total (odometer).', v);
    }
    return v.date ? t('The distance is the sum of the trips Mate has recorded since {date}: {distance}.', v)
      : t('The distance is the sum of the trips Mate has recorded: {distance}.', v);
  }

  function distanceInfo() {
    const tt = data?.totals || {};
    const para = (head, ...body) => h('div', null, h('strong', null, head), ...body.map((b) => h('p', { class: 'small', style: { margin: '4px 0 0' } }, b)));
    modal(t('How is the distance calculated?'), h('div', { class: 'stack' },
      para(t('A sum of tracked trips'), distanceNote(tt)),
      para(t('Why it can be incomplete'),
        t('Škoda provides no trip history, so nothing from before Mate started is known unless you import it.'),
        pollingLine(),
        t('Times when Mate was not running, or the API key had expired, leave gaps too.')),
      para(t('It gets more complete over time'),
        t('Everything is saved in Mate’s own database (the data folder), so the history keeps growing the longer Mate runs. Keep that folder, or its backups, to keep your history.')),
      para(t('How to check it'),
        t('The odometer is exact. The “Odometer Δ” column in the monthly table shows what the odometer saw, including drives Mate never caught as a trip.')),
      para(t('Fill the past'), t('Trips from before Mate started can be imported from the MyŠkoda app’s trip export.'))),
    (close) => [h('a', { class: 'btn', href: '#/import', onclick: close }, t('Import trips')), button(t('Close'), { kind: 'primary', onClick: close })]);
  }
  const infoBtn = () => h('button', { class: 'btn ghost sm b-info', type: 'button', title: t('How is the distance calculated?'), 'aria-label': t('How is the distance calculated?'), onclick: distanceInfo }, icon('info', { size: 17 }));

  function totalsFor(rows) {
    // all-time totals come from the server; a shorter period is summed from the monthly rows
    if (months === 0 && data.totals) return { ...data.totals };
    const km = sum(rows, 'km'), kwh = sum(rows, 'charged_kwh'), cost = sum(rows, 'cost'), driven = sum(rows.filter((r) => r.km > 0), 'trip_kwh'), drivenKm = sum(rows.filter((r) => r.km > 0), 'km');
    return { trips: sum(rows, 'trips'), km, charges: sum(rows, 'charges'), charged_kwh: kwh, home_kwh: sum(rows, 'home_kwh'), public_kwh: sum(rows, 'public_kwh'), unknown_place_kwh: sum(rows, 'unknown_place_kwh'),
      inferred_charges: sum(rows, 'inferred_charges'), cost,
      kwh_100km: drivenKm > 0 && driven > 0 ? (driven / drivenKm) * 100 : null, cost_per_100km: km > 0 && cost > 0 ? (cost / km) * 100 : null };
  }

  // The page: the tab control, then the active tab's body. Overview is unchanged apart from the tab control.
  function draw() {
    shell(...(tab === 'parked' ? renderParked() : renderOverview()));
  }

  // Show the active tab. Parked asks only for parked-loss and Overview only for stats, so neither one's failure blocks the other.
  function show() {
    seq++;  // an answer that is still on its way for the tab we left must not draw
    if (tab === 'parked') return firstParkedPage();
    if (INSIGHTS[tab]) return loadInsight();
    if (data) return draw();
    return loadStats();
  }

  const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

  function parkedQuery() {
    const today = new Date(), from = monthsAgo(today, months);
    return new URLSearchParams({ from: months ? isoDay(from) : '1970-01-01', to: isoDay(today), tz_offset: String(today.getTimezoneOffset()),
      limit: String(PARKED_PAGE), offset: String(parkedOffset) });
  }

  // `quiet` keeps the page on screen while another page of the table is fetched.
  async function loadParked({ quiet = false } = {}) {
    const mine = ++seq;
    if (!quiet) shell(loading());
    try {
      const out = await ctx.api.get(`${base}/parked-loss?${parkedQuery()}`);
      if (mine !== seq) return false;
      if (parkedOffset && !out.sessions.length) {  // the history shrank under this page: show the last one there is
        parkedOffset = Math.max(0, Math.ceil(out.total / PARKED_PAGE) - 1) * PARKED_PAGE;
        return loadParked({ quiet });
      }
      parked = out;
      draw();
      return true;
    } catch (e) { if (mine === seq) fail(e, t('Could not load parked loss'), () => loadParked()); }
    return false;
  }

  function firstParkedPage() {
    parkedOffset = 0;
    return loadParked();
  }

  // Redrawing replaces the button that was pressed: put the keyboard back on it, or on its partner at either end.
  async function goParked(offset, pressed) {
    parkedOffset = offset;
    if (!await loadParked({ quiet: true })) return;
    const buttons = [...root.querySelectorAll('.pager button')];
    if (pressed === 'older') buttons.reverse();
    buttons.find((b) => !b.disabled)?.focus({ preventScroll: true });
  }

  function parkedPager() {
    const { total, offset } = parked;
    if (total <= PARKED_PAGE) return null;
    const to = Math.min(offset + PARKED_PAGE, total);
    return h('div', { class: 'pager', role: 'navigation', 'aria-label': t('Pages') },
      button(t('Newer'), { ic: 'left', size: 'sm', disabled: offset <= 0, onClick: () => goParked(Math.max(0, offset - PARKED_PAGE), 'newer') }),
      h('span', { class: 'small muted' }, t('{from}–{to} of {total}', { from: f.num(offset + 1), to: f.num(to), total: f.num(total) })),
      button(`${t('Older')} →`, { size: 'sm', disabled: to >= total, onClick: () => goParked(offset + PARKED_PAGE, 'older') }));
  }

  // Charging and Driving start on the first day of a month, so a period lines up with the rows of the monthly table.
  function insightQuery() {
    const today = new Date(), q = new URLSearchParams({ tz_offset: String(today.getTimezoneOffset()) });
    if (months) {
      q.set('from', isoDay(new Date(today.getFullYear(), today.getMonth() - (months - 1), 1)));
      q.set('to', isoDay(today));
    }
    return q;
  }

  async function loadInsight() {
    const mine = ++seq, kind = tab;
    shell(loading());
    try {
      const out = await ctx.api.get(`${base}/insights/${kind}?${insightQuery()}`);
      if (mine === seq) shell(h('div', { class: 'row' }, ...periodControl(loadInsight)), ...INSIGHTS[kind].render(out));
    } catch (e) { if (mine === seq) fail(e, t(INSIGHTS[kind].error), loadInsight); }
  }

  function renderParked() {
    const header = h('div', { class: 'row' }, ...periodControl(firstParkedPage));
    const cur = ctx.currency, a = parked?.aggregates || {}, rows = parked?.sessions || [];
    if (!parked?.total) return [header, empty(t('No parked sessions'), t('A session needs at least six hours, a charge level at both ends and no charging or driving in between.'), 'clock')];
    const dash = '–';
    const totals = h('div', { class: 'grid auto' },
      card(null, medianLossStat(a.median_kwh_per_day)),
      card(null, stat(t('Parked sessions'), a.count != null ? f.num(a.count) : dash, { ic: 'clock' })),
      // likewise an energy total of exactly zero; null (no stand counted in that window) stays a dash
      card(null, stat(t('Energy'), a.kwh === 0 ? floorValue() : f.kwh(a.kwh), { ic: 'bolt',
        sub: a.kwh_7d != null || a.kwh_30d != null ? `${t('Last 7 days')} ${kwhText(a.kwh_7d)} · ${t('Last 30 days')} ${kwhText(a.kwh_30d)}` : null })),
      card(null, stat(t('Cost'), a.cost != null ? f.money(a.cost, cur) : dash, { ic: 'coin' })));
    const note = h('p', { class: 'small muted' }, t('The charge level is a whole percent, so a loss below one percent is not measurable (below the detection floor).'),
      parked.detection_floor_kwh != null ? ` ${t('One percent is roughly {energy}.', { energy: f.kwh(parked.detection_floor_kwh, 2) })}` : null, ' ',
      t('Costs are estimates. Sessions marked as a likely unrecorded charge are left out of the figures above.'));
    const tbl = table([
      { label: t('Start'), render: (r) => h('div', null, f.dateTime(r.start), r.warning ? h('div', null, chip(t('Likely an unrecorded charge'), 'warn', 'info')) : null), cls: 'nowrap' },
      { label: t('Place'), render: (r) => r.place || dash },
      { label: t('Hours'), render: (r) => f.num(r.hours, 1), num: true },
      { label: t('SoC'), render: (r) => (r.start_soc != null && r.end_soc != null ? `${r.start_soc} → ${r.end_soc} %` : dash), num: true, cls: 'nowrap' },
      // A flagged row (likely an unrecorded charge) is not a loss: no energy, rate or cost is shown for it. A stand below the
      // floor says so once, in the energy column; its rate is a dash, not a second copy of the sentence.
      { label: 'kWh', render: (r) => (r.warning ? dash : r.below_detection_floor ? belowFloor() : f.kwh(r.kwh, 1)), num: true },
      { label: t('kWh/day'), render: (r) => (r.warning || r.below_detection_floor || r.kwh_per_day == null ? dash : f.num(r.kwh_per_day, 1)), num: true },
      { label: t('Cost'), render: (r) => (!r.warning && r.cost != null ? f.money(r.cost, cur) : dash), num: true, cls: 'nowrap' },
    ], rows, { label: t('Parked sessions'), emptyNode: empty(t('No parked sessions')) });
    return [header, totals, card(t('Parked sessions'), h('div', { class: 'stack' }, tbl, parkedPager()), { ic: 'clock' }), note];
  }

  function renderOverview() {
    const cur = data.currency || ctx.currency;
    const all = data.monthly || [];
    const rows = months ? all.slice(-months) : all;
    if (!all.length && !(data.totals?.trips || data.totals?.charges)) {
      return [empty(t('No statistics yet'), t('Statistics appear once Mate has recorded trips and charges.'), 'chart')];
    }
    const tot = totalsFor(rows);
    const knownPlace = (tot.home_kwh || 0) + (tot.public_kwh || 0);  // charges at an unknown place count as neither
    const share = knownPlace > 0 ? (tot.home_kwh / knownPlace) * 100 : null;
    const unit = f.distUnit(), conv = (v) => (f.getUnits() === 'mi' ? v / MI : v), toD = (v) => (f.getUnits() === 'mi' ? v * MI : v);
    const cats = (fn) => rows.map((r) => ({ label: f.monthLabel(r.month), tip: f.monthLabel(r.month), values: fn(r) }));
    const anyGuess = rows.some((r) => r.cost_known === false);

    const header = h('div', { class: 'row between' },
      h('div', { class: 'row' }, ...periodControl(draw)),
      h('div', { class: 'row' },
        h('a', { class: 'btn sm', href: `${base}/export/trips.csv`, download: 'skoda-mate-trips.csv' }, t('Export trips (CSV)')),
        h('a', { class: 'btn sm', href: `${base}/export/charges.csv`, download: 'skoda-mate-charges.csv' }, t('Export charges (CSV)'))));

    const totals = h('div', { class: 'grid auto' },
      // The one distance figure Škoda reports directly: the car's lifetime odometer.
      data.totals?.odometer_km ? card(null, stat(t('Odometer (lifetime)'), f.num(toD(data.totals.odometer_km)), { unit, ic: 'gauge',
        sub: data.totals?.odometer_tracked_km != null && data.totals.odometer_tracked_km > 0
          ? t('{distance} measured by Mate since {date}', { distance: f.km(data.totals.odometer_tracked_km, 0), date: f.date(data.totals.odometer_tracked_since) })
          : t('reported by the car') })) : null,
      card(null, h('div', { class: 'b-has-info' }, infoBtn(), stat(t('Distance'), f.num(toD(tot.km || 0)), { unit, ic: 'route',
        sub: `${tn('{n} trip', '{n} trips', tot.trips || 0)}${months === 0 && data.totals?.since ? ` · ${t('since {date}', { date: f.date(data.totals.since) })}` : ''}` }))),
      card(null, stat(t('Energy charged'), f.num(tot.charged_kwh || 0, 0), { unit: 'kWh', ic: 'bolt',
        sub: `${tn('{n} charge', '{n} charges', tot.charges || 0)}${tot.inferred_charges ? ` · ${tn('{n} inferred', '{n} inferred', tot.inferred_charges)}` : ''}` })),
      card(null, stat(t('Charging cost'), f.money(tot.cost || 0, cur), { ic: 'coin' })),
      card(null, stat(t('Consumption'), tot.kwh_100km != null ? f.num(conv(tot.kwh_100km), 1) : '–', { unit: f.consUnit(), ic: 'gauge' })),
      card(null, stat(`${t('Cost per 100')} ${unit}`, tot.cost_per_100km != null ? f.money(conv(tot.cost_per_100km), cur) : '–', { ic: 'coin' })),
      card(null, stat(t('Home vs public'), share != null ? `${f.num(share, 0)} / ${f.num(100 - share, 0)}` : '–', { unit: share != null ? '%' : null, ic: 'home',
        sub: [share != null ? `${t('Home')} ${f.kwh(tot.home_kwh, 0)} · ${t('Public')} ${f.kwh(tot.public_kwh, 0)}` : null,
          tot.unknown_place_kwh > 0 ? t('{energy} at an unknown place', { energy: f.kwh(tot.unknown_place_kwh, 0) }) : null].filter(Boolean).join(' · ') || null })));
    // Charges can only be called "home" once the home position is known (Charge prices, with a map).
    const needsHome = tot.unknown_place_kwh > 0 && !ctx.overview?.tariff?.home_lat;

    const charts = h('div', { class: 'grid g2' },
      card(`${t('Distance')} (${unit})`, barChart({ categories: cats((r) => [toD(r.km || 0)]), series: [{ name: t('Distance') }], fmt: (v) => f.num(v, 0), height: 210 }), { ic: 'route', actions: infoBtn() }),
      card(`${t('Energy charged')} (kWh)`, barChart({ categories: cats((r) => [r.ac_kwh || 0, r.dc_kwh || 0, r.inferred_kwh || 0]), series: [{ name: t('AC') }, { name: t('DC') }, { name: t('inferred (from battery level)'), color: 'var(--muted)' }], stacked: true, fmt: (v) => f.num(v, 0), height: 210 }), { ic: 'bolt' }),
      card(`${t('Charging cost')} (${cur})`, barChart({ categories: cats((r) => [r.cost || 0]), series: [{ name: t('Charging cost'), color: 'var(--chart-3)' }], fmt: (v) => f.num(v, 0), height: 210 }), { ic: 'coin' }),
      card(`${t('Consumption')} (${f.consUnit()})`, barChart({ categories: cats((r) => [r.kwh_100km != null ? conv(r.kwh_100km) : 0]), series: [{ name: t('Consumption'), color: 'var(--chart-2)' }], fmt: (v) => f.num(v, 1), height: 210 }), { ic: 'gauge' }));

    const tbl = table([
      { label: t('Month'), render: (r) => f.monthLabel(r.month), cls: 'nowrap' },
      { label: t('Trips'), render: (r) => r.trips, num: true },
      { label: `${t('Distance')} (${unit})`, render: (r) => f.num(toD(r.km || 0)), num: true },
      { label: `${t('Odometer')} Δ (${unit})`, render: (r) => (r.odo_km != null ? f.num(toD(r.odo_km), 0) : '–'), num: true },
      { label: t('Consumption'), render: (r) => (r.kwh_100km != null ? f.num(conv(r.kwh_100km), 1) : '–'), num: true },
      { label: `${t('Charged')} (kWh)`, render: (r) => f.num(r.charged_kwh || 0, 1), num: true },
      { label: t('AC'), render: (r) => f.num(r.ac_kwh || 0, 1), num: true },
      { label: t('inferred'), render: (r) => f.num(r.inferred_kwh || 0, 1), num: true },
      { label: t('DC'), render: (r) => f.num(r.dc_kwh || 0, 1), num: true },
      { label: t('Cost'), render: (r) => f.money(r.cost || 0, cur), num: true, cls: 'nowrap' },
    ], [...rows].reverse(), { label: t('Monthly statistics'), emptyNode: empty(t('No statistics yet')) });

    // The odometer counts the car's whole life; Mate only knows the drives since it started tracking.
    const odo = data.totals?.odometer_km, all_km = data.totals?.km || 0;
    const coverage = odo && data.totals?.since && all_km < odo * 0.9
      ? banner('info', t('These statistics cover only what Mate has recorded since {date}: {recorded} of the {odometer} the car has driven in total (odometer). Škoda provides no trip history from before that.', { date: f.date(data.totals.since), recorded: f.km(all_km), odometer: f.km(odo) })) : null;

    const homeHint = needsHome ? banner('info', t('Set your home position to split charges into Home and Public.'), ' ', h('a', { href: '#/prices' }, t('Open charge prices'))) : null;
    return [coverage, homeHint, ctx.overview.needs_capacity ? banner('info', t('Škoda does not report the battery size. Enter it to get energy, consumption and costs.'), ' ', h('a', { href: '#/settings' }, t('Set battery capacity'))) : null,
      header, totals, charts, card(t('Monthly overview'), tbl, { ic: 'calendar' }),
      card(t('How these numbers are made'), h('ul', { class: 'b-notes small' },
        h('li', null, t('Trips are derived by Mate from the odometer and the parked/driving state, not delivered by Škoda.')),
        h('li', null, t('Energy comes from the battery capacity you entered in Settings and the change in charge level (charged: measured at the wall during detected charges).')),
        h('li', null, t('Consumption is the energy used while driving divided by distance, so it is an estimate.')),
        h('li', null, t('Škoda offers no charging history. Charges Mate sees live are measured; charges it did not see are inferred from the battery level rising between trips or readings (marked “inferred”, with estimated energy).')),
        h('li', null, t('Costs use your prices from Charge prices; charges away from your home position count as public.')),
        anyGuess ? h('li', null, chip(t('Some months contain costs that are only a tariff guess.'), 'warn', 'info')) : null), { ic: 'info' })];
  }

  async function loadStats() {
    shell(loading());
    try { data = await ctx.api.get(`${base}/stats`); if (tab === 'overview') draw(); } catch (e) { if (tab === 'overview') fail(e, t('Could not load statistics'), loadStats); }
  }
  await show();
  // A stand counts only after six hours, so the Parked tab is not re-asked every tick (changing the period reloads it);
  // Charging and Driving likewise change only with a new trip or charge. The statistics are refreshed on Overview alone.
  ctx.onTick(async () => {
    if (tab !== 'overview') return;
    try { data = await ctx.api.get(`${base}/stats`); if (tab === 'overview') draw(); } catch { /* keep the current view */ }
  });
}
