// Place detail: the geofence on the map, its visits and charges, and the shared edit form.
import { h, mount } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { banner, button, card, chip, empty, loading, stat, table, toast } from '../lib/ui.js';
import { mapView } from '../lib/mapview.js';
import * as f from '../lib/format.js';
import { t } from '../i18n.js';
import { placeForm } from './places.js';
import { placeChip } from './charges.js';

const KIND_LABEL = { home: 'Home', work: 'Work', place: 'Place' };
const KIND_TONE = { home: 'good', work: 'info', place: '' };
const KIND_ICON = { home: 'home', work: 'building', place: 'pin' };
const kindName = (kind) => t(KIND_LABEL[kind] || 'Place');
const displayName = (p) => (p.kind === 'home' && p.name === 'Home' ? t('Home') : p.name);
// Date and time on two short lines: on a phone a full date-time wraps into four lines and pushes the table off screen.
// The full f.dateTime stays in the tooltip (and the charge link's aria-label).
const when = (iso) => h('span', { class: 'pd-when', title: f.dateTime(iso) }, f.date(iso), h('br'), h('span', { class: 'tiny muted' }, f.time(iso)));

export default async function place(root, ctx) {
  const id = Number(ctx.params?.[0]);
  const state = { place: null, homeExists: false };

  const backLink = () => h('a', { class: 'a-back', href: '#/places' }, icon('left', { size: 16 }), t('Back to places'));

  function notFound() {
    ctx.setTitle(t('Place not found.'));
    mount(root, h('div', { class: 'stack' }, backLink(), empty(t('Place not found.'), t('The place may have been removed.'), 'pin')));
  }

  async function load() {
    const tz = new Date().getTimezoneOffset();
    const [place, list] = await Promise.all([
      // The server computes day_count and visit minutes in the viewer's local day, so both reads need the offset.
      ctx.api.get(`/api/places/${id}?tz_offset=${tz}`),
      // Only for `homeExists`: the form offers the Home kind only while no other place owns it.
      ctx.api.get(`/api/places?tz_offset=${tz}`).catch(() => null),
    ]);
    state.place = place;
    state.homeExists = (list?.items || []).some((p) => p.kind === 'home' && p.id !== id);
  }

  async function onSaved(result) {
    if (result?.ok) { ctx.nav('places'); return; }  // deleted: the shared form already confirmed and toasted
    try { await load(); draw(); } catch (e) { toast(t(e.message || String(e)), 'bad'); }
  }

  function openForm({ remove = false } = {}) {
    placeForm({ place: state.place, homeExists: state.homeExists, onSaved });
    // Delete stays in the shared form (same confirmation, German text and API call). Opening it and starting that
    // action is the only way to reuse it without a second delete path; cancelling leaves the edit form open.
    if (remove) document.querySelector('.scrim .modal .btn.danger')?.click();
  }

  function draw() {
    const p = state.place;
    const name = displayName(p);
    ctx.setTitle(name);

    const head = h('div', { class: 'pl-head' },
      h('div', { class: 'pd-title' },
        h('h1', null, name),
        h('div', { class: 'pd-meta' }, chip(kindName(p.kind), KIND_TONE[p.kind] || '', KIND_ICON[p.kind] || 'pin'))),
      h('div', { class: 'row tight' },
        button(t('Edit place'), { ic: 'edit', onClick: () => openForm() }),
        p.kind === 'home' ? null : button(t('Delete place'), { kind: 'danger', ic: 'trash', onClick: () => openForm({ remove: true }) })));

    const mapCard = card(t('Position'), mapView({
      height: 'short',
      markers: [{ lat: p.lat, lon: p.lon, label: name }],
      // No id: the circle is a passive hint, not a second click target.
      circles: [{ lat: p.lat, lon: p.lon, radius: p.radius_m, color: p.color, label: name }],
    }), { ic: 'map' });

    const stats = h('div', { class: 'grid auto pd-stats' },
      card(null, stat(t('Visits'), f.num(p.visit_count), { ic: 'pin' })),
      card(null, stat(t('Days'), f.num(p.day_count), { ic: 'calendar' })),
      card(null, stat(t('Parked time'), f.duration(p.parked_minutes), { ic: 'clock' })),
      card(null, stat(t('Charged'), f.kwh(p.charged_kwh), { ic: 'bolt' })),
      card(null, stat(t('Cost'), f.money(p.cost, p.currency || ctx.currency), { ic: 'coin' })));

    const visits = table([
      { label: t('Arrival'), render: (v) => when(v.arrived_at) },
      { label: t('Departure'), render: (v) => (v.left_at ? when(v.left_at) : '–') },
      { label: t('Duration'), num: true, render: (v) => f.duration(v.minutes) },
      { label: t('Status'), render: (v) => chip(t(v.open ? 'Open now' : 'Closed'), v.open ? 'good' : '') },
    ], p.visits || [], { label: t('Recent visits'), emptyNode: empty(t('No visits yet'), null, 'pin') });

    const charges = table([
      { label: t('Date'), render: (c) => h('a', { class: 'pd-date', href: `#/charges/${c.id}`, 'aria-label': `${t('Charge')} ${f.dateTime(c.started_at)}` },
        when(c.started_at), icon('right', { size: 14 })) },
      { label: t('Energy'), num: true, render: (c) => f.kwh(c.energy_kwh) },
      { label: t('Cost'), num: true, render: (c) => h('div', { class: 'pd-cost' },
        h('strong', null, `${c.cost_basis === 'tariff-guess' ? '≈ ' : ''}${f.money(c.cost, p.currency || ctx.currency)}`),
        h('div', { class: 'row tight pd-basis' }, placeChip(c),
          c.cost_basis === 'manual' ? h('span', { class: 'chip', title: t('Cost entered by you') }, icon('edit', { size: 12 }), t('manual')) : null)) },
    ], p.charges || [], { label: t('Recent charges'), emptyNode: empty(t('No charges yet'), null, 'plug') });

    mount(root, h('div', { class: 'stack' },
      backLink(),
      head,
      mapCard,
      stats,
      card(t('Recent visits'), h('div', { class: 'pd-visits' }, visits), { ic: 'clock' }),
      card(t('Recent charges'), charges, { ic: 'plug' })));
  }

  async function start() {
    ctx.setTitle(t('Place'));
    mount(root, loading());
    if (!Number.isFinite(id) || id <= 0) { notFound(); return; }
    try {
      await load();
    } catch (e) {
      if (e.status === 404) { notFound(); return; }
      mount(root, h('div', { class: 'stack' }, backLink(),
        banner('bad', `${t('Could not load this place')}: ${t(e.message || String(e))}`),
        button(t('Try again'), { onClick: start, ic: 'refresh' })));
      return;
    }
    draw();
  }

  await start();
}
