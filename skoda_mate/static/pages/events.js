// Events: what Mate noticed between readings (locks, doors, plug, charging, trips, commands), filterable and grouped by day.
import { h, mount, debounce } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { banner, button, card, chip, empty, field, loading } from '../lib/ui.js';
import * as f from '../lib/format.js';
import { extendDE, t } from '../i18n.js';

extendDE({
  'Events': 'Ereignisse', 'All': 'Alle', 'Search': 'Suchen', 'From': 'Von', 'To': 'Bis', 'Clear filters': 'Filter zurücksetzen', 'Load more': 'Mehr laden',
  'Showing': 'Zeige', 'of': 'von', 'events': 'Ereignisse', 'No events found': 'Keine Ereignisse gefunden', 'Nothing matches these filters.': 'Zu diesen Filtern gibt es nichts.',
  'Mate records events when it notices a change between two readings.': 'Mate zeichnet Ereignisse auf, wenn es zwischen zwei Messungen eine Änderung bemerkt.',
  'Could not load events': 'Ereignisse konnten nicht geladen werden', 'Try again': 'Erneut versuchen',
  'Event types': 'Ereignisarten', 'Locked': 'Verriegelt', 'Unlocked': 'Entriegelt', 'Door opened': 'Tür geöffnet', 'Door closed': 'Tür geschlossen',
  'Window opened': 'Fenster geöffnet', 'Window closed': 'Fenster geschlossen', 'Trunk opened': 'Kofferraum geöffnet', 'Trunk closed': 'Kofferraum geschlossen',
  'Bonnet opened': 'Motorhaube geöffnet', 'Bonnet closed': 'Motorhaube geschlossen', 'Sunroof opened': 'Schiebedach geöffnet', 'Sunroof closed': 'Schiebedach geschlossen',
  'Lights on': 'Licht an', 'Lights off': 'Licht aus', 'Plugged in': 'Angesteckt', 'Unplugged': 'Abgesteckt', 'Plug locked': 'Stecker verriegelt', 'Plug unlocked': 'Stecker entriegelt',
  'Climate': 'Klima', 'Auxiliary heating': 'Standheizung', 'Ventilation': 'Lüftung', 'Charging started': 'Laden gestartet', 'Charging finished': 'Laden beendet',
  'Charging status': 'Ladestatus', 'Trip started': 'Fahrt gestartet', 'Trip finished': 'Fahrt beendet', 'Command': 'Befehl',
  'sent': 'gesendet', 'failed': 'fehlgeschlagen', 'Command sent': 'Befehl gesendet', 'Command failed': 'Befehl fehlgeschlagen',
  'Start charging': 'Laden starten', 'Stop charging': 'Laden stoppen', 'Set charge limit': 'Ladelimit setzen', 'Set charge mode': 'Lademodus setzen',
  'Update charging profile': 'Ladeprofil ändern', 'Start climate': 'Klima starten', 'Stop climate': 'Klima stoppen', 'Start auxiliary heating': 'Standheizung starten',
  'Stop auxiliary heating': 'Standheizung stoppen', 'Start ventilation': 'Lüftung starten', 'Stop ventilation': 'Lüftung stoppen',
});

const KINDS = {
  locked: ['Locked', 'lock', 'good'], unlocked: ['Unlocked', 'unlock', 'warn'],
  door_opened: ['Door opened', 'door', 'warn'], door_closed: ['Door closed', 'door', ''], window_opened: ['Window opened', 'window', 'warn'], window_closed: ['Window closed', 'window', ''],
  trunk_opened: ['Trunk opened', 'door', 'warn'], trunk_closed: ['Trunk closed', 'door', ''], bonnet_opened: ['Bonnet opened', 'door', 'warn'], bonnet_closed: ['Bonnet closed', 'door', ''],
  sunroof_opened: ['Sunroof opened', 'window', 'warn'], sunroof_closed: ['Sunroof closed', 'window', ''], lights_on: ['Lights on', 'sun', ''], lights_off: ['Lights off', 'moon', ''],
  plugged_in: ['Plugged in', 'plug', 'info'], unplugged: ['Unplugged', 'plug', ''], plug_locked: ['Plug locked', 'lock', ''], plug_unlocked: ['Plug unlocked', 'unlock', ''],
  climate: ['Climate', 'thermo', 'info'], aux_heating: ['Auxiliary heating', 'flame', 'info'], ventilation: ['Ventilation', 'fan', 'info'],
  charge_start: ['Charging started', 'bolt', 'good'], charge_end: ['Charging finished', 'bolt', 'good'], charge_state: ['Charging status', 'battery', ''],
  trip_start: ['Trip started', 'route', 'info'], trip_end: ['Trip finished', 'route', 'info'], command: ['Command', 'sliders', ''],
};
const COMMAND_LABEL = {
  start_charging: 'Start charging', stop_charging: 'Stop charging', set_charge_limit: 'Set charge limit', set_charge_mode: 'Set charge mode', update_charging_profile: 'Update charging profile',
  start_climate: 'Start climate', stop_climate: 'Stop climate', start_aux_heating: 'Start auxiliary heating', stop_aux_heating: 'Stop auxiliary heating',
  start_ventilation: 'Start ventilation', stop_ventilation: 'Stop ventilation',
};
const PAGE = 50;
const kindLabel = (k) => (KINDS[k] ? t(KINDS[k][0]) : k.replace(/_/g, ' '));

/** The detail text of an event in the user's units; commands get an outcome chip. */
function detail(e) {
  const d = e.detail;
  if (e.kind === 'command' && d) {
    const m = /^(\S+) (sent|failed(?:: (.*))?)$/s.exec(d);
    if (m) {
      const ok = m[2] === 'sent';
      return h('span', { class: 'row tight' }, h('span', null, t(COMMAND_LABEL[m[1]] || m[1])), ok ? chip(t('sent'), 'good', 'check') : chip(t('failed'), 'bad', 'alert'),
        !ok && m[3] ? h('span', { class: 'small muted' }, m[3]) : null);
    }
  }
  if (!d) return null;
  const km = /^([\d.]+) km$/.exec(d);
  if (e.kind === 'trip_end' && km) return f.km(+km[1], 1);
  return d.replace(/_/g, ' ').replace(/ -> /g, ' → ');
}

export default async function events(root, ctx) {
  ctx.setTitle(t('Events'));
  const base = `/api/vehicles/${ctx.vid}/events`;
  const flt = { kind: '', q: '', from: '', to: '' };
  let items = [], total = 0, kinds = [], seq = 0, loadedOnce = false;

  const chipsBox = h('div', { class: 'row tight', role: 'group', 'aria-label': t('Event types') });
  const listBox = h('div', { class: 'stack' });
  const moreBox = h('div', { class: 'center' });
  const info = h('div', { class: 'small muted', 'aria-live': 'polite' });

  const qInput = h('input', { type: 'search', value: flt.q, placeholder: t('Search'), oninput: debounce((e) => { flt.q = e.target.value.trim(); load(true); }, 300) });
  const fromInput = h('input', { type: 'date', value: flt.from, onchange: (e) => { flt.from = e.target.value; load(true); } });
  const toInput = h('input', { type: 'date', value: flt.to, onchange: (e) => { flt.to = e.target.value; load(true); } });
  const clearBtn = button(t('Clear filters'), { ic: 'x', size: 'sm', onClick: () => {
    flt.kind = flt.q = flt.from = flt.to = ''; qInput.value = ''; fromInput.value = ''; toInput.value = ''; load(true);
  } });

  function drawChips() {
    const mk = (k, label) => h('button', { type: 'button', class: ['chip', 'b-chip', flt.kind === k ? 'good' : ''], 'aria-pressed': String(flt.kind === k), onclick: () => { flt.kind = k; load(true); } }, label);
    mount(chipsBox, mk('', t('All')), ...kinds.map((k) => mk(k, kindLabel(k))));
  }

  function drawList() {
    clearBtn.hidden = !(flt.kind || flt.q || flt.from || flt.to);
    if (!items.length) {
      mount(listBox, empty(t('No events found'), (flt.kind || flt.q || flt.from || flt.to) ? t('Nothing matches these filters.') : t('Mate records events when it notices a change between two readings.'), 'activity'));
      mount(moreBox); info.textContent = '';
      return;
    }
    const groups = [];
    for (const e of items) {
      const day = f.localDay(e.at);
      if (!groups.length || groups.at(-1).day !== day) groups.push({ day, at: e.at, list: [] });
      groups.at(-1).list.push(e);
    }
    mount(listBox, ...groups.map((g) => h('section', { class: 'b-day-group' },
      h('h2', { class: 'b-dayh' }, f.dayLabel(g.at)),
      h('ul', { class: 'b-events' }, ...g.list.map((e) => {
        const k = KINDS[e.kind] || ['', 'activity', ''];
        return h('li', { class: 'b-event' },
          h('span', { class: ['b-event-ic', k[2]] }, icon(k[1], { size: 16 })),
          h('span', { class: 'b-event-main' }, h('strong', null, kindLabel(e.kind)), detail(e) ? h('span', { class: 'b-event-detail' }, detail(e)) : null),
          h('time', { class: 'small muted nowrap', datetime: e.at }, f.time(e.at)));
      })))));
    info.textContent = `${t('Showing')} ${items.length} ${t('of')} ${total} ${t('events')}`;
    mount(moreBox, items.length < total ? button(t('Load more'), { ic: 'down', onClick: () => load(false) }) : null);
  }

  async function load(reset, silent = false) {
    const mine = ++seq;
    if (reset && !silent) mount(listBox, loading());
    const p = new URLSearchParams({ limit: PAGE, offset: reset ? 0 : items.length });
    if (flt.kind) p.set('kind', flt.kind);
    if (flt.q) p.set('q', flt.q);
    if (flt.from) p.set('from', flt.from);
    if (flt.to) p.set('to', flt.to);
    try {
      const r = await ctx.api.get(`${base}?${p}`);
      if (mine !== seq) return;
      items = reset ? r.items : [...items, ...r.items];
      total = r.total; kinds = r.kinds || kinds; loadedOnce = true;
      drawChips(); drawList();
    } catch (e) {
      if (mine !== seq || silent) return;
      mount(listBox, banner('bad', `${t('Could not load events')}: ${e.message}`), button(t('Try again'), { ic: 'refresh', onClick: () => load(reset) }));
    }
  }

  mount(root, card(null, h('div', { class: 'stack' },
    chipsBox,
    h('div', { class: 'grid g3 b-filters' }, field(t('Search'), qInput), field(t('From'), fromInput), field(t('To'), toInput)),
    h('div', { class: 'row between' }, info, clearBtn))),
  listBox, moreBox);
  clearBtn.hidden = true;
  await load(true);
  ctx.onTick(() => { if (loadedOnce && items.length <= PAGE) load(true, true); });
}
