// Places: the named geofences the car stops at. The page lists them, draws them on a map and opens one form for
// creating and editing. The form is exported because the place detail page (pages/place.js) reuses it.
import { h, mount } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { asyncButton, banner, button, card, chip, confirmDialog, empty, field, loading, modal, toast } from '../lib/ui.js';
import { mapView } from '../lib/mapview.js';
import * as f from '../lib/format.js';
import { t, tn, N_ } from '../i18n.js';
import { api } from '../app.js';

const KINDS = [['home', 'Home'], ['work', N_('Work')], ['place', 'Place']];
const KIND_TONE = { home: 'good', work: 'info', place: '' };
// The same palette as places.COLORS in skoda_mate/places.py.
const COLOURS = [
  ['#0b7a52', N_('Green')], ['#1d5fa8', N_('Blue')], ['#b86e00', N_('Amber')],
  ['#7a3fa8', N_('Purple')], ['#b3261e', N_('Red')], ['#0e7a7a', N_('Teal')],
];
const PRICE_FIELDS = [
  ['price_kwh', 1000, 'Price per kWh must be between 0 and 1000.'],
  ['price_minute', 1000, 'Price per minute must be between 0 and 1000.'],
  ['session_fee', 10000, 'Session fee must be between 0 and 10000.'],
];

const displayName = (p) => (p.kind === 'home' && p.name === 'Home' ? t('Home') : p.name);
const kindName = (kind) => t(KINDS.find(([k]) => k === kind)?.[1] || 'Place');
const radiusText = (m) => { const metres = m ?? 150; return f.km(metres / 1000, metres < 1000 ? 2 : 1); };
const amount = (v) => (v === '' || v == null || Number.isNaN(Number(v)) ? null : Number(v));

function placeRow(p, onEdit) {
  const name = displayName(p);
  const meta = [
    radiusText(p.radius_m),
    tn('{n} Visit', '{n} Visits', p.visit_count ?? 0),
    tn('{n} Day', '{n} Days', p.day_count ?? 0),
    p.last_seen ? t('last seen {date}', { date: f.dateTime(p.last_seen) }) : null,
  ].filter(Boolean).join(' · ');
  const edit = button(t('Edit'), { size: 'sm', ic: 'edit', title: `${t('Edit')}: ${name}`, onClick: () => onEdit(p) });
  edit.setAttribute('aria-label', `${t('Edit')}: ${name}`);
  return h('div', { class: 'pl-row' },
    h('a', { class: 'pl-row-link', href: `#/places/${p.id}` },
      h('span', { class: 'pl-row-main' },
        h('span', { class: 'pl-name' },
          h('span', { class: 'pl-dot', style: p.color ? { background: p.color } : null }),
          h('strong', null, name)),
        chip(kindName(p.kind), KIND_TONE[p.kind] || '', p.kind === 'home' ? 'home' : null),
        h('span', { class: 'pl-meta tiny muted' }, meta)),
      icon('right', { size: 16 })),
    edit);
}

/**
 * The create/edit dialog. Exported for the place detail page; `onSaved` runs after a successful save or delete so the
 * caller can refresh. `place` is the stored place, `point` the chosen map position, `draft` field values carried from
 * a previous "Pick on the map", `homeExists` disables Home when one already exists, and `onPick` closes the dialog so
 * the caller can reopen it at the next map click.
 */
export function placeForm({ place = null, point = null, draft: carried = null, homeExists = false, onPick = null, onSaved } = {}) {
  const editing = !!place;
  const lockedKind = place?.kind === 'home';
  const homeTaken = homeExists && !lockedKind;
  const lat = point?.lat ?? place?.lat ?? null;
  const lon = point?.lon ?? place?.lon ?? null;
  const base = {
    name: place?.name ?? '',
    kind: place?.kind ?? 'place',
    radius_m: place?.radius_m ?? 150,
    color: place?.color ?? '',
    price_kwh: place?.price_kwh ?? '',
    price_minute: place?.price_minute ?? '',
    session_fee: place?.session_fee ?? '',
    free: !!place?.free,
  };
  // A draft carried from "Pick on the map" wins over what is stored, so every field the user typed survives the reopen.
  const draft = carried ? { ...base, ...carried } : base;

  const inputs = {};
  inputs.name = h('input', { type: 'text', maxlength: 60, autocomplete: 'off', value: draft.name,
    oninput: (e) => { draft.name = e.target.value; } });
  inputs.radius_m = h('input', { type: 'number', inputmode: 'numeric', min: 20, max: 5000, step: 1, value: draft.radius_m,
    oninput: (e) => { draft.radius_m = e.target.value; } });
  for (const [key] of PRICE_FIELDS) {
    inputs[key] = h('input', { type: 'number', inputmode: 'decimal', min: 0, step: '0.01', value: draft[key],
      oninput: (e) => { draft[key] = e.target.value; } });
  }
  const kindInput = h('select', { onchange: (e) => { draft.kind = e.target.value; } },
    ...KINDS.map(([value, label]) => h('option', { value, disabled: value === 'home' && homeTaken }, t(label))));
  kindInput.value = draft.kind;
  const colourInput = h('select', { onchange: (e) => { draft.color = e.target.value; } },
    h('option', { value: '' }, t('Default')),
    ...COLOURS.map(([value, label]) => h('option', { value }, t(label))));
  colourInput.value = draft.color;
  const freeBox = h('input', { type: 'checkbox', checked: draft.free,
    onchange: (e) => { draft.free = e.target.checked; syncFree(); } });
  const freeHint = h('p', { class: 'tiny muted', hidden: !draft.free }, t('A free place cannot have a price.'));
  function syncFree() {
    for (const [key] of PRICE_FIELDS) {
      inputs[key].disabled = draft.free;
      if (draft.free) { inputs[key].value = ''; draft[key] = ''; }
    }
    freeHint.hidden = !draft.free;
  }
  syncFree();
  const pointText = lat == null || lon == null ? t('No point chosen') : `${f.num(lat, 5)}, ${f.num(lon, 5)}`;
  let closeForm = () => {};
  const pickBtn = onPick
    ? button(t('Pick on the map'), { size: 'sm', ic: 'pin',
      onClick: () => { const fields = { ...draft }; closeForm(); onPick(fields); } })
    : null;

  const body = h('div', { class: 'stack pl-form' },
    lat == null || lon == null ? banner('warn', t('Choose a point on the map first.')) : null,
    field(t('Name'), inputs.name),
    lockedKind
      ? h('div', { class: 'field' }, h('span', null, t('Kind')),
        h('div', { class: 'row tight' }, chip(t('Home'), 'good', 'home'), h('span', { class: 'tiny muted' }, t('A home place keeps its kind.'))))
      : field(t('Kind'), kindInput, homeTaken ? t('A home place already exists.') : null),
    h('div', { class: 'grid g2' }, field(t('Radius (metres)'), inputs.radius_m), field(t('Colour'), colourInput)),
    h('div', { class: 'pl-coords' }, icon('pin', { size: 16 }),
      h('div', null, h('span', { class: 'tiny muted' }, t('Position')), h('div', null, pointText)),
      pickBtn),
    h('div', { class: 'grid g3' },
      field(t('Price per kWh'), inputs.price_kwh),
      field(t('Price per minute'), inputs.price_minute),
      field(t('Session fee'), inputs.session_fee)),
    h('label', { class: 'pl-check' }, freeBox, h('span', null, t('Free'))),
    freeHint,
    lockedKind ? h('p', { class: 'tiny muted' }, t('Home cannot be deleted.')) : null);

  function placeBody() {
    const name = draft.name.trim();
    if (!name || name.length > 60) throw new Error(t('Name must be 1 to 60 characters.'));
    if (lat == null || lon == null) throw new Error(t('Choose a point on the map first.'));
    const radius = Number(draft.radius_m);
    if (!Number.isFinite(radius) || radius < 20 || radius > 5000) throw new Error(t('Radius must be between 20 and 5000 metres.'));
    const payload = { name, kind: draft.kind, lat, lon, radius_m: Math.round(radius), color: draft.color || null,
      price_kwh: null, price_minute: null, session_fee: null, free: !!draft.free };
    if (draft.free) {
      if (PRICE_FIELDS.some(([key]) => amount(draft[key]) != null)) throw new Error(t('A free place cannot have a price.'));
    } else {
      for (const [key, max, message] of PRICE_FIELDS) {
        const value = amount(draft[key]);
        if (value != null && !(value >= 0 && value <= max)) throw new Error(t(message));
        payload[key] = value;
      }
    }
    return payload;
  }

  closeForm = modal(t(editing ? 'Edit place' : N_('New place')), body, (close) => {
    const save = async () => {
      const payload = placeBody();
      const saved = editing ? await api.put(`/api/places/${place.id}`, payload) : await api.post('/api/places', payload);
      toast(t('Place saved'), 'good');
      close();
      await onSaved?.(saved);
    };
    const remove = async () => {
      const yes = await confirmDialog(t('Delete this place?'),
        t('Trips and charges at this place lose their link. This cannot be undone.'),
        { confirmLabel: t('Delete place'), danger: true });
      if (!yes) return;
      const result = await api.del(`/api/places/${place.id}`);
      toast(t('Place deleted'), 'good');
      close();
      await onSaved?.(result);
    };
    return [
      editing && !lockedKind ? asyncButton(t('Delete place'), remove, { kind: 'danger', ic: 'trash' }) : null,
      button(t('Cancel'), { onClick: close }),
      asyncButton(t('Save'), save, { kind: 'primary', ic: 'check', disabled: lat == null || lon == null }),
    ];
  });
}

export default async function placesPage(root, ctx) {
  ctx.setTitle(t('Places'));
  mount(root, loading());

  let state = { places: [], parked: [] };
  let mapBox = null;
  let addBtn = null;
  let pick = null;  // { place, fields } while "Pick on the map" waits for the next map click
  const pickHint = h('div');

  async function load() {
    const [list, mapData] = await Promise.all([
      // The list's day_count is local-day based, exactly like the detail page; api.get adds tz_offset only for vehicle paths.
      ctx.api.get(`/api/places?tz_offset=${new Date().getTimezoneOffset()}`),
      ctx.api.get(`/api/vehicles/${ctx.vid}/map?limit=500`),
    ]);
    state = {
      places: list?.items || [],
      parked: (mapData?.parked || []).filter((c) => c.place_id == null && c.lat != null && c.lon != null),
    };
  }

  const hasHome = (place) => state.places.some((p) => p.kind === 'home' && p.id !== place?.id);

  function openForm({ place = null, point = null, fields = null } = {}) {
    placeForm({
      place, point, draft: fields, homeExists: hasHome(place), onSaved: refresh,
      onPick: (next) => { pick = { place, fields: next }; drawPick(); },
    });
  }

  function drawPick() {
    mount(pickHint, pick ? banner('info', t('Click the map to choose the new point.'),
      button(t('Cancel'), { size: 'sm', onClick: () => { pick = null; drawPick(); addBtn?.focus(); } })) : null);
  }

  // Any other opener drops a pending pick: the draft only survives the map click it was made for.
  function startForm(opts = {}) { pick = null; drawPick(); openForm(opts); }

  function choosePoint(lat, lon) {
    const held = pick;
    pick = null;
    drawPick();
    openForm({ place: held?.place ?? null, point: { lat, lon }, fields: held?.fields ?? null });
  }

  function mapOptions() {
    return {
      markers: state.places.map((p) => ({ lat: p.lat, lon: p.lon, label: displayName(p) })),
      circles: state.places.map((p) => ({ lat: p.lat, lon: p.lon, radius: p.radius_m, color: p.color || undefined,
        label: displayName(p), id: p.id })),
      // While picking, a click anywhere - a place circle included - only sets the new point for the pending draft.
      onCircleClick: (id) => {
        const p = state.places.find((x) => x.id === id);
        if (!p) return;
        if (pick) choosePoint(p.lat, p.lon); else startForm({ place: p });
      },
      onMapClick: (lat, lon) => (pick ? choosePoint(lat, lon) : startForm({ point: { lat, lon } })),
    };
  }

  function edit(place) { startForm({ place }); }

  async function refresh() {
    try {
      await load();
      drawList();
      drawDetected();
      mapBox?.update({ ...mapOptions(), fit: false });
      // The modal closed before this ran; if the row or circle that opened it is gone, land on a stable control.
      if (document.activeElement === document.body || document.activeElement == null) addBtn?.focus();
    } catch (e) {
      toast(`${t('Could not load the places')}: ${e.message}`, 'bad');
    }
  }

  const listBody = h('div');
  function drawList() {
    if (!state.places.length) {
      mount(listBody, empty(t('No places yet'), t('Click the map to add the first one.'), 'pin'));
      return;
    }
    mount(listBody, h('div', { class: 'pl-list' }, ...state.places.map((p) => placeRow(p, edit))));
  }

  const detectedBody = h('div');
  function drawDetected() {
    if (!state.parked.length) {
      mount(detectedBody, empty(t('No detected places'), t('Mate finds a place when the car parks somewhere new.'), 'pin'));
      return;
    }
    mount(detectedBody, h('div', null,
      h('p', { class: 'small muted' }, t('Parking spots that no place covers yet.')),
      h('div', { class: 'pl-detected' }, ...state.parked.map((c) => {
        const where = c.address ? f.shortPlace(c.address) : `${f.num(c.lat, 5)}, ${f.num(c.lon, 5)}`;
        const nameIt = button(t('Name this place'), { size: 'sm', ic: 'pin',
          onClick: () => startForm({ point: { lat: c.lat, lon: c.lon } }) });
        nameIt.setAttribute('aria-label', `${t('Name this place')}: ${where}`);
        return h('div', { class: 'pl-det-row' },
          h('div', { class: 'pl-det-main' }, h('strong', null, where),
            h('div', { class: 'tiny muted' },
              `${tn('{n} reading while parked', '{n} readings while parked', c.n ?? 1)} · ${t('last seen {date}', { date: f.dateTime(c.last_seen) })}`)),
          nameIt);
      }))));
  }

  function addPlace() {
    const pos = ctx.overview?.sections?.position;
    const moving = pos?.state === 'IN_MOTION';  // while driving the position is stale, exactly like pages/map.js
    if (!moving && pos?.lat != null && pos?.lon != null) startForm({ point: { lat: pos.lat, lon: pos.lon } });
    else toast(t('The car is not parked. Click the map to choose a place.'), 'info');
  }

  try {
    await load();
  } catch (e) {
    mount(root, h('h1', null, t('Places')),
      banner('bad', `${t('Could not load the places')}: ${e.message}`),
      h('div', null, button(t('Try again'), { ic: 'refresh', onClick: () => placesPage(root, ctx) })));
    return;
  }

  addBtn = button(t('Add place'), { kind: 'primary', ic: 'plus', onClick: addPlace });
  const head = h('div', { class: 'pl-head' },
    h('div', { class: 'stack' }, h('h1', null, t('Places')),
      h('p', { class: 'muted' }, t('Name the places the car stops at, give them a radius and a price.'))),
    addBtn);
  mapBox = mapView(mapOptions());
  drawList();
  drawDetected();
  mount(root, head,
    card(null, mapBox, { cls: 'pl-mapcard' }),
    pickHint,
    h('p', { class: 'small muted' }, t('Click a circle on the map to edit its place. Click an empty spot to add a place.')),
    card(t('Your places'), listBody, { ic: 'pin' }),
    card(t('Detected places'), detectedBody, { ic: 'map' }));
}
