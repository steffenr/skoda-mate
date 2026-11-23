// Škoda Mate dashboard shell: hash router, API helper, shared context, header, banners.
// Pages live in ./pages/<name>.js and export `default async function (root, ctx)` (optionally returning a cleanup fn).
import { h, mount, clear } from './lib/dom.js';
import { icon } from './lib/icons.js';
import { asyncButton, banner, button, chip, empty, loading, modal, toast } from './lib/ui.js';
import * as f from './lib/format.js';
import { setLang, t } from './i18n.js';

// ------------------------------------------------------------------ API
async function request(method, path, body) {
  // Date filters are local days: tell the server our UTC offset (minutes, as JS reports it) so "today" means today here.
  if (method === 'GET' && path.startsWith('/api/vehicles/') && !path.includes('tz_offset=')) {
    path += `${path.includes('?') ? '&' : '?'}tz_offset=${new Date().getTimezoneOffset()}`;
  }
  const res = await fetch(path, { method, headers: body !== undefined ? { 'content-type': 'application/json' } : {}, body: body !== undefined ? JSON.stringify(body) : undefined, credentials: 'same-origin' });
  if (res.status === 401) { location.href = '/login'; await new Promise(() => {}); }
  const ct = res.headers.get('content-type') || '';
  const data = ct.includes('json') ? await res.json().catch(() => null) : null;
  if (!res.ok) {
    const detail = data && (typeof data.detail === 'string' ? data.detail : data.detail?.map?.((d) => d.msg).join('; '));
    // A bare FastAPI "Not Found" on an /api/ path means the server has no such route: the page is newer than the running
    // backend (it was updated but not restarted). Say so instead of a cryptic "Not found".
    const missing = res.status === 404 && path.startsWith('/api/') && detail === 'Not Found';
    const err = new Error(missing
      ? t('The server does not know this feature yet. Mate is probably still running an older version: restart it (ddev restart, or docker compose up -d --build).')
      : detail || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
}
export const api = {
  get: (p) => request('GET', p), post: (p, b = {}) => request('POST', p, b), put: (p, b = {}) => request('PUT', p, b),
  patch: (p, b = {}) => request('PATCH', p, b), del: (p) => request('DELETE', p),
};

// ------------------------------------------------------------------ routes
export const NAV = [
  ['', 'Overview', 'overview'], ['trips', 'Trips', 'route'], ['charges', 'Charges', 'plug'], ['prices', 'Prices', 'coin'], ['battery', 'Battery', 'battery'],
  ['control', 'Control', 'sliders'], ['stats', 'Statistics', 'chart'], ['map', 'Map', 'map'], ['events', 'Events', 'activity'],
  ['settings', 'Settings', 'settings'], ['system', 'System', 'shield'],
];
const ROUTES = [
  [/^$/, 'overview'], [/^trips$/, 'trips'], [/^trips\/(\d+)$/, 'trip'], [/^charges$/, 'charges'], [/^charges\/(\d+)$/, 'charge'], [/^prices$/, 'prices'],
  [/^battery$/, 'battery'], [/^control$/, 'control'], [/^stats$/, 'stats'], [/^map$/, 'map'], [/^events$/, 'events'],
  [/^settings$/, 'settings'], [/^system(?:\/(status|capabilities|calls|diagnostics))?$/, 'system'], [/^import$/, 'import'],
];
const SECTION = { trip: 'trips', charge: 'charges', import: 'trips', capabilities: 'system' };

// ------------------------------------------------------------------ state
const S = { vehicles: [], vid: null, overview: null, settings: null, cleanup: null, ticks: new Set(), seq: 0 };

export const nav = (path) => { location.hash = `#/${path}`; };
const parseHash = () => {
  const [path, qs] = location.hash.replace(/^#\/?/, '').split('?');
  return { path: path.replace(/\/$/, ''), query: new URLSearchParams(qs || '') };
};

function applyTheme(theme) {
  if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}

// Every page registers its German strings when its module loads. A string used on the Overview but defined on another
// page would stay English until that page was opened, so load all page modules up front (a few small files).
import './de_backend.js';
const PAGE_MODULES = ["overview", "trips", "trip", "charges", "charge", "battery", "control", "stats", "map", "events", "settings", "system", "import", "capabilities"];
const preloadPages = () => Promise.all(PAGE_MODULES.map((n) => import(`./pages/${n}.js`).catch(() => null)));

async function loadSettings() {
  S.settings = await api.get("/api/settings");
  f.setLocale({ units: S.settings.units, language: S.settings.language });
  setLang(S.settings.language);
  document.documentElement.lang = S.settings.language;
  applyTheme(S.settings.theme);
  await preloadPages();
}

async function loadOverview() {
  if (!S.vid) return null;
  S.overview = await api.get(`/api/vehicles/${S.vid}/overview`);
  return S.overview;
}

function makeCtx(params, query) {
  return {
    api, vid: S.vid, vin: S.overview?.vehicle.vin, params, query, nav, toast, t, f,
    get overview() { return S.overview; }, get settings() { return S.settings; },
    get currency() { return S.overview?.tariff?.currency || 'EUR'; },
    refresh: async () => { await loadOverview(); paintHeader(); paintBanners(); return S.overview; },
    reloadSettings: async () => { await loadSettings(); paintShell(); },
    onTick: (fn) => { S.ticks.add(fn); },
    setTitle: (s) => { document.title = `${s} · Škoda Mate`; },
  };
}

// ------------------------------------------------------------------ shell
let els = {};

function navLink(path, label, ic, current) {
  return h('a', { href: `#/${path}`, 'aria-current': current ? 'page' : null }, icon(ic, { size: 19 }), h('span', null, t(label)));
}

function paintShell() {
  if (els.skip) els.skip.textContent = t('Skip to content');
  const { path } = parseHash();
  const match = ROUTES.find(([re]) => re.test(path));
  const section = match ? (SECTION[match[1]] ?? (match[1] === 'overview' ? '' : match[1])) : '';
  const brand = h('a', { class: 'brand', href: '#/', 'aria-label': `Škoda Mate, ${t('Overview')}` }, h('div', { class: 'mark' }, icon('car', { size: 20 })), h('div', null, 'Škoda Mate', h('small', null, 'v' + (S.version || ''))));
  mount(els.sidebar, brand, h('nav', { class: 'nav', 'aria-label': 'Main' }, ...NAV.map(([p, l, i], k) => [k === 9 ? h('div', { class: 'sep' }) : null, navLink(p, l, i, p === section)]),
    // Sign out is the last entry of the same list: same shape, same alignment as the links above
    h('div', { class: 'sep' }),
    h('button', { class: 'signout', type: 'button', onclick: signOut }, icon('logout', { size: 19 }), h('span', null, t('Sign out')))),
    S.overview?.demo ? h('div', { class: 'foot' }, h('span', { class: 'badge-demo' }, 'DEMO')) : null);
  const tab = (p, l, i) => h('a', { href: `#/${p}`, 'aria-current': p === section ? 'page' : null }, icon(i, { size: 21 }), t(l));
  mount(els.tabbar, tab('', 'Overview', 'overview'), tab('trips', 'Trips', 'route'), tab('charges', 'Charges', 'plug'), tab('control', 'Control', 'sliders'),
    h('button', { type: 'button', onclick: moreMenu }, icon('menu', { size: 21 }), t('More')));
}

function moreMenu() {
  const body = h('div', { class: 'stack' }, ...NAV.filter(([p]) => !['', 'trips', 'charges', 'control'].includes(p)).map(([p, l, i]) =>
    h('a', { class: 'btn', href: `#/${p}`, onclick: () => document.querySelector('.scrim')?.remove() }, icon(i, { size: 18 }), t(l))),
    h('button', { class: 'btn danger', type: 'button', onclick: signOut }, icon('logout', { size: 18 }), t('Sign out')));
  modal(t('More'), body, (close) => [button(t('Close'), { onClick: close })]);
}

async function signOut() {
  try { await fetch('/api/logout', { method: 'POST' }); } catch { /* ignore */ }
  location.href = '/login';
}

function statusLine(o) {
  const p = o?.poller;
  if (!p || !p.known) return t('Not connected');
  const parts = [];
  if (p.captured_at) parts.push(`${t('Car reported')} ${f.ago(p.captured_at)}`);
  else if (p.last_ok) parts.push(`${t('Updated')} ${f.ago(p.last_ok)}`);
  if (p.next_poll_in != null && !p.blocked) parts.push(`${t('next check in')} ${f.inSeconds(p.next_poll_in)}`);
  return parts.join(' · ');
}

function paintHeader() {
  const o = S.overview;
  const v = S.vehicles.find((x) => x.id === S.vid);
  const info = o?.sections?.info;
  const health = linkHealth(o);
  const title = h('div', { class: ['title', S.vehicles.length > 1 ? 'multi' : ''] },
    h('div', { class: 'name' }, h('strong', null, info?.name || v?.name || v?.vin || 'Škoda Mate'),
      info?.license_plate ? h('span', { class: 'plate' }, info.license_plate) : null),
    h('div', { class: 'status', title: health.tip }, h('i', { class: ['dot', health.kind, health.kind === 'bad' ? 'pulse' : ''] }), h('span', null, statusLine(o))));
  const b = o?.poller?.budget;
  const pickSel = S.vehicles.length > 1 ? h('select', { 'aria-label': t('Switch car'), onchange: (e) => { S.vid = +e.target.value; localStorage.setItem('vid', S.vid); boot(true); } },
    ...S.vehicles.map((x) => h('option', { value: x.id, selected: x.id === S.vid }, (x.name || x.vin) + (x.active === false ? ' (' + t('history only') + ')' : '')))) : null;
  // a visible pill (car icon + name + chevron), so switching cars is discoverable
  const pick = pickSel ? h('label', { class: 'carpick', title: t('Switch car') }, icon('car', { size: 16 }), pickSel, icon('down', { size: 14 })) : null;
  const refreshBtn = asyncButton(t('Refresh now'), async () => {
    const r = await api.post(`/api/vehicles/${S.vid}/refresh`);
    await loadOverview(); paintHeader(); paintBanners(); S.ticks.forEach((fn) => fn());
    if (r.ok) toast(t('Updated from Škoda'), 'good');
    else toast(r.error || t('Could not refresh'), 'bad');
  }, { ic: 'refresh', size: 'sm', title: t('Reads the car once (uses 1 of your 20 requests per hour)') });
  const dark = (document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')) === 'dark';
  // A link, not a bare number: it says what it counts and leads to the details.
  const meter = b ? h('a', { class: ['chip', b.remaining <= 0 ? 'warn' : ''], href: '#/system',
    title: `${t('Requests to Škoda used this hour')}: ${b.used} ${t('of')} ${b.limit - b.reserve} ${t('for reading')} (${t('the rest is kept for commands')}). ${t('Details on the System page.')}`,
    'aria-label': `${t('Requests used this hour')}: ${b.used} ${t('of')} ${b.limit - b.reserve}` }, icon('signal', { size: 13 }), `${b.used}/${b.limit - b.reserve}`) : null;
  mount(els.topbar, title, pick, meter, refreshBtn,
    h('button', { class: 'btn ghost sm', type: 'button', title: dark ? t('Switch to light theme') : t('Switch to dark theme'),
      'aria-label': dark ? t('Switch to light theme') : t('Switch to dark theme'), onclick: toggleTheme }, icon(dark ? 'sun' : 'moon', { size: 18 })));
}

/** Is Mate's link to the car healthy? green = recent successful read, amber = old or rate-limited, red = failing. */
function linkHealth(o) {
  const p = o?.poller;
  if (!p || !p.known) return { kind: '', tip: t('Not connected') };
  if (p.blocked || (p.error && p.error_kind !== 'budget')) return { kind: 'bad', tip: p.error || t('Škoda is not accepting the request') };
  if (p.error_kind === 'budget' || (p.budget && p.budget.remaining <= 0)) return { kind: 'warn', tip: t('Request limit reached; Mate waits for the next free slot.') };
  const ageS = p.last_ok ? (Date.now() - new Date(p.last_ok).getTime()) / 1000 : null;
  const limit = Math.max(2 * ((p.interval && p.interval.idle) || 1200), 2400);
  if (ageS == null || ageS > limit) return { kind: 'warn', tip: t('Mate has not read the car for a while.') };
  return { kind: 'good', tip: t('Connected: Mate read the car recently.') };
}

async function toggleTheme() {
  const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const next = cur === 'dark' ? 'light' : 'dark';
  applyTheme(next); paintHeader();
  try { await api.put('/api/settings', { theme: next }); S.settings.theme = next; } catch { /* keep the local choice */ }
}

function daysUntil(iso) { return iso ? Math.floor((new Date(iso) - Date.now()) / 864e5) : null; }

function paintBanners() {
  const o = S.overview;
  const list = [];
  if (o) {
    const p = o.poller || {};
    if (p.blocked || p.error_kind === 'api-key-expired') list.push(banner('bad', h('b', null, t('Škoda is not accepting the API key.')), ' ', p.error || '', ' ', h('a', { href: '#/settings' }, t('Update the key'))));
    else if (p.error && p.error_kind !== 'budget') list.push(banner('warn', p.error, ' ', t('Mate will retry automatically.')));
    const d = daysUntil(p.key_expires_at);
    if (d != null && d <= 14 && !p.blocked) list.push(banner('warn', d < 0 ? t('The API key has expired.') : `${t('The API key expires in')} ${d} ${d === 1 ? t('day') : t('days')}.`, ' ', h('a', { href: '#/settings' }, t('Create a new one in the MyŠkoda app and enter it here.'))));
    if (o.needs_capacity) list.push(banner('info', t('Škoda does not report the battery size. Enter it to get energy, consumption and costs.'), ' ', h('a', { href: '#/settings' }, t('Set battery capacity'))));
    if (o.demo) list.push(banner('info', t('Demo mode: this is a fictional car. Nothing is sent to Škoda.')));
  }
  mount(els.banners, ...list);
}

// ------------------------------------------------------------------ routing
async function route() {
  const seq = ++S.seq;
  if (typeof S.cleanup === 'function') { try { S.cleanup(); } catch { /* ignore */ } }
  S.cleanup = null; S.ticks.clear();
  const { path, query } = parseHash();
  if (path === 'capabilities') { location.replace('#/system/capabilities'); return; } // old link: Capabilities now lives inside System
  paintShell();
  const match = ROUTES.map(([re, name]) => [re.exec(path), name]).find(([m]) => m);
  if (!match) { mount(els.view, empty(t('Page not found'), null, 'compass')); return; }
  const [m, name] = match;
  mount(els.view, loading());
  window.scrollTo(0, 0);
  try {
    if (!S.vid) { mount(els.view, empty(t('No vehicle yet'), t('Waiting for the first reading from Škoda…'), 'car')); return; }
    const mod = await import(`./pages/${name}.js`).catch((e) => { if (String(e).includes('Failed to fetch') || String(e).includes('error loading')) return null; throw e; });
    if (seq !== S.seq) return;
    if (!mod) { mount(els.view, empty(t('This page is not available yet'), null, 'info')); return; }
    const root = h('div', { class: 'page' });
    mount(els.view, root);
    const ctx = makeCtx(m.slice(1), query);
    const result = await mod.default(root, ctx);
    // Every page needs one level-1 heading for screen-reader navigation; pages that draw none get a hidden one.
    if (seq === S.seq && !root.querySelector('h1')) {
      const label = (NAV.find(([p]) => p === (SECTION[name] ?? (name === 'overview' ? '' : name))) || [])[1];
      root.prepend(h('h1', { class: 'sr-h1' }, t(label || 'Škoda Mate')));
    }
    if (seq !== S.seq) { if (typeof result === 'function') result(); return; }
    S.cleanup = result;
  } catch (e) {
    console.error(e);
    mount(els.view, h('div', { class: 'card' }, banner('bad', t('Something went wrong on this page.'), ' ', String(e.message || e)),
      h('div', { style: { marginTop: '12px' } }, button(t('Try again'), { onClick: route, ic: 'refresh' }))));
  }
}

async function tick() {
  if (document.hidden || !S.vid) return;
  try { await loadOverview(); paintHeader(); paintBanners(); S.ticks.forEach((fn) => { try { fn(); } catch (e) { console.error(e); } }); } catch { /* transient */ }
}

async function boot(again = false) {
  try {
    const [vehicles, health] = await Promise.all([api.get('/api/vehicles'), fetch('/health').then((r) => r.json())]);
    S.vehicles = vehicles; S.version = health.version;
    const saved = +localStorage.getItem('vid');
    S.vid = (vehicles.find((v) => v.id === saved) || vehicles[0])?.id ?? null;
    if (!again) await loadSettings();
    await loadOverview();
  } catch (e) { console.error(e); }
  paintShell(); paintHeader(); paintBanners();
  await route();
}

export function start(root) {
  els = {
    sidebar: h('aside', { class: 'sidebar' }), topbar: h('header', { class: 'topbar' }), banners: h('div', { class: 'view', style: { paddingBottom: 0 } }),
    view: h('div', { class: 'view', id: 'main', tabindex: '-1' }), tabbar: h('nav', { class: 'tabbar', 'aria-label': 'Main' }),
  };
  // The skip link must not change the URL hash: the hash is the router (#main would open a page called "main").
  const skip = els.skip = h('a', { class: 'skip', href: '#main', onclick: (e) => { e.preventDefault(); els.view.focus(); els.view.scrollIntoView(); } }, t('Skip to content'));
  mount(root, skip, h('div', { class: 'app' }, els.sidebar,
    h('div', { class: 'main' }, els.topbar, h('main', null, els.banners, els.view))), els.tabbar);
  window.addEventListener('hashchange', route);
  setInterval(tick, 30000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) tick(); });
  boot();
}
