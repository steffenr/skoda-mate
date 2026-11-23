// Import the trip history exported from the MyŠkoda app (CSV). Preview first (nothing is saved), then import.
// Duplicates are handled by the server (see skoda_mate/importer.py): overlapping files, re-imports and trips Mate
// already has are recognised, so importing is always safe to repeat.
import { h, mount } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { asyncButton, banner, button, card, chip, empty, field, stat, table, toast } from '../lib/ui.js';
import * as f from '../lib/format.js';
import { extendDE, t } from '../i18n.js';

extendDE({
  'Import trips': 'Fahrten importieren', 'Back to trips': 'Zurück zu den Fahrten',
  'How to export your trips from the MyŠkoda app': 'So exportierst du deine Fahrten aus der MyŠkoda-App',
  'Open the MyŠkoda app and select your car.': 'Öffne die MyŠkoda-App und wähle dein Auto.',
  'Open the trip statistics (the list of your trips). Menu names can differ slightly between app versions.': 'Öffne die Fahrtstatistik (die Liste deiner Fahrten). Die Menünamen können sich je nach App-Version leicht unterscheiden.',
  'Choose the period you want and use the export (share) button to save a CSV file. The app names it tripStatistics_<VIN>.csv, or tripStatistics_from_DDMMYYYY_to_DDMMYYYY_<VIN>.csv for a chosen period.': 'Wähle den gewünschten Zeitraum und speichere mit der Export-Schaltfläche (Teilen) eine CSV-Datei. Die App nennt sie tripStatistics_<FIN>.csv, bei einem gewählten Zeitraum tripStatistics_from_TTMMJJJJ_to_TTMMJJJJ_<FIN>.csv.',
  'Move the file(s) to this computer (AirDrop, e-mail, cloud drive) and choose them below. You can pick several files at once.': 'Übertrage die Datei(en) auf diesen Computer (AirDrop, E-Mail, Cloud) und wähle sie unten aus. Du kannst mehrere Dateien gleichzeitig wählen.',
  'The app cannot export the whole history.': 'Die App kann nicht die gesamte Historie exportieren.',
  'It looks like the app only keeps roughly the last seven months of trips: in a sample export the oldest trip was from 30 April 2026, although the car had driven over 33,000 km before that. Export what the app offers, and repeat the export now and then (for example monthly). From now on Mate keeps the history itself; you only need the import for the time before Mate started.': 'Es sieht so aus, als behielte die App nur etwa die letzten sieben Monate an Fahrten: In einer Beispiel-Exportdatei stammte die älteste Fahrt vom 30. April 2026, obwohl das Auto davor über 33.000 km gefahren war. Exportiere, was die App anbietet, und wiederhole den Export ab und zu (zum Beispiel monatlich). Ab jetzt führt Mate die Historie selbst; der Import ist nur für die Zeit vor Mates Start nötig.',
  'Your files': 'Deine Dateien', 'Time zone of the export': 'Zeitzone des Exports',
  'The export contains local times without a time zone. Use the zone where the car is driven.': 'Der Export enthält Ortszeiten ohne Zeitzone. Nimm die Zone, in der das Auto gefahren wird.',
  'CSV files': 'CSV-Dateien', 'Check the files (nothing is saved)': 'Dateien prüfen (es wird nichts gespeichert)', 'Choose at least one CSV file first.': 'Wähle zuerst mindestens eine CSV-Datei.',
  'Preview': 'Vorschau', 'Imported': 'Importiert', 'new trips': 'neue Fahrten', 'already known': 'bereits bekannt', 'completed with the car’s figures': 'mit den Werten des Autos ergänzt',
  'repeated in your files': 'in deinen Dateien doppelt', 'without distance (skipped)': 'ohne Strecke (übersprungen)', 'Period': 'Zeitraum', 'Distance': 'Strecke',
  'public charging stops found': 'öffentliche Ladestopps gefunden', 'overnight charges derived': 'nächtliche Ladevorgänge abgeleitet',
  'Import {n} trips': 'Importiere {n} Fahrten', 'Nothing new to import.': 'Es gibt nichts Neues zu importieren.',
  'Nothing was saved yet. Press import to add the new trips.': 'Es wurde noch nichts gespeichert. Drücke „Importieren“, um die neuen Fahrten hinzuzufügen.',
  'Done. You can import the same files again at any time: nothing is added twice.': 'Fertig. Du kannst dieselben Dateien jederzeit erneut importieren: Nichts wird doppelt angelegt.',
  'Open the trips': 'Fahrten ansehen', 'Statistics': 'Statistik',
  'How duplicates are handled': 'Wie Duplikate behandelt werden',
  'The same trip in several files (overlapping periods, the full export plus a period) is counted once.': 'Dieselbe Fahrt in mehreren Dateien (überlappende Zeiträume, der komplette Export plus ein Zeitraum) wird nur einmal gezählt.',
  'A trip Mate already has (recorded by Mate or fetched earlier) is recognised by its start time and distance or its odometer range, and is completed with the car’s own figures instead of being added again. Your notes stay.': 'Eine Fahrt, die Mate schon hat (von Mate aufgezeichnet oder früher geladen), wird an Startzeit und Strecke oder am Kilometerstand erkannt und mit den Werten des Autos ergänzt, statt erneut angelegt. Deine Notizen bleiben.',
  'Nothing is ever deleted, and an export of another car is refused.': 'Es wird nie etwas gelöscht, und der Export eines anderen Autos wird abgelehnt.',
  'Rows without a distance (the car was on but did not move) are skipped.': 'Zeilen ohne Strecke (das Auto war an, ist aber nicht gefahren) werden übersprungen.',
  'Trips with public charging stops also add one charge each; overnight charges are derived from the charge levels between trips (marked “inferred”).': 'Fahrten mit öffentlichen Ladestopps legen zusätzlich je einen Ladevorgang an; nächtliche Ladevorgänge werden aus den Ladeständen zwischen den Fahrten abgeleitet (als „abgeleitet“ markiert).',
  'in these files': 'in diesen Dateien', 'counted once': 'einmal gezählt', 'Some files or rows could not be used:': 'Einige Dateien oder Zeilen konnten nicht verwendet werden:',
  'new': 'neu', 'known': 'bekannt', 'completed': 'ergänzt', 'Start': 'Start', 'From': 'Von', 'To': 'Nach', 'Status': 'Status', 'file': 'Datei', 'files': 'Dateien', 'rows': 'Zeilen', 'trips': 'Fahrten',
});

const STATUS = { new: ['new', 'good'], updated: ['completed', 'info'], unchanged: ['known', ''] };

export default async function importPage(root, ctx) {
  ctx.setTitle(t('Import trips'));
  const base = `/api/vehicles/${ctx.vid}/import/trips`;
  let tz = 'Europe/Berlin';
  try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || tz; } catch { /* keep the default */ }
  let files = [];  // File objects
  let report = null;
  const slot = h('div', { class: 'stack' });

  const input = h('input', { type: 'file', accept: '.csv,text/csv', multiple: true, id: 'b-import-files', onchange: () => { files = [...input.files]; report = null; check.disabled = !files.length; paint(); } });
  const tzInput = h('input', { type: 'text', list: 'b-tz-list', value: tz, autocomplete: 'off', oninput: (e) => { tz = e.target.value.trim(); report = null; paintResult(); } });
  const tzList = h('datalist', { id: 'b-tz-list' });
  try { for (const z of Intl.supportedValuesOf('timeZone')) tzList.append(h('option', { value: z })); } catch { /* the field still accepts any zone name */ }

  async function send(dry) {
    const payload = [];
    for (const file of files) payload.push({ name: file.name, text: await file.text() });
    return ctx.api.post(base, { files: payload, tz, dry_run: dry });
  }

  const check = asyncButton(t('Check the files (nothing is saved)'), async () => {
    if (!files.length) { toast(t('Choose at least one CSV file first.'), 'bad'); return; }
    report = await send(true);
    paintResult();
  }, { ic: 'search', disabled: true });  // enabled once a file is chosen

  function summary(r) {
    const fileErrors = r.files.flatMap((x) => x.errors.map((e) => `${x.name}: ${e}`));
    return h('div', { class: 'stack' },
      fileErrors.length ? banner('warn', h('b', null, t('Some files or rows could not be used:')), h('ul', { class: 'b-notes small' }, ...fileErrors.slice(0, 8).map((e) => h('li', null, e)))) : null,
      h('div', { class: 'grid auto' },
        card(null, stat(t('new trips'), f.num(r.new), { ic: 'plus', sub: r.km ? `${f.km(r.km, 0)} ${t('in these files')}` : null })),
        card(null, stat(t('already known'), f.num(r.unchanged), { ic: 'check' })),
        card(null, stat(t('completed with the car’s figures'), f.num(r.updated), { ic: 'edit' })),
        card(null, stat(t('repeated in your files'), f.num(r.duplicates_in_upload), { ic: 'list', sub: t('counted once') }))),
      h('div', { class: 'small muted' }, [
        r.first ? `${t('Period')}: ${f.date(r.first)} – ${f.date(r.last)}` : null,
        r.skipped_no_distance ? `${r.skipped_no_distance} ${t('without distance (skipped)')}` : null,
        r.public_charges ? `${r.public_charges} ${t('public charging stops found')}` : null,
        !r.dry_run && r.charges_inferred ? `${r.charges_inferred} ${t('overnight charges derived')}` : null].filter(Boolean).join(' · ')),
      r.preview.length ? table([
        { label: t('Start'), render: (x) => f.dateTime(x.start), cls: 'nowrap' }, { label: t('From'), render: (x) => f.shortPlace(x.from) },
        { label: t('To'), render: (x) => f.shortPlace(x.to) }, { label: t('Distance'), render: (x) => f.km(x.km, 0), num: true },
        { label: t('Status'), render: (x) => chip(t(STATUS[x.status][0]), STATUS[x.status][1]) }], r.preview, { label: t('Import preview') }) : null);
  }

  function paintResult() {
    const box = document.getElementById('b-import-result');
    if (!box) return;
    if (!report) { mount(box); return; }
    const todo = report.new + report.updated;
    mount(box, card(report.dry_run ? t('Preview') : t('Imported'), h('div', { class: 'stack' }, summary(report),
      report.dry_run
        ? h('div', { class: 'row' }, todo
          ? asyncButton(t('Import {n} trips').replace('{n}', todo), async () => {
            const done = await send(false);
            report = done;
            toast(t('Done. You can import the same files again at any time: nothing is added twice.'), 'good');
            await ctx.refresh();
            paintResult();
          }, { ic: 'upload', kind: 'primary' }) : null,
          h('span', { class: 'small muted' }, todo ? t('Nothing was saved yet. Press import to add the new trips.') : t('Nothing new to import.')))
        : h('div', { class: 'stack' }, banner('info', t('Done. You can import the same files again at any time: nothing is added twice.')),
          h('div', { class: 'row' }, h('a', { class: 'btn primary', href: '#/trips' }, icon('route', { size: 16 }), t('Open the trips')),
            h('a', { class: 'btn', href: '#/stats' }, icon('chart', { size: 16 }), t('Statistics')))))));
  }

  function paint() {
    mount(slot,
      card(t('Your files'), h('div', { class: 'stack' },
        field(t('CSV files'), input),
        files.length ? h('ul', { class: 'b-notes small' }, ...files.map((x) => h('li', null, `${x.name} · ${f.num(x.size / 1024, 0)} kB`))) : null,
        field(t('Time zone of the export'), tzInput, t('The export contains local times without a time zone. Use the zone where the car is driven.')), tzList,
        h('div', { class: 'row' }, check)), { ic: 'upload' }),
      h('div', { id: 'b-import-result' }));
    paintResult();
  }

  mount(root,
    h('div', { class: 'row between' }, h('h1', null, t('Import trips')), h('a', { class: 'btn sm', href: '#/trips' }, icon('left', { size: 15 }), t('Back to trips'))),
    card(t('How to export your trips from the MyŠkoda app'), h('div', { class: 'stack' },
      h('ol', { class: 'b-notes' },
        h('li', null, t('Open the MyŠkoda app and select your car.')),
        h('li', null, t('Open the trip statistics (the list of your trips). Menu names can differ slightly between app versions.')),
        h('li', null, t('Choose the period you want and use the export (share) button to save a CSV file. The app names it tripStatistics_<VIN>.csv, or tripStatistics_from_DDMMYYYY_to_DDMMYYYY_<VIN>.csv for a chosen period.')),
        h('li', null, t('Move the file(s) to this computer (AirDrop, e-mail, cloud drive) and choose them below. You can pick several files at once.'))),
      banner('info', h('b', null, t('The app cannot export the whole history.')), ' ',
        t('It looks like the app only keeps roughly the last seven months of trips: in a sample export the oldest trip was from 30 April 2026, although the car had driven over 33,000 km before that. Export what the app offers, and repeat the export now and then (for example monthly). From now on Mate keeps the history itself; you only need the import for the time before Mate started.'))), { ic: 'info' }),
    slot,
    card(t('How duplicates are handled'), h('ul', { class: 'b-notes small' },
      h('li', null, t('The same trip in several files (overlapping periods, the full export plus a period) is counted once.')),
      h('li', null, t('A trip Mate already has (recorded by Mate or fetched earlier) is recognised by its start time and distance or its odometer range, and is completed with the car’s own figures instead of being added again. Your notes stay.')),
      h('li', null, t('Nothing is ever deleted, and an export of another car is refused.')),
      h('li', null, t('Rows without a distance (the car was on but did not move) are skipped.')),
      h('li', null, t('Trips with public charging stops also add one charge each; overnight charges are derived from the charge levels between trips (marked “inferred”).'))), { ic: 'shield' }));
  paint();
}
