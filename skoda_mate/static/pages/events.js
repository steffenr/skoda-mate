// Activity: the day as a timeline (drive, charge, climate, parked, unheard) and, as a second tab, the event list: what Mate
// noticed between readings (locks, doors, plug, charging, trips, commands), filterable and grouped by day.
import { h, mount, debounce } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { banner, button, card, chip, empty, field, loading, seg } from '../lib/ui.js';
import * as f from '../lib/format.js';
import { barBox, clockAt, dayStartMs } from '../lib/dates.js';
import { actionLabel, checkLabel } from '../lib/quality.js';
import { t, tn, N_ } from '../i18n.js';

const KINDS = {
  locked: ['Locked', 'lock', 'good'], unlocked: ['Unlocked', 'unlock', 'warn'],
  door_opened: [N_('Door opened'), 'door', 'warn'], door_closed: [N_('Door closed'), 'door', ''], window_opened: [N_('Window opened'), 'window', 'warn'], window_closed: [N_('Window closed'), 'window', ''],
  trunk_opened: [N_('Trunk opened'), 'door', 'warn'], trunk_closed: [N_('Trunk closed'), 'door', ''], bonnet_opened: [N_('Bonnet opened'), 'door', 'warn'], bonnet_closed: [N_('Bonnet closed'), 'door', ''],
  sunroof_opened: [N_('Sunroof opened'), 'window', 'warn'], sunroof_closed: [N_('Sunroof closed'), 'window', ''], lights_on: [N_('Lights on'), 'sun', ''], lights_off: [N_('Lights off'), 'moon', ''],
  plugged_in: [N_('Plugged in'), 'plug', 'info'], unplugged: [N_('Unplugged'), 'plug', ''], plug_locked: [N_('Plug locked'), 'lock', ''], plug_unlocked: [N_('Plug unlocked'), 'unlock', ''],
  climate: ['Climate', 'thermo', 'info'], aux_heating: [N_('Auxiliary heating'), 'flame', 'info'], ventilation: ['Ventilation', 'fan', 'info'],
  charge_start: [N_('Charging started'), 'bolt', 'good'], charge_end: [N_('Charging finished'), 'bolt', 'good'], charge_state: [N_('Charging status'), 'battery', ''],
  trip_start: [N_('Trip started'), 'route', 'info'], trip_end: [N_('Trip finished'), 'route', 'info'], command: ['Command', 'sliders', ''],
  quality_fix: [N_('Data fixed'), 'shield', 'good'], quality_review: [N_('Data reviewed'), 'shield', ''],
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
  // Data quality (quality.fix / quality.review): "<action>:<rows changed>" and "<check>:on|off"
  const fixed = e.kind === 'quality_fix' && /^(\w+):(\d+)$/.exec(d || '');
  if (fixed) return `${actionLabel(fixed[1])}: ${tn('{n} changed', '{n} changed', +fixed[2], { n: f.num(+fixed[2]) })}`;
  const reviewed = e.kind === 'quality_review' && /^(\w+):(on|off)$/.exec(d || '');
  if (reviewed) return `${checkLabel(reviewed[1])}: ${reviewed[2] === 'on' ? t('marked as reviewed') : t('review undone')}`;
  if (!d) return null;
  const km = /^([\d.]+) km$/.exec(d);
  if (e.kind === 'trip_end' && km) return f.km(+km[1], 1);
  return d.replace(/_/g, ' ').replace(/ -> /g, ' → ');
}

/** The filtered event table. Mounts into `root` and returns the refresh to run on a poll tick. */
async function listTab(root, ctx) {
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
    info.textContent = tn('Showing {shown} of {n} event', 'Showing {shown} of {n} events', total, { shown: items.length });
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
  return () => { if (loadedOnce && items.length <= PAGE) load(true, true); };
}

// ---------------------------------------------------------------- timeline

const MAX_BACK_DAYS = 30;  // the oldest reachable day is today minus 30; the endpoint answers any range of up to 31 days
const SEGMENT_LABEL = { drive: 'Driving', charge: 'Charging', climate: 'Climate', aux: N_('Auxiliary heating'), vent: 'Ventilation', parked: 'Parked', unknown: 'Not heard from' };
const SEGMENT_COLOUR = { aux: 'climate', vent: 'climate' };  // aux and vent share the climate colour and legend entry
const LEGEND = ['drive', 'charge', 'climate', 'parked', 'unknown'];
const segLabel = (k) => t(SEGMENT_LABEL[k] || k);

const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n, 12);  // noon keeps DST shifts off the date
const parseDay = (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d, 12); };
const todayNoon = () => parseDay(isoDay(new Date()));

/** One bar. `dayStart`/`dayEnd` are the server's bounds of its day (ms), not the browser's midnight. Only a drive or charge
 * with a record to open is a button; every other bar is a plain labelled element (no focus stop, no pointer cursor). */
function bar(iv, dayStart, dayEnd, tzOffset) {
  const { left, width } = barBox(iv.start, iv.minutes, dayStart, dayEnd);
  const text = `${segLabel(iv.kind)} ${clockAt(iv.start, tzOffset, f.getLocale())} – ${clockAt(iv.end, tzOffset, f.getLocale())}${iv.estimated ? ` (${t('estimated')})` : ''}`;
  const href = iv.kind === 'drive' && iv.trip_id != null ? `#/trips/${iv.trip_id}` : iv.kind === 'charge' && iv.charge_id != null ? `#/charges/${iv.charge_id}` : null;
  const attrs = { class: ['tl-bar', `tl-${SEGMENT_COLOUR[iv.kind] || iv.kind}`, iv.estimated ? 'tl-estimated' : ''], style: { left: `${left}%`, width: `${width}%` }, title: text };
  return href ? h('button', { ...attrs, type: 'button', 'aria-label': text, onclick: () => { location.hash = href; } })
    : h('div', { ...attrs, role: 'img', 'aria-label': text });
}

// `f.money` prints 2 decimals, so anything under half a cent would read "0.00": it counts as zero.
const MONEY_STEP = 0.01;

/** The parts of a day or week line from a timeline `summary`. Driving time and parked time always appear; everything else
 * only when non-zero (never "0.0 kWh"). A charge's energy belongs to the day it started: the morning after an overnight
 * charge has charging time but no kWh, so it shows the time. A cost with a charge that had no amount is "at least"; a known cost that rounds to 0.00 is "free", an unknown one is left out. */
function summaryParts(s, currency) {
  const charged = s.kwh > 0 ? `${t('Charged')} ${f.kwh(s.kwh)}` : s.charge_min > 0 ? `${t('Charging')} ${f.duration(s.charge_min)}` : null;
  return [`${t('Driving')} ${f.duration(s.drive_min)}`, charged,
    s.climate_min > 0 ? `${t('Climate')} ${f.duration(s.climate_min)}` : null,
    `${t('Parked')} ${f.duration(s.parked_min)}`,
    s.unknown_min > 0 ? `${t('Not heard from')} ${f.duration(s.unknown_min)}` : null,
    s.km > 0 ? f.km(s.km, 1) : null,
    s.cost >= MONEY_STEP / 2 ? (s.cost_partial ? t('at least {amount}', { amount: f.money(s.cost, currency) }) : f.money(s.cost, currency))
      : s.cost != null && s.cost >= 0 && !s.cost_partial ? t('free') : null].filter(Boolean);
}

function dayBlock(day, tzOffset, currency) {
  const noon = parseDay(day.date);
  const dayStart = dayStartMs(day.date, tzOffset), dayEnd = dayStartMs(isoDay(addDays(noon, 1)), tzOffset);
  return h('section', { class: 'tl-day' },
    h('h2', { class: 'b-dayh' }, f.date(noon.toISOString(), { weekday: 'long', day: 'numeric', month: 'short' })),
    h('div', { class: 'tl-scroll' }, h('div', { class: 'tl-track' }, ...day.intervals.map((iv) => bar(iv, dayStart, dayEnd, tzOffset)))),
    h('div', { class: 'small muted' }, summaryParts(day.summary, currency).join(' · ')),
    h('details', { class: 'tl-text' }, h('summary', null, t('Text list')),
      h('ul', null, ...day.intervals.map((iv) => h('li', null,
        `${segLabel(iv.kind)}, ${clockAt(iv.start, tzOffset, f.getLocale())} – ${clockAt(iv.end, tzOffset, f.getLocale())} (${f.duration(iv.minutes)})${iv.estimated ? ` · ${t('estimated')}` : ''}${iv.place ? ` · ${iv.place}` : ''}`)))));
}

/** The week timeline. Mounts into `root` and returns the refresh to run on a poll tick. */
async function timelineTab(root, ctx) {
  let to = todayNoon(), seq = 0, loadedOnce = false, following = true;
  const earliest = () => addDays(todayNoon(), -MAX_BACK_DAYS);
  // Back one week, but never past the oldest reachable day: the last step is shorter instead of unreachable.
  const go = (target) => { to = target > todayNoon() ? todayNoon() : target; following = to.getTime() === todayNoon().getTime(); load(); };
  const step = (ic, label, onClick) => {
    const b = button('', { ic, size: 'sm', title: label, onClick });
    b.setAttribute('aria-label', label);
    return b;
  };
  const prev = step('left', t('Previous week'), () => { const floor = addDays(earliest(), 6); const back = addDays(to, -7); go(back < floor ? floor : back); });
  const next = step('right', t('Next week'), () => go(addDays(to, 7)));
  const todayBtn = button(t('Today'), { size: 'sm', onClick: () => go(todayNoon()) });
  const range = h('strong', { 'aria-live': 'polite' });
  const body = h('div', { class: 'stack' });
  const legend = h('div', { class: 'legend', role: 'group', 'aria-label': t('Colour key') },
    h('span', null, t('24 h')), ...LEGEND.map((k) => h('span', null, h('i', { class: `tl-${k}` }), segLabel(k))));

  async function load(silent = false) {
    const mine = ++seq;
    const today = todayNoon(), from = addDays(to, -6);
    prev.disabled = from <= earliest(); next.disabled = to >= today;
    range.textContent = `${f.date(from.toISOString())} – ${f.date(to.toISOString())}`;
    if (!silent) mount(body, loading());
    try {
      // one offset for the request and for the bars, so the bars use the very day bounds the server cut at
      const tzOffset = new Date().getTimezoneOffset();
      const q = new URLSearchParams({ from: isoDay(from), to: isoDay(to), tz_offset: String(tzOffset) });
      const r = await ctx.api.get(`/api/vehicles/${ctx.vid}/timeline?${q}`);
      if (mine !== seq) return;
      loadedOnce = true;
      mount(body, r.days.some((d) => d.intervals.length) ? h('div', { class: 'stack' },
        h('div', { class: ['small', 'muted', 'tl-week'] }, `${t('Week')}: ${summaryParts(r.summary, ctx.currency).join(' · ')}`),
        ...r.days.map((d) => dayBlock(d, tzOffset, ctx.currency)))
        : empty(t('Nothing recorded in this week'), t('Mate records a day from the readings it has. A gap means it did not hear from the car.'), 'activity'));
    } catch (e) {
      if (mine !== seq || silent) return;
      mount(body, banner('bad', `${t('Could not load the timeline')}: ${e.message}`), button(t('Try again'), { ic: 'refresh', onClick: () => load() }));
    }
  }

  mount(root, h('div', { class: 'row between tl-toolbar' }, h('div', { class: 'row tight' }, prev, todayBtn, next), range), legend,
    h('p', { class: 'small muted tl-precision' }, t('Times are accurate to the poll interval.')), body);
  await load();
  // Past midnight "today" moves on: a view that follows today follows it, a past week stays where it is.
  return () => {
    if (!loadedOnce || !following) return;
    to = todayNoon();
    load(true);
  };
}

export default async function activity(root, ctx) {
  ctx.setTitle(t('Activity'));
  let mode = 'timeline', refresh = null, token = 0;
  const panel = h('div', { class: 'stack' });
  async function show() {
    const mine = ++token;
    refresh = null;
    const tick = await (mode === 'timeline' ? timelineTab : listTab)(mount(panel), ctx);
    if (mine === token) refresh = tick;
  }
  mount(root, h('div', null, seg([['timeline', t('Timeline')], ['list', t('List')]], mode, (m) => { mode = m; show(); }, t('Activity'))), panel);
  ctx.onTick(() => refresh?.());
  await show();
}
