// Control: every remote command the official Škoda API offers, gated on what this car supports.
// 202 from Škoda means "request performed", not "done": the car confirms with the next reading.
import { h, mount } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { asyncButton, banner, button, card, chip, empty, field, loading, table, toast } from '../lib/ui.js';
import * as f from '../lib/format.js';
import { t, tx, N_ } from '../i18n.js';
import { estimateNote, liveSoc } from '../lib/livesoc.js';

const CHARGE_STATE = {
  CHARGING: [N_('Charging##state'), 'good'], READY_FOR_CHARGING: [N_('Plugged in, not charging'), 'info'], CONNECT_CABLE: [N_('Cable not connected'), ''],
  CONSERVING: [N_('Conserving (battery care)'), 'info'], DISCHARGING: ['Discharging', 'warn'], CHARGING_INTERRUPTED: ['Charging interrupted', 'warn'],
};
const MODE_LABEL = {
  MANUAL: 'Manual', TIMER: 'Timer', TIMER_CHARGING_WITH_CLIMATISATION: N_('Timer with climate'), PREFERRED_CHARGING_TIMES: 'Preferred charging times',
  ONLY_OWN_CURRENT: 'Only own current', IMMEDIATE_DISCHARGING: 'Immediate discharging', HOME_STORAGE_CHARGING: 'Home storage charging',
};
const DAYS = ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'SUNDAY'];
const DAY_SHORT = { MONDAY: N_('MON'), TUESDAY: N_('TUE'), WEDNESDAY: N_('WED'), THURSDAY: N_('THU'), FRIDAY: N_('FRI'), SATURDAY: N_('SAT'), SUNDAY: N_('SUN') };
const DAY_LONG = { MONDAY: 'Monday', TUESDAY: 'Tuesday', WEDNESDAY: 'Wednesday', THURSDAY: 'Thursday', FRIDAY: 'Friday', SATURDAY: 'Saturday', SUNDAY: 'Sunday' };
const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;
const toNum = (v) => (v === '' || v == null || Number.isNaN(Number(v)) ? null : Number(v));

function selectField(label, options, value, onChange, { disabled } = {}) {
  const sel = h('select', { disabled, onchange: (e) => onChange(e.target.value) },
    ...options.map(([v, l]) => h('option', { value: v, selected: v === value }, l)));
  return field(label, sel);
}

export default async function control(root, ctx) {
  ctx.setTitle(t('Control'));
  const base = `/api/vehicles/${ctx.vid}`;
  let info = null, infoError = null, pending = null, pendingTimer = null, dead = false;
  const st = {};                 // form values, kept across redraws
  const drafts = new Map();      // profile id -> { key, d } (key = server version the draft was made from)
  const openProfiles = new Set();

  async function loadInfo() {
    try { info = await ctx.api.get(`${base}/commands`); infoError = null; } catch (e) { infoError = e.message; }
  }

  // ---- sending
  async function send(name, params, label, onOk) {
    let r;
    try {
      r = await ctx.api.post(`${base}/command`, { name, params });
    } catch (e) {            // 400: bad parameters, unsupported, or the request limit is used up. Nothing was sent.
      toast(`${label}: ${e.message}`, 'bad');
      return false;
    }
    if (r.ok) {
      const wait = r.refresh_in || 45;
      if (onOk) onOk();
      toast(`${label}: ${t('Request performed')} (HTTP ${r.status || 202}). ${t('The car confirms with the next reading.')}`, 'good');
      pending = { label, wait };
      clearTimeout(pendingTimer);
      pendingTimer = setTimeout(async () => {   // the server re-reads the car after ~45 s; pick that up
        pending = null;
        if (dead) return;
        try { await ctx.refresh(); await loadInfo(); } catch { /* transient */ }
        render(true);
      }, (wait + 8) * 1000);
    } else {
      toast(`${label}: ${tx(r) || t('Failed')}${r.kind ? ` (${r.kind})` : ''}`, 'bad');   // Škoda's own message
    }
    try { await ctx.refresh(); await loadInfo(); } catch { /* transient */ }
    render(true);
    return r.ok;
  }

  const cmdMap = () => Object.fromEntries((ctx.overview.commands || []).map((c) => [c.name, c]));
  const gate = (name) => {
    const c = cmdMap()[name];
    if (!c || c.supported === false) return { ok: false, reason: t('Not supported by this car') };
    if (c.supported == null) return { ok: false, reason: t('Supported operations not known yet') };
    return { ok: true };
  };
  const label = (name) => { const c = cmdMap()[name]; return t(c?.label || name); };

  /** A command button; disabled with the reason when the car cannot do it. `get` may return {error} to block sending. */
  function cmdBtn(name, text, get, opts = {}) {
    const g = gate(name);
    if (!g.ok) return null;  // only controls this car supports are shown; the rest is listed under Capabilities
    return asyncButton(text, async () => {
      const p = typeof get === 'function' ? get() : get;
      if (p && p.error) { toast(tx(p), 'bad'); return; }
      await send(name, p, label(name), opts.onOk);
    }, { ...opts, disabled: !g.ok || opts.disabled, title: g.ok ? opts.title : g.reason });
  }
  const reasonNote = () => null;  // unsupported controls are not shown at all, so there is nothing to explain here

  // ---- Start/Stop as ONE toggle. The car confirms a command only with the next reading (~45 s), so right after a command is
  // accepted the toggle already shows the state it is heading for, instead of an unchanged, tempting-to-press-again button.
  const opt = {};
  const setOpt = (key, on) => { opt[key] = { on, until: Date.now() + 75000 }; };
  const isOn = (key, actual) => {
    const o = opt[key];
    if (!o) return !!actual;
    if (o.on === !!actual || Date.now() >= o.until) { delete opt[key]; return !!actual; }
    return o.on;
  };
  /** One button that is "Start X" while off and "Stop X" while on. `blocked` is a reason text: the start is disabled and says why. */
  function toggle({ key, on, start, stop, getStart, ic, blocked }) {
    const shown = isOn(key, on);
    const btn = shown
      ? cmdBtn(stop, label(stop), undefined, { ic: ic[1], kind: 'danger', onOk: () => setOpt(key, false) })
      : cmdBtn(start, label(start), getStart, { ic: ic[0], kind: 'primary', disabled: !!blocked, title: blocked || undefined, onOk: () => setOpt(key, true) });
    if (!btn) return null;
    return h('div', { class: 'stack b-toggle' }, btn,
      !shown && blocked ? h('div', { class: 'small muted b-reason' }, icon('info', { size: 14 }), ' ', blocked) : null,
      opt[key] ? h('div', { class: 'small muted' }, icon('clock', { size: 14 }), ' ', t('Waiting for the car to confirm …')) : null);
  }
  const can = (...names) => names.some((n) => gate(n).ok);

  // ---- sections
  function chargingCard(o, s) {
    const ch = o.sections.charging, cs = CHARGE_STATE[s.charge_state];
    const limitNow = s.target_soc != null ? Math.round(s.target_soc) : null;
    if (st.limit == null) st.limit = limitNow ?? 80;
    const modes = ch?.settings?.available_modes || [];
    if (st.mode == null) st.mode = ch?.settings?.preferred_mode || modes[0] || '';

    let limitBtn = null, modeBtn = null;
    const modeNow = ch?.settings?.preferred_mode ?? null;
    const sync = () => { if (limitBtn) limitBtn.disabled = st.limit === limitNow; if (modeBtn) modeBtn.disabled = st.mode === modeNow; };  // nothing to send while nothing changed
    const out = h('output', { class: 'b-big' }, `${st.limit} %`);
    const slider = h('input', { type: 'range', min: 50, max: 100, step: 10, value: st.limit, 'aria-label': t('Charge limit'),
      oninput: (e) => { st.limit = +e.target.value; out.textContent = `${st.limit} %`; sync(); } });
    const step = (d) => () => { st.limit = Math.max(50, Math.min(100, st.limit + d)); slider.value = st.limit; out.textContent = `${st.limit} %`; sync(); };
    const limit = h('div', { class: 'stack' },
      h('div', { class: 'row between' }, h('strong', null, t('Charge limit')), h('span', { class: 'small muted' }, `${t('Charge limit now')}: ${limitNow != null ? `${limitNow} %` : t('Not known')}`)),
      h('div', { class: 'b-stepper' }, button('', { ic: 'minus', onClick: step(-10), title: t('Decrease'), size: 'sm' }), slider,
        button('', { ic: 'plus', onClick: step(10), title: t('Increase'), size: 'sm' }), out),
      h('div', { class: 'row' }, (limitBtn = cmdBtn('set_charge_limit', t('Set limit'), () => ({ percent: st.limit }), { ic: 'check', disabled: st.limit === limitNow })),
        h('span', { class: 'tiny muted' }, t('Most cars accept the charge limit in steps of 10 %.'))),
      reasonNote(['set_charge_limit']));

    const modeGate = gate('set_charge_mode');
    const mode = h('div', { class: 'stack' },
      modes.length ? selectField(t('Charge mode'), modes.map((m) => [m, t(MODE_LABEL[m] || m)]), st.mode, (v) => { st.mode = v; sync(); }, { disabled: !modeGate.ok })
        : h('div', { class: 'small muted' }, `${t('Charge mode')}: ${ch?.settings?.preferred_mode ? t(MODE_LABEL[ch.settings.preferred_mode] || ch.settings.preferred_mode) : t('Not known')}`),
      modes.length ? (modeBtn = cmdBtn('set_charge_mode', t('Set mode'), () => ({ mode: st.mode }), { ic: 'check', disabled: st.mode === modeNow })) : null,
      reasonNote(['set_charge_mode']));

    const live = liveSoc(s, o.vehicle?.capacity_kwh);
    const status = h('div', { class: 'stack' }, h('div', { class: 'row' },
      cs ? chip(t(cs[0]), cs[1], s.charging ? 'bolt' : 'plug') : chip(t('Unknown'), '', 'plug'),
      s.charging && s.charge_power_kw != null ? chip(f.kw(s.charge_power_kw), 'good') : null,
      s.charging && s.remaining_min != null ? chip(t('{duration} remaining', { duration: f.duration(s.remaining_min) }), '') : null,
      s.soc != null ? chip(`${live ? '≈ ' : ''}${Math.round(live ? live.soc : s.soc)} %`, '', 'battery') : null,
      // with a single mode there is nothing to choose: just state it
      modes.length <= 1 && ch?.settings?.preferred_mode ? chip(`${t('Charge mode')}: ${t(MODE_LABEL[ch.settings.preferred_mode] || ch.settings.preferred_mode)}`, '', 'sliders') : null),
      estimateNote(live, s));
    const startStop = toggle({ key: 'charging', on: s.charging, start: 'start_charging', stop: 'stop_charging', ic: ['play', 'stop'],
      blocked: s.plug_connected === false ? t('Plug in the car to start charging.') : null });
    const parts = [can('start_charging', 'stop_charging') ? startStop : null, can('set_charge_limit') ? limit : null, can('set_charge_mode') && modes.length > 1 ? mode : null].filter(Boolean);
    return card(t('Charging'), h('div', { class: 'stack' }, status, ...parts.flatMap((p, i) => (i ? [h('hr', { class: 'b-sep' }), p] : [p]))), { ic: 'bolt' });
  }

  function climateCard(o) {
    const cl = o.sections.climate, snap = o.snapshot;
    if (st.temp == null) st.temp = cl?.target?.value ?? snap?.climate_target ?? 21;
    if (st.noExt == null) st.noExt = cl?.without_external_power ?? false;
    const inp = h('input', { type: 'number', min: 15.5, max: 30, step: 0.5, value: st.temp, inputmode: 'decimal',
      oninput: (e) => { st.temp = e.target.value === '' ? '' : Number(e.target.value); } });
    const bump = (d) => () => { const v = Math.min(30, Math.max(15.5, (toNum(st.temp) ?? 21) + d)); st.temp = v; inp.value = v; };
    const validate = () => {
      const v = toNum(st.temp);
      if (v == null || v < 15.5 || v > 30) return { error: t('Choose a temperature between 15.5 and 30 °C.') };
      return { temperature: Math.round(v * 2) / 2, without_external_power: unplugged || !!st.noExt };
    };
    const unplugged = snap?.plug_connected === false;     // then the climate can only run on the battery
    const auxState = ['HEATING_AUXILIARY', 'VENTILATION'].includes(cl?.state);
    const running = !!cl?.running && !auxState;
    const state = cl ? h('div', { class: 'row' }, chip(cl.running ? t('Running') : t('Off'), cl.running ? 'good' : '', 'thermo'),
      cl.target?.value != null ? chip(t('target {temp}', { temp: f.temp(cl.target.value) }), '') : null,
      cl.running && cl.reach_at ? chip(t('ready {time}', { time: f.time(cl.reach_at) }), 'info', 'clock') : null)
      : h('div', { class: 'small muted' }, o.parts.airConditioning?.reason || t('Not known'));
    const going = isOn('climate', running);
    const form = going ? null : h('div', { class: 'stack' },
      h('div', null, field(t('Target temperature'), h('div', { class: 'b-stepper' },
        button('', { ic: 'minus', onClick: bump(-0.5), title: t('Decrease'), size: 'sm' }), inp, button('', { ic: 'plus', onClick: bump(0.5), title: t('Increase'), size: 'sm' }), h('span', { class: 'b-big' }, '°C')))),
      h('label', { class: 'b-check' }, h('input', { type: 'checkbox', checked: unplugged || !!st.noExt, disabled: unplugged, onchange: (e) => { st.noExt = e.target.checked; } }),
        h('span', null, t('Without external power'))),
      unplugged ? h('div', { class: 'small muted' }, icon('info', { size: 14 }), ' ', t('Not plugged in: the climate runs on the battery.')) : null);
    const body = h('div', { class: 'stack' }, state, form,
      toggle({ key: 'climate', on: running, start: 'start_climate', stop: 'stop_climate', getStart: validate, ic: ['thermo', 'x'] }));
    return card(t('Climate'), body, { ic: 'thermo' });
  }

  function auxCard(o) {
    const spinSet = info?.spin_set;
    if (st.auxTemp == null) st.auxTemp = '';
    if (st.auxDur == null) st.auxDur = 30;
    if (st.auxMode == null) st.auxMode = 'HEATING';
    const g = gate('start_aux_heating');
    const validate = () => {
      const tt = toNum(st.auxTemp), d = toNum(st.auxDur);
      if (st.auxTemp !== '' && (tt == null || tt < 15.5 || tt > 30)) return { error: t('Choose a temperature between 15.5 and 30 °C.') };
      if (d == null || d < 5 || d > 60) return { error: t('Choose a duration between 5 and 60 minutes.') };
      const p = { duration_min: Math.round(d), mode: st.auxMode };
      if (tt != null) p.temperature = Math.round(tt * 2) / 2;
      return p;
    };
    const noSpin = g.ok && info && !spinSet;
    const cl = o.sections.climate;
    const auxOn = !!cl?.running && cl?.state === 'HEATING_AUXILIARY';
    const auxGoing = isOn('aux', auxOn);                  // while running, only the status and the Stop button
    const body = h('div', { class: 'stack' },
      h('div', { class: 'small muted' }, t('The auxiliary heater needs your S-PIN.')),
      noSpin ? banner('warn', t('No S-PIN is stored.'), ' ', h('a', { href: '#/settings' }, t('Add it under Settings.'))) : null,
      h('div', { class: 'grid g2' },
        field(t('Target temperature'), h('input', { type: 'number', min: 15.5, max: 30, step: 0.5, placeholder: '—', value: st.auxTemp, disabled: !g.ok, inputmode: 'decimal',
          oninput: (e) => { st.auxTemp = e.target.value; } })),
        field(t('Duration (minutes)'), h('input', { type: 'number', min: 5, max: 60, step: 1, value: st.auxDur, disabled: !g.ok, inputmode: 'numeric', oninput: (e) => { st.auxDur = e.target.value; } }))),
      selectField(t('Mode'), [['HEATING', t('Heating')], ['VENTILATION', t('Ventilation only')]], st.auxMode, (v) => { st.auxMode = v; }, { disabled: !g.ok }),
      toggle({ key: 'aux', on: auxOn, start: 'start_aux_heating', stop: 'stop_aux_heating', getStart: validate, ic: ['flame', 'x'],
        blocked: noSpin ? t('Add your S-PIN under Settings first.') : null }));
    return card(t('Auxiliary heater'), auxGoing ? h('div', { class: 'stack' }, chip(t('Running'), 'good', 'flame'), body.lastChild) : body, { ic: 'flame' });
  }

  function ventCard(o) {
    const cl = o.sections.climate;
    const on = !!cl?.running && cl?.state === 'VENTILATION';
    return card(t('Ventilation'), h('div', { class: 'stack' }, isOn('vent', on) ? chip(t('Running'), 'good', 'fan') : null,
      toggle({ key: 'vent', on, start: 'start_ventilation', stop: 'stop_ventilation', ic: ['fan', 'x'] })), { ic: 'fan' });
  }

  // ---- charging profile editor
  const draftOf = (p) => {
    const s = p.settings || {}, m = s.minBatteryStateOfCharge || {};
    return {
      name: p.name || '', target: s.targetStateOfChargeInPercent ?? '', maxCur: s.maxChargingCurrent || '', unlock: s.autoUnlockPlugWhenCharged || '',
      minOn: !!m.enabled, minVal: m.minimumBatteryStateOfChargeInPercent ?? '',
      times: (p.preferredChargingTimes || []).map((x) => ({ id: x.id, enabled: !!x.enabled, start: x.startTime || '', end: x.endTime || '' })),
      timers: (p.timers || []).map((x) => ({ id: x.id, enabled: !!x.enabled, type: x.type || 'RECURRING', time: x.time || '', days: [...(x.recurringOn || [])], one: x.oneOffDay || '' })),
    };
  };
  const validateDraft = (d) => {
    if (!d.name.trim()) return t('Name must not be empty.');
    if (d.target !== '' && !(toNum(d.target) >= 1 && toNum(d.target) <= 100)) return t('Target charge must be between 1 and 100 %.');
    if (d.minOn && !(toNum(d.minVal) >= 1 && toNum(d.minVal) <= 100)) return t('Minimum charge must be between 1 and 100 %.');
    if (d.times.some((x) => !HHMM.test(x.start) || !HHMM.test(x.end))) return t('Charging times need a start and an end time.');
    if (d.timers.some((x) => !HHMM.test(x.time))) return t('Timers need a time.');
    if (d.timers.some((x) => x.type === 'RECURRING' && !x.days.length)) return t('Recurring timers need at least one weekday.');
    return null;
  };
  const paramsOf = (id, d) => {
    const p = { profile_id: id, name: d.name.trim() };
    if (d.target !== '') p.target_soc = Math.round(toNum(d.target));
    if (d.maxCur) p.max_current = d.maxCur;
    if (d.unlock) p.auto_unlock = d.unlock;
    p.min_soc_enabled = d.minOn;
    if (d.minOn) p.min_soc = Math.round(toNum(d.minVal));
    p.charging_times = d.times.map((x) => ({ id: x.id, enabled: x.enabled, start: x.start, end: x.end }));
    p.timers = d.timers.map((x) => {
      const o = { id: x.id, enabled: x.enabled, type: x.type, time: x.time };
      if (x.type === 'RECURRING') o.recurring_on = [...x.days];
      else if (x.one) o.one_off_day = x.one;
      return o;
    });
    return p;
  };

  function profileEditor(p, canEdit) {
    const key = JSON.stringify(p);
    let rec = drafts.get(p.id);
    if (!rec || rec.key !== key) { rec = { key, d: draftOf(p), dirty: false }; drafts.set(p.id, rec); }  // car data changed: take it over
    const d = rec.d;
    const dirtyNote = h('span', { class: 'chip warn', hidden: !rec.dirty }, t('unsaved changes'));
    const touch = () => { rec.dirty = true; dirtyNote.hidden = false; };
    const maxNext = (arr) => arr.reduce((m, x) => Math.max(m, Number(x.id) || 0), 0) + 1;

    const timesBox = h('div', { class: 'stack' });
    const drawTimes = () => mount(timesBox,
      d.times.length ? null : h('div', { class: 'small muted' }, t('No windows set')),
      ...d.times.map((x, i) => h('div', { class: 'b-line' },
        h('label', { class: 'b-check' }, h('input', { type: 'checkbox', checked: x.enabled, disabled: !canEdit, onchange: (e) => { x.enabled = e.target.checked; touch(); } }), h('span', null, `${t('Enabled')} #${x.id}`)),
        field(t('From'), h('input', { type: 'time', value: x.start, disabled: !canEdit, oninput: (e) => { x.start = e.target.value; touch(); } })),
        field(t('To'), h('input', { type: 'time', value: x.end, disabled: !canEdit, oninput: (e) => { x.end = e.target.value; touch(); } })),
        button(t('Remove'), { ic: 'trash', size: 'sm', kind: 'danger', disabled: !canEdit, onClick: () => { d.times.splice(i, 1); touch(); drawTimes(); } }))),
      button(t('Add time window'), { ic: 'plus', size: 'sm', disabled: !canEdit, onClick: () => { d.times.push({ id: maxNext(d.times), enabled: true, start: '22:00', end: '06:00' }); touch(); drawTimes(); } }));
    drawTimes();

    const timersBox = h('div', { class: 'stack' });
    const drawTimers = () => mount(timersBox,
      d.timers.length ? null : h('div', { class: 'small muted' }, t('No timers set')),
      ...d.timers.map((x, i) => h('div', { class: 'b-line b-timer' },
        h('label', { class: 'b-check' }, h('input', { type: 'checkbox', checked: x.enabled, disabled: !canEdit, onchange: (e) => { x.enabled = e.target.checked; touch(); } }), h('span', null, `${t('Enabled')} #${x.id}`)),
        field(t('Time'), h('input', { type: 'time', value: x.time, disabled: !canEdit, oninput: (e) => { x.time = e.target.value; touch(); } })),
        selectField(t('Type'), [['RECURRING', t('Recurring')], ['ONE_OFF', t('One-off')]], x.type, (v) => { x.type = v; touch(); drawTimers(); }, { disabled: !canEdit }),
        x.type === 'RECURRING'
          ? h('fieldset', { class: 'b-days' }, h('legend', null, t('Day')), ...DAYS.map((day) => h('label', { class: 'b-day' },
            h('input', { type: 'checkbox', checked: x.days.includes(day), disabled: !canEdit, onchange: (e) => { x.days = e.target.checked ? [...x.days, day] : x.days.filter((y) => y !== day); touch(); } }),
            h('span', null, t(DAY_SHORT[day])))))
          : selectField(t('Day'), [['', '–'], ...DAYS.map((day) => [day, t(DAY_LONG[day])])], x.one, (v) => { x.one = v; touch(); }, { disabled: !canEdit }),
        button(t('Remove'), { ic: 'trash', size: 'sm', kind: 'danger', disabled: !canEdit, onClick: () => { d.timers.splice(i, 1); touch(); drawTimers(); } }))),
      button(t('Add timer'), { ic: 'plus', size: 'sm', disabled: !canEdit, onClick: () => { d.timers.push({ id: maxNext(d.timers), enabled: true, type: 'RECURRING', time: '07:30', days: [], one: '' }); touch(); drawTimers(); } }));
    drawTimers();

    const dis = !canEdit;
    const form = h('div', { class: 'stack' },
      h('div', { class: 'grid g2' },
        field(t('Profile name'), h('input', { type: 'text', maxlength: 60, value: d.name, disabled: dis, oninput: (e) => { d.name = e.target.value; touch(); } })),
        field(t('Target charge'), h('input', { type: 'number', min: 1, max: 100, step: 1, value: d.target, disabled: dis, inputmode: 'numeric', oninput: (e) => { d.target = e.target.value; touch(); } }), '%'),
        selectField(t('Maximum current'), [['', '–'], ['MAXIMUM', t('Maximum')], ['REDUCED', t('Reduced')]], d.maxCur, (v) => { d.maxCur = v; touch(); }, { disabled: dis }),
        selectField(t('Unlock plug when charged'), [['', '–'], ['PERMANENT', t('Permanent')], ['OFF', t('Off')]], d.unlock, (v) => { d.unlock = v; touch(); }, { disabled: dis })),
      h('div', { class: 'b-line' },
        h('label', { class: 'b-check' }, h('input', { type: 'checkbox', checked: d.minOn, disabled: dis, onchange: (e) => { d.minOn = e.target.checked; touch(); } }), h('span', null, t('Keep at least this charge'))),
        field(t('Minimum charge level'), h('input', { type: 'number', min: 1, max: 100, step: 1, value: d.minVal, disabled: dis, inputmode: 'numeric', oninput: (e) => { d.minVal = e.target.value; touch(); } }))),
      h('div', { class: 'stack' }, h('h3', null, t('Preferred charging times')), timesBox),
      h('div', { class: 'stack' }, h('h3', null, t('Timers')), timersBox),
      h('div', { class: 'row' },
        cmdBtn('update_charging_profile', t('Save profile'), () => { const e = validateDraft(d); return e ? { error: e } : paramsOf(p.id, d); }, { ic: 'check', kind: 'primary', disabled: dis, onOk: () => { rec.dirty = false; } }),
        button(t('Discard changes'), { ic: 'refresh', onClick: () => { drafts.delete(p.id); render(true); } }), dirtyNote));

    const det = h('details', { class: 'b-profile', open: openProfiles.has(p.id) || null, ontoggle: (e) => { if (e.target.open) openProfiles.add(p.id); else openProfiles.delete(p.id); } },
      h('summary', null, h('strong', null, p.name || `#${p.id}`), ' ',
        chip(`${d.target !== '' ? `${d.target} %` : '–'}`, ''), p.id === ctxCurrentId() ? chip(t('Charging profile at the current position'), 'info', 'pin') : null,
        p.id === ctxCurrentId() && ctx.overview.sections.profiles?.current?.next_charging_time
          ? chip(t('next charge {time}', { time: ctx.overview.sections.profiles.current.next_charging_time }), '', 'clock') : null),
      form);
    return det;
  }
  const ctxCurrentId = () => ctx.overview.sections.profiles?.current?.id;

  function profilesCard(o) {
    const prof = o.sections.profiles;
    const g = gate('update_charging_profile');
    let body;
    if (!o.parts.chargingProfiles?.available && !prof?.profiles?.length) body = empty(t('No charging profiles reported.'), o.parts.chargingProfiles?.reason, 'plug');
    else if (!prof?.profiles?.length) body = empty(t('No charging profiles reported.'), null, 'plug');
    else body = h('div', { class: 'stack' }, ...prof.profiles.map((p) => profileEditor(p, g.ok)));
    const note = h('div', { class: 'small muted b-reason' }, icon('info', { size: 14 }), ' ', t('The Škoda API can only change existing profiles. Create a new one in the MyŠkoda app or in the car; it appears here after the next reading.'));
    return card(t('Charging profiles'), h('div', { class: 'stack' }, body, note), { ic: 'sliders' });
  }

  // ---- log + budget
  function summarize(params) {
    if (!params) return '–';
    const s = Object.entries(params).map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(', ');
    return s.length > 80 ? `${s.slice(0, 77)}…` : s;
  }
  function logCard(o) {
    const b = info?.budget || o.poller?.budget;
    const budget = b ? h('div', { class: 'stack' },
      h('div', { class: 'row' }, chip(`${b.used}/${b.limit}`, b.remaining_for_commands <= 0 ? 'warn' : '', 'signal'), h('span', { class: 'small' }, t('requests used this hour')),
        b.next_free_s ? chip(t('next free in {time}', { time: f.inSeconds(b.next_free_s) }), 'warn', 'clock') : null),
      h('div', { class: 'tiny muted' }, t('Every command costs 1 of the 20 requests per hour Škoda allows per car.'))) : null;
    let logBody;
    if (infoError) logBody = h('div', { class: 'stack' }, banner('bad', `${t('Could not load the command list')}: ${infoError}`), button(t('Try again'), { ic: 'refresh', onClick: async () => { await loadInfo(); render(true); } }));
    else if (!info) logBody = loading();
    else logBody = table([
      { label: t('When'), render: (c) => f.dateTime(c.at), cls: 'nowrap' },
      { label: t('Command'), render: (c) => label(c.name) },
      { label: t('Details'), render: (c) => h('span', { class: 'small muted' }, summarize(c.params)) },
      { label: t('Result'), render: (c) => (c.ok ? chip(t('Sent'), 'good', 'check') : h('div', null, chip(t('Failed'), 'bad', 'alert'), c.error ? h('div', { class: 'tiny' }, t(c.error)) : null)) },
    ], info.log, { label: t('Commands sent'), emptyNode: empty(t('No commands sent yet.'), null, 'list') });
    return card(t('Command log'), h('div', { class: 'stack' }, budget, logBody), { ic: 'list' });
  }

  const anySupported = () => can(...Object.keys(cmdMap()));
  function missingNote(any) {
    return h('div', { class: 'banner info' }, icon('info', { size: 18 }), h('div', { class: 'grow' },
      any ? null : h('div', null, h('strong', null, t('No remote commands available.')), ' ', t('Your car does not offer any, or Mate does not know yet which ones it supports.')),
      h('strong', null, t('Only supported controls are shown.')), ' ', t('Everything else, with the reason, is listed under Capabilities.'), ' ',
      h('a', { href: '#/system/capabilities' }, t('Open Capabilities'))));
  }

  // ---- render
  function render(force = false) {
    if (dead) return;
    const a = document.activeElement;
    if (!force && a && root.contains(a) && /^(INPUT|SELECT|TEXTAREA)$/.test(a.tagName)) return;   // do not wipe what the user is typing
    const o = ctx.overview, s = o.snapshot;
    if (!s || !s.recorded_at) { mount(root, empty(t('No reading yet'), t('Mate is asking Škoda for the first time. This takes a moment.'), 'refresh')); return; }
    const hasBattery = o.parts.charging?.available;
    mount(root,
      pending ? h('div', { class: 'banner info', role: 'status' }, icon('clock', { size: 18 }), h('div', { class: 'grow' }, h('strong', null, `${t('Waiting for confirmation')}: ${pending.label}.`), ' ',
        t('Škoda accepted the request. Mate reads the car again in about 45 seconds.'))) : null,
      // Only what this car can do. Everything else (and why) is on the Capabilities page.
      h('div', { class: 'grid g2 b-cards' },
        hasBattery && can('start_charging', 'stop_charging', 'set_charge_limit', 'set_charge_mode') ? chargingCard(o, s) : null,
        can('start_climate', 'stop_climate') ? climateCard(o) : null,
        can('start_aux_heating', 'stop_aux_heating') ? auxCard(o) : null,
        can('start_ventilation', 'stop_ventilation') ? ventCard(o) : null),
      hasBattery && can('update_charging_profile') ? profilesCard(o) : null, logCard(o), missingNote(anySupported(o)));
  }

  await loadInfo();
  render(true);
  ctx.onTick(async () => { await loadInfo(); render(); });
  return () => { dead = true; clearTimeout(pendingTimer); };
}
