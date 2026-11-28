// Škoda Mate dashboard shell: hash router, API helper, shared context, header, banners.
// Pages live in ./pages/<name>.js and export `default async function (root, ctx)` (optionally returning a cleanup fn).
import { h, mount, clear } from './lib/dom.js';
import { icon } from './lib/icons.js';
import { asyncButton, banner, button, chip, empty, loading, modal, toast } from './lib/ui.js';
import * as f from './lib/format.js';
import { disposeAllMaps } from './lib/mapview.js';
import { getLocale, setLang, t, tm, tx, tn } from './i18n.js';

// ------------------------------------------------------------------ API
// A request that never answers (laptop woke up on another network, server restarting) must end: otherwise the page waits
// for ever and, with the tick loop, requests pile up behind it. Reads are quick; a write or an import may take longer.
const READ_TIMEOUT_MS = 15000, WRITE_TIMEOUT_MS = 60000;
let signedOut = false;  // the session ended: stop talking to the server while the browser goes to /login

async function request(method, path, body) {
  // Date filters are local days: tell the server our UTC offset (minutes, as JS reports it) so "today" means today here.
  if (method === 'GET' && path.startsWith('/api/vehicles/') && !path.includes('tz_offset=')) {
    path += `${path.includes('?') ? '&' : '?'}tz_offset=${new Date().getTimezoneOffset()}`;
  }
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), method === 'GET' ? READ_TIMEOUT_MS : WRITE_TIMEOUT_MS);
  let res, data = null;
  try {
    res = await fetch(path, { method, headers: body !== undefined ? { 'content-type': 'application/json' } : {}, body: body !== undefined ? JSON.stringify(body) : undefined, credentials: 'same-origin', signal: ctl.signal });
    if (res.status === 401) { signedOut = true; location.href = '/login'; await new Promise(() => {}); }
    const ct = res.headers.get('content-type') || '';
    data = ct.includes('json') ? await res.json().catch(() => null) : null;
  } catch (e) {
    if (!ctl.signal.aborted) throw e;
    const err = new Error(t('The server did not answer in time.'));
    err.status = 0; err.timeout = true;
    throw err;
  } finally { clearTimeout(timer); }
  if (!res.ok) {
    const detail = data && (typeof data.detail === 'string' ? data.detail : data.detail?.map?.((d) => d.msg).join('; '));
    // A bare FastAPI "Not Found" on an /api/ path means the server has no such route: the page is newer than the running
    // backend (it was updated but not restarted). Say so instead of a cryptic "Not found".
    const missing = res.status === 404 && path.startsWith('/api/') && detail === 'Not Found';
    const err = new Error(missing
      ? t('The server does not know this feature yet. Mate is probably still running an older version: restart it (ddev restart, or docker compose up -d --build).')
      : (data?.detail_i18n ? tm(data.detail_i18n) : detail) || `Request failed (${res.status})`);
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
// One table drives the sidebar, the router, the page modules and which nav entry is highlighted. `path` is the route a
// link points at (`:id` is a number); `pattern` overrides what the router matches when a page owns several routes. A page
// without a label is a detail view (no nav entry) and names the section it belongs to.
export const PAGES = [
  { path: '', name: 'overview', label: 'Overview', icon: 'overview' },
  { path: 'trips', name: 'trips', label: 'Trips', icon: 'route' },
  { path: 'trips/:id', name: 'trip', section: 'trips' },
  { path: 'charges', name: 'charges', label: 'Charges', icon: 'plug' },
  { path: 'charges/:id', name: 'charge', section: 'charges' },
  { path: 'prices', name: 'prices', label: 'Prices', icon: 'coin' },
  { path: 'battery', name: 'battery', label: 'Battery', icon: 'battery' },
  { path: 'control', name: 'control', label: 'Control', icon: 'sliders' },
  { path: 'stats', name: 'stats', label: 'Statistics', icon: 'chart' },
  { path: 'map', name: 'map', label: 'Map', icon: 'map' },
  { path: 'places', name: 'places', label: 'Places', icon: 'pin' },
  { path: 'places/:id', name: 'place', section: 'places' },
  { path: 'events', name: 'events', label: 'Activity', icon: 'activity' },
  { path: 'settings', name: 'settings', label: 'Settings', icon: 'settings', sepBefore: true },
  { path: 'system', name: 'system', label: 'System', icon: 'shield', pattern: 'system(?:/(status|capabilities|calls|diagnostics))?' },
  { path: 'import', name: 'import', section: 'trips' },
  { path: 'capabilities', name: 'capabilities', section: 'system' },  // old link, redirected in route()
];
export const NAV = PAGES.filter((p) => p.label);
const sectionOf = (page) => page.section ?? page.path;
const patternOf = (page) => page.pattern ?? page.path.replace(/\/:id/g, '/(\\d+)');
const pageByPath = (path) => PAGES
  .map((p) => [new RegExp(`^${patternOf(p)}$`).exec(path), p])
  .find(([m]) => m);

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

async function loadSettings() {
  S.settings = await api.get("/api/settings");
  await setLang(S.settings.language, S.settings.locale);
  // getLocale() is 'en' when the catalog could not be loaded: formats and lang then match the English texts
  f.setLocale({ units: S.settings.units, locale: getLocale() });
  document.documentElement.lang = getLocale();
  applyTheme(S.settings.theme);
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
    // the sidebar, the header and the banners all show translated text: repaint them, not only at the next tick
    reloadSettings: async () => { await loadSettings(); paintShell(); paintHeader(); paintBanners(); },
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
  const match = pageByPath(path);
  const section = match ? sectionOf(match[1]) : '';
  // The name comes from the visible text (WCAG 2.5.3): no aria-label that drops it, the version is decoration.
  const brand = h('a', { class: 'brand', href: '#/' }, h('div', { class: 'mark' }, icon('car', { size: 20 })),
    h('div', null, 'Škoda Mate', h('small', { 'aria-hidden': 'true' }, 'v' + (S.version || ''))));
  mount(els.sidebar, brand, h('nav', { class: 'nav', 'aria-label': 'Main' },
    ...NAV.map((page) => [page.sepBefore ? h('div', { class: 'sep' }) : null, navLink(page.path, page.label, page.icon, page.path === section)]),
    // Sign out is the last entry of the same list: same shape, same alignment as the links above
    h('div', { class: 'sep' }),
    h('button', { class: 'signout', type: 'button', onclick: signOut }, icon('logout', { size: 19 }), h('span', null, t('Sign out')))),
    S.overview?.demo ? h('div', { class: 'foot' }, h('span', { class: 'badge-demo' }, t('Demo'))) : null);
  const tab = (p, l, i) => h('a', { href: `#/${p}`, 'aria-current': p === section ? 'page' : null }, icon(i, { size: 21 }), t(l));
  mount(els.tabbar, tab('', 'Overview', 'overview'), tab('trips', 'Trips', 'route'), tab('charges', 'Charges', 'plug'), tab('control', 'Control', 'sliders'),
    h('button', { type: 'button', onclick: moreMenu }, icon('menu', { size: 21 }), t('More')));
}

function moreMenu() {
  const body = h('div', { class: 'stack' }, ...NAV.filter((page) => !['', 'trips', 'charges', 'control'].includes(page.path)).map((page) =>
    h('a', { class: 'btn', href: `#/${page.path}`, onclick: () => document.querySelector('.scrim')?.remove() }, icon(page.icon, { size: 18 }), t(page.label))),
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
  if (p.captured_at) parts.push(t('Car reported {ago}', { ago: f.ago(p.captured_at) }));
  else if (p.last_ok) parts.push(t('Updated {ago}', { ago: f.ago(p.last_ok) }));
  if (p.next_poll_in != null && !p.blocked) parts.push(t('next check in {time}', { time: f.inSeconds(p.next_poll_in) }));
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
    else toast(tx(r) || t('Could not refresh'), 'bad');
  }, { ic: 'refresh', size: 'sm', title: t('Reads the car once (uses 1 of your 20 requests per hour)') });
  const dark = (document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')) === 'dark';
  // A link, not a bare number: it says what it counts and leads to the details.
  const meter = b ? h('a', { class: ['chip', b.remaining <= 0 ? 'warn' : ''], href: '#/system',
    title: t('Requests to Škoda used this hour: {used} of {max} for reading (the rest is kept for commands). Details on the System page.', { used: b.used, max: b.limit - b.reserve }),
    'aria-label': t('{used}/{max} requests used this hour', { used: b.used, max: b.limit - b.reserve }) }, icon('signal', { size: 13 }), `${b.used}/${b.limit - b.reserve}`) : null;
  mount(els.topbar, title, pick, meter, refreshBtn,
    h('button', { class: 'btn ghost sm', type: 'button', title: dark ? t('Switch to light theme') : t('Switch to dark theme'),
      'aria-label': dark ? t('Switch to light theme') : t('Switch to dark theme'), onclick: toggleTheme }, icon(dark ? 'sun' : 'moon', { size: 18 })));
}

/** Is Mate's link to the car healthy? green = recent successful read, amber = old or rate-limited, red = failing. */
function linkHealth(o) {
  const p = o?.poller;
  if (!p || !p.known) return { kind: '', tip: t('Not connected') };
  if (p.blocked || (p.error && p.error_kind !== 'budget')) return { kind: 'bad', tip: tx(p) || t('Škoda is not accepting the request') };
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
  // The browser's own problems first: a stale page must say so, whatever the car reports.
  if (S.offline) list.push(banner('warn', t('This device is offline. The dashboard shows the last data and continues when the connection is back.')));
  else if (T.failures >= 2) list.push(banner('warn', t('Mate cannot be reached. Last update {ago}. Trying again.', { ago: f.ago(new Date(T.lastOk).toISOString()) })));
  if (S.newVersion) list.push(banner('info', t('Škoda Mate was updated to version {version}.', { version: S.newVersion }), ' ', h('a', { href: location.pathname, onclick: (e) => { e.preventDefault(); location.reload(); } }, t('Reload the page'))));
  if (o) {
    const p = o.poller || {};
    if (p.blocked || p.error_kind === 'api-key-expired') list.push(banner('bad', h('b', null, t('Škoda is not accepting the API key.')), ' ', tx(p) || '', ' ', h('a', { href: '#/settings' }, t('Update the key'))));
    else if (p.error && p.error_kind !== 'budget') list.push(banner('warn', tx(p), ' ', t('Mate will retry automatically.')));
    const d = daysUntil(p.key_expires_at);
    if (d != null && d <= 14 && !p.blocked) list.push(banner('warn', d < 0 ? t('The API key has expired.') : tn('The API key expires in {n} day.', 'The API key expires in {n} days.', d), ' ', h('a', { href: '#/settings' }, t('Create a new one in the MyŠkoda app and enter it here.'))));
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
  disposeAllMaps();   // the page that is left takes its Leaflet maps (and their window listeners) with it
  const { path, query } = parseHash();
  if (path === 'capabilities') { location.replace('#/system/capabilities'); return; } // old link: Capabilities now lives inside System
  paintShell();
  const match = pageByPath(path);
  if (!match) { mount(els.view, empty(t('Page not found'), null, 'compass')); return; }
  const [m, page] = match;
  const name = page.name;
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
    // Every page needs one level-1 heading for screen-reader navigation; pages that draw none get a hidden one. It lives
    // beside .page, not inside it: pages that redraw themselves later (Overview refreshes after the parked-loss answer)
    // would wipe it out of their re-rendered root.
    if (seq === S.seq && !root.querySelector('h1')) {
      const navPage = page.label ? page : PAGES.find((p) => p.path === sectionOf(page));
      els.view.prepend(h('h1', { class: 'sr-h1' }, t(navPage?.label || 'Škoda Mate')));
    }
    if (seq !== S.seq) { if (typeof result === 'function') result(); return; }
    S.cleanup = result;
  } catch (e) {
    console.error(e);
    mount(els.view, h('div', { class: 'card' }, banner('bad', t('Something went wrong on this page.'), ' ', String(e.message || e)),
      h('div', { style: { marginTop: '12px' } }, button(t('Try again'), { onClick: route, ic: 'refresh' }))));
  }
}

// ------------------------------------------------------------------ tick
// A dashboard tab can stay open for days, so the 30 s loop must survive a bad network:
//  - one tick at a time (a slow answer never queues a second request behind it),
//  - every request has a timeout (see request()),
//  - after failures the loop backs off (1, 3, 7 skipped ticks, then every 8th) and a banner says the data is stale,
//  - it stops asking while the browser is offline and resumes on the `online` event,
//  - it compares /health's version now and then and offers a reload when the server was updated.
const VERSION_CHECK_EVERY = 10;  // ticks (about 5 minutes)
const T = { running: false, failures: 0, skips: 0, count: 0, lastOk: Date.now() };  // the page loads with fresh data

/** What the overview says apart from the poller block, whose countdown and budget change on every call. */
function overviewKey(o) {
  if (!o) return '';
  const { poller, ...rest } = o;  // eslint-disable-line no-unused-vars
  return JSON.stringify(rest);
}

async function checkVersion() {
  try {
    const health = await fetch('/health', { credentials: 'same-origin', cache: 'no-store' }).then((r) => r.json());
    if (health.version && S.version && health.version !== S.version) { S.newVersion = health.version; paintBanners(); }
  } catch { /* the next check tries again */ }
}

async function tick(force = false) {
  if (document.hidden || !S.vid || signedOut || T.running) return;
  if (navigator.onLine === false) { if (!S.offline) { S.offline = true; paintBanners(); } return; }
  if (!force && T.failures >= 2) {  // back off: 2 failures skip 1 tick, 3 skip 3, 4 or more skip 7
    const wait = Math.min(2 ** (T.failures - 1) - 1, 7);
    if (T.skips < wait) { T.skips++; return; }
  }
  T.skips = 0; T.running = true;
  const before = overviewKey(S.overview);
  try {
    await loadOverview();
    const wasStale = T.failures >= 2 || S.offline;
    T.failures = 0; T.lastOk = Date.now(); S.offline = false;
    const changed = overviewKey(S.overview) !== before;
    paintHeader(); if (wasStale || changed) paintBanners();
    S.ticks.forEach((fn) => { try { fn(changed || wasStale); } catch (e) { console.error(e); } });
    if (++T.count % VERSION_CHECK_EVERY === 0) checkVersion();
  } catch {
    if (++T.failures === 2) paintBanners();  // two in a row: say so; a single hiccup stays quiet
  } finally { T.running = false; }
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
  setInterval(() => tick(), 30000);
  // Coming back to the tab or to the network: ask at once, without waiting out a back-off, and look for a new version.
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { tick(true); checkVersion(); } });
  window.addEventListener('online', () => tick(true));
  window.addEventListener('offline', () => { S.offline = true; paintBanners(); });
  boot();
}
