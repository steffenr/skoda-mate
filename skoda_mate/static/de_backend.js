// German for the texts that come from the backend (features.py: Capabilities page, part states) and for raw Škoda API values.
// Keyed by the exact English string; a missing entry falls back to English. Checked by scripts/dom-smoke/german_leaks.mjs.
import { extendDE } from './i18n.js';

// login, setup and request-limit messages from web.py
extendDE({
  'The current password is wrong.': 'Das aktuelle Passwort ist falsch.',
  'Wrong setup code. It is in Mate\'s log and in setup-code.txt in the data folder (or it is your SETUP_CODE).': 'Falscher Einrichtungscode. Er steht im Log von Mate und in setup-code.txt im Datenordner (oder es ist dein SETUP_CODE).',
  'The request is too large.': 'Die Anfrage ist zu groß.',
});

// places: validation, the one-home rule and a missing place
extendDE({
  'Name must be 1 to 60 characters.': 'Der Name muss 1 bis 60 Zeichen lang sein.',
  'Kind must be home, work or place.': 'Die Art muss Heimatort, Arbeit oder Ort sein.',
  'Latitude must be between -90 and 90.': 'Der Breitengrad muss zwischen -90 und 90 liegen.',
  'Longitude must be between -180 and 180.': 'Der Längengrad muss zwischen -180 und 180 liegen.',
  'Radius must be between 20 and 5000 metres.': 'Der Radius muss zwischen 20 und 5000 Metern liegen.',
  'Colour must be a hex colour such as #0b7a52.': 'Die Farbe muss eine Hex-Farbe wie #0b7a52 sein.',
  'Price per kWh must be between 0 and 10.': 'Der Preis pro kWh muss zwischen 0 und 10 liegen.',
  'Price per minute must be between 0 and 10.': 'Der Preis pro Minute muss zwischen 0 und 10 liegen.',
  'Session fee must be between 0 and 1000.': 'Die Grundgebühr muss zwischen 0 und 1000 liegen.',
  'A free place cannot have a price.': 'Ein kostenloser Ort darf keinen Preis haben.',
  'Only one home place is allowed.': 'Es ist nur ein Heimatort erlaubt.',
  'The home place cannot be deleted.': 'Der Heimatort kann nicht gelöscht werden.',
  'The home place cannot change its kind.': 'Der Heimatort kann seine Art nicht ändern.',
  'Place not found.': 'Ort nicht gefunden.',
});

extendDE({
  'AdBlue range': 'AdBlue-Reichweite', 'Address': 'Adresse', 'Allowed without external power': 'Ohne externe Stromversorgung erlaubt', 'At a saved charging location': 'An einem gespeicherten Ladeort',
  'Auxiliary heater': 'Standheizung', 'Battery capacity': 'Batteriekapazität', 'Battery capacity estimate': 'Schätzung der Batteriekapazität', 'Battery care limit': 'Limit der Batterieschonung', 'Battery care mode': 'Batterieschonmodus',
  'Battery health (SoH)': 'Batteriezustand (SoH)', 'Battery level': 'Batteriestand', 'Bonnet': 'Motorhaube', 'Car type': 'Fahrzeugtyp', 'Change the charge mode': 'Lademodus ändern',
  'Changes a saved charging location profile: target level, current, minimum level, preferred charging times, timers, auto-unlock of the plug.': 'Ändert ein gespeichertes Ladeprofil: Ziel-Ladestand, Strom, Mindestladestand, bevorzugte Ladezeiten, Timer, automatisches Entriegeln des Steckers.',
  'Charge limit': 'Ladelimit', 'Charge modes the car offers': 'Lademodi, die das Auto anbietet', 'Charge type': 'Ladeart', 'Charges': 'Ladevorgänge', 'Charging & battery': 'Laden & Batterie',
  'Charging history import': 'Import des Ladeverlaufs', 'Charging power': 'Ladeleistung', 'Charging profiles': 'Ladeprofile', 'Charging rate': 'Laderate', 'Charging state': 'Ladezustand',
  'Chooses how the car charges (manual, timer, preferred times, own current only, …). The car lists the modes it offers.': 'Legt fest, wie das Auto lädt (manuell, Timer, bevorzugte Zeiten, nur eigener Strom, …). Das Auto nennt die Modi, die es anbietet.',
  'Climate': 'Klima',
  'Control → Auxiliary heater': 'Steuerung → Standheizung', 'Control → Auxiliary heater (S-PIN in Settings)': 'Steuerung → Standheizung (S-PIN in den Einstellungen)', 'Control → Charge limit': 'Steuerung → Ladelimit',
  'Control → Charge mode': 'Steuerung → Lademodus', 'Control → Charging profiles': 'Steuerung → Ladeprofile', 'Control → Charging, Overview quick control': 'Steuerung → Laden, Schnellsteuerung auf der Übersicht',
  'Control → Climate': 'Steuerung → Klima', 'Control → Climate, Overview quick control': 'Steuerung → Klima, Schnellsteuerung auf der Übersicht', 'Control → Ventilation': 'Steuerung → Lüftung',
  'Costs and Home vs Public': 'Kosten und Zuhause vs. Öffentlich',
  'Derived from the odometer and the parked/driving state, or imported from the MyŠkoda app\'s trip export. Times are accurate to the poll interval for derived trips.': 'Aus Kilometerstand und Park-/Fahrzustand abgeleitet oder aus dem Fahrten-Export der MyŠkoda-App importiert. Bei abgeleiteten Fahrten sind die Zeiten auf das Abfrageintervall genau.',
  'Disabled for this car (consent, licence or workshop mode)': 'Für dieses Auto deaktiviert (Einwilligung, Lizenz oder Werkstattmodus)',
  'Doors': 'Türen', 'Doors and trunk locked': 'Türen und Kofferraum verriegelt', 'Doors, windows & lights': 'Türen, Fenster & Licht', 'Driving route and speed trace': 'Fahrtroute und Geschwindigkeitsverlauf',
  'Edit a charging profile': 'Ladeprofil bearbeiten', 'Electric range': 'Elektrische Reichweite', 'Everything Mate has recorded can be browsed, exported as CSV and backed up.': 'Alles, was Mate aufgezeichnet hat, lässt sich durchsuchen, als CSV exportieren und sichern.',
  'Fills the time before Mate started from the trip export of the MyŠkoda app (the app seems to keep only about seven months).': 'Füllt die Zeit vor Mates Start aus dem Fahrten-Export der MyŠkoda-App (die App scheint nur etwa sieben Monate zu behalten).',
  'Front window heating': 'Frontscheibenheizung', 'Fuel & range': 'Kraftstoff & Reichweite', 'Fuel & range (combustion and hybrid cars)': 'Kraftstoff & Reichweite (Verbrenner und Hybrid)', 'Fully charged at': 'Voll geladen um',
  'History import': 'Verlaufs-Import', 'Home Assistant': 'Home Assistant', 'Honk, flash, wake-up': 'Hupen, Blinken, Aufwecken', 'Latitude': 'Breitengrad', 'Licence plate': 'Kennzeichen', 'Lights': 'Licht',
  'Live updates': 'Live-Aktualisierungen', 'Lock / unlock': 'Ver- / Entriegeln', 'Locked (all doors)': 'Verriegelt (alle Türen)', 'Longitude': 'Längengrad', 'Maps, events, exports, backup': 'Karten, Ereignisse, Exporte, Sicherung',
  'Maximum AC current': 'Maximaler AC-Strom',
  'Measured while Mate sees the car charging; otherwise inferred from the battery level rising between trips or readings (marked “inferred”).': 'Gemessen, solange Mate das Auto beim Laden sieht; sonst aus dem steigenden Batteriestand zwischen Fahrten oder Messungen abgeleitet (als „abgeleitet“ markiert).',
  'Monthly distance, energy, cost and consumption computed from the trips and charges Mate has stored, plus the odometer for the distance.': 'Monatliche Strecke, Energie, Kosten und Verbrauch, berechnet aus den gespeicherten Fahrten und Ladevorgängen, plus der Kilometerstand für die Strecke.',
  'Name': 'Name', 'Next charging time there': 'Nächste Ladezeit dort', 'No history endpoint. Sessions are detected live from the charging status.': 'Kein Verlaufs-Endpunkt. Ladevorgänge werden live am Ladestatus erkannt.',
  'No push events: Mate polls within Škoda\'s request limit (about 20 per hour per car).': 'Keine Push-Ereignisse: Mate fragt im Rahmen von Škodas Anfragelimit ab (etwa 20 pro Stunde und Auto).',
  'No trip data. Trips are derived by Mate from the odometer and the parked/driving state, so times are accurate to the poll interval.': 'Keine Fahrtdaten. Mate leitet Fahrten aus Kilometerstand und Park-/Fahrzustand ab, die Zeiten sind daher auf das Abfrageintervall genau.',
  'Not controllable through the public API.': 'Über die öffentliche API nicht steuerbar.', 'Not in the public API, so there is no consumption-versus-temperature chart.': 'Nicht in der öffentlichen API, daher gibt es kein Diagramm Verbrauch gegen Temperatur.',
  'Not in the public API.': 'Nicht in der öffentlichen API.', 'Not offered by the public API.': 'Von der öffentlichen API nicht angeboten.', 'Not reported': 'Nicht gemeldet',
  'Not reported. Enter it in Settings so energy and consumption can be computed.': 'Nicht gemeldet. Gib sie in den Einstellungen ein, damit Energie und Verbrauch berechnet werden können.',
  'Not reported. Mate shows an estimate from charges, which includes charging losses.': 'Nicht gemeldet. Mate zeigt eine Schätzung aus Ladevorgängen, die Ladeverluste enthält.',
  'Not supported by this car': 'Von diesem Auto nicht unterstützt', 'Odometer': 'Kilometerstand',
  'One request returns every data part below, in one go. Mate asks for all of them each time, because the request limit is per request, not per part.': 'Eine Anfrage liefert alle Datenbereiche unten auf einmal. Mate fragt jedes Mal alle ab, weil das Limit pro Anfrage gilt, nicht pro Bereich.',
  'Outside temperature': 'Außentemperatur', 'Overview and every page; polled on the intervals set under Settings → Polling': 'Übersicht und jede Seite; abgefragt in den Intervallen unter Einstellungen → Abfrage', 'Picture': 'Bild', 'Plug connection': 'Steckerverbindung', 'Plug lock': 'Steckerverriegelung',
  'Position': 'Position', 'Position is not available while driving, and the quota allows ~20 reads per hour.': 'Während der Fahrt ist keine Position verfügbar, und das Kontingent erlaubt ca. 20 Abfragen pro Stunde.',
  'Pre-conditions the cabin to a target temperature, optionally also without an external power connection.': 'Temperiert den Innenraum auf eine Zieltemperatur, optional auch ohne externe Stromversorgung.',
  'Preferred charge mode': 'Bevorzugter Lademodus', 'Primary engine': 'Primärer Antrieb', 'Primary: battery level': 'Primär: Batteriestand', 'Primary: fuel level': 'Primär: Kraftstoffstand', 'Primary: range': 'Primär: Reichweite',
  'Profile at the current position': 'Profil am aktuellen Standort', 'Profile number there': 'Profilnummer dort', 'Read the vehicle': 'Fahrzeug auslesen', 'Rear window heating': 'Heckscheibenheizung',
  'Reliable lock status': 'Verlässlicher Verriegelungsstatus', 'Reported by the car at': 'Vom Auto gemeldet um', 'Run time': 'Laufzeit', 'Saved profiles': 'Gespeicherte Profile',
  'Seat and steering-wheel heating, climate timers': 'Sitz- und Lenkradheizung, Klima-Timer', 'Secondary engine': 'Sekundärer Antrieb', 'Secondary: battery level': 'Sekundär: Batteriestand', 'Secondary: fuel level': 'Sekundär: Kraftstoffstand', 'Secondary: range': 'Sekundär: Reichweite',
  'Send destination to the car, charger search': 'Ziel an das Auto senden, Ladesäulensuche',
  'Sensors, a position tracker, a charge-limit number and buttons for the commands, over MQTT (optional).': 'Sensoren, ein Positions-Tracker, ein Ladelimit-Regler und Schaltflächen für die Befehle, über MQTT (optional).',
  'Service, inspection, warning lights, software version': 'Service, Inspektion, Warnleuchten, Softwareversion', 'Set the charge limit': 'Ladelimit setzen',
  'Sets the target state of charge. Cars usually accept 50 to 100 % in steps of 10.': 'Setzt den Ziel-Ladestand. Autos akzeptieren meist 50 bis 100 % in 10er-Schritten.',
  'Side windows': 'Seitenscheiben', 'Start charging': 'Laden starten', 'Start mode': 'Startmodus', 'Start the auxiliary heater': 'Standheizung starten', 'Start the climate control': 'Klimatisierung starten', 'Start the ventilation': 'Lüftung starten',
  'Starts a charging session on the connected cable.': 'Startet einen Ladevorgang am angeschlossenen Kabel.', 'Starts the fuel or electric auxiliary heater (cars that have one). Needs your S-PIN.': 'Startet die Kraftstoff- oder Elektro-Standheizung (bei Autos mit Standheizung). Benötigt deine S-PIN.',
  'Starts when the car is unlocked': 'Startet beim Entriegeln des Autos', 'State': 'Zustand', 'Statistics': 'Statistik', 'Stop charging': 'Laden stoppen', 'Stop the auxiliary heater': 'Standheizung stoppen', 'Stop the climate control': 'Klimatisierung stoppen',
  'Stop the ventilation': 'Lüftung stoppen', 'Stops a running air-conditioning process.': 'Stoppt eine laufende Klimatisierung.', 'Stops the auxiliary heater.': 'Stoppt die Standheizung.', 'Stops the running charging session.': 'Stoppt den laufenden Ladevorgang.',
  'Stops the ventilation.': 'Stoppt die Lüftung.', 'Sunroof': 'Schiebedach', 'Target reached at': 'Ziel erreicht um', 'Target temperature': 'Zieltemperatur', 'Target there': 'Ziel dort', 'Temporarily unavailable': 'Vorübergehend nicht verfügbar',
  'The public API has no lock or unlock operation. The lock state is shown read-only.': 'Die öffentliche API hat keine Ver- oder Entriegelungsfunktion. Der Verriegelungsstatus wird nur angezeigt.',
  'Time to fully charged': 'Zeit bis voll geladen', 'Total range': 'Gesamtreichweite', 'Trip history from the car': 'Fahrtenverlauf vom Auto', 'Trips': 'Fahrten', 'Trunk': 'Kofferraum', 'Unlock the plug when charged': 'Stecker nach dem Laden entriegeln',
  'VIN': 'FIN', 'Vehicle': 'Fahrzeug', 'Ventilates the cabin without heating or cooling (cars that have it).': 'Lüftet den Innenraum ohne Heizen oder Kühlen (bei Autos mit dieser Funktion).', 'Ventilation': 'Lüftung',
  'Wall energy per 100 % of charge from long AC charges.': 'Netzenergie pro 100 % Ladung aus langen AC-Ladevorgängen.',
  'Window heating enabled': 'Scheibenheizung aktiviert', 'Your tariff and your home position (set on a map in Settings) applied to the charges.': 'Dein Tarif und deine Heimposition (in den Einstellungen auf einer Karte festgelegt), angewendet auf die Ladevorgänge.',
  'chargeMode (one of the modes the car offers)': 'chargeMode (einer der Modi, die das Auto anbietet)', 'include = which parts (Mate always asks for all)': 'include = welche Bereiche (Mate fragt immer alle ab)', 'none': 'keine',
  'spin, targetTemperature, durationInSeconds, startMode (heating or ventilation)': 'spin, targetTemperature, durationInSeconds, startMode (Heizen oder Lüften)', 'targetStateOfChargeInPercent (1-100)': 'targetStateOfChargeInPercent (1-100)',
  'targetTemperature (°C), airConditioningWithoutExternalPower': 'targetTemperature (°C), airConditioningWithoutExternalPower', 'the whole profile (Mate edits a copy of what the car reported)': 'das ganze Profil (Mate bearbeitet eine Kopie dessen, was das Auto gemeldet hat)',
  'Parameters': 'Parameter', 'Parameter': 'Parameter',
  // data-part states and shared words used with them
  'present': 'vorhanden',
  // raw API values (see tEnum in i18n.js)
  'enum:YES': 'Ja', 'enum:NO': 'Nein', 'enum:ON': 'An', 'enum:OFF': 'Aus', 'enum:OPEN': 'Offen', 'enum:OPENED': 'Offen', 'enum:CLOSED': 'Geschlossen', 'enum:LOCKED': 'Verriegelt', 'enum:UNLOCKED': 'Entriegelt',
  'enum:UNKNOWN': 'Unbekannt', 'enum:UNSUPPORTED': 'Nicht unterstützt', 'enum:INVALID': 'Ungültig', 'enum:TRUNK_OPENED': 'Kofferraum offen', 'enum:PARKED': 'Geparkt', 'enum:IN_MOTION': 'In Fahrt',
  'enum:CONNECTED': 'Verbunden', 'enum:DISCONNECTED': 'Getrennt', 'enum:CHARGING': 'Lädt', 'enum:READY_FOR_CHARGING': 'Bereit zum Laden', 'enum:CONNECT_CABLE': 'Kabel anschließen', 'enum:CONSERVING': 'Batterieschonung',
  'enum:DISCHARGING': 'Entlädt', 'enum:CHARGING_INTERRUPTED': 'Laden unterbrochen', 'enum:AC': 'AC', 'enum:DC': 'DC', 'enum:COOLING': 'Kühlen', 'enum:HEATING': 'Heizen', 'enum:HEATING_AUXILIARY': 'Heizen (Standheizung)',
  'enum:VENTILATION': 'Lüften', 'enum:PREHEATING': 'Vorheizen', 'enum:COMPLETED': 'Abgeschlossen', 'enum:MANUAL': 'Manuell', 'enum:TIMER': 'Timer', 'enum:TIMER_CHARGING_WITH_CLIMATISATION': 'Timer-Laden mit Klimatisierung',
  'enum:PREFERRED_CHARGING_TIMES': 'Bevorzugte Ladezeiten', 'enum:ONLY_OWN_CURRENT': 'Nur eigener Strom', 'enum:IMMEDIATE_DISCHARGING': 'Sofort entladen', 'enum:HOME_STORAGE_CHARGING': 'Heimspeicher-Laden',
  'enum:PERMANENT': 'Dauerhaft', 'enum:MAXIMUM': 'Maximal', 'enum:REDUCED': 'Reduziert', 'enum:ACTIVATED': 'Aktiviert', 'enum:DEACTIVATED': 'Deaktiviert', 'enum:ELECTRIC': 'Elektrisch', 'enum:GASOLINE': 'Benzin',
  'enum:DIESEL': 'Diesel', 'enum:CNG': 'Erdgas (CNG)', 'enum:LPG': 'Autogas (LPG)', 'enum:HYBRID': 'Hybrid', 'enum:HEATING_AUXILIARY_': 'Heizen (Standheizung)', 'enum:RECURRING': 'Wiederkehrend', 'enum:ONE_OFF': 'Einmalig',
  'enum:CELSIUS': '°C', 'enum:FAHRENHEIT': '°F', 'enum:MONDAY': 'Montag', 'enum:TUESDAY': 'Dienstag', 'enum:WEDNESDAY': 'Mittwoch', 'enum:THURSDAY': 'Donnerstag', 'enum:FRIDAY': 'Freitag', 'enum:SATURDAY': 'Samstag', 'enum:SUNDAY': 'Sonntag',
});

extendDE({
  'Wall energy per 100 % SoC from AC charges of 30 %+ (includes charging losses). MyŠkoda does not report battery health.': 'Netzenergie pro 100 % Ladestand aus AC-Ladevorgängen ab 30 % (inklusive Ladeverlusten). MyŠkoda meldet keinen Batteriezustand.',
  'The vehicle has no auxiliary heater': 'Das Fahrzeug hat keine Standheizung', 'The vehicle has no active ventilation': 'Das Fahrzeug hat keine aktive Lüftung',
});

extendDE({
  'Add your S-PIN under Settings first.': 'Hinterlege zuerst deine S-PIN in den Einstellungen.', 'Waiting for the car to confirm …': 'Warte auf die Bestätigung des Autos …',
  'Plug in the car to start charging.': 'Stecke das Auto an, um das Laden zu starten.', 'Not plugged in: the climate runs on the battery.': 'Nicht angesteckt: Die Klimatisierung läuft über die Batterie.',
});

extendDE({
  'Not supported by your car': 'Von deinem Auto nicht unterstützt', 'The Škoda API offers these, but your car does not report them.': 'Die Škoda-API bietet diese, aber dein Auto meldet sie nicht.', 'Would report': 'Würde melden',
});

extendDE({
  'The Škoda API can only change existing profiles. Create a new one in the MyŠkoda app or in the car; it appears here after the next reading.': 'Die Škoda-API kann nur bestehende Profile ändern. Lege ein neues in der MyŠkoda-App oder im Auto an; es erscheint hier nach der nächsten Messung.',
});

extendDE({
  'Auto uses your home place from Charge prices.': 'Automatisch verwendet deinen Heimatort aus den Ladepreisen.',
  'Prices per kWh and your home place moved to their own page.': 'Preise pro kWh und dein Heimatort haben jetzt eine eigene Seite.',
  'Open charge prices': 'Ladepreise öffnen',
  'Costs use your prices from Charge prices; charges away from your home position count as public.': 'Kosten nutzen deine Preise aus den Ladepreisen; Ladevorgänge außerhalb deiner Heimposition zählen als öffentlich.',
});

// Home Assistant (MQTT) card in Settings, and the messages the server sends for it
extendDE({
  'MQTT → Home Assistant': 'MQTT → Home Assistant',
  'Makes the car available in Home Assistant as native entities (sensors and commands) through MQTT discovery.': 'Stellt das Auto in Home Assistant als native Entitäten (Sensoren und Befehle) per MQTT-Discovery bereit.',
  'Could not load the Home Assistant settings': 'Die Home-Assistant-Einstellungen konnten nicht geladen werden',
  'This is currently set by environment variables (MQTT_HOST …). Saving here replaces them.': 'Dies ist aktuell über Umgebungsvariablen (MQTT_HOST …) gesetzt. Speichern hier ersetzt sie.',
  'Enabled': 'Aktiviert', 'Broker': 'Broker', 'Port': 'Port', 'Username': 'Benutzername', 'Password': 'Passwort', 'Topic prefix': 'Topic-Präfix', 'Discovery': 'Discovery', 'TLS insecure': 'TLS unsicher',
  'Change it only if several Mate installations talk to the same broker: it keeps their entities and commands apart. Otherwise leave it.': 'Ändere ihn nur, wenn mehrere Mate-Installationen mit demselben Broker sprechen: Er trennt deren Entitäten und Befehle. Sonst so lassen.',
  '•••••••• (stored; leave empty to keep)': '•••••••• (gespeichert; leer lassen zum Behalten)', 'Stored, but cannot be read: enter it again': 'Gespeichert, aber nicht lesbar: bitte erneut eingeben',
  'Remove the stored password': 'Gespeichertes Passwort entfernen', 'The stored password will be removed when you save.': 'Das gespeicherte Passwort wird beim Speichern entfernt.',
  'Test connection': 'Verbindung testen', 'Save': 'Speichern', 'Saved. Mate is connecting to Home Assistant.': 'Gespeichert. Mate verbindet sich mit Home Assistant.', 'Saved.': 'Gespeichert.',
  'Connected': 'Verbunden', 'Connecting …': 'Verbinde …', 'Not connected': 'Nicht verbunden', 'Disabled': 'Deaktiviert', 'Waiting for the Škoda connection': 'Warte auf die Škoda-Verbindung',
  'entities for': 'Entitäten für', 'car': 'Auto', 'cars': 'Autos', 'last update sent': 'letzte Aktualisierung gesendet',
  'How to connect Home Assistant (step by step)': 'So verbindest du Home Assistant (Schritt für Schritt)',
  'Make sure an MQTT broker runs.': 'Stelle sicher, dass ein MQTT-Broker läuft.',
  'In Home Assistant: Settings → Add-ons → Add-on store → “Mosquitto broker” → Install → Start, and switch on “Start on boot”. (Home Assistant OS or Supervised. If you run Home Assistant in Docker or as Core, use your own Mosquitto broker instead.)': 'In Home Assistant: Einstellungen → Add-ons → Add-on-Store → „Mosquitto broker“ → Installieren → Starten und „Beim Start starten“ aktivieren. (Home Assistant OS oder Supervised. Läuft Home Assistant in Docker oder als Core, nutze stattdessen deinen eigenen Mosquitto-Broker.)',
  'Create a user for Mate.': 'Lege einen Benutzer für Mate an.',
  'Settings → People → Users → Add user, for example “skoda_mate” with a password. It needs no administrator rights. The Mosquitto add-on accepts Home Assistant users.': 'Einstellungen → Personen → Benutzer → Benutzer hinzufügen, zum Beispiel „skoda_mate“ mit einem Passwort. Administratorrechte sind nicht nötig. Das Mosquitto-Add-on akzeptiert Home-Assistant-Benutzer.',
  'Add the MQTT integration.': 'Füge die MQTT-Integration hinzu.',
  'Settings → Devices & services → Add integration → MQTT. Broker: core-mosquitto (or the IP address), port 1883, and the user and password from step 2. Leave “Enable discovery” on (discovery prefix: {prefix}).': 'Einstellungen → Geräte & Dienste → Integration hinzufügen → MQTT. Broker: core-mosquitto (oder die IP-Adresse), Port 1883, dazu Benutzer und Passwort aus Schritt 2. „Discovery aktivieren“ eingeschaltet lassen (Discovery-Präfix: {prefix}).',
  'Fill in the form above.': 'Fülle das Formular oben aus.',
  'Broker = the IP address of the machine that runs the broker, usually the IP address of Home Assistant (for example 192.168.1.10). Port 1883, the user and password from step 2. Keep the topic prefix and keep “Discovery” ticked.': 'Broker = die IP-Adresse des Rechners, auf dem der Broker läuft, meist die IP-Adresse von Home Assistant (zum Beispiel 192.168.1.10). Port 1883, Benutzer und Passwort aus Schritt 2. Topic-Präfix beibehalten und „Discovery“ angehakt lassen.',
  'Test, enable, save.': 'Testen, aktivieren, speichern.',
  'Press “Test connection”. When it says “Connected”, tick “Enabled” and press “Save”. No restart is needed.': 'Drücke „Verbindung testen“. Sobald dort „Verbunden“ steht, hake „Aktiviert“ an und drücke „Speichern“. Ein Neustart ist nicht nötig.',
  'Find your car in Home Assistant.': 'Finde dein Auto in Home Assistant.',
  'Settings → Devices & services → MQTT → Devices: your car appears as a device with all its entities. Add them to a dashboard: Overview → pencil icon → Add card → Tile or Entities.': 'Einstellungen → Geräte & Dienste → MQTT → Geräte: Dein Auto erscheint als Gerät mit allen Entitäten. Füge sie einem Dashboard hinzu: Übersicht → Stiftsymbol → Karte hinzufügen → Kachel oder Entitäten.',
  'Mate runs in Docker or DDEV?': 'Mate läuft in Docker oder DDEV?',
  'Then “localhost” and “homeassistant.local” usually do not work from inside the container. Use the IP address of Home Assistant.': 'Dann funktionieren „localhost“ und „homeassistant.local“ aus dem Container meist nicht. Nutze die IP-Adresse von Home Assistant.',
  'What you get': 'Was du bekommst', 'Sensors': 'Sensoren', 'Mate’s own values': 'Mates eigene Werte', 'Binary sensors': 'Binärsensoren', 'Position': 'Position', 'Controls': 'Steuerung',
  'battery, range, charging power, charge limit, time to full, charge state and type, odometer, climate, auxiliary heater, ventilation, fuel, last update.': 'Batterie, Reichweite, Ladeleistung, Ladelimit, Zeit bis voll, Ladezustand und -art, Kilometerstand, Klima, Standheizung, Lüftung, Kraftstoff, letzte Aktualisierung.',
  'last trip distance, energy and consumption; last charge energy and cost.': 'Strecke, Energie und Verbrauch der letzten Fahrt; Energie und Kosten des letzten Ladevorgangs.',
  'charging, plug connected, plug locked, doors, windows, trunk, bonnet, lights, driving, unlocked (read-only: the API cannot lock).': 'lädt, Stecker verbunden, Stecker verriegelt, Türen, Fenster, Kofferraum, Motorhaube, Licht, unterwegs, entriegelt (nur lesend: Die API kann nicht verriegeln).',
  'a device tracker, so the car shows on the Home Assistant map.': 'ein Gerätetracker, damit das Auto auf der Home-Assistant-Karte erscheint.',
  'only if “Allow commands from Home Assistant” is ticked: buttons to start and stop charging, climate and ventilation, to stop the auxiliary heater, and a charge-limit slider. They use the same request budget as the Control page.': 'nur wenn „Befehle aus Home Assistant erlauben“ angehakt ist: Tasten zum Starten und Stoppen von Laden, Klima und Lüftung, zum Stoppen der Standheizung sowie ein Ladelimit-Regler. Sie nutzen dasselbe Anfragebudget wie die Seite „Steuerung“.',
  'Allow commands from Home Assistant': 'Befehle aus Home Assistant erlauben',
  'Buttons for charging, climate and ventilation and a charge-limit slider; at most one command every 30 s. The auxiliary heater can only be started on the Control page.': 'Tasten für Laden, Klima und Lüftung sowie ein Ladelimit-Regler; höchstens ein Befehl alle 30 s. Die Standheizung lässt sich nur auf der Seite „Steuerung“ starten.',
  'Anyone who can publish to your broker can then control these functions. Use broker ACLs and TLS.': 'Wer auf deinem Broker veröffentlichen kann, kann diese Funktionen dann steuern. Nutze Broker-ACLs und TLS.',
  'If something does not work': 'Wenn etwas nicht funktioniert',
  '“Cannot reach …”': '„Cannot reach …“ (nicht erreichbar)', 'wrong IP or port, the broker is not running, or a firewall blocks port 1883.': 'falsche IP oder falscher Port, der Broker läuft nicht oder eine Firewall blockiert Port 1883.',
  '“refused the user name or password”': '„refused the user name or password“ (Benutzername oder Passwort abgelehnt)', 'check the user and password; the user must exist in Home Assistant.': 'prüfe Benutzer und Passwort; der Benutzer muss in Home Assistant existieren.',
  'No device appears': 'Es erscheint kein Gerät', 'make sure “Discovery” is ticked here and “Enable discovery” is on in the MQTT integration, with the same discovery prefix.': 'stelle sicher, dass „Discovery“ hier angehakt und „Discovery aktivieren“ in der MQTT-Integration eingeschaltet ist, mit demselben Discovery-Präfix.',
  'Entities show “unavailable”': 'Entitäten zeigen „nicht verfügbar“', 'Mate is stopped or cannot reach the broker. Mate marks them available again by itself once it reconnects.': 'Mate ist gestoppt oder erreicht den Broker nicht. Sobald Mate sich wieder verbindet, markiert es sie von selbst wieder als verfügbar.',
  'Two Mate installations, one broker': 'Zwei Mate-Installationen, ein Broker', 'give each one its own topic prefix.': 'gib jeder ein eigenes Topic-Präfix.',
  // messages from the server
  'Connected to the broker.': 'Mit dem Broker verbunden.',
  'The broker refused the user name or password. Check both (in Home Assistant: the user must exist and be allowed to use MQTT).': 'Der Broker hat Benutzername oder Passwort abgelehnt. Prüfe beides (in Home Assistant muss der Benutzer existieren und MQTT nutzen dürfen).',
  'The broker address may only contain letters, digits, dots, dashes and colons (no http:// and no spaces).': 'Die Broker-Adresse darf nur Buchstaben, Ziffern, Punkte, Bindestriche und Doppelpunkte enthalten (kein http:// und keine Leerzeichen).',
  'The port must be a number between 1 and 65535.': 'Der Port muss eine Zahl zwischen 1 und 65535 sein.',
  'The topic prefix may only contain letters, digits, - and _ (no slashes), up to 40 characters.': 'Das Topic-Präfix darf nur Buchstaben, Ziffern, - und _ enthalten (keine Schrägstriche), höchstens 40 Zeichen.',
  'Enter the broker address (the IP address or name of the computer running Home Assistant\'s MQTT broker).': 'Gib die Broker-Adresse ein (IP-Adresse oder Name des Rechners, auf dem der MQTT-Broker von Home Assistant läuft).',
  'Enter the broker address first.': 'Gib zuerst die Broker-Adresse ein.',
  'Enter the password again: the broker address changed.': 'Gib das Passwort erneut ein: Die Broker-Adresse hat sich geändert.',
  'Unknown action.': 'Unbekannte Aktion.',
  'Unknown check.': 'Unbekannte Prüfung.',
  // activity timeline and parked loss: refused ranges and parameters
  'The start must be before the end.': 'Der Beginn muss vor dem Ende liegen.',
  'The range is limited to 31 days.': 'Der Zeitraum ist auf 31 Tage begrenzt.',
  'min_hours must be between 1 and 168.': 'Die Mindestdauer muss zwischen 1 und 168 Stunden liegen.',
  'min_hours must be greater than 0.': 'Die Mindestdauer muss größer als 0 sein.',
});
