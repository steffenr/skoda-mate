// The car picture: Škoda's own render (`renderUrl` from the API) when available, otherwise a drawn silhouette. Status
// badges sit under it. The render URL is a remote image; if it fails to load we fall back without noise.
import { h, svg } from './dom.js';
import { icon } from './icons.js';
import { chip } from './ui.js';
import { N_, t, tEnum } from '../i18n.js';

const CLIMATE_CHIP = {
  COOLING: N_('Climate cooling'), HEATING: N_('Climate heating'), HEATING_AUXILIARY: N_('Climate heating (auxiliary heater)'),
  VENTILATION: N_('Climate ventilation'), ON: N_('Climate on'),
};

function silhouette() {
  return svg('svg', { class: 'silhouette', viewBox: '0 0 420 170', role: 'img', 'aria-label': t('Car') },
    svg('path', { d: 'M28 118c-6 0-10-4-10-10v-9c0-8 5-14 13-16l44-9 39-31c6-5 13-8 21-8h112c10 0 19 4 26 11l32 28 56 12c8 2 13 8 13 16v6c0 6-4 10-10 10h-14', fill: 'none', stroke: 'currentColor', 'stroke-width': 4, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }),
    svg('path', { d: 'M126 60h74v28h-98zM210 60h50l30 28h-80z', fill: 'currentColor', opacity: .18 }),
    svg('path', { d: 'M62 118h262', stroke: 'currentColor', 'stroke-width': 4, 'stroke-linecap': 'round' }),
    ...[110, 322].map((cx) => svg('g', null,
      svg('circle', { cx, cy: 122, r: 25, fill: 'var(--surface)', stroke: 'currentColor', 'stroke-width': 4 }),
      svg('circle', { cx, cy: 122, r: 9, fill: 'currentColor', opacity: .35 }))));
}

/** carView(overview) -> element. Uses overview.sections.info.render_url, snapshot flags and the charging state. */
export function carView(o) {
  const snap = o.snapshot || {};
  const url = o.sections?.info?.render_url;
  const charging = !!snap.charging;
  const box = h('div', { class: ['carview', charging ? 'charging' : ''] });
  const fallback = () => { box.querySelector('img')?.remove(); if (!box.querySelector('.silhouette')) box.prepend(silhouette()); };
  if (url) {
    const img = h('img', { src: url, alt: o.sections?.info?.name || t('Car'), loading: 'lazy', referrerpolicy: 'no-referrer' });
    img.addEventListener('error', fallback);
    box.append(img);
  } else box.append(silhouette());

  // ---- vehicle status: one summary line + four cells. Calm when all is well, loud only where something needs attention.
  // The API says "unknown" by omitting a value; that must never be shown as closed or locked.
  const cell = (ic, label, value, kind) => h('div', { class: ['cs-cell', kind] }, icon(ic, { size: 18 }),
    h('div', { class: 'cs-text' }, h('span', { class: 'cs-l' }, label), h('strong', { class: 'cs-v' }, value)));
  const attention = [];                                  // what the summary line lists
  const flag = (text, kind) => { attention.push(text); return kind; };

  let doors;
  if (snap.doors_open === true) doors = cell('door', t('Doors'), t('Open'), flag(t('Door open'), 'bad'));
  else if (snap.locked === false) doors = cell('unlock', t('Doors'), t('Unlocked'), flag(t('Unlocked'), 'bad'));
  else if (snap.locked === true) doors = cell('lock', t('Doors'), t('Locked'), 'ok');
  else doors = cell('lock', t('Doors'), t('Unknown'), 'unknown');

  let windows;
  if (snap.windows_open === true) windows = cell('window', t('Windows'), t('Open'), flag(t('Window open'), 'warn'));
  else if (snap.sunroof_open === true) windows = cell('window', t('Windows'), t('Sunroof open'), flag(t('Sunroof open'), 'warn'));
  else if (snap.windows_open === false) windows = cell('window', t('Windows'), t('Closed'), 'ok');
  else windows = cell('window', t('Windows'), t('Unknown'), 'unknown');

  let trunk;
  if (snap.trunk_open === true) trunk = cell('car', t('Trunk & bonnet'), t('Trunk open'), flag(t('Trunk open'), 'bad'));
  else if (snap.bonnet_open === true) trunk = cell('car', t('Trunk & bonnet'), t('Bonnet open'), flag(t('Bonnet open'), 'bad'));
  else if (snap.trunk_open === false && snap.bonnet_open === false) trunk = cell('car', t('Trunk & bonnet'), t('Closed'), 'ok');
  else trunk = cell('car', t('Trunk & bonnet'), t('Unknown'), 'unknown');

  const lights = snap.lights_on === true ? cell('sun', t('Lights'), t('On'), 'info')
    : snap.lights_on === false ? cell('sun', t('Lights'), t('Off'), 'ok') : cell('sun', t('Lights'), t('Unknown'), 'unknown');

  const cells = [doors, windows, trunk, lights];
  const unknownCount = cells.filter((c) => c.classList.contains('unknown')).length;
  const worst = cells.some((c) => c.classList.contains('bad')) ? 'bad' : attention.length ? 'warn' : unknownCount === cells.length ? 'unknown' : unknownCount ? 'partial' : 'ok';
  const summaryText = attention.length ? `${t('Check the car')}: ${attention.join(' · ')}`
    : worst === 'unknown' ? t('Status not reported') : worst === 'partial' ? t('Status only partly reported') : t('Everything closed and locked');
  const summary = h('div', { class: ['cs-summary', worst], role: 'status' },
    icon(worst === 'ok' ? 'check' : worst === 'bad' || worst === 'warn' ? 'alert' : 'info', { size: 16 }), h('span', null, summaryText));

  // ---- what is going on right now (only when it is): charging line, driving, climate. Parked / plugged are shown elsewhere.
  const live = [];
  // charging details live next to the battery on the overview; the car only shows its own state
  if (snap.in_motion) live.push(chip(t('Driving##state'), 'info', 'route'));
  if (snap.climate_state && !['OFF', 'UNKNOWN', 'UNSUPPORTED', 'COMPLETED'].includes(snap.climate_state)) live.push(chip(CLIMATE_CHIP[snap.climate_state] ? t(CLIMATE_CHIP[snap.climate_state]) : `${t('Climate')}: ${tEnum(snap.climate_state)}`, 'info', 'thermo'));

  return h('div', { class: 'carcard' }, summary, box, h('div', { class: 'cs-grid' }, ...cells), live.length ? h('div', { class: 'badges' }, ...live) : null);
}
