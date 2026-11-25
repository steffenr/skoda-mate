// Statistics: totals and monthly charts derived by Mate from its own snapshots, trips and charges.
import { h, mount } from '../lib/dom.js';
import { banner, button, card, chip, empty, loading, modal, seg, stat, table } from '../lib/ui.js';
import { icon } from '../lib/icons.js';
import { barChart } from '../lib/charts.js';
import * as f from '../lib/format.js';
import { extendDE, t } from '../i18n.js';

extendDE({
  'Statistics': 'Statistik', 'Period': 'Zeitraum', 'Last 6 months': 'Letzte 6 Monate', 'Last 12 months': 'Letzte 12 Monate', 'All': 'Alle',
  '6 months': '6 Monate', '12 months': '12 Monate', 'all': 'alle',
  'Distance': 'Strecke', 'Trips': 'Fahrten', 'Energy charged': 'Geladene Energie', 'Charging cost': 'Ladekosten', 'Consumption': 'Verbrauch',
  'Cost per 100': 'Kosten pro 100', 'Home vs public': 'Zuhause vs. öffentlich', 'Home': 'Zuhause', 'Public': 'Öffentlich', 'AC': 'AC', 'DC': 'DC',
  'Monthly overview': 'Monatsübersicht', 'Month': 'Monat', 'Driven': 'Gefahren', 'Charged': 'Geladen', 'Cost': 'Kosten', 'Charges': 'Ladevorgänge',
  'Export': 'Export', 'Export trips (CSV)': 'Fahrten exportieren (CSV)', 'Export charges (CSV)': 'Ladevorgänge exportieren (CSV)',
  'No statistics yet': 'Noch keine Statistik', 'Statistics appear once Mate has recorded trips and charges.': 'Die Statistik erscheint, sobald Mate Fahrten und Ladevorgänge aufgezeichnet hat.',
  'How these numbers are made': 'Wie diese Zahlen entstehen',
  'Trips are derived by Mate from the odometer and the parked/driving state, not delivered by Škoda.': 'Fahrten leitet Mate aus Kilometerstand und Park-/Fahrzustand ab, Škoda liefert sie nicht.',
  'Energy comes from the battery capacity you entered in Settings and the change in charge level (charged: measured at the wall during detected charges).': 'Energie ergibt sich aus der in den Einstellungen eingetragenen Batteriekapazität und der Änderung des Ladestands (geladen: am Netz gemessen bei erkannten Ladevorgängen).',
  'Costs use your tariff from Settings; charges away from your home position count as public.': 'Kosten nutzen deinen Tarif aus den Einstellungen; Ladevorgänge außerhalb deiner Heimposition zählen als öffentlich.',
  'Consumption is the energy used while driving divided by distance, so it is an estimate.': 'Der Verbrauch ist die beim Fahren genutzte Energie geteilt durch die Strecke, also eine Schätzung.',
  'Some months contain costs that are only a tariff guess.': 'Manche Monate enthalten Kosten, die nur eine Tarifschätzung sind.',
  'Škoda does not report the battery size. Enter it to get energy, consumption and costs.': 'Škoda meldet die Batteriegröße nicht. Trage sie ein, um Energie, Verbrauch und Kosten zu erhalten.',
  'Set battery capacity': 'Batteriekapazität eintragen', 'Could not load statistics': 'Statistik konnte nicht geladen werden', 'Try again': 'Erneut versuchen',
  'Share of energy': 'Anteil der Energie', 'since': 'seit', 'Odometer': 'Kilometerstand',
  'Škoda offers no charging history. Charges Mate sees live are measured; charges it did not see are inferred from the battery level rising between trips or readings (marked “inferred”, with estimated energy).':
    'Škoda bietet keinen Ladeverlauf. Ladevorgänge, die Mate live sieht, sind gemessen; solche, die es nicht gesehen hat, werden aus dem steigenden Batteriestand zwischen Fahrten oder Messungen abgeleitet (als „abgeleitet“ markiert, Energie geschätzt).',
  'How is the distance calculated?': 'Wie wird die Strecke berechnet?', 'A sum of tracked trips': 'Eine Summe aufgezeichneter Fahrten',
  'The distance is the sum of the trips Mate has recorded': 'Die Strecke ist die Summe der Fahrten, die Mate aufgezeichnet hat',
  'the car has driven in total (odometer).': 'das Auto insgesamt gefahren ist (Kilometerstand).',
  'Why it can be incomplete': 'Warum sie unvollständig sein kann',
  'Škoda provides no trip history, so nothing from before Mate started is known unless you import it.': 'Škoda liefert keinen Fahrtenverlauf, daher ist nichts aus der Zeit vor Mates Start bekannt, außer du importierst es.',
  'Mate reads a parked car about every {idle} minutes and a driving or charging car about every {active} minutes, because Škoda allows around 20 requests per hour.': 'Mate liest ein geparktes Auto etwa alle {idle} Minuten aus und ein fahrendes oder ladendes etwa alle {active} Minuten, weil Škoda rund 20 Anfragen pro Stunde erlaubt.',
  'Mate reads the car only every few minutes, because Škoda allows around 20 requests per hour.': 'Mate liest das Auto nur alle paar Minuten aus, weil Škoda rund 20 Anfragen pro Stunde erlaubt.',
  'A very short trip between two readings can be missed, or is only noticed from the odometer (marked ≈). Shorter intervals catch more, but use more of the request budget.': 'Eine sehr kurze Fahrt zwischen zwei Messungen kann verpasst oder nur am Kilometerstand bemerkt werden (mit ≈ markiert). Kürzere Intervalle erkennen mehr, verbrauchen aber mehr vom Anfragebudget.',
  'Change the polling interval': 'Abfrageintervall ändern',
  'Times when Mate was not running, or the API key had expired, leave gaps too.': 'Auch Zeiten, in denen Mate nicht lief oder der API-Schlüssel abgelaufen war, hinterlassen Lücken.',
  'It gets more complete over time': 'Mit der Zeit wird sie vollständiger',
  'Everything is saved in Mate’s own database (the data folder), so the history keeps growing the longer Mate runs. Keep that folder, or its backups, to keep your history.': 'Alles wird in Mates eigener Datenbank gespeichert (Ordner „data“), die Historie wächst also, je länger Mate läuft. Behalte diesen Ordner oder seine Backups, um deine Historie zu behalten.',
  'How to check it': 'So prüfst du sie', 'The odometer is exact. The “Odometer Δ” column in the monthly table shows what the odometer saw, including drives Mate never caught as a trip.': 'Der Kilometerstand ist exakt. Die Spalte „Kilometerstand Δ“ in der Monatstabelle zeigt, was der Kilometerstand gesehen hat, auch Fahrten, die Mate nie als Fahrt erfasst hat.',
  'Fill the past': 'Die Vergangenheit auffüllen', 'Trips from before Mate started can be imported from the MyŠkoda app’s trip export.': 'Fahrten aus der Zeit vor Mates Start können aus dem Fahrten-Export der MyŠkoda-App importiert werden.',
  'Import trips': 'Fahrten importieren',
  'at an unknown place': 'an unbekanntem Ort', 'Set your home position to split charges into Home and Public.': 'Lege deine Heimposition fest, um Ladevorgänge in „Zuhause“ und „Öffentlich“ zu trennen.', 'Open Settings': 'Einstellungen öffnen',
  'inferred': 'abgeleitet', 'inferred (from battery level)': 'abgeleitet (aus dem Batteriestand)',
  'Odometer (lifetime)': 'Kilometerstand (gesamt)', 'measured by Mate since': 'von Mate gemessen seit', 'reported by the car': 'vom Auto gemeldet',
  'These statistics cover only what Mate has recorded since':'Diese Statistik umfasst nur, was Mate seit dem', 'of the': 'von den',
  'the car has driven in total (odometer). Škoda provides no trip history from before that.': 'insgesamt gefahrenen (Kilometerstand) erfasst hat. Škoda liefert keine Fahrten aus der Zeit davor.',
});

const MI = 0.621371;
const sum = (rows, k) => rows.reduce((a, r) => a + (r[k] || 0), 0);

export default async function stats(root, ctx) {
  ctx.setTitle(t('Statistics'));
  const base = `/api/vehicles/${ctx.vid}`;
  let months = +(sessionStorage.getItem('b-stats-months') || 12);
  if (![6, 12, 0].includes(months)) months = 12;
  let data = null;

  const fail = (e) => mount(root, h('div', { class: 'card' }, banner('bad', `${t('Could not load statistics')}: ${e.message}`),
    h('div', { style: { marginTop: '12px' } }, button(t('Try again'), { ic: 'refresh', onClick: load }))));

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

  function distanceInfo() {
    const tt = data?.totals || {};
    const para = (head, ...body) => h('div', null, h('strong', null, head), ...body.map((b) => h('p', { class: 'small', style: { margin: '4px 0 0' } }, b)));
    modal(t('How is the distance calculated?'), h('div', { class: 'stack' },
      para(t('A sum of tracked trips'), `${t('The distance is the sum of the trips Mate has recorded')}${tt.since ? ` ${t('since')} ${f.date(tt.since)}` : ''}: ${f.km(tt.km || 0)}${tt.odometer_km ? ` ${t('of the')} ${f.km(tt.odometer_km)} ${t('the car has driven in total (odometer).')}` : '.'}`),
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

  function draw() {
    const cur = data.currency || ctx.currency;
    const all = data.monthly || [];
    const rows = months ? all.slice(-months) : all;
    if (!all.length && !(data.totals?.trips || data.totals?.charges)) {
      mount(root, empty(t('No statistics yet'), t('Statistics appear once Mate has recorded trips and charges.'), 'chart'));
      return;
    }
    const tot = totalsFor(rows);
    const knownPlace = (tot.home_kwh || 0) + (tot.public_kwh || 0);  // charges at an unknown place count as neither
    const share = knownPlace > 0 ? (tot.home_kwh / knownPlace) * 100 : null;
    const unit = f.distUnit(), conv = (v) => (f.getUnits() === 'mi' ? v / MI : v), toD = (v) => (f.getUnits() === 'mi' ? v * MI : v);
    const cats = (fn) => rows.map((r) => ({ label: f.monthLabel(r.month), tip: f.monthLabel(r.month), values: fn(r) }));
    const anyGuess = rows.some((r) => r.cost_known === false);

    const period = seg([[6, t('6 months')], [12, t('12 months')], [0, t('all')]], months, (v) => { months = v; try { sessionStorage.setItem('b-stats-months', v); } catch { /* optional */ } draw(); });
    period.setAttribute('aria-labelledby', 'b-period-label');
    const header = h('div', { class: 'row between' },
      h('div', { class: 'row' }, h('span', { class: 'small muted', id: 'b-period-label' }, t('Period')), period),
      h('div', { class: 'row' },
        h('a', { class: 'btn sm', href: `${base}/export/trips.csv`, download: 'skoda-mate-trips.csv' }, t('Export trips (CSV)')),
        h('a', { class: 'btn sm', href: `${base}/export/charges.csv`, download: 'skoda-mate-charges.csv' }, t('Export charges (CSV)'))));

    const totals = h('div', { class: 'grid auto' },
      // The one distance figure Škoda reports directly: the car's lifetime odometer.
      data.totals?.odometer_km ? card(null, stat(t('Odometer (lifetime)'), f.num(toD(data.totals.odometer_km)), { unit, ic: 'gauge',
        sub: data.totals?.odometer_tracked_km != null && data.totals.odometer_tracked_km > 0
          ? `${f.km(data.totals.odometer_tracked_km, 0)} ${t('measured by Mate since')} ${f.date(data.totals.odometer_tracked_since)}`
          : t('reported by the car') })) : null,
      card(null, h('div', { class: 'b-has-info' }, infoBtn(), stat(t('Distance'), f.num(toD(tot.km || 0)), { unit, ic: 'route',
        sub: `${tot.trips || 0} ${t('Trips').toLowerCase()}${months === 0 && data.totals?.since ? ` · ${t('since')} ${f.date(data.totals.since)}` : ''}` }))),
      card(null, stat(t('Energy charged'), f.num(tot.charged_kwh || 0, 0), { unit: 'kWh', ic: 'bolt',
        sub: `${tot.charges || 0} ${t('Charges').toLowerCase()}${tot.inferred_charges ? ` · ${tot.inferred_charges} ${t('inferred')}` : ''}` })),
      card(null, stat(t('Charging cost'), f.money(tot.cost || 0, cur), { ic: 'coin' })),
      card(null, stat(t('Consumption'), tot.kwh_100km != null ? f.num(conv(tot.kwh_100km), 1) : '–', { unit: f.consUnit(), ic: 'gauge' })),
      card(null, stat(`${t('Cost per 100')} ${unit}`, tot.cost_per_100km != null ? f.money(conv(tot.cost_per_100km), cur) : '–', { ic: 'coin' })),
      card(null, stat(t('Home vs public'), share != null ? `${f.num(share, 0)} / ${f.num(100 - share, 0)}` : '–', { unit: share != null ? '%' : null, ic: 'home',
        sub: [share != null ? `${t('Home')} ${f.kwh(tot.home_kwh, 0)} · ${t('Public')} ${f.kwh(tot.public_kwh, 0)}` : null,
          tot.unknown_place_kwh > 0 ? `${f.kwh(tot.unknown_place_kwh, 0)} ${t('at an unknown place')}` : null].filter(Boolean).join(' · ') || null })));
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
      ? banner('info', `${t('These statistics cover only what Mate has recorded since')} ${f.date(data.totals.since)}: ${f.km(all_km)} ${t('of the')} ${f.km(odo)} ${t('the car has driven in total (odometer). Škoda provides no trip history from before that.')}`) : null;

    const homeHint = needsHome ? banner('info', t('Set your home position to split charges into Home and Public.'), ' ', h('a', { href: '#/prices' }, t('Open charge prices'))) : null;
    mount(root, coverage, homeHint, ctx.overview.needs_capacity ? banner('info', t('Škoda does not report the battery size. Enter it to get energy, consumption and costs.'), ' ', h('a', { href: '#/settings' }, t('Set battery capacity'))) : null,
      header, totals, charts, card(t('Monthly overview'), tbl, { ic: 'calendar' }),
      card(t('How these numbers are made'), h('ul', { class: 'b-notes small' },
        h('li', null, t('Trips are derived by Mate from the odometer and the parked/driving state, not delivered by Škoda.')),
        h('li', null, t('Energy comes from the battery capacity you entered in Settings and the change in charge level (charged: measured at the wall during detected charges).')),
        h('li', null, t('Consumption is the energy used while driving divided by distance, so it is an estimate.')),
        h('li', null, t('Škoda offers no charging history. Charges Mate sees live are measured; charges it did not see are inferred from the battery level rising between trips or readings (marked “inferred”, with estimated energy).')),
        h('li', null, t('Costs use your prices from Charge prices; charges away from your home position count as public.')),
        anyGuess ? h('li', null, chip(t('Some months contain costs that are only a tariff guess.'), 'warn', 'info')) : null), { ic: 'info' }));
  }

  async function load() {
    mount(root, loading());
    try { data = await ctx.api.get(`${base}/stats`); draw(); } catch (e) { fail(e); }
  }
  await load();
  ctx.onTick(async () => { try { data = await ctx.api.get(`${base}/stats`); draw(); } catch { /* keep the current view */ } });
}
