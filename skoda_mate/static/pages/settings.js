// Settings: display, tariff and home position, battery capacity, polling budget, MyŠkoda API key / S-PIN, data export.
// The API key itself is never typed into the SPA: /setup handles it. Every save shows the server's own error message.
import { h, mount } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { asyncButton, banner, button, card, chip, confirmDialog, empty, field, kv, loading, seg, toast } from '../lib/ui.js';
import { mapView } from '../lib/mapview.js';
import * as f from '../lib/format.js';
import { extendDE, t } from '../i18n.js';

extendDE({
  'history only': 'nur Historie', 'Remove this car': 'Dieses Auto entfernen', 'Remove this car?': 'Dieses Auto entfernen?', 'Remove': 'Entfernen', 'Car removed': 'Auto entfernt', 'Car added': 'Auto hinzugefügt', 'Add car': 'Auto hinzufügen',
  'Mate stops reading it. Its history stays and comes back if you add the car again.': 'Mate liest es nicht mehr aus. Die Historie bleibt erhalten und ist wieder da, wenn du das Auto erneut hinzufügst.',
  'Add another car': 'Weiteres Auto hinzufügen', 'cars': 'Autos', 'the maximum for one installation. Remove a car to add another.': 'das Maximum pro Installation. Entferne ein Auto, um ein weiteres hinzuzufügen.', 'One installation tracks up to 5 cars.': 'Eine Installation verwaltet bis zu 5 Autos.', 'VIN': 'FIN',
  'Uses the API key that is already stored. The key must cover this car: create or edit it in the MyŠkoda app and choose all your cars.': 'Verwendet den bereits gespeicherten API-Schlüssel. Der Schlüssel muss dieses Auto abdecken: Erstelle oder bearbeite ihn in der MyŠkoda-App und wähle alle deine Autos.',
  'Click the map to place your home, or drag the pin. Then press “Save tariff” to keep it.': 'Klicke auf die Karte, um dein Zuhause zu setzen, oder ziehe die Markierung. Danach „Tarif speichern“ drücken.',
  'The car is parked here': 'Hier steht das Auto', 'Home': 'Zuhause',
  'Click the map to place your home, drag the pin, or use the locate button (top left) to use this device’s position. Then press “Save tariff” to keep it.': 'Klicke auf die Karte, ziehe die Markierung oder nutze die Ortungstaste (oben links), um die Position dieses Geräts zu verwenden. Danach „Tarif speichern“ drücken.',
  'Home pin moved to your position. Press “Save tariff” to keep it.': 'Heim-Markierung auf deine Position gesetzt. Zum Behalten „Tarif speichern“ drücken.',
  'Could not get your position': 'Position konnte nicht ermittelt werden', 'Show my position': 'Meine Position anzeigen',
  'This needs your permission and an https:// or localhost address.': 'Dafür sind deine Erlaubnis und eine https://- oder localhost-Adresse nötig.',
  'Settings': 'Einstellungen', 'Display': 'Anzeige', 'Units': 'Einheiten', 'Language': 'Sprache', 'Theme': 'Design', 'Automatic': 'Automatisch', 'Light': 'Hell', 'Dark': 'Dunkel',
  'Kilometres': 'Kilometer', 'Miles': 'Meilen', 'Save': 'Speichern', 'Saved': 'Gespeichert', 'Try again': 'Erneut versuchen',
  'Tariff': 'Tarif', 'Currency': 'Währung', 'Home charging price per kWh': 'Heimladen, Preis pro kWh', 'Public AC price per kWh': 'Öffentlich AC, Preis pro kWh', 'Public DC price per kWh': 'Öffentlich DC, Preis pro kWh',
  'Used to estimate the cost of charges and trips. Manual costs on a charge always win.': 'Dient zur Schätzung der Kosten von Ladevorgängen und Fahrten. Manuell eingetragene Kosten haben immer Vorrang.',
  'Home position': 'Heimposition', 'Charges within the radius of this position count as home charges.': 'Ladevorgänge innerhalb des Radius um diese Position gelten als Heimladen.',
  'Latitude': 'Breitengrad', 'Longitude': 'Längengrad', 'Radius (metres)': 'Radius (Meter)', 'Use current parking position': 'Aktuelle Parkposition verwenden',
  'Clear home position': 'Heimposition löschen', 'Not set': 'Nicht gesetzt', 'Home position saved': 'Heimposition gespeichert', 'Save tariff': 'Tarif speichern',
  'Enter both latitude and longitude, or leave both empty.': 'Gib Breiten- und Längengrad an oder lass beide leer.',
  'Latitude must be between -90 and 90.': 'Der Breitengrad muss zwischen -90 und 90 liegen.', 'Longitude must be between -180 and 180.': 'Der Längengrad muss zwischen -180 und 180 liegen.',
  'Radius must be between 20 and 5000 metres.': 'Der Radius muss zwischen 20 und 5000 Metern liegen.', 'Prices must be between 0 and 10 per kWh.': 'Preise müssen zwischen 0 und 10 pro kWh liegen.',
  'Currency must be a short code such as EUR.': 'Die Währung muss ein kurzer Code wie EUR sein.',
  'Battery capacity': 'Batteriekapazität', 'Usable capacity in kWh': 'Nutzbare Kapazität in kWh', 'Default for new vehicles (kWh)': 'Standard für neue Fahrzeuge (kWh)',
  'Škoda does not report the battery size. Mate needs it to turn the change in charge level into kWh, consumption and cost.': 'Škoda meldet die Batteriegröße nicht. Mate braucht sie, um die Änderung des Ladestands in kWh, Verbrauch und Kosten umzurechnen.',
  'Capacity must be between 10 and 200 kWh.': 'Die Kapazität muss zwischen 10 und 200 kWh liegen.', 'Save default': 'Standard speichern',
  'Polling': 'Abfrage', 'Idle interval (seconds)': 'Intervall im Ruhezustand (Sekunden)', 'Active interval (seconds)': 'Intervall bei Aktivität (Sekunden)', 'Command reserve (requests per hour)': 'Befehlsreserve (Anfragen pro Stunde)',
  'Škoda allows about 20 requests per hour per car. Mate reads the car on this schedule and keeps the reserve free for commands.': 'Škoda erlaubt etwa 20 Anfragen pro Stunde und Auto. Mate liest das Auto in diesem Takt aus und hält die Reserve für Befehle frei.',
  'requests per hour': 'Anfragen pro Stunde', 'when idle': 'im Ruhezustand', 'when active': 'bei Aktivität', 'Request limit': 'Anfragelimit', 'Available for reading': 'Für Auslesen verfügbar',
  'Command reserve': 'Befehlsreserve', 'Too many requests: Škoda would block the key.': 'Zu viele Anfragen: Škoda würde den Schlüssel sperren.', 'Within the limit.': 'Im Rahmen des Limits.',
  'The minimum is': 'Das Minimum ist', 'seconds': 'Sekunden', 'Save polling': 'Abfrage speichern',
  'Idle interval must be between 180 and 21600 seconds.': 'Das Ruhe-Intervall muss zwischen 180 und 21600 Sekunden liegen.',
  'Active interval must be between 180 and 3600 seconds.': 'Das Aktiv-Intervall muss zwischen 180 und 3600 Sekunden liegen.', 'Command reserve must be between 0 and 10.': 'Die Befehlsreserve muss zwischen 0 und 10 liegen.',
  'MyŠkoda API key': 'MyŠkoda-API-Schlüssel', 'Connected': 'Verbunden', 'Not connected': 'Nicht verbunden', 'Key expires': 'Schlüssel läuft ab', 'expired': 'abgelaufen', 'days left': 'Tage übrig', 'day left': 'Tag übrig',
  'Official Škoda API documentation': 'Offizielle Škoda-API-Dokumentation', 'Create or manage API keys': 'API-Schlüssel erstellen oder verwalten',
  'Replace the API key': 'API-Schlüssel ersetzen', 'The key is entered on the setup page, not here, so it never passes through this dashboard.': 'Der Schlüssel wird auf der Einrichtungsseite eingegeben, nicht hier, damit er nie durch dieses Dashboard läuft.',
  'Vehicle': 'Fahrzeug', 'State': 'Status', 'Last successful reading': 'Letzte erfolgreiche Messung', 'OK': 'OK', 'Blocked': 'Gesperrt', 'Error': 'Fehler', 'Unknown': 'Unbekannt',
  'No vehicles connected.': 'Keine Fahrzeuge verbunden.', 'The key expires soon. Create a new one in the MyŠkoda app and enter it on the setup page.': 'Der Schlüssel läuft bald ab. Erstelle in der MyŠkoda-App einen neuen und gib ihn auf der Einrichtungsseite ein.',
  'The key has expired.': 'Der Schlüssel ist abgelaufen.', 'Could not read the stored key. The data key may have changed; enter the key again.': 'Der gespeicherte Schlüssel ist nicht lesbar. Der Datenschlüssel hat sich evtl. geändert; gib den API-Schlüssel erneut ein.',
  'S-PIN': 'S-PIN', 'Needed only for the auxiliary heater. It is stored encrypted and never shown again.': 'Nur für die Standheizung nötig. Sie wird verschlüsselt gespeichert und nie wieder angezeigt.',
  'S-PIN (4 digits)': 'S-PIN (4 Ziffern)', 'Save S-PIN': 'S-PIN speichern', 'Remove S-PIN': 'S-PIN entfernen', 'An S-PIN is stored.': 'Eine S-PIN ist gespeichert.', 'No S-PIN is stored.': 'Es ist keine S-PIN gespeichert.',
  'The S-PIN is 4 digits.': 'Die S-PIN besteht aus 4 Ziffern.', 'S-PIN saved': 'S-PIN gespeichert', 'S-PIN removed': 'S-PIN entfernt', 'Connect an API key first.': 'Verbinde zuerst einen API-Schlüssel.',
  'Remove the stored S-PIN?': 'Gespeicherte S-PIN entfernen?', 'The auxiliary heater cannot be started until you add it again.': 'Die Standheizung lässt sich erst wieder starten, wenn du die S-PIN neu hinterlegst.',
  'Disconnect from Škoda': 'Von Škoda trennen', 'Disconnect Mate from Škoda?': 'Mate von Škoda trennen?', 'Mate stops reading your car and deletes the stored API key and S-PIN. Your recorded trips, charges and settings stay.': 'Mate liest dein Auto nicht mehr aus und löscht den gespeicherten API-Schlüssel und die S-PIN. Aufgezeichnete Fahrten, Ladevorgänge und Einstellungen bleiben erhalten.',
  'Disconnect': 'Trennen', 'Disconnected from Škoda': 'Von Škoda getrennt',
  'Data': 'Daten', 'Export CSV': 'CSV exportieren', 'Trips': 'Fahrten', 'Charges': 'Ladevorgänge', 'Events': 'Ereignisse', 'Readings': 'Messwerte',
  'Import trip history': 'Fahrtenverlauf importieren', 'Import trips': 'Fahrten importieren',
  'Add trips from before Mate started with the trip export of the MyŠkoda app.': 'Füge Fahrten aus der Zeit vor Mates Start über den Fahrten-Export der MyŠkoda-App hinzu.',
  'Database backup': 'Datenbank-Sicherung', 'Download a consistent copy of the whole database (SQLite). Keep it private: it contains positions and, encrypted, your API key.': 'Lade eine konsistente Kopie der gesamten Datenbank (SQLite) herunter. Halte sie privat: Sie enthält Positionen und, verschlüsselt, deinen API-Schlüssel.',
  'Download backup': 'Sicherung herunterladen', 'Dashboard login': 'Dashboard-Login', 'Signed-in account': 'Angemeldetes Konto', 'Change the dashboard login': 'Dashboard-Login ändern', 'Not set': 'Nicht gesetzt',
  'Could not load settings': 'Einstellungen konnten nicht geladen werden', 'Could not load the connection status': 'Verbindungsstatus konnte nicht geladen werden',
  'Demo mode: this is a fictional car. Nothing is sent to Škoda.': 'Demo-Modus: Das ist ein fiktives Auto. Es wird nichts an Škoda gesendet.',
});

const num = (v) => (v === '' || v == null || Number.isNaN(Number(v)) ? null : Number(v));
const fail = (msg) => { throw new Error(msg); };
const daysUntil = (iso) => (iso ? Math.floor((new Date(iso) - Date.now()) / 864e5) : null);

export default async function settings(root, ctx) {
  ctx.setTitle(t('Settings'));
  let S = null, status = null, statusError = null;
  const redraws = [];
  const wrap = (fn) => { const box = h('div'); const draw = () => mount(box, fn()); redraws.push(draw); draw(); return box; };

  const refreshLocal = async () => { S = await ctx.api.get('/api/settings'); };
  /** PUT /api/settings and take over the response (the full settings object). */
  async function put(body) { S = await ctx.api.put('/api/settings', body); return S; }

  // ------------------------------------------------------------ display
  function displayCard() {
    const d = { units: S.units, language: S.language, theme: S.theme };
    const group = (id, label, options, key) => {
      const s = seg(options, d[key], (v) => { d[key] = v; });
      s.setAttribute('aria-labelledby', id);
      return h('div', null, h('div', { class: 'b-label', id }, label), s);
    };
    return card(t('Display'), h('div', { class: 'stack' },
      h('div', { class: 'grid g3' },
        group('b-units', t('Units'), [['km', t('Kilometres')], ['mi', t('Miles')]], 'units'),
        group('b-lang', t('Language'), [['en', 'English'], ['de', 'Deutsch']], 'language'),
        group('b-theme', t('Theme'), [['auto', t('Automatic')], ['light', t('Light')], ['dark', t('Dark')]], 'theme')),
      asyncButton(t('Save'), async () => {
        await put({ units: d.units, language: d.language, theme: d.theme });
        await ctx.reloadSettings();      // applies units, language and theme right away
        redrawAll();
        toast(t('Saved'), 'good');
      }, { ic: 'check', kind: 'primary' })), { ic: 'settings' });
  }

  // ------------------------------------------------------------ tariff
  function tariffCard() {
    // Prices and the home place have their own page (sidebar: Prices); this card only points there.
    return card(t('Charge prices'), h('div', { class: 'stack' },
      h('div', { class: 'small muted' }, t('Prices per kWh and your home place moved to their own page.')),
      h('a', { class: 'btn', href: '#/prices' }, icon('coin', { size: 16 }), t('Open charge prices'))), { ic: 'coin' });
  }

  // ------------------------------------------------------------ battery capacity
  function capacityCard() {
    const d = { def: S.battery_kwh_default ?? '', veh: Object.fromEntries((S.vehicles || []).map((v) => [v.id, v.battery_kwh ?? ''])) };
    const check = (v) => { if (!(num(v) >= 10 && num(v) <= 200)) fail(t('Capacity must be between 10 and 200 kWh.')); };
    const rows = (S.vehicles || []).map((v) => h('div', { class: 'form-row' },
      field(`${t('Usable capacity in kWh')} · ${v.name || v.vin}`, h('input', { type: 'number', min: 10, max: 200, step: 0.1, inputmode: 'decimal', value: d.veh[v.id], oninput: (e) => { d.veh[v.id] = e.target.value; } })),
      asyncButton(t('Save'), async () => {
        if (d.veh[v.id] !== '') check(d.veh[v.id]);
        await ctx.api.put(`/api/vehicles/${v.id}`, { battery_kwh: d.veh[v.id] === '' ? '' : num(d.veh[v.id]) });
        await refreshLocal(); await ctx.refresh(); redraws[2]();
        toast(t('Saved'), 'good');
      }, { ic: 'check', kind: 'primary' })));
    return card(t('Battery capacity'), h('div', { class: 'stack' },
      h('div', { class: 'small muted' }, t('Škoda does not report the battery size. Mate needs it to turn the change in charge level into kWh, consumption and cost.')),
      ...rows,
      h('div', { class: 'form-row' },
        field(t('Default for new vehicles (kWh)'), h('input', { type: 'number', min: 10, max: 200, step: 0.1, inputmode: 'decimal', value: d.def, oninput: (e) => { d.def = e.target.value; } })),
        asyncButton(t('Save default'), async () => {
          check(d.def);
          await put({ battery_kwh_default: num(d.def) });
          await ctx.refresh(); redraws[2]();
          toast(t('Saved'), 'good');
        }, { ic: 'check' }))), { ic: 'battery' });
  }

  // ------------------------------------------------------------ polling
  function pollingCard() {
    const min = S.poll_min_s || 180, limit = ctx.overview?.poller?.budget?.limit || 20;
    const d = { idle: S.poll_idle_s, active: S.poll_active_s, reserve: S.command_reserve };
    const out = h('div', { class: 'stack', 'aria-live': 'polite' });
    const calc = () => {
      const idle = num(d.idle), active = num(d.active), reserve = num(d.reserve) ?? 0;
      const rate = (s) => (s > 0 ? 3600 / s : null);
      const ri = rate(idle), ra = rate(active), room = limit - reserve;
      const bad = (ri != null && ri > room) || (ra != null && ra > room);
      mount(out,
        h('div', { class: 'row' }, chip(`${ri != null ? f.num(ri, 1) : '–'} ${t('requests per hour')} ${t('when idle')}`, ri != null && ri > room ? 'bad' : 'good', 'clock'),
          chip(`${ra != null ? f.num(ra, 1) : '–'} ${t('requests per hour')} ${t('when active')}`, ra != null && ra > room ? 'bad' : 'good', 'bolt')),
        kv([[t('Request limit'), `${limit} / h`], [t('Command reserve'), `${reserve} / h`], [t('Available for reading'), `${room} / h`]]),
        bad ? banner('warn', t('Too many requests: Škoda would block the key.')) : h('div', { class: 'small muted' }, t('Within the limit.')));
    };
    const numIn = (key, minV, maxV) => h('input', { type: 'number', min: minV, max: maxV, step: 1, inputmode: 'numeric', value: d[key], oninput: (e) => { d[key] = e.target.value; calc(); } });
    calc();
    return card(t('Polling'), h('div', { class: 'stack' },
      h('div', { class: 'small muted' }, t('Škoda allows about 20 requests per hour per car. Mate reads the car on this schedule and keeps the reserve free for commands.')),
      h('div', { class: 'grid g3' },
        field(t('Idle interval (seconds)'), numIn('idle', min, 21600), `${t('The minimum is')} ${min} ${t('seconds')}`),
        field(t('Active interval (seconds)'), numIn('active', min, 3600), `${t('The minimum is')} ${min} ${t('seconds')}`),
        field(t('Command reserve (requests per hour)'), numIn('reserve', 0, 10))),
      out,
      asyncButton(t('Save polling'), async () => {
        if (!(num(d.idle) >= min && num(d.idle) <= 21600)) fail(t('Idle interval must be between 180 and 21600 seconds.'));
        if (!(num(d.active) >= min && num(d.active) <= 3600)) fail(t('Active interval must be between 180 and 3600 seconds.'));
        if (!(num(d.reserve) >= 0 && num(d.reserve) <= 10)) fail(t('Command reserve must be between 0 and 10.'));
        await put({ poll_idle_s: Math.round(num(d.idle)), poll_active_s: Math.round(num(d.active)), command_reserve: Math.round(num(d.reserve)) });
        await ctx.refresh(); redraws[3]();
        toast(t('Saved'), 'good');
      }, { ic: 'check', kind: 'primary' })), { ic: 'clock' });
  }

  // ------------------------------------------------------------ API key, S-PIN
  async function loadStatus() {
    try { status = await ctx.api.get('/api/setup/status'); statusError = null; } catch (e) { status = null; statusError = e.message; }
  }
  function keyCard() {
    if (statusError) return card(t('MyŠkoda API key'), h('div', { class: 'stack' }, banner('bad', `${t('Could not load the connection status')}: ${statusError}`),
      button(t('Try again'), { ic: 'refresh', onClick: async () => { await loadStatus(); redraws[4](); } })), { ic: 'key' });
    if (!status) return card(t('MyŠkoda API key'), loading(), { ic: 'key' });
    const demo = ctx.overview?.demo;
    const vehicles = status.vehicles || [];
    const rows = vehicles.map((v) => {
      const days = daysUntil(v.key_expires_at);
      const stateChip = v.blocked ? chip(t('Blocked'), 'bad', 'alert') : v.error ? chip(t('Error'), 'warn', 'alert') : v.last_ok ? chip(t('OK'), 'good', 'check') : chip(t('Unknown'), '');
      const expiry = days == null ? chip('–', '') : days < 0 ? chip(t('expired'), 'bad', 'alert') : chip(`${days} ${days === 1 ? t('day left') : t('days left')}`, days <= 14 ? 'warn' : 'good', 'calendar');
      return h('div', { class: 'b-vehicle' },
        h('div', { class: 'row between' }, h('strong', null, v.name || t('Vehicle')), stateChip),
        kv([['VIN', v.vin], [t('Key expires'), h('span', { class: 'row tight', style: { justifyContent: 'flex-end' } }, v.key_expires_at ? f.date(v.key_expires_at) : '–', expiry)],
          [t('Last successful reading'), v.last_ok ? f.dateTime(v.last_ok) : '–']]),
        v.error ? h('div', { class: 'small b-errtext' }, v.error) : null,
        vehicles.length > 1 ? asyncButton(t('Remove this car'), async () => {
          if (!await confirmDialog(t('Remove this car?'), t('Mate stops reading it. Its history stays and comes back if you add the car again.'), { confirmLabel: t('Remove'), danger: true })) return;
          await ctx.api.del(`/api/setup/vehicles/${v.vin}`);
          toast(t('Car removed'), 'good'); location.reload();  // the header's car picker must update too
        }, { ic: 'trash', size: 'sm', kind: 'danger' }) : null);
    });
    const addVin = h('input', { type: 'text', placeholder: 'TMBJB9NY5RF999999', maxlength: 20, autocomplete: 'off', spellcheck: 'false' });
    const full = vehicles.length >= 5;
    const addCar = vehicles.length && status.skoda_set && full ? h('div', { class: 'small muted' }, `${vehicles.length} / 5 ${t('cars')}: ${t('the maximum for one installation. Remove a car to add another.')}`)
      : vehicles.length && status.skoda_set ? h('div', { class: 'stack b-section' }, h('h3', null, `${t('Add another car')} (${vehicles.length} / 5)`),
      h('div', { class: 'small muted' }, t('One installation tracks up to 5 cars.')),
      h('div', { class: 'small muted' }, t('Uses the API key that is already stored. The key must cover this car: create or edit it in the MyŠkoda app and choose all your cars.')),
      h('div', { class: 'form-row' }, field(t('VIN'), addVin), asyncButton(t('Add car'), async () => {
        await ctx.api.post('/api/setup/vehicles', { vin: addVin.value });
        toast(t('Car added'), 'good'); location.reload();
      }, { ic: 'plus', kind: 'primary' }))) : null;
    const soon = vehicles.map((v) => daysUntil(v.key_expires_at)).filter((d) => d != null);
    const worst = soon.length ? Math.min(...soon) : null;
    const d = { pin: '' };
    const pinOk = () => /^\d{4}$/.test(d.pin);
    const pinDisabled = !status.skoda_set;
    return card(t('MyŠkoda API key'), h('div', { class: 'stack' },
      demo ? banner('info', t('Demo mode: this is a fictional car. Nothing is sent to Škoda.')) : null,
      h('div', { class: 'row' }, status.skoda_set ? chip(t('Connected'), 'good', 'check') : chip(t('Not connected'), 'warn', 'wifioff'),
        h('a', { class: 'btn sm', href: '/setup' }, icon('key', { size: 15 }), t('Replace the API key'))),
      h('div', { class: 'tiny muted' }, t('The key is entered on the setup page, not here, so it never passes through this dashboard.')),
      h('div', { class: 'row tight small' },
        h('a', { href: 'https://public.api.connect.skoda-auto.cz/docs', target: '_blank', rel: 'noopener' }, icon('external', { size: 14 }), ' ', t('Official Škoda API documentation')),
        h('a', { href: 'https://go.skoda.eu/api-keys', target: '_blank', rel: 'noopener' }, icon('external', { size: 14 }), ' ', t('Create or manage API keys'))),
      status.key_readable === false ? banner('bad', t('Could not read the stored key. The data key may have changed; enter the key again.')) : null,
      worst != null && worst < 0 ? banner('bad', t('The key has expired.'), ' ', h('a', { href: '/setup' }, t('Replace the API key')))
        : worst != null && worst <= 14 ? banner('warn', t('The key expires soon. Create a new one in the MyŠkoda app and enter it on the setup page.'), ' ', h('a', { href: '/setup' }, t('Replace the API key'))) : null,
      vehicles.length ? h('div', { class: 'stack' }, ...rows, addCar) : empty(t('No vehicles connected.'), null, 'car'),
      h('h3', null, t('S-PIN')),
      h('div', { class: 'small muted' }, t('Needed only for the auxiliary heater. It is stored encrypted and never shown again.')),
      h('div', { class: 'row' }, status.spin_set ? chip(t('An S-PIN is stored.'), 'good', 'lock') : chip(t('No S-PIN is stored.'), '', 'unlock')),
      h('div', { class: 'form-row' },
        field(t('S-PIN (4 digits)'), h('input', { type: 'password', inputmode: 'numeric', pattern: '[0-9]{4}', maxlength: 4, autocomplete: 'off', disabled: pinDisabled, oninput: (e) => { d.pin = e.target.value; } }),
          pinDisabled ? t('Connect an API key first.') : null),
        asyncButton(t('Save S-PIN'), async () => {
          if (!pinOk()) fail(t('The S-PIN is 4 digits.'));
          await ctx.api.put('/api/setup/spin', { spin: d.pin });
          await loadStatus(); await ctx.refresh(); redraws[4]();
          toast(t('S-PIN saved'), 'good');
        }, { ic: 'check', kind: 'primary', disabled: pinDisabled }),
        asyncButton(t('Remove S-PIN'), async () => {
          if (!await confirmDialog(t('Remove the stored S-PIN?'), t('The auxiliary heater cannot be started until you add it again.'), { confirmLabel: t('Remove S-PIN'), danger: true })) return;
          await ctx.api.put('/api/setup/spin', { spin: '' });
          await loadStatus(); await ctx.refresh(); redraws[4]();
          toast(t('S-PIN removed'), 'good');
        }, { ic: 'trash', kind: 'danger', disabled: pinDisabled || !status.spin_set })),
      h('hr', { class: 'b-sep' }),
      asyncButton(t('Disconnect from Škoda'), async () => {
        if (!await confirmDialog(t('Disconnect Mate from Škoda?'), t('Mate stops reading your car and deletes the stored API key and S-PIN. Your recorded trips, charges and settings stay.'), { confirmLabel: t('Disconnect'), danger: true })) return;
        await ctx.api.del('/api/setup/skoda');
        await loadStatus(); await ctx.refresh(); redraws[4]();
        toast(t('Disconnected from Škoda'), 'good');
      }, { ic: 'wifioff', kind: 'danger', disabled: !status.skoda_set })), { ic: 'key' });
  }

  // ------------------------------------------------------------ Home Assistant (MQTT)
  let mq = null, mqError = null;
  async function loadMqtt() {
    try { mq = await ctx.api.get('/api/settings/mqtt'); mqError = null; } catch (e) { mq = null; mqError = e.message; }
  }
  const MQTT_STATUS = {
    connected: ['Connected', 'good', 'check'], connecting: ['Connecting …', 'info', 'clock'], error: ['Not connected', 'bad', 'alert'],
    disabled: ['Disabled', '', 'wifioff'], waiting: ['Waiting for the Škoda connection', 'warn', 'clock'],
  };

  function mqttGuide(m) {
    const li = (...c) => h('li', null, ...c);
    return h('details', { class: 'b-guide' },
      h('summary', null, icon('info', { size: 16 }), ' ', t('How to connect Home Assistant (step by step)')),
      h('div', { class: 'stack' },
        h('ol', { class: 'b-steps' },
          li(h('strong', null, t('Make sure an MQTT broker runs.')), ' ', t('In Home Assistant: Settings → Add-ons → Add-on store → “Mosquitto broker” → Install → Start, and switch on “Start on boot”. (Home Assistant OS or Supervised. If you run Home Assistant in Docker or as Core, use your own Mosquitto broker instead.)')),
          li(h('strong', null, t('Create a user for Mate.')), ' ', t('Settings → People → Users → Add user, for example “skoda_mate” with a password. It needs no administrator rights. The Mosquitto add-on accepts Home Assistant users.')),
          li(h('strong', null, t('Add the MQTT integration.')), ' ', t('Settings → Devices & services → Add integration → MQTT. Broker: core-mosquitto (or the IP address), port 1883, and the user and password from step 2. Leave “Enable discovery” on (discovery prefix: {prefix}).').replace('{prefix}', m?.discovery_prefix || 'homeassistant')),
          li(h('strong', null, t('Fill in the form above.')), ' ', t('Broker = the IP address of the machine that runs the broker, usually the IP address of Home Assistant (for example 192.168.1.10). Port 1883, the user and password from step 2. Keep the topic prefix and keep “Discovery” ticked.')),
          li(h('strong', null, t('Test, enable, save.')), ' ', t('Press “Test connection”. When it says “Connected”, tick “Enabled” and press “Save”. No restart is needed.')),
          li(h('strong', null, t('Find your car in Home Assistant.')), ' ', t('Settings → Devices & services → MQTT → Devices: your car appears as a device with all its entities. Add them to a dashboard: Overview → pencil icon → Add card → Tile or Entities.'))),
        banner('warn', h('b', null, t('Mate runs in Docker or DDEV?')), ' ', t('Then “localhost” and “homeassistant.local” usually do not work from inside the container. Use the IP address of Home Assistant.')),
        h('h3', null, t('What you get')),
        h('ul', { class: 'b-notes small' },
          li(h('b', null, t('Sensors')), ': ', t('battery, range, charging power, charge limit, time to full, charge state and type, odometer, climate, auxiliary heater, ventilation, fuel, last update.')),
          li(h('b', null, t('Mate’s own values')), ': ', t('last trip distance, energy and consumption; last charge energy, cost and place; current place, parked loss over 7 days, capacity estimate, projected range at 100 % and the number of data-quality issues.')),
          li(h('b', null, t('Binary sensors')), ': ', t('charging, plug connected, plug locked, doors, windows, trunk, bonnet, lights, driving, climate running, unlocked (read-only: the API cannot lock).')),
          li(h('b', null, t('Position')), ': ', t('a device tracker, so the car shows on the Home Assistant map.')),
          li(h('b', null, t('Controls')), ': ', t('only if “Allow commands from Home Assistant” is ticked: buttons to start and stop charging, climate and ventilation, to stop the auxiliary heater, and a charge-limit slider. They use the same request budget as the Control page.'))),
        h('h3', null, t('If something does not work')),
        h('ul', { class: 'b-notes small' },
          li(h('b', null, t('“Cannot reach …”')), ': ', t('wrong IP or port, the broker is not running, or a firewall blocks port 1883.')),
          li(h('b', null, t('“refused the user name or password”')), ': ', t('check the user and password; the user must exist in Home Assistant.')),
          li(h('b', null, t('No device appears')), ': ', t('make sure “Discovery” is ticked here and “Enable discovery” is on in the MQTT integration, with the same discovery prefix.')),
          li(h('b', null, t('Entities show “unavailable”')), ': ', t('Mate is stopped or cannot reach the broker. Mate marks them available again by itself once it reconnects.')),
          li(h('b', null, t('Two Mate installations, one broker')), ': ', t('give each one its own topic prefix.')))));
  }

  function mqttCard() {
    const title = t('MQTT → Home Assistant');
    if (mqError) return card(title, banner('bad', `${t('Could not load the Home Assistant settings')}: ${mqError}`), { ic: 'plug' });
    if (!mq) return card(title, loading(), { ic: 'plug' });
    const c = mq.config;
    const d = { enabled: c.enabled, host: c.host, port: c.port, user: c.user, password: '', clear: false, prefix: c.prefix, discovery: c.discovery, commands: !!c.commands, publish_fields: !!c.publish_fields, tls: c.tls, tls_insecure: c.tls_insecure };
    // The stored password is only reused for the broker it was saved for (the server enforces this too).
    const brokerChanged = () => d.host.trim() !== c.host || Number(d.port) !== Number(c.port) || !!d.tls !== !!c.tls;
    const pwPlaceholder = c.password_unreadable ? t('Stored, but cannot be read: enter it again') : c.password_set ? t('•••••••• (stored; leave empty to keep)') : '';
    const base = JSON.stringify(d);
    const dirty = () => JSON.stringify(d) !== base;
    const els = {};
    let testResult = null;
    const resultBox = h('div');
    const showResult = () => mount(resultBox, testResult ? banner(testResult.ok ? 'info' : 'bad', testResult.message) : null);
    const st = mq.status, [stLabel, stKind, stIc] = MQTT_STATUS[st.state] || MQTT_STATUS.disabled;
    const stChip = chip(t(stLabel), stKind, stIc);
    const saveBtn = asyncButton(t('Save'), async () => {
      const body = { ...d, port: Number(d.port) || d.port };
      if (!body.password) delete body.password;
      if (!body.clear) delete body.clear; else body.clear_password = true;
      delete body.clear;
      try { mq = await ctx.api.put('/api/settings/mqtt', body); } catch (e) { throw new Error(t(e.message)); }
      toast(t(d.enabled ? 'Saved. Mate is connecting to Home Assistant.' : 'Saved.'), 'good');
      redraws[6]();
      pollStatus();
    }, { ic: 'check', kind: 'primary', disabled: true });
    const testBtn = asyncButton(t('Test connection'), async () => {
      testResult = null; showResult();
      const body = { host: d.host, port: Number(d.port) || d.port, user: d.user, tls: d.tls, tls_insecure: d.tls_insecure, clear_password: d.clear };
      if (d.password) body.password = d.password;
      try { testResult = await ctx.api.post('/api/settings/mqtt/test', body); } catch (e) { testResult = { ok: false, message: e.message }; }
      testResult.message = t(testResult.message);
      showResult();
    }, { ic: 'signal' });
    const sync = () => {
      saveBtn.disabled = !dirty();
      if (els.insecure) { els.insecure.disabled = !d.tls; if (!d.tls) { d.tls_insecure = false; els.insecure.checked = false; } }
      if (els.clear) els.clear.hidden = !(c.password_set && !d.password);
      if (els.password && !d.clear) els.password.placeholder = c.password_set && brokerChanged() ? t('Enter the password again: the broker address changed.') : pwPlaceholder;
    };
    const text = (key, props) => { els[key] = h('input', { ...props, value: d[key] ?? '', oninput: (e) => { d[key] = e.target.value; if (key === 'password') d.clear = false; sync(); } }); return els[key]; };
    const check = (key, label, extra) => {
      const box = h('input', { type: 'checkbox', checked: !!d[key], onchange: (e) => { d[key] = e.target.checked; sync(); } });
      if (extra) els[extra] = box;
      return h('label', { class: 'b-check' }, box, h('span', null, label));
    };
    const body = h('div', { class: 'stack' },
      c.source === 'env' ? banner('info', t('This is currently set by environment variables (MQTT_HOST …). Saving here replaces them.')) : null,
      h('div', { class: 'small muted' }, t('Makes the car available in Home Assistant as native entities (sensors and commands) through MQTT discovery.')),
      st.state === 'error' && st.error ? banner('bad', t(st.error)) : null,
      st.state === 'connected' ? h('div', { class: 'small muted' }, `${st.entities} ${t('entities for')} ${st.vehicles} ${st.vehicles === 1 ? t('car') : t('cars')}${st.last_publish ? ` · ${t('last update sent')} ${f.ago(new Date(st.last_publish * 1000).toISOString())}` : ''}`) : null,
      check('enabled', t('Enabled')),
      h('div', { class: 'form-grid mq-host' }, field(t('Broker'), text('host', { type: 'text', placeholder: '192.168.1.10', autocomplete: 'off', spellcheck: 'false', inputmode: 'url' })),
        field(t('Port'), text('port', { type: 'number', min: 1, max: 65535, inputmode: 'numeric' }))),
      h('div', { class: 'form-grid' }, field(t('Username'), text('user', { type: 'text', autocomplete: 'off', spellcheck: 'false' })),
        field(t('Password'), text('password', { type: 'password', autocomplete: 'new-password', placeholder: pwPlaceholder }))),
      (els.clear = h('button', { type: 'button', class: 'linklike', hidden: !(c.password_set && !d.password), onclick: () => { d.clear = true; els.password.value = ''; els.password.placeholder = t('The stored password will be removed when you save.'); sync(); } }, t('Remove the stored password'))),
      field(t('Topic prefix'), text('prefix', { type: 'text', autocomplete: 'off', spellcheck: 'false' }), t('Change it only if several Mate installations talk to the same broker: it keeps their entities and commands apart. Otherwise leave it.')),
      h('div', { class: 'row' }, check('discovery', t('Discovery')), check('tls', 'TLS'), check('tls_insecure', t('TLS insecure'), 'insecure')),
      check('publish_fields', t('Also publish one topic per value')),
      h('div', { class: 'small muted' }, t('For tools other than Home Assistant: each value on its own retained topic, {prefix}/VIN/fields/…. Events are always published to {prefix}/VIN/events.').replaceAll('{prefix}', c.prefix)),
      check('commands', t('Allow commands from Home Assistant')),
      h('div', { class: 'small muted' }, t('Buttons for charging, climate and ventilation and a charge-limit slider; at most one command every 30 s. The auxiliary heater can only be started on the Control page.'), ' ',
        h('b', null, t('Anyone who can publish to your broker can then control these functions. Use broker ACLs and TLS.'))),
      h('div', { class: 'row mq-actions' }, testBtn, saveBtn),
      resultBox,
      mqttGuide(mq));
    setTimeout(sync, 0);
    return h('section', { class: 'card' }, h('header', null, icon('plug', { size: 20 }), h('h2', null, title), stChip), body);
  }

  let pollTimer = null;
  function pollStatus() {   // after a save the connection takes a moment: refresh the chip a few times
    clearTimeout(pollTimer);
    let n = 0;
    const tick = async () => {
      if (!document.body.contains(root) || n++ > 6) return;
      await loadMqtt(); if (!root.contains(document.activeElement) || document.activeElement === document.body) redraws[6]();
      if (mq?.status?.state === 'connecting') pollTimer = setTimeout(tick, 1500);
    };
    pollTimer = setTimeout(tick, 1200);
  }

  // ------------------------------------------------------------ data
  function dataCard() {
    const base = `/api/vehicles/${ctx.vid}/export`;
    const link = (what, label) => h('a', { class: 'btn', href: `${base}/${what}.csv`, download: `skoda-mate-${what}.csv` }, icon('download', { size: 16 }), label);
    return card(t('Data'), h('div', { class: 'stack' },
      h('h3', null, t('Export CSV')),
      h('div', { class: 'row' }, link('trips', t('Trips')), link('charges', t('Charges')), link('events', t('Events')), link('snapshots', t('Readings'))),
      h('h3', null, t('Import trip history')),
      h('div', { class: 'small muted' }, t('Add trips from before Mate started with the trip export of the MyŠkoda app.')),
      h('div', null, h('a', { class: 'btn', href: '#/import' }, icon('upload', { size: 16 }), t('Import trips'))),
      h('h3', null, t('Database backup')),
      h('div', { class: 'small muted' }, t('Download a consistent copy of the whole database (SQLite). Keep it private: it contains positions and, encrypted, your API key.')),
      h('div', null, h('a', { class: 'btn', href: '/api/backup' }, icon('download', { size: 16 }), t('Download backup'))),
      h('h3', null, t('Dashboard login')),
      h('div', { class: 'row between' }, h('span', { class: 'small' }, `${t('Signed-in account')}: ${status?.login_email || t('Not set')}`),
        h('a', { class: 'btn sm', href: '/setup' }, t('Change the dashboard login')))), { ic: 'download' });
  }

  // ------------------------------------------------------------ assemble
  function redrawAll() { redraws.forEach((r) => r()); ctx.setTitle(t('Settings')); }

  mount(root, loading());
  try {
    await Promise.all([refreshLocal(), loadStatus()]);
  } catch (e) {
    mount(root, h('div', { class: 'card' }, banner('bad', `${t('Could not load settings')}: ${e.message}`),
      h('div', { style: { marginTop: '12px' } }, button(t('Try again'), { ic: 'refresh', onClick: () => settings(root, ctx) }))));
    return;
  }
  const boxes = [wrap(displayCard), wrap(tariffCard), wrap(capacityCard), wrap(pollingCard), wrap(keyCard), wrap(dataCard), wrap(mqttCard)];  // redraws[0..6]
  // Two columns on wide screens (one on phones and narrow windows): display, prices, battery, polling and data on the left, the Škoda and Home Assistant connections on the right
  mount(root, h('div', { class: 'set-cols' },
    h('div', { class: 'set-col' }, boxes[0], boxes[1], boxes[2], boxes[3], boxes[5]),
    h('div', { class: 'set-col' }, boxes[4], boxes[6])));
  loadMqtt().then(() => redraws[6]());
  root.classList.add('b-settings');
  // The data card shows the login e-mail from the status, so it follows the key card's redraws
  const keyRedraw = redraws[4];
  redraws[4] = () => { keyRedraw(); redraws[5](); };
}
