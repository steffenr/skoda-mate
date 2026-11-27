// Minimal i18n: pages write English with t('English text'); a catalog looks it up by that exact string and falls back
// to English, so a missing entry is never an error. One catalog is loaded at a time; English needs none.
// Placeholders are {named}. A key may carry a context, 'Open##action', when one English text needs two translations.

/** @typedef {Record<string, string | Record<string, string>>} Catalog  an object value holds plural forms */
/** @type {Record<string, () => Promise<Catalog>>} */
export const CATALOGS = {};

let lang = 'en';
let locale = 'en';
let current = {};
let latest = 0;

/** Switch language. The page keeps its old texts until the catalog is there; when switches overlap, the last one wins. */
export async function setLang(code, bcp47) {
  const mine = ++latest;
  let loaded = {};
  if (Object.hasOwn(CATALOGS, code)) {
    try { loaded = await CATALOGS[code](); } catch (e) { console.warn(`translation ${code} not loaded, showing English`, e); }
  }
  if (mine !== latest) return;
  lang = code;
  locale = bcp47 ?? code;
  current = loaded;
}
export const getLang = () => lang;
export const getLocale = () => locale;
export const catalog = () => current;

const DE = {
  'Loading…': 'Lädt …', 'Nothing here yet': 'Noch nichts vorhanden', 'Cancel': 'Abbrechen', 'Confirm': 'Bestätigen',
  'Overview': 'Übersicht', 'Trips': 'Fahrten', 'Charges': 'Ladevorgänge', 'Prices': 'Preise', 'Battery': 'Batterie', 'Control': 'Steuerung',
  'Statistics': 'Statistik', 'Map': 'Karte', 'Events': 'Ereignisse', 'Settings': 'Einstellungen', 'System': 'System',
  'Refresh now': 'Jetzt aktualisieren', 'Sign out': 'Abmelden', 'Charge limit': 'Ladelimit', 'Battery unknown': 'Batterie unbekannt',
  'Range': 'Reichweite', 'Charging': 'Lädt', 'Parked': 'Geparkt', 'Driving': 'Unterwegs', 'Locked': 'Verriegelt', 'Unlocked': 'Entriegelt',
  'Today': 'Heute', 'Yesterday': 'Gestern', 'Distance': 'Strecke', 'Duration': 'Dauer', 'Energy': 'Energie', 'Consumption': 'Verbrauch',
  'Cost': 'Kosten', 'Start': 'Start', 'End': 'Ende', 'Home': 'Zuhause', 'Public': 'Öffentlich', 'Save': 'Speichern',
  'Key expires': 'Schlüssel läuft ab', 'Not available': 'Nicht verfügbar', 'Odometer': 'Kilometerstand', 'Climate': 'Klima',
  'Doors': 'Türen', 'Windows': 'Fenster', 'Demo': 'Demo', 'requests used this hour': 'Anfragen in dieser Stunde', 'Last update from the car': 'Letzte Meldung des Autos', 'Updated': 'Aktualisiert',
};
const lookup = (key) => (Object.hasOwn(current, key) ? current[key] : lang === 'de' && Object.hasOwn(DE, key) ? DE[key] : undefined);
const english = (key) => key.replace(/##.*$/s, '');
// One pass over the template: a value that itself looks like {a placeholder} stays as it is.
const fill = (template, vars) => (vars ? template.replace(/\{(\w+)\}/g, (m, k) => (Object.hasOwn(vars, k) ? String(vars[k]) : m)) : template);

export function t(key, vars) {
  const found = lookup(key);
  return fill(typeof found === 'string' && found ? found : english(key), vars);
}

/** A text with a count: tn('{n} day', '{n} days', days). The catalog entry sits under `other` and holds the forms its
 *  language has; the CLDR rules of the locale pick one. `vars.n` is shown instead of `n` (a formatted number). */
export function tn(one, other, n, vars) {
  const values = { n, ...vars };
  const forms = lookup(other);
  const form = forms && typeof forms === 'object' ? forms[new Intl.PluralRules(locale).select(Number(n))] ?? forms.other : undefined;
  if (form) return fill(form, values);
  return fill(english(new Intl.PluralRules('en').select(Number(n)) === 'one' ? one : other), values);
}

/** Marks a text that reaches t() through a variable, so the extractor sees it. */
export const N_ = (key) => key;
export const hasKey = (key) => Object.hasOwn(current, key) || (lang === 'de' && Object.hasOwn(DE, key));
export function extendDE(entries) { Object.assign(DE, entries); }
extendDE({
  'The server does not know this feature yet. Mate is probably still running an older version: restart it (ddev restart, or docker compose up -d --build).': 'Der Server kennt diese Funktion noch nicht. Mate läuft vermutlich noch in einer älteren Version: Starte es neu (ddev restart oder docker compose up -d --build).',
  // shell (app.js)
  'More': 'Mehr', 'Close': 'Schließen', 'next check in': 'nächste Prüfung in', 'Updated from Škoda': 'Von Škoda aktualisiert',
  'Could not refresh': 'Aktualisierung fehlgeschlagen', 'Reads the car once (uses 1 of your 20 requests per hour)': 'Liest das Auto einmal aus (verbraucht 1 deiner 20 Anfragen pro Stunde)',
  'Requests to Škoda used this hour': 'Anfragen an Škoda in dieser Stunde', 'of': 'von', 'for reading': 'zum Lesen', 'the rest is kept for commands': 'der Rest bleibt für Befehle reserviert', 'Details on the System page.': 'Details auf der Seite „System“.', 'Requests used this hour': 'Anfragen in dieser Stunde',
  'Switch car': 'Auto wechseln', 'Switch to light theme': 'Zum hellen Design wechseln', 'Switch to dark theme': 'Zum dunklen Design wechseln', 'Škoda is not accepting the request': 'Škoda akzeptiert die Anfrage nicht', 'Request limit reached; Mate waits for the next free slot.': 'Anfragelimit erreicht; Mate wartet auf den nächsten freien Platz.', 'Mate has not read the car for a while.': 'Mate hat das Auto seit einer Weile nicht ausgelesen.', 'Connected: Mate read the car recently.': 'Verbunden: Mate hat das Auto kürzlich ausgelesen.',
  'requests/h': 'Anfragen/h', 'Toggle theme': 'Design wechseln', 'Škoda is not accepting the API key.': 'Škoda akzeptiert den API-Schlüssel nicht.',
  'Update the key': 'Schlüssel erneuern', 'Mate will retry automatically.': 'Mate versucht es automatisch erneut.', 'The API key has expired.': 'Der API-Schlüssel ist abgelaufen.',
  'The API key expires in': 'Der API-Schlüssel läuft ab in', 'day': 'Tag', 'days': 'Tagen',
  'Create a new one in the MyŠkoda app and enter it here.': 'Erstelle in der MyŠkoda-App einen neuen und gib ihn hier ein.',
  'Page not found': 'Seite nicht gefunden', 'No vehicle yet': 'Noch kein Fahrzeug', 'Waiting for the first reading from Škoda…': 'Warte auf die erste Messung von Škoda …',
  'This page is not available yet': 'Diese Seite ist noch nicht verfügbar', 'Something went wrong on this page.': 'Auf dieser Seite ist etwas schiefgelaufen.',
  'Cooling': 'Kühlen', 'Heating': 'Heizen', 'Heating (auxiliary heater)': 'Heizen (Standheizung)', 'Ventilation': 'Lüften', 'Running': 'Läuft',
  // car + map
  'Car': 'Auto', 'Door open': 'Tür offen', 'Window open': 'Fenster offen', 'Trunk open': 'Kofferraum offen', 'Bonnet open': 'Motorhaube offen',
  'The map could not be loaded': 'Die Karte konnte nicht geladen werden',
  // charge detail
  'Use the location of this charge as your home. Charges within the home radius then count as Home.': 'Den Ort dieses Ladevorgangs als Zuhause verwenden. Ladevorgänge im Heimradius zählen dann als Zuhause.',
  'This charge has no known location.': 'Für diesen Ladevorgang ist kein Ort bekannt.',
  // overview
  'range': 'Reichweite', 'Fuel': 'Kraftstoff', 'full at': 'voll um', 'No battery or fuel data reported by this car.': 'Das Auto meldet keine Batterie- oder Kraftstoffdaten.',
  'Doors, windows & locks': 'Türen, Fenster & Schlösser', 'door open': 'Tür offen', 'window open': 'Fenster offen', 'trunk open': 'Kofferraum offen',
  'bonnet open': 'Motorhaube offen', 'lights on': 'Licht an', 'everything closed': 'alles geschlossen', 'Plug': 'Stecker', 'cable locked': 'Kabel verriegelt',
  'cable unlocked': 'Kabel entriegelt', 'Driving: the position is not reported while moving': 'Unterwegs: während der Fahrt wird keine Position gemeldet',
  'Parked here': 'Hier geparkt', 'Position': 'Position', 'No position': 'Keine Position', 'reported': 'gemeldet', 'Last trip': 'Letzte Fahrt',
  'No trips yet': 'Noch keine Fahrten', 'Last charge': 'Letzter Ladevorgang', 'No charges yet': 'Noch keine Ladevorgänge', 'Battery, last 48 hours': 'Batterie, letzte 48 Stunden',
  'Sent. The car confirms on the next reading.': 'Gesendet. Das Auto bestätigt es bei der nächsten Messung.', 'Quick controls': 'Schnellsteuerung',
  'Škoda confirms commands with a short delay. More options under Control.': 'Škoda bestätigt Befehle mit kurzer Verzögerung. Mehr Optionen unter Steuerung.',
});
export const hasDE = (en) => Object.prototype.hasOwnProperty.call(DE, en);  // for the translation coverage check
extendDE({
  'Windows closed': 'Fenster geschlossen', 'Windows: unknown': 'Fenster: unbekannt', 'Doors locked': 'Türen verriegelt', 'Doors: unknown': 'Türen: unbekannt', 'to': 'bis',
  'Sunroof open': 'Schiebedach offen', 'Trunk and bonnet closed': 'Kofferraum und Motorhaube geschlossen', 'Trunk, bonnet and sunroof closed': 'Kofferraum, Motorhaube und Schiebedach geschlossen', 'Lights off': 'Licht aus',
});
export const dictionary = () => DE;  // for the translation leak crawler

/** A raw Škoda API value (READY_FOR_CHARGING, CLOSED, …) as readable text in the current language. */
export function tEnum(v) {
  if (typeof v !== 'string' || !/^[A-Z][A-Z0-9_]+$/.test(v)) return v;
  const human = v.charAt(0) + v.slice(1).toLowerCase().replaceAll('_', ' ');
  return (lang === 'de' && DE[`enum:${v}`]) || human;
}
extendDE({
  'Everything closed and locked': 'Alles geschlossen und verriegelt', 'Check the car': 'Bitte prüfen', 'Status not reported': 'Status nicht gemeldet', 'Status only partly reported': 'Status nur teilweise gemeldet',
  'Trunk & bonnet': 'Kofferraum & Motorhaube', 'Lights': 'Licht', 'Open': 'Offen', 'Closed': 'Geschlossen', 'On': 'An', 'Off': 'Aus', 'Unknown': 'Unbekannt', 'Locked': 'Verriegelt', 'Unlocked': 'Entriegelt', 'Windows': 'Fenster', 'Doors': 'Türen',
});
