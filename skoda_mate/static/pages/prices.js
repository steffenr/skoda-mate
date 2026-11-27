// Charge prices: what a kWh costs (home, public AC, public DC). One page, one save bar.
// Data: GET/PUT /api/settings { tariff: { currency, home_kwh, public_ac_kwh, public_dc_kwh } }; the home place is a
// geofence of its own, so GET /api/places feeds the card and POST /api/vehicles/{vid}/home-here moves it.
import { h, mount } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { asyncButton, banner, button, card, field, toast } from '../lib/ui.js';
import * as f from '../lib/format.js';
import { t } from '../i18n.js';

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
  try { return new Intl.NumberFormat(f.getLocale(), { style: 'currency', currency: code }).formatToParts(0).find((p) => p.type === 'currency')?.value || code; } catch { return code; }
}

export default async function prices(root, ctx) {
  ctx.setTitle(t('Charge prices'));
  let S, placeList;
  try {
    [S, placeList] = await Promise.all([
      ctx.api.get('/api/settings'),
      ctx.api.get(`/api/places?tz_offset=${new Date().getTimezoneOffset()}`),
    ]);
  } catch (e) { mount(root, banner('bad', `${t('Could not load the prices')}: ${e.message}`)); return; }
  const tf = S.tariff || {};
  const fromTariff = (x) => ({ currency: x.currency || 'EUR', home: x.home_kwh ?? '', ac: x.public_ac_kwh ?? '', dc: x.public_dc_kwh ?? '' });
  let saved = fromTariff(tf);
  const d = { ...saved };
  const els = {};

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

  // ---- home place: edited on its own page, so this card only summarizes it and links there
  let home = (placeList?.items || []).find((p) => p.kind === 'home') || null;
  const homeBox = h('div');
  const homeName = () => (home.name === 'Home' ? t('Home') : home.name);
  const radiusText = (m) => { const metres = m ?? 150; return f.km(metres / 1000, metres < 1000 ? 2 : 1); };
  function drawHome() {
    if (!home) {
      mount(homeBox, h('div', { class: 'stack' },
        h('div', { class: 'small muted' }, t('No home place yet.')),
        h('div', { class: 'row' }, h('a', { class: 'btn', href: '#/places' }, icon('plus', { size: 16 }), t('Add home place')))));
      return;
    }
    mount(homeBox, h('div', { class: 'row between' },
      h('div', null,
        h('strong', null, homeName()),
        h('div', { class: 'small muted' }, `${radiusText(home.radius_m)} · ${f.num(home.visit_count ?? 0)} ${t('Visits')}`)),
      h('a', { class: 'btn sm', href: `#/places/${home.id}` }, icon('edit', { size: 16 }), t('Edit home place'))));
  }
  async function loadHome() {
    const list = await ctx.api.get(`/api/places?tz_offset=${new Date().getTimezoneOffset()}`);
    home = (list?.items || []).find((p) => p.kind === 'home') || null;
  }
  const placeCard = card(t('Home place'), h('div', { class: 'stack' },
    h('div', { class: 'small muted' }, t('Charges within the radius of this position count as home charges.')),
    homeBox,
    h('div', { class: 'row' }, asyncButton(t('Use current parking position'), async () => {
      await ctx.api.post(`/api/vehicles/${ctx.vid}/home-here`);
      await loadHome();
      drawHome();
      await ctx.refresh();
      toast(t('Home position saved'), 'good');
    }, { ic: 'pin' }))), { ic: 'home' });

  // ---- save / discard
  async function save() {
    if (!/^[A-Za-z]{1,4}$/.test(String(d.currency).trim())) fail(t('Currency must be a short code such as EUR.'));
    for (const k of ['home', 'ac', 'dc']) if (d[k] !== '' && !(num(d[k]) >= 0 && num(d[k]) <= 10)) fail(t('Prices must be between 0 and 10 per kWh.'));
    // No home keys: the home place belongs to the Places page, and a prices save must leave it untouched.
    const res = await ctx.api.put('/api/settings', { tariff: { currency: String(d.currency).trim().toUpperCase(), home_kwh: d.home, public_ac_kwh: d.ac, public_dc_kwh: d.dc } });
    saved = fromTariff(res.tariff || {}); Object.assign(d, saved);
    for (const k of Object.keys(els)) if (els[k] && k in d) els[k].value = d[k];
    syncExamples(); syncBar();
    await ctx.refresh();
    toast(t('Prices saved'), 'good');
  }
  function discard() {
    Object.assign(d, saved);
    for (const k of Object.keys(els)) if (els[k] && k in d) els[k].value = d[k];
    syncExamples(); syncBar();
    toast(t('Changes discarded'), 'info');
  }
  saveBtn = asyncButton(t('Save prices'), save, { ic: 'check', kind: 'primary', disabled: true });
  discardBtn = button(t('Discard'), { ic: 'x', disabled: true, onClick: discard });
  const bar = h('div', { class: 'pr-bar' }, status, h('div', { class: 'row tight' }, discardBtn, saveBtn));

  mount(root,
    h('div', { class: 'stack' }, h('h1', null, t('Charge prices')), h('p', { class: 'muted' }, t('Set what each kWh costs, so Mate can price your charges.'))),
    banner('info', t('Changes recalculate the cost of every charge and trip without a manual price, including past ones. A price you set by hand on a charge always wins.')),
    pricesCard, placeCard, bar);
  drawHome(); syncExamples(); syncBar();
}
