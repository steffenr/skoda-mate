// Import the trip history exported from the MyŠkoda app (CSV). Preview first (nothing is saved), then import.
// Duplicates are handled by the server (see skoda_mate/importer.py): overlapping files, re-imports and trips Mate
// already has are recognised, so importing is always safe to repeat.
import { h, mount } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { asyncButton, banner, button, card, chip, empty, field, stat, table, toast } from '../lib/ui.js';
import * as f from '../lib/format.js';
import { t, tm } from '../i18n.js';

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
    const fileErrors = r.files.flatMap((x) => x.errors.map((e, i) => `${x.name}: ${x.errors_i18n?.[i] ? tm(x.errors_i18n[i]) : e}`));
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
        { label: t('To##place'), render: (x) => f.shortPlace(x.to) }, { label: t('Distance'), render: (x) => f.km(x.km, 0), num: true },
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
