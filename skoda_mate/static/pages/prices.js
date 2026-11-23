// Charge prices: what a kWh costs (home, public AC, public DC) and where "home" is. One page, one save bar.
// Data: GET/PUT /api/settings { tariff: { currency, home_kwh, public_ac_kwh, public_dc_kwh, home_lat, home_lon, home_radius_m } }.
import { h, mount } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { asyncButton, banner, button, card, chip, field, toast } from '../lib/ui.js';
import { mapView } from '../lib/mapview.js';
import * as f from '../lib/format.js';
import { extendDE, t } from '../i18n.js';
import '../de_backend.js';

extendDE({
  'Prices': 'Preise', 'Charge prices': 'Ladepreise', 'Set what each kWh costs, so Mate can price your charges.': 'Lege fest, was jede kWh kostet, damit Mate deine Ladevorgänge bewerten kann.',
  'Prices per kWh': 'Preise pro kWh', 'Currency': 'Währung', 'Home': 'Zuhause', 'Public AC': 'Öffentlich AC', 'Public DC': 'Öffentlich DC',
  'Wallbox or home socket': 'Wallbox oder Haushaltssteckdose', 'Public AC charging stations (up to 22 kW)': 'Öffentliche AC-Ladesäulen (bis 22 kW)', 'DC fast chargers': 'DC-Schnelllader',
  'Default': 'Standard', 'Empty uses the default price': 'Leer verwendet den Standardpreis', 'Example': 'Beispiel', 'per kWh': 'pro kWh',
  'Changes recalculate the cost of every charge and trip without a manual price, including past ones. A price you set by hand on a charge always wins.': 'Änderungen berechnen die Kosten aller Ladevorgänge und Fahrten ohne manuellen Preis neu, auch vergangene. Ein von Hand gesetzter Preis bei einem Ladevorgang gilt immer.',
  'Home place': 'Heimatort', 'Charges within the radius of this position count as home charges.': 'Ladevorgänge innerhalb des Radius dieser Position zählen als Laden zuhause.',
  'Unsaved changes': 'Ungespeicherte Änderungen', 'All changes saved': 'Alle Änderungen gespeichert', 'Discard': 'Verwerfen', 'Save prices': 'Preise speichern', 'Prices saved': 'Preise gespeichert',
  'Changes discarded': 'Änderungen verworfen', 'Pin moved to your position. Press “Save prices” to keep it.': 'Pin an deine Position verschoben. Drücke „Preise speichern“, um ihn zu behalten.',
  'Click the map to place your home, drag the pin, or use the locate button (top left) to use this device’s position.': 'Klicke auf die Karte, um dein Zuhause zu setzen, ziehe den Pin oder nutze die Ortungstaste (oben links), um die Position dieses Geräts zu verwenden.',
  'Home pin removed. Press “Save prices” to keep it.': 'Heim-Pin entfernt. Drücke „Preise speichern“, um es zu behalten.',
  'Could not load the prices': 'Preise konnten nicht geladen werden', 'Latitude': 'Breitengrad', 'Longitude': 'Längengrad', 'Radius (metres)': 'Radius (Meter)',
  'Use current parking position': 'Aktuelle Parkposition verwenden', 'Clear home position': 'Heimposition löschen', 'Home position saved': 'Heimposition gespeichert', 'Not set': 'Nicht gesetzt',
  'The car is parked here': 'Das Auto steht hier', 'Could not get your position': 'Position konnte nicht ermittelt werden', 'This needs your permission and an https:// or localhost address.': 'Dafür brauchst du die Erlaubnis und eine https://- oder localhost-Adresse.',
  'Currency must be a short code such as EUR.': 'Die Währung muss ein kurzer Code wie EUR sein.', 'Prices must be between 0 and 10 per kWh.': 'Preise müssen zwischen 0 und 10 pro kWh liegen.',
  'Enter both latitude and longitude, or leave both empty.': 'Gib Breiten- und Längengrad an oder lasse beide leer.', 'Latitude must be between -90 and 90.': 'Der Breitengrad muss zwischen -90 und 90 liegen.',
  'Longitude must be between -180 and 180.': 'Der Längengrad muss zwischen -180 und 180 liegen.', 'Radius must be between 20 and 5000 metres.': 'Der Radius muss zwischen 20 und 5000 Metern liegen.',
});

const DEFAULTS = { home: 0.30, ac: 0.55, dc: 0.79 };
const ROWS = [
  { key: 'home', ic: 'home', tone: 'good', title: 'Home', sub: 'Wallbox or home socket' },
  { key: 'ac', ic: 'plug', tone: 'info', title: 'Public AC', sub: 'Public AC charging stations (up to 22 kW)' },
  { key: 'dc', ic: 'bolt', tone: 'warn', title: 'Public DC', sub: 'DC fast chargers' },
];
const EXAMPLE_KWH = 30;
const num = (v) => (v === '' || v == null || Number.isNaN(Number(v)) ? null : Number(v));
const fail = (msg) => { throw new Error(msg); };

/** The currency symbol for an ISO code in the current language ("€"), or the code itself. */
function symbolOf(code) {
  try { return new Intl.NumberFormat(f.getLocale?.() || undefined, { style: 'currency', currency: code }).formatToParts(0).find((p) => p.type === 'currency')?.value || code; } catch { return code; }
}

export default async function prices(root, ctx) {
  ctx.setTitle(t('Charge prices'));
  let S;
  try { S = await ctx.api.get('/api/settings'); } catch (e) { mount(root, banner('bad', `${t('Could not load the prices')}: ${e.message}`)); return; }
  const tf = S.tariff || {};
  const fromTariff = (x) => ({ currency: x.currency || 'EUR', home: x.home_kwh ?? '', ac: x.public_ac_kwh ?? '', dc: x.public_dc_kwh ?? '', lat: x.home_lat ?? '', lon: x.home_lon ?? '', radius: x.home_radius_m ?? 150 });
  let saved = fromTariff(tf);
  const d = { ...saved };
  const els = {};
  let map = null;

  // ---- save bar (a single place to save and discard; disabled while there is nothing to save)
  const dirty = () => JSON.stringify(d) !== JSON.stringify(saved);
  const status = h('span', { class: 'pr-status' });
  let saveBtn, discardBtn;
  const syncBar = () => {
    const isDirty = dirty();
    status.className = `pr-status ${isDirty ? 'dirty' : ''}`;
    mount(status, h('i', { class: ['dot', isDirty ? 'warn' : 'good'] }), t(isDirty ? 'Unsaved changes' : 'All changes saved'));
    if (saveBtn) saveBtn.disabled = !isDirty;
    if (discardBtn) discardBtn.disabled = !isDirty;
  };

  // ---- price rows
  const examples = {};
  const sym = () => symbolOf(String(d.currency).trim().toUpperCase() || 'EUR');
  const money = (v) => f.money(v, String(d.currency).trim().toUpperCase() || 'EUR');
  const effective = (k) => (num(d[k]) != null ? num(d[k]) : DEFAULTS[k]);
  const syncExamples = () => {
    for (const r of ROWS) {
      if (!examples[r.key]) continue;
      examples[r.key].textContent = `${t('Example')}: ${EXAMPLE_KWH} kWh = ${money(EXAMPLE_KWH * effective(r.key))}${num(d[r.key]) == null ? ` · ${t('Empty uses the default price')}` : ''}`;
    }
    document.querySelectorAll('.pr-sym').forEach((e) => { e.textContent = sym(); });
  };
  const priceRow = (r) => {
    els[r.key] = h('input', { type: 'number', min: 0, max: 10, step: 0.01, inputmode: 'decimal', placeholder: f.num(DEFAULTS[r.key], 2), value: d[r.key], 'aria-label': `${t(r.title)} — ${t('Prices per kWh')}`,
      oninput: (e) => { d[r.key] = e.target.value; syncExamples(); syncBar(); } });
    examples[r.key] = h('div', { class: 'tiny muted pr-example' });
    return h('div', { class: `pr-row ${r.tone}` },
      h('div', { class: 'pr-ic' }, icon(r.ic, { size: 22 })),
      h('div', { class: 'pr-text' }, h('strong', null, t(r.title)), h('div', { class: 'small muted' }, t(r.sub)), examples[r.key]),
      h('label', { class: 'pr-input' }, h('span', { class: 'pr-sym' }, sym()), els[r.key], h('span', { class: 'pr-unit' }, `/ kWh`)));
  };
  els.currency = h('input', { type: 'text', maxlength: 4, autocomplete: 'off', value: d.currency, oninput: (e) => { d.currency = e.target.value; syncExamples(); syncBar(); } });

  const pricesCard = card(t('Prices per kWh'), h('div', { class: 'stack' },
    h('div', { class: 'pr-currency' }, field(t('Currency'), els.currency)),
    h('div', { class: 'pr-rows' }, ...ROWS.map(priceRow))), { ic: 'coin' });

  // ---- home place
  const validPoint = () => d.lat !== '' && d.lon !== '' && Math.abs(num(d.lat)) <= 90 && Math.abs(num(d.lon)) <= 180;
  const radiusM = () => { const r = num(d.radius); return r >= 20 && r <= 5000 ? r : 150; };
  const carPos = ctx.overview?.sections?.position;
  const mapState = () => (validPoint()
    ? { markers: [{ lat: num(d.lat), lon: num(d.lon), draggable: true, onDrag: pick, label: t('Home') }], circle: { lat: num(d.lat), lon: num(d.lon), radius: radiusM() } }
    : { markers: carPos?.lat != null ? [{ lat: carPos.lat, lon: carPos.lon, kind: 'b', label: t('The car is parked here') }] : [], circle: null });
  const homeChip = h('div', { class: 'row' });
  const syncHome = () => mount(homeChip, validPoint() ? chip(`${f.num(num(d.lat), 5)}, ${f.num(num(d.lon), 5)}`, 'good', 'home') : chip(t('Not set'), '', 'home'));
  function pick(lat, lon) {
    d.lat = lat.toFixed(6); d.lon = lon.toFixed(6);
    els.lat.value = d.lat; els.lon.value = d.lon;
    map?.update({ ...mapState(), fit: false }); syncHome(); syncBar();
  }
  const coord = (key, props) => {
    els[key] = h('input', { ...props, value: d[key], oninput: (e) => { d[key] = e.target.value; map?.update({ ...mapState(), fit: false }); syncHome(); syncBar(); } });
    return els[key];
  };
  map = mapView({
    height: '', zoom: 16, onPick: pick, ...mapState(), locate: true,
    onLocate: (lat, lon) => { pick(lat, lon); map.map?.flyTo([lat, lon], 17); toast(t('Pin moved to your position. Press “Save prices” to keep it.'), 'good'); },
    onLocateError: (msg) => toast(`${t('Could not get your position')}: ${msg}. ${t('This needs your permission and an https:// or localhost address.')}`, 'bad'),
  });
  const placeCard = card(t('Home place'), h('div', { class: 'stack' },
    h('div', { class: 'small muted' }, t('Charges within the radius of this position count as home charges.')), homeChip, map,
    h('div', { class: 'tiny muted' }, t('Click the map to place your home, drag the pin, or use the locate button (top left) to use this device’s position.')),
    h('div', { class: 'grid g3' },
      field(t('Latitude'), coord('lat', { type: 'number', step: 'any', min: -90, max: 90, inputmode: 'decimal' })),
      field(t('Longitude'), coord('lon', { type: 'number', step: 'any', min: -180, max: 180, inputmode: 'decimal' })),
      field(t('Radius (metres)'), coord('radius', { type: 'number', step: 1, min: 20, max: 5000, inputmode: 'numeric' }))),
    h('div', { class: 'row' },
      asyncButton(t('Use current parking position'), async () => {
        const r = await ctx.api.post(`/api/vehicles/${ctx.vid}/home-here`);
        d.lat = saved.lat = String(r.home_lat); d.lon = saved.lon = String(r.home_lon);
        els.lat.value = d.lat; els.lon.value = d.lon; map.update({ ...mapState(), fit: true }); syncHome(); syncBar();
        await ctx.refresh();
        toast(`${t('Home position saved')}: ${f.num(r.home_lat, 5)}, ${f.num(r.home_lon, 5)}`, 'good');
      }, { ic: 'pin' }),
      button(t('Clear home position'), { ic: 'x', onClick: () => {
        d.lat = ''; d.lon = ''; els.lat.value = ''; els.lon.value = ''; map.update({ ...mapState(), fit: false }); syncHome(); syncBar();
        toast(t('Home pin removed. Press “Save prices” to keep it.'), 'info');
      } }))), { ic: 'home' });

  // ---- save / discard
  async function save() {
    if (!/^[A-Za-z]{1,4}$/.test(String(d.currency).trim())) fail(t('Currency must be a short code such as EUR.'));
    for (const k of ['home', 'ac', 'dc']) if (d[k] !== '' && !(num(d[k]) >= 0 && num(d[k]) <= 10)) fail(t('Prices must be between 0 and 10 per kWh.'));
    const lat = num(d.lat), lon = num(d.lon);
    if ((d.lat === '') !== (d.lon === '')) fail(t('Enter both latitude and longitude, or leave both empty.'));
    if (d.lat !== '' && !(lat >= -90 && lat <= 90)) fail(t('Latitude must be between -90 and 90.'));
    if (d.lon !== '' && !(lon >= -180 && lon <= 180)) fail(t('Longitude must be between -180 and 180.'));
    if (!(num(d.radius) >= 20 && num(d.radius) <= 5000)) fail(t('Radius must be between 20 and 5000 metres.'));
    const res = await ctx.api.put('/api/settings', { tariff: { currency: String(d.currency).trim().toUpperCase(), home_kwh: d.home, public_ac_kwh: d.ac, public_dc_kwh: d.dc,
      home_lat: d.lat === '' ? null : lat, home_lon: d.lon === '' ? null : lon, home_radius_m: Math.round(num(d.radius)) } });
    saved = fromTariff(res.tariff || {}); Object.assign(d, saved);
    for (const k of Object.keys(els)) if (els[k] && k in d) els[k].value = d[k];
    syncExamples(); syncHome(); syncBar();
    await ctx.refresh();
    toast(t('Prices saved'), 'good');
  }
  function discard() {
    Object.assign(d, saved);
    for (const k of Object.keys(els)) if (els[k] && k in d) els[k].value = d[k];
    map.update({ ...mapState(), fit: true }); syncExamples(); syncHome(); syncBar();
    toast(t('Changes discarded'), 'info');
  }
  saveBtn = asyncButton(t('Save prices'), save, { ic: 'check', kind: 'primary', disabled: true });
  discardBtn = button(t('Discard'), { ic: 'x', disabled: true, onClick: discard });
  const bar = h('div', { class: 'pr-bar' }, status, h('div', { class: 'row tight' }, discardBtn, saveBtn));

  mount(root,
    h('div', { class: 'stack' }, h('h1', null, t('Charge prices')), h('p', { class: 'muted' }, t('Set what each kWh costs, so Mate can price your charges.'))),
    banner('info', t('Changes recalculate the cost of every charge and trip without a manual price, including past ones. A price you set by hand on a charge always wins.')),
    pricesCard, placeCard, bar);
  syncExamples(); syncHome(); syncBar();
}
