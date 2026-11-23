// System: transparency page. What Mate asked Škoda, what the car can and cannot do, and the raw data behind every number.
import { h, mount } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { asyncButton, banner, button, card, chip, empty, kv, loading, table } from '../lib/ui.js';
import capabilitiesPage from './capabilities.js';
import * as f from '../lib/format.js';
import { extendDE, t } from '../i18n.js';

extendDE({
  'Skip to content': 'Zum Inhalt springen', 'Table': 'Tabelle', 'Commands sent': 'Gesendete Befehle', 'Monthly statistics': 'Monatsstatistik', 'Import preview': 'Importvorschau',
  'Status': 'Status', 'Capabilities': 'Funktionen', 'API calls': 'API-Aufrufe', 'Diagnostics': 'Diagnose', 'System sections': 'Bereiche von System',
  'Newer': 'Neuer', 'Older': 'Älter', 'Only failed': 'Nur fehlgeschlagene', 'No failed calls.': 'Keine fehlgeschlagenen Aufrufe.', 'Calls': 'Aufrufe', 'Pages': 'Seiten',
  'System': 'System', 'Request budget': 'Anfragebudget', 'Requests used in the last hour': 'Anfragen in der letzten Stunde', 'Request limit': 'Anfragelimit',
  'Reserved for commands': 'Für Befehle reserviert', 'Left for reading': 'Zum Auslesen übrig', 'Left for commands': 'Für Befehle übrig', 'Škoda reports remaining': 'Škoda meldet noch',
  'Next free slot in': 'Nächster freier Platz in', 'Limit reached': 'Limit erreicht', 'Within the limit': 'Im Rahmen des Limits',
  'Škoda allows about 20 requests per hour per car. Every reading and every command costs one request.': 'Škoda erlaubt etwa 20 Anfragen pro Stunde und Auto. Jede Messung und jeder Befehl kostet eine Anfrage.',
  'Polling status': 'Abfragestatus', 'Last successful reading': 'Letzte erfolgreiche Messung', 'Car reported': 'Auto meldete', 'Next reading in': 'Nächste Messung in', 'Readings so far': 'Bisherige Messungen',
  'Mode': 'Modus', 'Active (car is busy)': 'Aktiv (Auto ist beschäftigt)', 'Idle': 'Ruhe', 'Intervals': 'Intervalle', 'idle': 'Ruhe', 'active': 'aktiv', 'Blocked': 'Gesperrt', 'Last error': 'Letzter Fehler',
  'API key expires': 'API-Schlüssel läuft ab', 'Not connected': 'Nicht verbunden', 'Reading is blocked until the key is replaced.': 'Das Auslesen ist gesperrt, bis der Schlüssel ersetzt wird.', 'none': 'keiner',
  'Recent API calls': 'Letzte API-Aufrufe', 'When': 'Wann', 'Endpoint': 'Endpunkt', 'Result': 'Ergebnis', 'OK': 'OK', 'Failed': 'Fehlgeschlagen', 'No calls yet.': 'Noch keine Aufrufe.',
  'Could not load': 'Konnte nicht geladen werden', 'Try again': 'Erneut versuchen',
  'Data parts': 'Datenbereiche', 'What the car reports, part by part.': 'Was das Auto meldet, Bereich für Bereich.', 'Part': 'Bereich', 'State': 'Status', 'Reason': 'Grund',
  'present': 'vorhanden', 'unsupported': 'nicht unterstützt', 'disabled': 'deaktiviert', 'unavailable': 'nicht verfügbar', 'missing': 'fehlt', 'unknown': 'unbekannt',
  'Errors reported by Škoda': 'Von Škoda gemeldete Fehler', 'No errors reported.': 'Keine Fehler gemeldet.',
  'Supported operations': 'Unterstützte Funktionen', 'Remote operations this car accepts. Controls for anything else are shown disabled.': 'Fernfunktionen, die dieses Auto akzeptiert. Alles andere ist in der Steuerung deaktiviert.',
  'Not known yet. Mate has not received the list from Škoda.': 'Noch nicht bekannt. Mate hat die Liste noch nicht von Škoda erhalten.', 'This car supports no remote operations.': 'Dieses Auto unterstützt keine Fernfunktionen.',
  'Not available through the official Škoda API': 'Über die offizielle Škoda-API nicht verfügbar', 'These things exist in other apps but the public API does not offer them, so Mate does not pretend to.': 'Das gibt es in anderen Apps, die öffentliche API bietet es aber nicht. Mate tut deshalb nicht so, als ginge es.',
  'Raw data': 'Rohdaten', 'Show raw data': 'Rohdaten anzeigen', 'Hide raw data': 'Rohdaten ausblenden',
  'The raw answer contains your VIN, licence plate and exact position. Do not post it publicly.': 'Die Rohdaten enthalten FIN, Kennzeichen und genaue Position. Poste sie nicht öffentlich.',
  'The last answer exactly as Škoda sent it.': 'Die letzte Antwort genau so, wie Škoda sie gesendet hat.', 'No raw data stored yet.': 'Noch keine Rohdaten gespeichert.',
  'Diagnostics': 'Diagnose', 'Download diagnostics': 'Diagnose herunterladen',
  'A report for bug reports: poller status, data parts, supported operations, recent calls and commands, and the answer from Škoda with VIN, plate, name, position and profile names removed. The API key and S-PIN are never included.':
    'Ein Bericht für Fehlermeldungen: Abfragestatus, Datenbereiche, unterstützte Funktionen, letzte Aufrufe und Befehle sowie die Antwort von Škoda ohne FIN, Kennzeichen, Name, Position und Profilnamen. API-Schlüssel und S-PIN sind nie enthalten.',
  'App': 'App', 'Version': 'Version', 'Health': 'Zustand', 'Connected to Škoda': 'Mit Škoda verbunden', 'Last successful contact': 'Letzter erfolgreicher Kontakt', 'Healthy': 'In Ordnung', 'Demo mode': 'Demo-Modus', 'yes': 'ja', 'no': 'nein',
  'Start charging': 'Laden starten', 'Stop charging': 'Laden stoppen', 'Set charge limit': 'Ladelimit setzen', 'Set charge mode': 'Lademodus setzen', 'Update charging profile': 'Ladeprofil ändern',
  'Start climate': 'Klima starten', 'Stop climate': 'Klima stoppen', 'Start auxiliary heating': 'Standheizung starten', 'Stop auxiliary heating': 'Standheizung stoppen',
  'Start ventilation': 'Lüftung starten', 'Stop ventilation': 'Lüftung stoppen',
  'Lock / unlock': 'Verriegeln / Entriegeln', 'Honk, flash, wake-up': 'Hupen, Blinken, Aufwecken', 'Trip history from the car': 'Fahrtenverlauf vom Auto', 'Driving route and speed trace': 'Fahrstrecke und Geschwindigkeitsverlauf',
  'Charging history import': 'Import des Ladeverlaufs', 'Battery health (SoH)': 'Batteriezustand (SoH)', 'Battery capacity': 'Batteriekapazität', 'Outside temperature': 'Außentemperatur',
  'Service, inspection, warning lights, software version': 'Service, Inspektion, Warnleuchten, Softwareversion', 'Seat and steering-wheel heating, climate timers': 'Sitz- und Lenkradheizung, Klima-Timer',
  'Live updates': 'Live-Updates', 'Send destination to the car, charger search': 'Ziel ans Auto senden, Ladesäulensuche',
  'The public API has no lock or unlock operation. The lock state is shown read-only.': 'Die öffentliche API kennt kein Verriegeln oder Entriegeln. Der Schlossstatus wird nur angezeigt.',
  'Not offered by the public API.': 'Von der öffentlichen API nicht angeboten.',
  'No trip data. Trips are derived by Mate from the odometer and the parked/driving state, so times are accurate to the poll interval.': 'Keine Fahrtdaten. Mate leitet Fahrten aus Kilometerstand und Park-/Fahrzustand ab, die Zeiten sind daher nur auf das Abfrageintervall genau.',
  'Position is not available while driving, and the quota allows ~20 reads per hour.': 'Die Position ist während der Fahrt nicht verfügbar, und das Kontingent erlaubt etwa 20 Abfragen pro Stunde.',
  'No history endpoint. Sessions are detected live from the charging status.': 'Es gibt keinen Verlaufsendpunkt. Ladevorgänge werden live aus dem Ladestatus erkannt.',
  'Not reported. Mate shows an estimate from charges, which includes charging losses.': 'Wird nicht gemeldet. Mate zeigt eine Schätzung aus Ladevorgängen, die Ladeverluste enthält.',
  'Not reported. Enter it in Settings so energy and consumption can be computed.': 'Wird nicht gemeldet. Trage sie in den Einstellungen ein, damit Energie und Verbrauch berechnet werden können.',
  'Not in the public API, so there is no consumption-versus-temperature chart.': 'Nicht in der öffentlichen API, daher gibt es kein Diagramm Verbrauch gegen Temperatur.',
  'Not in the public API.': 'Nicht in der öffentlichen API.', 'Not controllable through the public API.': 'Über die öffentliche API nicht steuerbar.',
  'No push events: Mate polls within Škoda\'s request limit (about 20 per hour per car).': 'Keine Push-Ereignisse: Mate fragt im Rahmen von Škodas Anfragelimit ab (etwa 20 pro Stunde und Auto).',
});

const PART_STATE = { present: 'good', unsupported: '', disabled: 'warn', unavailable: 'warn', missing: 'bad', unknown: '' };
const OP_LABEL = {
  startCharging: 'Start charging', stopCharging: 'Stop charging', setChargingLimit: 'Set charge limit', setChargeMode: 'Set charge mode', updateChargingProfile: 'Update charging profile',
  startAirConditioning: 'Start climate', stopAirConditioning: 'Stop climate', startAuxiliaryHeating: 'Start auxiliary heating', stopAuxiliaryHeating: 'Stop auxiliary heating',
  startActiveVentilation: 'Start ventilation', stopActiveVentilation: 'Stop ventilation',
};
// api_calls.at is epoch seconds (the other timestamps are ISO strings)
const isoOf = (at) => (typeof at === 'number' ? new Date(at * 1000).toISOString() : at);

export default async function system(root, ctx) {
  ctx.setTitle(t('System'));
  const base = `/api/vehicles/${ctx.vid}`;
  const TABS = [['status', 'Status'], ['capabilities', 'Capabilities'], ['calls', 'API calls'], ['diagnostics', 'Diagnostics']];
  const tab = TABS.some(([k]) => k === ctx.params[0]) ? ctx.params[0] : 'status';
  const PAGE = 25;
  let calls = null, callsError = null, health = null, healthError = null, offset = 0, failedOnly = false;

  const fetchCalls = () => ctx.api.get(`${base}/calls?limit=${PAGE}&offset=${offset}${failedOnly ? '&failed=true' : ''}`)
    .then((r) => { calls = r; callsError = null; }).catch((e) => { callsError = e.message; });

  const fetchAll = async () => {
    await Promise.all([
      tab === 'calls' ? fetchCalls() : null,
      fetch('/health').then((r) => r.json()).then((r) => { health = r; healthError = null; }).catch((e) => { healthError = e.message; }),
    ]);
  };

  // ---- budget + poller
  function budgetCard(o) {
    const p = o.poller, b = p?.budget;
    if (!b) return card(t('Request budget'), empty(t('Not connected'), null, 'wifioff'), { ic: 'signal' });
    return card(t('Request budget'), h('div', { class: 'stack' },
      h('div', { class: 'row' }, chip(`${b.used}/${b.limit}`, b.limited || b.remaining <= 0 ? 'warn' : 'good', 'signal'), h('span', { class: 'small' }, t('Requests used in the last hour')),
        b.limited ? chip(t('Limit reached'), 'warn', 'alert') : chip(t('Within the limit'), 'good', 'check')),
      h('div', { class: 'bar', role: 'img', 'aria-label': `${b.used} / ${b.limit}` }, h('i', { style: { width: `${Math.min(100, (b.used / b.limit) * 100)}%` } })),
      kv([[t('Request limit'), `${b.limit} / h`], [t('Reserved for commands'), `${b.reserve} / h`], [t('Left for reading'), b.remaining], [t('Left for commands'), b.remaining_for_commands],
        [t('Škoda reports remaining'), b.header_remaining ?? '–'], [t('Next free slot in'), b.next_free_s ? f.inSeconds(b.next_free_s) : '–']]),
      h('div', { class: 'tiny muted' }, t('Škoda allows about 20 requests per hour per car. Every reading and every command costs one request.'))), { ic: 'signal' });
  }

  function pollerCard(o) {
    const p = o.poller;
    if (!p || !p.known) return card(t('Polling status'), empty(t('Not connected'), null, 'wifioff'), { ic: 'refresh' });
    return card(t('Polling status'), h('div', { class: 'stack' },
      p.blocked ? banner('bad', t('Blocked'), ': ', t('Reading is blocked until the key is replaced.'), ' ', h('a', { href: '#/settings' }, t('Settings'))) : null,
      kv([
        [t('Last successful reading'), p.last_ok ? `${f.dateTime(p.last_ok)} (${f.ago(p.last_ok)})` : '–'],
        [t('Car reported'), p.captured_at ? f.ago(p.captured_at) : '–'],
        [t('Next reading in'), p.next_poll_in != null && !p.blocked ? f.inSeconds(p.next_poll_in) : '–'],
        [t('Mode'), p.active ? t('Active (car is busy)') : t('Idle')],
        [t('Intervals'), p.interval ? `${f.inSeconds(p.interval.idle)} ${t('idle')} · ${f.inSeconds(p.interval.active)} ${t('active')}` : '–'],
        [t('Readings so far'), p.polls ?? '–'],
        [t('API key expires'), p.key_expires_at ? f.date(p.key_expires_at) : '–'],
        [t('Last error'), p.error ? `${p.error}${p.error_kind ? ` (${p.error_kind})` : ''}` : t('none')],
      ])), { ic: 'refresh' });
  }

  // ---- calls
  function callsCard() {
    const go = async (o, failed = failedOnly) => { offset = o; failedOnly = failed; calls = null; draw(); await fetchCalls(); draw(); };
    let body;
    if (callsError) body = h('div', { class: 'stack' }, banner('bad', `${t('Could not load')}: ${callsError}`), button(t('Try again'), { ic: 'refresh', onClick: () => go(offset) }));
    else if (!calls) body = loading();
    else {
      const from = calls.total ? offset + 1 : 0, to = Math.min(offset + PAGE, calls.total);
      const pager = calls.total > PAGE ? h('div', { class: 'pager', role: 'navigation', 'aria-label': t('Pages') },
        button(t('Newer'), { ic: 'left', size: 'sm', disabled: offset <= 0, onClick: () => go(Math.max(0, offset - PAGE)) }),
        h('span', { class: 'small muted' }, `${from}–${to} ${t('of')} ${calls.total}`),
        button(`${t('Older')} →`, { size: 'sm', disabled: to >= calls.total, onClick: () => go(offset + PAGE) })) : null;
      body = h('div', { class: 'stack' }, table([
        { label: t('When'), render: (c) => f.dateTime(isoOf(c.at)), cls: 'nowrap' },
        { label: t('Endpoint'), render: (c) => h('code', null, c.endpoint) },
        { label: t('Result'), render: (c) => (c.ok ? chip(t('OK'), 'good', 'check') : h('div', null, chip(t('Failed'), 'bad', 'alert'), c.error ? h('div', { class: 'tiny' }, c.error) : null)) },
      ], calls.items, { label: t('Recent API calls'), emptyNode: empty(failedOnly ? t('No failed calls.') : t('No calls yet.'), null, 'list') }), pager);
    }
    const filter = h('label', { class: 'b-check' }, h('input', { type: 'checkbox', checked: failedOnly, onchange: (e) => go(0, e.target.checked) }), t('Only failed'));
    return card(t('Recent API calls'), h('div', { class: 'stack' }, filter, body), { ic: 'list' });
  }

  // ---- parts, errors, operations
  function partsCard(o) {
    const parts = Object.entries(o.parts || {});
    const errs = o.api_errors || [];
    const matrix = table([
      { label: t('Part'), render: ([, p]) => t(p.label) },
      { label: t('State'), render: ([, p]) => chip(t(p.state), PART_STATE[p.state] ?? '', p.state === 'present' ? 'check' : p.state === 'missing' ? 'alert' : 'info') },
      { label: t('Reason'), render: ([, p]) => h('span', { class: 'small muted' }, p.reason ? t(p.reason) : '–') },
    ], parts, { label: t('Data parts') });
    return card(t('Data parts'), h('div', { class: 'stack' }, h('div', { class: 'small muted' }, t('What the car reports, part by part.')), matrix,
      h('h3', null, t('Errors reported by Škoda')),
      errs.length ? h('ul', { class: 'b-notes small' }, ...errs.map((e) => h('li', null, h('code', null, e.type), e.description ? ` — ${t(e.description)}` : ''))) : h('div', { class: 'small muted' }, t('No errors reported.'))), { ic: 'shield' });
  }

  function opsCard(o) {
    const ops = o.operations;
    return card(t('Supported operations'), h('div', { class: 'stack' }, h('div', { class: 'small muted' }, t('Remote operations this car accepts. Controls for anything else are shown disabled.')),
      ops == null ? h('div', { class: 'small' }, t('Not known yet. Mate has not received the list from Škoda.'))
        : ops.length ? h('div', { class: 'row tight' }, ...ops.map((op) => h('span', { class: 'chip good', title: op }, icon('check', { size: 13 }), t(OP_LABEL[op] || op))))
          : h('div', { class: 'small' }, t('This car supports no remote operations.'))), { ic: 'sliders' });
  }


  // ---- raw viewer (loaded only when opened: it contains VIN and position)
  function rawCard() {
    const pre = h('pre', { class: 'b-raw', tabindex: 0, 'aria-label': t('Raw data') });
    const status = h('div');
    let loaded = false;
    const load = async () => {
      mount(status, loading());
      try {
        const r = await ctx.api.get(`${base}/raw`);
        pre.textContent = Object.keys(r || {}).length ? JSON.stringify(r, null, 2) : '';
        mount(status, Object.keys(r || {}).length ? null : empty(t('No raw data stored yet.'), null, 'info'));
        loaded = true;
      } catch (e) {
        mount(status, banner('bad', `${t('Could not load')}: ${e.message}`), button(t('Try again'), { ic: 'refresh', onClick: load }));
      }
    };
    const det = h('details', { class: 'b-rawbox', ontoggle: () => { if (det.open && !loaded) load(); } },
      h('summary', null, t('Show raw data')),
      h('div', { class: 'stack' }, banner('warn', t('The raw answer contains your VIN, licence plate and exact position. Do not post it publicly.')),
        h('div', { class: 'tiny muted' }, t('The last answer exactly as Škoda sent it.')), status, pre));
    return card(t('Raw data'), det, { ic: 'activity' });
  }

  function diagCard() {
    return card(t('Diagnostics'), h('div', { class: 'stack' },
      h('div', { class: 'small muted' }, t('A report for bug reports: poller status, data parts, supported operations, recent calls and commands, and the answer from Škoda with VIN, plate, name, position and profile names removed. The API key and S-PIN are never included.')),
      h('div', null, h('a', { class: 'btn', href: `${base}/diagnostics`, download: 'skoda-mate-diagnostics.json' }, icon('download', { size: 16 }), t('Download diagnostics')))), { ic: 'download' });
  }

  function appCard(o) {
    return card(t('App'), healthError ? banner('bad', `${t('Could not load')}: ${healthError}`) : !health ? loading() : h('div', { class: 'stack' },
      h('div', { class: 'row' }, health.ok ? chip(t('Healthy'), 'good', 'check') : chip(t('Failed'), 'bad', 'alert'), o.demo ? chip(t('Demo mode'), 'info') : null),
      kv([[t('Version'), `v${health.version}`], [t('Connected to Škoda'), health.connected ? t('yes') : t('no')],
        [t('Last successful contact'), health.last_ok ? f.dateTime(health.last_ok) : '–'], [t('Last error'), health.last_error || t('none')]])), { ic: 'shield' });
  }

  const tabs = () => h('nav', { class: 'tabs', 'aria-label': t('System sections') },
    ...TABS.map(([k, label]) => h('a', { href: k === 'status' ? '#/system' : `#/system/${k}`, 'aria-current': k === tab ? 'page' : null }, t(label))));

  function panel() {
    const o = ctx.overview;
    if (tab === 'calls') return [callsCard()];
    if (tab === 'diagnostics') return [h('div', { class: 'grid g2' }, partsCard(o), h('div', { class: 'stack' }, rawCard(), diagCard()))];
    return [h('div', { class: 'grid g2' }, budgetCard(o), pollerCard(o)), h('div', { class: 'grid g2' }, appCard(o), opsCard(o))];
  }

  function draw() {
    mount(root, h('h1', null, t('System')), tabs(), ...panel());
  }

  if (tab === 'capabilities') {
    mount(root, h('h1', null, t('System')), tabs());
    const inner = h('div', { class: 'stack' });
    root.append(inner);
    await capabilitiesPage(inner, ctx);
    ctx.setTitle(`${t('Capabilities')} · ${t('System')}`);
    return;
  }
  mount(root, h('h1', null, t('System')), tabs(), loading());
  await fetchAll();
  draw();
  // Re-drawing would collapse the raw viewer, so on a tick only refresh the live parts when it is closed.
  ctx.onTick(async () => { if (root.querySelector('.b-rawbox[open]')) return; await fetchAll(); draw(); });
}
