// Real-browser end-to-end check (puppeteer-core + installed Chromium) against a running DEMO server.
//   npm install puppeteer-core --no-save   (once)   then:   BASE=http://localhost:8765 node browser_e2e.mjs
// 1. phone viewport: every page must fit the screen (no horizontal scroll) and nothing may throw
// 2. click-through: navigation, refresh, a command, a setting, units, language, the mobile "More" menu
import puppeteer from 'puppeteer-core';

const BASE = process.env.BASE || 'http://localhost:8765';
const SHOTS = process.env.SHOTS || '';
const CHROME = process.env.CHROME || '/Applications/Chromium.app/Contents/MacOS/Chromium';
const ROUTES = ['', 'trips', 'trips/5', 'charges', 'charges/3', 'battery', 'control', 'stats', 'map', 'events', 'settings', 'system'];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
const check = (name, ok, extra = '') => { if (!ok) failed++; console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${extra ? '  ' + extra : ''}`); };

const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox', '--disable-gpu'] });
const errors = [];
const watch = (page) => {
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource|favicon/.test(m.text())) errors.push(m.text().slice(0, 160)); });
};
const reset = async () => { const p = await browser.newPage(); await p.goto(BASE + '/'); await p.evaluate(() => fetch('/api/settings', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ units: 'km', language: 'en', theme: 'dark' }) })); await p.close(); };
await reset();

// ---------------------------------------------------------------- 1. phone
const phone = await browser.newPage();
watch(phone);
await phone.setViewport({ width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
await phone.goto(BASE + '/', { waitUntil: 'networkidle0' });
console.log('--- phone 390x844');
for (const r of ROUTES) {
  await phone.goto(`${BASE}/#/${r}`, { waitUntil: 'networkidle0' });
  await sleep(1800);
  const m = await phone.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    // Content inside a horizontally scrollable box (tables, the system tab row) is reachable, not clipped: the page
    // itself must not scroll sideways, which is what the scrollWidth check below covers.
    const scrolls = (e) => {
      for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) {
        const ox = getComputedStyle(p).overflowX;
        if ((ox === 'auto' || ox === 'scroll') && p.scrollWidth > p.clientWidth + 1) return true;
      }
      return false;
    };
    const over = [...document.querySelectorAll('#main *')].filter((e) => e.getBoundingClientRect().right > vw + 1 && getComputedStyle(e).position !== 'fixed'
      && !e.closest('.leaflet-container') && !e.closest('svg') && !scrolls(e))
      .map((e) => `${e.tagName.toLowerCase()}.${(e.className && e.className.baseVal === undefined ? e.className : '').toString().split(' ')[0]} +${Math.round(e.getBoundingClientRect().right - vw)}px`);
    return { scrollW: document.documentElement.scrollWidth, vw, over: [...new Set(over)].slice(0, 4), text: document.getElementById('main').innerText.length };
  });
  check(`phone #/${r || 'overview'} fits`, m.scrollW <= m.vw + 1 && m.over.length === 0 && m.text > 40, `scrollWidth=${m.scrollW}/${m.vw} ${m.over.join(' ')}`);
  if (SHOTS && ['', 'control', 'trips'].includes(r)) await phone.screenshot({ path: `${SHOTS}/phone-${r || 'overview'}.png` });
}
const tabs = await phone.$$('.tabbar a, .tabbar button');
check('phone bottom tab bar has 5 entries', tabs.length === 5, String(tabs.length));
await phone.goto(`${BASE}/#/`, { waitUntil: 'networkidle0' });
await phone.evaluate(() => [...document.querySelectorAll('.tabbar button')].find((b) => /More/.test(b.textContent)).click());
await sleep(400);
check('"More" menu opens with the other pages', (await phone.$$('.modal a.btn')).length >= 5);
await phone.keyboard.press('Escape');
await phone.close();

// ---------------------------------------------------------------- 2. desktop click-through
const d = await browser.newPage();
watch(d);
await d.setViewport({ width: 1280, height: 900 });
await d.goto(BASE + '/', { waitUntil: 'networkidle0' });
await sleep(1500);
console.log('--- desktop click-through');
const labels = ['Trips', 'Charges', 'Battery', 'Control', 'Statistics', 'Map', 'Events', 'Settings', 'System'];
for (const l of labels) {
  await d.evaluate((txt) => [...document.querySelectorAll('.sidebar .nav a')].find((a) => a.textContent.trim() === txt).click(), l);
  await sleep(1300);
  const h = await d.evaluate(() => location.hash);
  const ok = await d.evaluate(() => !/Something went wrong|not available yet/.test(document.getElementById('main').innerText) && document.getElementById('main').innerText.length > 30);
  check(`sidebar → ${l}`, ok, h);
}
await d.evaluate(() => document.querySelector('.brand').click());
await sleep(900);
check('clicking "Škoda Mate" opens the Overview', await d.evaluate(() => location.hash === '#/' || location.hash === '' || location.hash === '#'), await d.evaluate(() => location.hash));

// ---------------------------------------------------------------- 3. map clustering and its fallback
await d.goto(`${BASE}/#/map`, { waitUntil: 'networkidle0' });
await sleep(2500);
const clusters = await d.evaluate(() => document.querySelectorAll('.marker-cluster').length);
check('map clusters crowded pins', clusters > 0, `${clusters} cluster(s)`);
if (SHOTS) await d.screenshot({ path: `${SHOTS}/map-clusters.png` });
// The plugin is optional: with its files blocked the map must still show plain pins, without an error page or banner.
const fb = await browser.newPage();
watch(fb);
await fb.setRequestInterception(true);
fb.on('request', (req) => (req.url().includes('markercluster') ? req.abort() : req.continue()));
await fb.goto(`${BASE}/#/map`, { waitUntil: 'networkidle0' });
await sleep(2500);
const fallback = await fb.evaluate(() => ({ pins: document.querySelectorAll('#main .pin').length, text: document.getElementById('main').innerText }));
check('map falls back to plain pins without the cluster plugin', fallback.pins > 0 && !/Something went wrong/.test(fallback.text), `${fallback.pins} pin(s)`);
if (SHOTS) await fb.screenshot({ path: `${SHOTS}/map-fallback.png` });
await fb.close();

// ---------------------------------------------------------------- 4. the legacy ownerless circle must not swallow map clicks
// The prices page draws a bare `circle` (a radius hint, no id) and asks the user to click the map to place the home pin.
// Under R8 only a circle that identifies a place (id) is interactive, so this one has to stay click-through.
await d.goto(`${BASE}/#/prices`, { waitUntil: 'networkidle0' });
await d.waitForSelector('#main .map.leaflet-container', { timeout: 10000 }).catch(() => {});
await sleep(1200);
const clickPlace = await d.evaluate(() => {
  const coords = () => [...document.querySelectorAll('#main .grid.g3 input[type=number]')];
  const radius = coords()[2];
  if (!radius) return null;
  radius.value = '5000';  // cover the whole viewport, so the click below is certainly inside the circle
  radius.dispatchEvent(new Event('input', { bubbles: true }));
  const map = document.querySelector('#main .map.leaflet-container');
  if (!map) return null;
  map.scrollIntoView({ block: 'center' });
  const b = map.getBoundingClientRect();
  return { x: b.left + b.width * 0.7, y: b.top + b.height * 0.7, before: coords().slice(0, 2).map((i) => i.value) };
});
await sleep(600);
if (clickPlace) await d.mouse.click(clickPlace.x, clickPlace.y);
await sleep(400);
const placed = await d.evaluate(() => ({
  latlon: [...document.querySelectorAll('#main .grid.g3 input[type=number]')].slice(0, 2).map((i) => i.value),
  circles: document.querySelectorAll('#main .leaflet-overlay-pane path').length,
  interactive: document.querySelectorAll('#main .leaflet-overlay-pane path.leaflet-interactive').length,
}));
check('ownerless circle keeps click-to-place on the prices map',
  !!clickPlace && placed.circles > 0 && placed.interactive === 0 && placed.latlon[0] !== clickPlace.before[0] && placed.latlon[1] !== clickPlace.before[1],
  `circle=${placed.circles} interactive=${placed.interactive} ${clickPlace?.before.join(',')} → ${placed.latlon.join(',')}`);

const before = await d.evaluate(() => fetch('/health').then((r) => r.json()));
await d.evaluate(() => [...document.querySelectorAll('.topbar button')].find((b) => /Refresh now/.test(b.textContent)).click());
await sleep(1800);
check('"Refresh now" works and shows a confirmation', await d.evaluate(() => /Updated from Škoda/.test(document.querySelector('.toasts')?.textContent || '')));

// a command through the Control page: charge limit 90
await d.goto(`${BASE}/#/control`, { waitUntil: 'networkidle0' });
await sleep(1200);
await d.evaluate(() => { const r = document.querySelector('input[type=range]'); r.value = 90; r.dispatchEvent(new Event('input', { bubbles: true })); r.dispatchEvent(new Event('change', { bubbles: true })); });
await d.evaluate(() => [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Set limit').click());
await sleep(1500);
const cmds = await d.evaluate(() => fetch('/api/vehicles/1/commands').then((r) => r.json()));
check('Control → "Set limit" sends the command (logged, accepted)', cmds.log[0]?.name === 'set_charge_limit' && cmds.log[0]?.ok === 1 && cmds.log[0]?.params?.percent === 90, JSON.stringify(cmds.log[0]?.params));

// settings: miles + German
await d.goto(`${BASE}/#/settings`, { waitUntil: 'networkidle0' });
await sleep(1200);
const press = (label) => d.evaluate((txt) => [...document.querySelectorAll('.seg button')].find((b) => b.textContent.trim() === txt).click(), label);
await press('Miles'); await press('Deutsch');
await d.evaluate(() => [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Save').click());
await sleep(1500);
const nav = await d.evaluate(() => [...document.querySelectorAll('.sidebar .nav a')].map((a) => a.textContent.trim()).join(','));
check('German applies immediately (navigation translated)', /Übersicht/.test(nav) && /Fahrten/.test(nav) && /Einstellungen/.test(nav), nav);
await d.goto(`${BASE}/#/`, { waitUntil: 'networkidle0' });
await sleep(1800);
const ov = await d.evaluate(() => document.getElementById('main').innerText);
check('miles are used on the Overview (odometer in mi)', /\bmi\b/.test(ov) && !/ km\b/.test(ov.replace(/km\/h/g, '')), ov.match(/[\d,.]+\s*(mi|km)/g)?.slice(0, 3).join(' | '));
const untranslated = ['Last trip', 'Quick controls', 'Battery, last 48 hours', 'Last charge'].filter((s) => ov.includes(s));  // ("Position" is the same word in German)
check('Overview text is German (no English headings left)', untranslated.length === 0, untranslated.join(', '));
for (const r of ['trips', 'charges', 'control', 'stats', 'settings', 'system']) {
  await d.goto(`${BASE}/#/${r}`, { waitUntil: 'networkidle0' }); await sleep(1300);
  const t = await d.evaluate(() => document.getElementById('main').innerText);
  const eng = ['Export CSV', 'Total distance', 'Start charging', 'Request budget', 'Home position', 'How these numbers are made'].filter((s) => t.includes(s));
  check(`German #/${r}`, eng.length === 0, eng.join(', '));
}
await d.goto(`${BASE}/#/trips`, { waitUntil: 'networkidle0' }); await sleep(1500);
if (SHOTS) await d.screenshot({ path: `${SHOTS}/german-trips.png` });
// restore and finish
await d.evaluate(() => fetch('/api/settings', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ units: 'km', language: 'en' }) }));
check('no JavaScript errors during the whole session', errors.length === 0, errors.slice(0, 3).join(' | '));
await browser.close();
console.log(failed ? `\n${failed} check(s) FAILED` : '\nend-to-end OK');
process.exit(failed ? 1 : 0);
